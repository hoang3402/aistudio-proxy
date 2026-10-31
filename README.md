# aistudio-proxy

Bản triển khai và bản vá của [AIstudioProxyAPI](https://github.com/CJackHwang/AIstudioProxyAPI.git) để chạy trong k3s:
một API kiểu OpenAI chạy qua giao diện web Google AI Studio (Camoufox headless), chỉ mở trong cluster và được
CLIProxyAPI gọi tới như nhà cung cấp `openai-compatibility` tên `aistudio`.

## Nguồn gốc và giấy phép

- Mã nguồn gốc: [CJackHwang/AIstudioProxyAPI](https://github.com/CJackHwang/AIstudioProxyAPI.git), commit `044c3db`, giấy phép **GNU AGPL-3.0**.
- Các file trong `src/` là **bản sao đã sửa** của file upstream (cùng đường dẫn, chép đè lên `/app` khi build), nên repo này cũng theo AGPL-3.0 (xem `LICENSE`).
- Proxy chỉ chạy nội bộ, không phục vụ người ngoài; nếu bạn mở ra ngoài, AGPL yêu cầu cung cấp mã nguồn cho người dùng đó.

## Có gì trong repo

| Đường dẫn | Việc |
|---|---|
| `src/` | file upstream đã vá (chép đè lên `/app`) |
| `aistudio-fixes.patch` | các bản vá giao diện ở dạng diff so với upstream `044c3db` |
| `aistudio-speech.patch` | phần sửa `api_utils/app.py` để đăng ký route speech (file mới: `browser_utils/speech.py`, `api_utils/routers/audio.py`) |
| `Containerfile` | image vá, dựng trên image upstream |
| `aistudio-proxy.yaml` | Namespace, PVC, Deployment, Service (ClusterIP, không Ingress) |
| `setup-secret.sh` | tạo secret `aistudio-auth` từ `auth/` |
| `add-to-cliproxyapi.sh` | đăng ký nhà cung cấp `aistudio` vào CLIProxyAPI qua Management API |

## Các bản vá (giao diện AI Studio 10/2026)

- Viewport 1440x900 để panel Run settings hiện (PR #323 của upstream).
- Click thật vào ô nhập trước khi gửi, nếu không Google trả "The caller does not have permission" (BotGuard).
- Selector nút Run và ô stop sequence theo giao diện mới.
- Bỏ qua temperature và top_p khi model không còn thanh trượt (Gemini 3.x).
- Bắt buộc `STREAM_PORT=0`: proxy luồng MITM tích hợp luôn nhận 403 từ Google.
- **Generate speech** (`fix2`): thêm `POST /v1/audio/speech`, xem mục dưới.

## Dựng lại từ đầu

Image nền `localhost/aistudio-proxy:044c3db` **không nằm trong repo** (6 GB, chỉ có trên máy dựng). Dựng lại:

```sh
git clone https://github.com/CJackHwang/AIstudioProxyAPI.git
cd AIstudioProxyAPI && git checkout 044c3db
podman build -f docker/Dockerfile -t localhost/aistudio-proxy:044c3db .   # context là gốc repo upstream
cd - && podman build -t localhost/aistudio-proxy:044c3db-fix4 .            # image vá của repo này
podman save localhost/aistudio-proxy:044c3db-fix4 | sudo k3s ctr images import -
```

## Bí mật (không có trong repo)

Tạo thư mục `auth/` (đã được `.gitignore`):

- `auth/main.json`: storage state đăng nhập Google, lấy bằng `launch_camoufox.py --debug --save-auth-as ...` của upstream.
- `auth/key.txt`: API key do bạn đặt; mọi request `/v1/*` cần header `Authorization: Bearer <key>`.

## Triển khai

```sh
./setup-secret.sh                       # secret aistudio-auth
kubectl apply -f aistudio-proxy.yaml
./add-to-cliproxyapi.sh                 # tuỳ chọn: đăng ký vào CLIProxyAPI (namespace cli)
```

Cookie hết hạn: thay `auth/main.json`, chạy lại `setup-secret.sh`, xoá `/app/auth_profiles/active/main.json` trong pod rồi restart Deployment.

## Generate speech: `POST /v1/audio/speech`

Đọc văn bản bằng trang https://aistudio.google.com/generate-speech (model Gemini TTS đang hiện trong Run settings, hiện là `gemini-3.8-flash-tts`),
theo khuôn OpenAI để client OpenAI dùng được. Gọi thẳng vào Service của proxy: **CLIProxyAPI không chuyển `/v1/audio/speech` tới nhà cung cấp này**
(nó chỉ chuyển cho xAI, `grok-tts`).

```sh
curl -sS http://aistudio-proxy.aistudio.svc.cluster.local:2048/v1/audio/speech \
  -H "Authorization: Bearer $(cat auth/key.txt)" -H 'Content-Type: application/json' \
  -d '{"input":"Xin chào, đây là thử giọng đọc.","voice":"Lumi","response_format":"wav"}' -o out.wav
```

| Tham số | Ghi chú |
|---|---|
| `input` | tối đa 20.000 ký tự; đã thử 3.593 ký tự (≈ 4 phút audio) |
| `voice` | tên giọng của AI Studio (vd `Lumi`, `Fola`); trống hoặc tên giọng OpenAI (`alloy`…) thì dùng `Fola`; không có giọng đó thì 400 |
| `response_format` | `wav` (mặc định) hoặc `pcm` (16-bit little-endian mono 24 kHz). Không có mp3/opus vì image không có bộ mã hoá |
| `model`, `speed` | bị bỏ qua |

Header trả về: `X-Audio-Seconds`, `X-Audio-Sample-Rate`.

### Cách hoạt động (đã đo thật, 10/2026)

- Một trang riêng trong **context riêng** của cùng trình duyệt (tách localStorage khỏi trang chat), mở lười ở yêu cầu đầu rồi giữ mở (yêu cầu đầu tốn thêm ~15 giây). Trang đang mở nhưng rảnh thì không ảnh hưởng chat.
- Audio không lấy từ thẻ `<audio>` mà bắt phản hồi RPC `MakerSuiteService/GenerateContent`: JSON lồng nhau, mỗi đoạn là `["audio/l16; rate=24000; channels=1", "<base64>"]`; ghép các đoạn (khoảng 80 đoạn cho câu ngắn) thành PCM little-endian.
- Bấm Run phải giống người thật (di chuột tới nút rồi nhấn thả, sau vài giây trang mở): bấm thẳng thì Google trả 403 "The caller does not have permission" (BotGuard). Đo được 10 trên 11 lần đầu thành công, nên có thử lại tối đa 3 lần bấm.
- Sau mỗi kết quả nút Run bị khoá (`aria-disabled`); Pause không mở lại được. Phải bấm **New chat** để sang hộp thoại mới trước lần đọc kế.
- Mỗi yêu cầu có chi phí cố định cỡ 10 giây (sang hộp thoại mới, chọn giọng, chờ trước khi bấm).

| Văn bản | Audio | Thời gian sinh |
|---|---|---|
| 30 ký tự | 2,5 giây | 2,3 đến 3,3 giây |
| 466 ký tự | 31 giây | 9,5 giây |
| 3.593 ký tự | 247 giây | 53,5 giây |

### Giới hạn

- Mỗi lần chỉ một yêu cầu (một trang): yêu cầu khác xếp hàng chờ.
- Đọc và chat dùng chung `processing_lock`, nên **không chạy chồng nhau** (đọc 3.600 ký tự giữ khoá khoảng 1 phút). Bản `fix2` không có khoá này: đo thật, chat chạy chồng với một lần đọc bị hỏng việc lấy lại nội dung trả lời và làm hỏng luôn yêu cầu chat kế tiếp.
- Khoá được giữ thêm `SPEECH_SETTLE_SECONDS` (mặc định 15, `0` = tắt) sau một lần đọc thành công; WAV vẫn trả về ngay. Lý do (đo thật, tái hiện 2/2): lượt chat **đầu tiên sau khi pod khởi động** (phải chọn model) mà chạy ngay lúc đọc vừa xong thì Google không trả lời (khối câu trả lời hiện ra, chữ không tới, 500 sau ~90 giây). Chạy chat đầu sau đó 15 giây, hoặc khi chat đã chạy trước đó, thì ổn. Chưa rõ cơ chế: đây là giảm thiểu, không phải nguyên nhân. Hệ quả: hai yêu cầu đọc liên tiếp cách nhau thêm tối đa 15 giây.
- Bộ lọc ngôn ngữ của danh sách giọng không có tiếng Việt; văn bản tiếng Việt vẫn được đọc, chất lượng cần nghe thử.
- Phụ thuộc giao diện trang Generate speech (nhãn nút "New chat", "Create new dialog", ô `Speech block text`, panel "Speaker settings"): Google đổi giao diện thì phải sửa selector trong `browser_utils/speech.py`.
- Chưa chọn được model khác và chưa có chế độ nhiều người nói.
