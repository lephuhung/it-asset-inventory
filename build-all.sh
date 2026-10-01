#!/usr/bin/env bash
# Build toàn bộ 2 thành phần (chạy từ root repo). Agent đã tách repo riêng. Mỗi phần độc lập; lỗi một phần không chặn phần khác.
set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAIL=0

echo "========== [1/2] Server FastAPI =========="
if [ -d "$ROOT/server" ]; then
  ( cd "$ROOT/server" && \
    if [ ! -d .venv ]; then python3 -m venv .venv; fi && \
    .venv/bin/pip install -q -e ".[dev]" && \
    .venv/bin/python -m compileall -q app && echo "  [OK] server compile" ) || { echo "  [FAIL] server"; FAIL=1; }
else
  echo "  [SKIP] chưa có server/"
fi

echo "========== [2/2] Portal Next.js =========="
if [ -d "$ROOT/portal" ]; then
  ( cd "$ROOT/portal" && \
    pnpm install --frozen-lockfile && \
    pnpm typecheck && pnpm build ) || { echo "  [FAIL] portal"; FAIL=1; }
else
  echo "  [SKIP] chưa có portal/"
fi

echo
if [ "$FAIL" -eq 0 ]; then echo "✅ BUILD TOÀN BỘ THÀNH CÔNG"; else echo "❌ CÓ THÀNH PHẦN LỖI — xem log trên"; fi
exit $FAIL
