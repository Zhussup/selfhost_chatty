#!/usr/bin/env bash
# Dev-режим: uvicorn --reload (бэкенд) + vite dev (фронт, hot-reload).
# /api запросы вит dev-сервера проксируются к бэкенду (BACKEND_PORT).
# Ctrl+C останавливает оба процесса.
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
    echo "[ERR] все порты $ORIG-$((ORIG + 10)) заняты" >&2
    exit 1
  fi
  echo "[WARN] порт $ORIG занят сторонним процессом — бэкенд на $APP_PORT" >&2
fi

echo "[dev] backend: http://localhost:$APP_PORT"
echo "[dev] vite:    http://localhost:5173  (если занят, vite возьмёт следующий)"

BACKEND_PORT="$APP_PORT" npm --prefix frontend run dev &
VITE_PID=$!
trap 'kill "$VITE_PID" 2>/dev/null || true' EXIT

# uvicorn в foreground: Ctrl+C уходит ко всей группе (vite получит тоже), EXIT-trap добьёт остатки
"$VENV/bin/uvicorn" backend.app:app --host 0.0.0.0 --port "$APP_PORT"