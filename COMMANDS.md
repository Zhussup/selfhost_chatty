# Project commands — cheat sheet

## 1. First time

```bash
cd ~/Desktop/projects/selfhost_chat
./setkey.sh               # asks for the key from ollama.com/settings/keys and writes it to .env
                          # (you can set the login password in .env as AUTH_PASSWORD=...)
```

## 2. Run everything (one command from anywhere)

```bash
chatty                    # start the server in the background and open the browser
chatty status             # is it up, on which port, does it answer
chatty stop               # stop it
chatty restart            # stop + start
chatty logs               # tail -f the background server's log
chatty fg                 # in the current terminal (Ctrl+C = stop), like ./run.sh
chatty dev                # dev mode: uvicorn + vite (Ctrl+C stops both)
```

- Installed once: `./bin/chatty install` (symlinks into `~/.local/bin/chatty`)
- Running `chatty` again while a server is live does **not** start a second one — it just opens a tab
- It also finds a server started by hand (`./run.sh`) and reports it

```bash
./run.sh                  # the same, but in the current terminal
RUN_FRONTEND=1 ./run.sh   # force a frontend rebuild (after editing src/)
```

- Port: if 8000 is taken (jupyterhub), it hops to a free one and prints
  `[WARN] ... — starting on NNNN`; pin it in `.env` with `APP_PORT=8001`
- chatty runtime (pid, log, url) lives in `.run/`, which is not committed

## 3. Development without rebuilds

```bash
./dev.sh                  # backend + vite dev server, one Ctrl+C for both
```

- Open **http://localhost:5173** (vite); `/api` is proxied to the backend
- Frontend edits reload live. The backend runs **without** `--reload`, so restart
  `./dev.sh` after changing Python — or add `--reload` to `dev.sh` if you want it
  (it re-runs `db.init()` and re-imports the app on every edit)

## 4. Stopping, and stuck processes

```bash
chatty stop                               # background server started through chatty
# Ctrl+C in the terminal running the script (./run.sh, ./dev.sh, chatty fg)
pkill -f "uvicorn backend.app"            # if it was started elsewhere / is hung
pkill -f vite                             # if the frontend dev server is hung
```

## 5. Tests

```bash
.venv/bin/python -m unittest discover -s tests   # stubbed upstream, no API key needed
npm --prefix frontend run build                  # typecheck + production build
```

## 6. Checking a live server

```bash
curl localhost:8000/healthz                # or whichever port chatty chose
grep '^AUTH_PASSWORD' .env                 # your password, for logging in
curl -sb cookies.txt localhost:8000/api/modes   # the chat mode registry
```

## 7. Cleaning up port 8000 (optional)

```bash
sudo systemctl disable --now jupyterhub    # disable the squatter for good
```

## 8. Data

```bash
.venv/bin/python -c "import sqlite3; sqlite3.connect('data/chat.db').execute('PRAGMA wal_checkpoint;')"
cp data/chat.db ~/backups/chat-$(date +%F).db   # a backup is a copy of the file
```
