# Image AIstudioProxyAPI đã vá cho giao diện AI Studio 10/2026.
# Base localhost/aistudio-proxy:044c3db = build nguyên bản từ docker/Dockerfile của upstream (commit 044c3db).
# Nội dung vá xem aistudio-fixes.patch:
#   - viewport 1440x900 để panel Run settings hiện (PR #323 upstream)
#   - click thật vào ô nhập trước khi gửi, nếu không Google trả "The caller does not have permission"
#   - selector nút Run và ô stop sequence theo giao diện mới
#   - bỏ qua temperature/top_p khi model không còn thanh trượt (Gemini 3.x)
#
# Build: podman build -t localhost/aistudio-proxy:044c3db-fix1 ~/aistudio-proxy
# Nạp vào k3s: podman save localhost/aistudio-proxy:044c3db-fix1 | sudo k3s ctr images import -
FROM localhost/aistudio-proxy:044c3db

COPY --chown=appuser:appgroup src/ /app/
