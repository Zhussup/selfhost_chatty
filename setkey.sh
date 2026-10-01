#!/usr/bin/env bash
# Записывает ключ Ollama Cloud в .env правильной строкой.
# Запустить в терминале проекта:  ./setkey.sh   затем вставить ключ и Enter.
set -euo pipefail
cd "$(dirname "$0")"

VENV=.venv
[ -d "$VENV" ] || python3 -m venv "$VENV"
[ -f .env ] || touch .env

printf "Ключ с ollama.com/settings/keys > "
read -r KEY
if [ -z "$KEY" ]; then
  echo "пусто — ничего не записано" >&2
  exit 1
fi
# обрезать возможные кавычки по краям
KEY="${KEY%\"}"; KEY="${KEY#\"}"; KEY="${KEY%\'}"; KEY="${KEY#\'}"

"$VENV/bin/python" - "$KEY" <<'PY'
import re, sys
key = sys.argv[1]
txt = open(".env").read()
if re.search(r'^OLLAMA_API_KEY=', txt, re.M):
    txt = re.sub(r'^OLLAMA_API_KEY=.*$', 'OLLAMA_API_KEY=' + key, txt, count=1, flags=re.M)
else:
    txt = txt.rstrip("\n") + "\n\nOLLAMA_API_KEY=" + key + "\n"
open(".env", "w").write(txt)
print(f"готово: сохранён ключ длиной {len(key)} символов")
PY

"$VENV/bin/python" - <<'PY'
import re
txt = open(".env").read()
m = re.search(r'^OLLAMA_API_KEY=(\S+)', txt, re.M)
if m and len(m.group(1)) >= 10:
    print("строка в .env на месте: длина =", len(m.group(1)))
else:
    print("ПРЕДУПРЕЖДЕНИЕ: строка пустая или подозрительно короткая")
PY

echo "теперь перезапусти:  ./run.sh   (или ./dev.sh)"