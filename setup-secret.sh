#!/usr/bin/env bash
# Tạo namespace aistudio và secret aistudio-auth từ auth/main.json (cookie Google) và auth/key.txt (API key).
# Chạy lại để cập nhật secret: key.txt được nạp lại mỗi lần pod khởi động,
# còn main.json chỉ được chép vào PVC khi PVC chưa có file (xem initContainer trong aistudio-proxy.yaml).
set -euo pipefail
export KUBECONFIG=~/.kube/config
cd "$(dirname "$0")"

kubectl get namespace aistudio >/dev/null 2>&1 || kubectl create namespace aistudio

kubectl -n aistudio create secret generic aistudio-auth \
    --from-file=main.json=auth/main.json \
    --from-file=key.txt=auth/key.txt \
    --dry-run=client -o yaml | kubectl apply -f -
echo "đã tạo/cập nhật secret aistudio-auth"
