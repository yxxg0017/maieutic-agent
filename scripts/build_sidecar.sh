#!/usr/bin/env bash
# 构建独立 sidecar 可执行文件（macOS / Linux）。
# 产物命名必须带 Rust target triple，Tauri externalBin 才能解析。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
OUT_DIR="$ROOT/apps/desktop/src-tauri/binaries"
VENV="$BACKEND/.venv"

if [[ ! -x "$VENV/bin/python" ]]; then
  echo "创建虚拟环境：$VENV"
  uv venv --python 3.11 "$VENV"
fi

"$VENV/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
(cd "$BACKEND" && uv pip install --python "$VENV/bin/python" -e ".[dev]")

TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"
mkdir -p "$OUT_DIR"

rm -rf "$BACKEND/build" "$BACKEND/dist"
(cd "$BACKEND" && "$VENV/bin/python" -m PyInstaller \
  --noconfirm --clean --onefile \
  --name kel-sidecar \
  --paths src \
  --collect-all langgraph \
  --collect-all langgraph_checkpoint \
  --collect-all langchain_core \
  --collect-submodules kel \
  --hidden-import aiosqlite \
  --hidden-import sqlite3 \
  --hidden-import keyring.backends.macOS \
  --hidden-import keyring.backends.Windows \
  --hidden-import keyring.backends.SecretService \
  sidecar_entry.py)

cp "$BACKEND/dist/kel-sidecar" "$OUT_DIR/kel-sidecar-$TRIPLE"
chmod +x "$OUT_DIR/kel-sidecar-$TRIPLE"
echo "已生成 $OUT_DIR/kel-sidecar-$TRIPLE"

# smoke test：ready 事件、健康检查与迁移
SMOKE_DIR="$(mktemp -d)"
KEL_SESSION_TOKEN=smoketoken "$OUT_DIR/kel-sidecar-$TRIPLE" --data-dir "$SMOKE_DIR" >"$SMOKE_DIR/ready.json" 2>"$SMOKE_DIR/err.log" &
SIDECAR_PID=$!
trap 'kill $SIDECAR_PID 2>/dev/null || true; rm -rf "$SMOKE_DIR"' EXIT

for _ in $(seq 1 60); do
  if grep -q '"event": "ready"' "$SMOKE_DIR/ready.json" 2>/dev/null; then break; fi
  sleep 1
done

PORT="$(python3 -c "import json;print(json.load(open('$SMOKE_DIR/ready.json'))['port'])")"
curl -fsS -H "Authorization: Bearer smoketoken" "http://127.0.0.1:$PORT/health" >/dev/null
SESSION="$(curl -fsS -X POST -H "Authorization: Bearer smoketoken" -H 'Content-Type: application/json' \
  -d '{"title":"smoke"}' "http://127.0.0.1:$PORT/v1/sessions" | python3 -c "import json,sys;print(json.load(sys.stdin)['session_id'])")"
curl -fsS -X POST -H "Authorization: Bearer smoketoken" -H 'Content-Type: application/json' \
  -d '{"content":"最小 smoke 会话"}' "http://127.0.0.1:$PORT/v1/sessions/$SESSION/messages" >/dev/null
curl -fsS -X POST -H "Authorization: Bearer smoketoken" "http://127.0.0.1:$PORT/shutdown" >/dev/null
echo "smoke test 通过"
