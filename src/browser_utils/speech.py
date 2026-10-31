"""Generate speech: điều khiển trang https://aistudio.google.com/generate-speech bằng chính trình duyệt của proxy.

Khác với trang chat (một trang dùng chung, hàng đợi trong queue_worker), trang speech có:
- context riêng (tách localStorage khỏi trang chat, kẻo lựa chọn model của hai trang đè lên nhau), sao chép cookie hiện tại của context chat;
- khoá riêng, nên một yêu cầu đọc không chặn hàng đợi chat (và ngược lại);
- trang mở lười ở yêu cầu đầu tiên rồi giữ mở: BotGuard của Google tin một trang đã "ấm" hơn một trang mới mở.

Audio không lấy từ thẻ <audio> mà bắt thẳng phản hồi RPC MakerSuiteService/GenerateContent: JSON lồng nhau, mỗi đoạn là
["audio/l16; rate=24000; channels=1", "<base64 PCM>"], ghép các đoạn theo thứ tự tài liệu.
"""

import asyncio
import base64
import json
import logging
import random
import re
import struct
import time
from typing import Any, List, Optional, Tuple

logger = logging.getLogger("AIStudioProxyServer")

SPEECH_URL = "https://aistudio.google.com/generate-speech"
DEFAULT_RATE = 24000
# Giọng mặc định của hộp thoại mới trên trang (hiện ở nút "Speaker 1 - Fola")
DEFAULT_VOICE = "Fola"
# Số lần bấm Run lại khi Google trả 403 "The caller does not have permission" (BotGuard không chấp nhận lần bấm đó)
MAX_CLICKS = 3
# Dừng chờ phản hồi: 60 giây cộng thêm theo độ dài văn bản (đo thật: xem README)
BASE_TIMEOUT_S = 60
PER_CHAR_TIMEOUT_S = 0.08
MAX_INPUT_CHARS = 20000


class SpeechError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def _audio_parts(node: Any, out: Optional[List[Tuple[str, str]]] = None) -> List[Tuple[str, str]]:
    """Gom mọi cặp [mime audio/*, base64] trong JSON lồng nhau, theo thứ tự tài liệu."""
    out = [] if out is None else out
    if isinstance(node, list):
        if len(node) >= 2 and isinstance(node[0], str) and node[0].lower().startswith("audio/") and isinstance(node[1], str):
            out.append((node[0], node[1]))
        else:
            for item in node:
                _audio_parts(item, out)
    return out


def parse_audio(body: bytes) -> Tuple[bytes, int]:
    """Phản hồi GenerateContent -> (PCM 16-bit little-endian mono, tần số lấy mẫu)."""
    try:
        parts = _audio_parts(json.loads(body))
    except ValueError as exc:
        raise SpeechError(f"Phản hồi không đọc được: {exc}") from exc
    if not parts:
        raise SpeechError("Phản hồi của AI Studio không có audio.")
    match = re.search(r"rate=(\d+)", parts[0][0])
    rate = int(match.group(1)) if match else DEFAULT_RATE
    return b"".join(base64.b64decode(data) for _, data in parts), rate


def pcm_to_wav(pcm: bytes, rate: int = DEFAULT_RATE) -> bytes:
    """Bọc PCM 16-bit mono bằng header WAV (44 byte)."""
    header = b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
    return header + b"data" + struct.pack("<I", len(pcm)) + pcm


