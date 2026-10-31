# Image AIstudioProxyAPI đã vá cho giao diện AI Studio 10/2026.
# Base localhost/aistudio-proxy:044c3db = build nguyên bản từ docker/Dockerfile của upstream (commit 044c3db).
# Nội dung vá xem aistudio-fixes.patch:
#   - viewport 1440x900 để panel Run settings hiện (PR #323 upstream)
#   - click thật vào ô nhập trước khi gửi, nếu không Google trả "The caller does not have permission"
#   - selector nút Run và ô stop sequence theo giao diện mới
#   - bỏ qua temperature/top_p khi model không còn thanh trượt (Gemini 3.x)
#   - (fix2) POST /v1/audio/speech: đọc văn bản bằng trang Generate speech (browser_utils/speech.py, api_utils/routers/audio.py)
#   - (fix3) route speech lấy processing_lock của hàng đợi chat: đọc và chat không chạy chồng nhau
#
# Build: podman build -t localhost/aistudio-proxy:044c3db-fix3 ~/aistudio-proxy
# Nạp vào k3s: podman save localhost/aistudio-proxy:044c3db-fix3 | sudo k3s ctr images import -
FROM localhost/aistudio-proxy:044c3db

COPY --chown=appuser:appgroup src/ /app/
