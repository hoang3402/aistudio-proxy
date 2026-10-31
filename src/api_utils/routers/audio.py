"""POST /v1/audio/speech: đọc văn bản bằng trang Generate speech của AI Studio (xem browser_utils/speech.py).

Theo khuôn của OpenAI (model, input, voice, response_format) để client OpenAI dùng được. Khác biệt cần biết:
- response_format chỉ có "wav" (mặc định) và "pcm" (16-bit little-endian mono, 24 kHz): image không có bộ mã hoá mp3/opus.
- `voice` là tên giọng của AI Studio (vd "Lumi"); tên giọng OpenAI (alloy, echo, nova…) hoặc để trống thì dùng giọng mặc định.
- `model` hiện bị bỏ qua: trang dùng model đang hiện trong Run settings (gemini-3.8-flash-tts).
- `speed` bị bỏ qua.
"""

import logging
from typing import Optional

from fastapi import Depends
from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from browser_utils.speech import DEFAULT_VOICE, SpeechError, pcm_to_wav, speech_service

from ..dependencies import get_logger, get_page_instance, get_server_state

router = APIRouter()

OPENAI_VOICES = {"alloy", "ash", "ballad", "coral", "echo", "fable", "nova", "onyx", "sage", "shimmer", "verse"}


class SpeechRequest(BaseModel):
    model: Optional[str] = None
    input: str
    voice: Optional[str] = None
    response_format: str = "wav"
    speed: Optional[float] = None


def _error(status: int, message: str, code: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"message": message, "type": "invalid_request_error" if status < 500 else "server_error", "param": None, "code": code}})


@router.post("/v1/audio/speech")
async def create_speech(
    request: SpeechRequest,
    logger: logging.Logger = Depends(get_logger),
    server_state: dict = Depends(get_server_state),
    page=Depends(get_page_instance),
):
    fmt = request.response_format.lower()
    if fmt not in ("wav", "pcm"):
        return _error(400, f'response_format "{request.response_format}" chưa hỗ trợ: chỉ có "wav" và "pcm" (không có bộ mã hoá mp3/opus trong image).', "unsupported_response_format")
    if not (server_state.get("is_page_ready") and server_state.get("is_browser_connected")) or page is None:
        return _error(503, "Trình duyệt hoặc trang AI Studio chưa sẵn sàng.", "service_unavailable")
    voice = request.voice.strip() if request.voice else None
    if voice and voice.lower() in OPENAI_VOICES:
        voice = None
    try:
        pcm, rate = await speech_service.synthesize(page, request.input, voice or DEFAULT_VOICE)
    except SpeechError as exc:
        logger.warning(f"[Speech] {exc.status}: {exc}")
        return _error(exc.status, str(exc), "speech_failed")
    seconds = len(pcm) / (rate * 2)
    headers = {"X-Audio-Seconds": f"{seconds:.2f}", "X-Audio-Sample-Rate": str(rate)}
    if fmt == "pcm":
        return Response(content=pcm, media_type=f"audio/L16;rate={rate};channels=1", headers=headers)
    return Response(content=pcm_to_wav(pcm, rate), media_type="audio/wav", headers=headers)
