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
| `aistudio-fixes.patch` | các bản vá ở dạng diff so với upstream `044c3db` |
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

## Dựng lại từ đầu

Image nền `localhost/aistudio-proxy:044c3db` **không nằm trong repo** (6 GB, chỉ có trên máy dựng). Dựng lại:

```sh
git clone https://github.com/CJackHwang/AIstudioProxyAPI.git
cd AIstudioProxyAPI && git checkout 044c3db
podman build -f docker/Dockerfile -t localhost/aistudio-proxy:044c3db .   # context là gốc repo upstream
cd - && podman build -t localhost/aistudio-proxy:044c3db-fix1 .            # image vá của repo này
podman save localhost/aistudio-proxy:044c3db-fix1 | sudo k3s ctr images import -
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
