#!/usr/bin/env bash
# Writes the Ollama Cloud key into .env as a proper line.
# Run it in the project terminal:  ./setkey.sh   then paste the key and press Enter.
set -euo pipefail
cd "$(dirname "$0")"

VENV=.venv
[ -d "$VENV" ] || python3 -m venv "$VENV"
[ -f .env ] || touch .env

printf "Key from ollama.com/settings/keys > "
read -r KEY
if [ -z "$KEY" ]; then
  echo "empty — nothing was written" >&2
  exit 1
fi
# strip possible surrounding quotes
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
print(f"done: saved a key of {len(key)} characters")
PY

"$VENV/bin/python" - <<'PY'
import re
txt = open(".env").read()
m = re.search(r'^OLLAMA_API_KEY=(\S+)', txt, re.M)
if m and len(m.group(1)) >= 10:
    print("the .env line is in place: length =", len(m.group(1)))
else:
    print("WARNING: the line is empty or suspiciously short")
PY

echo "now restart:  ./run.sh   (or ./dev.sh)"