#!/usr/bin/env bash
# Thêm (hoặc cập nhật) nhà cung cấp openai-compatibility "aistudio" trong CLIProxyAPI (namespace cli),
# trỏ tới service aistudio-proxy trong cluster. Giữ nguyên các mục khác (orcarouter...).
# Đi qua Management API nên thay đổi được lưu vào git store của CLIProxyAPI. Không in key ra màn hình.
set -euo pipefail
export KUBECONFIG=~/.kube/config
cd "$(dirname "$0")"

port=18317
kubectl -n cli port-forward deploy/cli-proxy-api-plus "$port:8317" >/dev/null 2>&1 &
pf=$!
trap 'kill $pf 2>/dev/null' EXIT
sleep 3

export MGMT_KEY=$(kubectl -n cli get secret cli-proxy-secret -o jsonpath='{.data.MANAGEMENT_PASSWORD}' | base64 -d)
export AISTUDIO_KEY=$(cat auth/key.txt)
url="http://127.0.0.1:$port/v0/management/openai-compatibility"

curl -sf -H "Authorization: Bearer $MGMT_KEY" "$url" | python3 -I -c '
import json, os, sys
items = json.load(sys.stdin)["openai-compatibility"]
for it in items:
    for k in it.get("api-key-entries") or []:
        k.pop("auth-index", None)
items = [it for it in items if it.get("name") != "aistudio"]
items.append({
    "name": "aistudio",
    "base-url": "http://aistudio-proxy.aistudio.svc.cluster.local:2048/v1",
    "api-key-entries": [{"api-key": os.environ["AISTUDIO_KEY"]}],
    "models": [
        {"name": "gemini-3.8-flash", "alias": "AI Studio Gemini 3.8 Flash"},
        {"name": "gemini-3.1-pro-preview", "alias": "AI Studio Gemini 3.1 Pro"},
        {"name": "gemini-4-argon", "alias": "AI Studio Gemini 4 Argon"},
    ],
})
json.dump(items, open("/dev/stdout", "w"))
' | curl -sf -X PUT -H "Authorization: Bearer $MGMT_KEY" -H 'Content-Type: application/json' --data-binary @- "$url" >/dev/null

curl -sf -H "Authorization: Bearer $MGMT_KEY" "$url" | python3 -I -c '
import json, sys
for it in json.load(sys.stdin)["openai-compatibility"]:
    print(it["name"], it["base-url"], [m.get("alias") or m["name"] for m in it.get("models") or []])
'