class SpeechService:
    """Một trang speech giữ mở, mỗi lần chỉ phục vụ một yêu cầu."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._context: Any = None
        self._page: Any = None
        self._responses: "asyncio.Queue[Tuple[int, bytes]]" = asyncio.Queue()
        # Sau mỗi lần có kết quả, nút Run bị khoá cho tới khi sang hộp thoại mới ("New chat")
        self._dirty = False

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    async def close(self) -> None:
        page, context = self._page, self._context
        self._page = self._context = None
        for closer in (page, context):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:  # noqa: BLE001
                    pass

    async def _on_response(self, response: Any) -> None:
        if "GenerateContent" not in response.url:
            return
        try:
            body = await response.body()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[Speech] không đọc được phản hồi GenerateContent: {exc}")
            return
        self._responses.put_nowait((response.status, body))

    async def _open(self, chat_page: Any) -> None:
        """Mở context + trang speech mới, vào màn soạn "Create new dialog"."""
        await self.close()
        browser = chat_page.context.browser
        storage = await chat_page.context.storage_state()
        viewport = chat_page.viewport_size or {"width": 1440, "height": 900}
        self._context = await browser.new_context(storage_state=storage, viewport=viewport)
        self._dirty = False
        page = self._page = await self._context.new_page()
        page.on("response", lambda r: asyncio.ensure_future(self._on_response(r)))
        await page.goto(SPEECH_URL, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(4000)
        welcome = page.get_by_role("button", name="Continue")
        if await welcome.count():
            await welcome.first.click()
            await page.wait_for_timeout(1500)
        await page.get_by_text("Create new dialog").first.click()
        await page.locator('textarea[aria-label="Speech block text"]').first.wait_for(state="visible", timeout=20_000)
        await page.wait_for_timeout(2500)
        logger.info("[Speech] đã mở trang Generate speech")

    async def _new_dialog(self, page: Any) -> None:
        """Sang hộp thoại mới trong cùng trang (giữ trang "ấm"): bấm New chat, vào lại màn soạn nếu hiện màn chọn mẫu."""
        await page.get_by_role("button", name="New chat").first.click()
        await page.wait_for_timeout(2500)
        landing = page.get_by_text("Create new dialog")
        if await landing.count() and await landing.first.is_visible():
            await landing.first.click()
            await page.wait_for_timeout(2500)
        await page.locator('textarea[aria-label="Speech block text"]').first.wait_for(state="visible", timeout=20_000)
        self._dirty = False

    async def _current_voice(self, page: Any) -> str:
        label = await page.get_by_role("button", name=re.compile(r"^Speaker 1")).first.inner_text()
        match = re.search(r"Speaker 1\s*-\s*(.+?)(?:\s+arrow_drop_down)?\s*$", label.strip())
        return match.group(1).strip() if match else label.strip()

    async def _ensure_voice(self, page: Any, voice: str) -> None:
        """Đặt giọng của Speaker 1: mở Speaker settings, tìm theo tên, bấm đúng nút. Giọng đã đúng thì không làm gì."""
        if (await self._current_voice(page)).lower() == voice.lower():
            return
        await page.get_by_role("button", name=re.compile(r"^Speaker 1")).first.click()
        await page.wait_for_timeout(1500)
        search = page.get_by_placeholder(re.compile(r"Search .*voices")).first
        await search.click()
        await page.keyboard.type(voice, delay=60)
        await page.wait_for_timeout(2500)
        hit = page.get_by_role("button", name=re.compile(rf"^{re.escape(voice)}\b", re.I))
        found = await hit.count() > 0
        if found:
            await hit.first.click()
            await page.wait_for_timeout(1200)
        await page.get_by_role("button", name="Close panel").first.click()
        await page.wait_for_timeout(800)
        if not found:
            raise SpeechError(f'Không tìm thấy giọng "{voice}" trong AI Studio.', 400)
        logger.info(f"[Speech] đã chọn giọng {voice}")

    async def _ensure_page(self, chat_page: Any) -> Any:
        if self._page is None or self._page.is_closed():
            await self._open(chat_page)
        return self._page

    async def _click_run(self, page: Any) -> None:
        """Bấm Run như người thật: di chuột tới nút rồi nhấn thả. Bấm kiểu thẳng (locator.click) hay bị Google trả 403."""
        run = page.get_by_role("button", name=re.compile(r"^Run")).first
        box = await run.bounding_box()
        if not box:
            raise SpeechError("Không thấy nút Run trên trang speech.")
        await page.mouse.move(box["x"] - 140 + random.uniform(-15, 15), box["y"] - 70 + random.uniform(-10, 10), steps=14)
        await page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=20)
        await page.wait_for_timeout(600)
        await page.mouse.down()
        await page.wait_for_timeout(90)
        await page.mouse.up()

    async def synthesize(self, chat_page: Any, text: str, voice: str = DEFAULT_VOICE) -> Tuple[bytes, int]:
        """Đọc `text` bằng giọng `voice` (tên trong AI Studio), trả (PCM 16-bit mono, tần số)."""
        text = text.strip()
        if not text:
            raise SpeechError("Chưa có nội dung để đọc.", 400)
        if len(text) > MAX_INPUT_CHARS:
            raise SpeechError(f"Văn bản quá dài ({len(text)} ký tự, tối đa {MAX_INPUT_CHARS}).", 400)
        async with self._lock:
            started = time.time()
            try:
                return await self._synthesize_locked(chat_page, text, voice)
            except SpeechError:
                raise
            except Exception as exc:  # noqa: BLE001
                # Trang hỏng giữa chừng (đóng, treo, giao diện đổi): bỏ trang để yêu cầu sau mở lại
                logger.error(f"[Speech] lỗi sau {time.time() - started:.1f}s: {exc}")
                await self.close()
                raise SpeechError(f"Trang Generate speech lỗi: {exc}") from exc

    async def _synthesize_locked(self, chat_page: Any, text: str, voice: str) -> Tuple[bytes, int]:
        page = await self._ensure_page(chat_page)
        if self._dirty:
            await self._new_dialog(page)
        await self._ensure_voice(page, voice)
        textarea = page.locator('textarea[aria-label="Speech block text"]').first
        await textarea.click()
        await page.keyboard.press("Control+A")
        await textarea.fill(text)
        # Gõ thêm rồi xoá một ký tự để ô nhập báo "đã thay đổi" cho Angular
        await page.keyboard.type(" ", delay=30)
        await page.keyboard.press("Backspace")
        timeout = BASE_TIMEOUT_S + PER_CHAR_TIMEOUT_S * len(text)
        last_status = 0
        for attempt in range(1, MAX_CLICKS + 1):
            await page.wait_for_timeout(5000 if attempt == 1 else 4000)
            while not self._responses.empty():
                self._responses.get_nowait()
            began = time.time()
            await self._click_run(page)
            try:
                status, body = await asyncio.wait_for(self._responses.get(), timeout=timeout)
            except asyncio.TimeoutError as exc:
                await self.close()
                raise SpeechError(f"AI Studio không trả audio sau {timeout:.0f} giây.", 504) from exc
            last_status = status
            if status == 200:
                pcm, rate = parse_audio(body)
                logger.info(f"[Speech] {len(text)} ký tự -> {len(pcm) / (rate * 2):.1f}s audio sau {time.time() - began:.1f}s (lần bấm {attempt})")
                self._dirty = True
                return pcm, rate
            logger.warning(f"[Speech] lần bấm {attempt}: HTTP {status} {body[:80]!r}")
        # Mỗi lần mở trang mới BotGuard lại chấm lại từ đầu: bỏ trang để lần sau thử lại từ trạng thái sạch
        await self.close()
        raise SpeechError(f"AI Studio từ chối {MAX_CLICKS} lần bấm Run liên tiếp (HTTP {last_status}).", 502)


speech_service = SpeechService()
