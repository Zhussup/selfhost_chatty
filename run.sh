#!/usr/bin/env bash
# The whole project in one command: venv -> deps -> frontend build (if dist is missing) -> uvicorn.
#   ./run.sh                  — start (the frontend builds itself if it is not there yet)
#   RUN_FRONTEND=1 ./run.sh   — force a frontend rebuild before starting
#   ./dev.sh                  — dev mode (uvicorn + vite dev server)
set -euo pipefail
cd "$(dirname "$0")"

VENV=.venv
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q -r requirements.txt

# frontend: install + build when dist is missing (or RUN_FRONTEND=1 — rebuild)
if [ -f frontend/package.json ] && { [ ! -d frontend/dist ] || [ "${RUN_FRONTEND:-0}" = "1" ]; }; then
  npm --prefix frontend install --no-audit --no-fund
  npm --prefix frontend run build
fi

# port: env var > .env > 8000; if taken — the nearest free one
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
  echo "[WARN] port $ORIG is taken by another process — starting on $APP_PORT" >&2
fi

exec "$VENV/bin/uvicorn" backend.app:app --host 0.0.0.0 --port "$APP_PORT"