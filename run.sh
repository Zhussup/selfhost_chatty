#!/usr/bin/env bash
# Весь проект одной командой: venv → deps → фронт-билд (если нет dist) → uvicorn.
#   ./run.sh                  — запуск (фронт соберётся сам, если его ещё нет)
#   RUN_FRONTEND=1 ./run.sh   — принудительно пересобрать фронт перед стартом
#   ./dev.sh                  — dev-режим с hot-reload (uvicorn --reload + vite)
set -euo pipefail
cd "$(dirname "$0")"

VENV=.venv
if [ ! -d "$VENV" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q -r requirements.txt

# фронт: install + build, если dist отсутствует (или RUN_FRONTEND=1 — пересборка)
if [ -f frontend/package.json ] && { [ ! -d frontend/dist ] || [ "${RUN_FRONTEND:-0}" = "1" ]; }; then
  npm --prefix frontend install --no-audit --no-fund
  npm --prefix frontend run build
fi

# порт: переменная окружения > .env > 8000; если занят — ближайший свободный
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
  echo "[WARN] порт $ORIG занят сторонним процессом — запускаюсь на $APP_PORT" >&2
fi

exec "$VENV/bin/uvicorn" backend.app:app --host 0.0.0.0 --port "$APP_PORT"