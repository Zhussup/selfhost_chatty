#!/usr/bin/env bash
# Dev mode: uvicorn (backend) + vite dev (frontend). Vite reloads on frontend
# edits; the backend has no --reload, so restart it after changing Python.
# /api requests from the vite dev server are proxied to the backend (BACKEND_PORT).
# Ctrl+C stops both processes.
set -euo pipefail
cd "$(dirname "$0")"

VENV=.venv
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
if [ ! -d frontend/node_modules ]; then
  npm --prefix frontend install --no-audit --no-fund
fi

if [ -z "${APP_PORT:-}" ] && [ -f .env ]; then
  APP_PORT=$(grep -E '^APP_PORT=' .env | head -1 | cut -d= -f2- | tr -d ' "') || true
fi
APP_PORT=${APP_PORT:-8000}

port_free() {
  "$VENV/bin/python" - "$1" <<'PY'
import errno, socket, sys
port = int(sys.argv[1])
bad = False
for fam, addr in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
    s = socket.socket(fam)
    try:
        s.bind((addr, port))
    except OSError as e:
        if e.errno in (errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL):
            continue          # family unsupported on this host — ignore
        bad = True            # address in use
    finally:
        s.close()
sys.exit(1 if bad else 0)
PY
}
if ! port_free "$APP_PORT"; then
  ORIG=$APP_PORT
  for p in $(seq "$((ORIG + 1))" "$((ORIG + 10))"); do
    if port_free "$p"; then APP_PORT=$p; break; fi
  done
  if [ "$APP_PORT" = "$ORIG" ]; then
    echo "[ERR] every port in $ORIG-$((ORIG + 10)) is taken" >&2
    exit 1
  fi
  echo "[WARN] port $ORIG is taken by another process — backend on $APP_PORT" >&2
fi

echo "[dev] backend: http://localhost:$APP_PORT"
echo "[dev] vite:    http://localhost:5173  (if taken, vite picks the next one)"

BACKEND_PORT="$APP_PORT" npm --prefix frontend run dev &
VITE_PID=$!
trap 'kill "$VITE_PID" 2>/dev/null || true' EXIT

# uvicorn in the foreground: Ctrl+C reaches the whole group (vite gets it too), the EXIT-trap clears the rest
"$VENV/bin/uvicorn" backend.app:app --host 0.0.0.0 --port "$APP_PORT"