
# selfhost chat
<p align="center">
  <img src="chatty_logo.png" alt="chatty" width="440">
</p>

A minimal self-hosted chat on the Ollama Cloud API (ollama.com): streaming answers,
tool calling, per-conversation chat modes, long-term notes, single-user auth, and a
token dashboard with **real** numbers (Ollama reports `prompt_eval_count` /
`eval_count` itself).

Backend — FastAPI + SQLite. Frontend — a React SPA (React 19, zustand, Vite), built
into `frontend/dist` and served by the backend at `/`.

## Features

- **Streaming** NDJSON chat with live thinking and tool chips, plus a stop button
- **Tools** the model can call: `web_search`, `fetch_page`, `calc`, `python`,
  `memory_write`, `memory_list`
- **Chat modes** — 16 personas, one per conversation (see below)
- **Reasoning level** per pane: off → low → medium → high
- **Split panes** — several conversations side by side, layout persisted locally
- **Quote-reply** from a selection, **edit & resend**, **retry** the last answer
- **Export** a conversation as Markdown or PDF
- **Dashboard** over `/api/stats/*`: tokens, tool use, top models, session counts

## Quick start

```bash
cp .env.example .env
./bin/chatty install   # once: puts the `chatty` command in ~/.local/bin
chatty                 # from anywhere: starts the server in the background, opens the browser
```

`chatty` also takes `stop` / `restart` / `status` / `logs` / `fg` (foreground in the
current terminal, Ctrl+C to stop). Without installing it, from the project root:

```bash
./run.sh          # backend; APP_PORT comes from .env (8000 by default)
```

On the first run `SECRET_KEY` and `AUTH_PASSWORD` are appended to `.env` — the password
is printed to the terminal, and that is your login. `.env` has one required key:

1. a key from https://ollama.com/settings/keys
2. `OLLAMA_API_KEY=...` in `.env`

App: http://localhost:8000. Before the SPA is built, `/` serves a smoke console
(log in, poke the API, raw NDJSON chat). Everything under `/api` sits behind a cookie
issued by `POST /api/auth/login {"password": ...}`; a built SPA (`RUN_FRONTEND=1 ./run.sh`
or `npm --prefix frontend run build`) replaces the console automatically.

**Port.** If APP_PORT is taken (on this machine port 8000 belongs to the system
`jupyterhub.service`), `run.sh` hops to the nearest free port and prints the address.
To keep the address stable, pin the port in `.env`: `APP_PORT=8001`. Kill the squatter
for good (JupyterHub wants it, we don't): `sudo systemctl disable --now jupyterhub`.

## Chat modes

A mode is a persona for one conversation: a prompt block, a tool policy, and a default
reasoning level. It is stored on the session row, so it survives a reload, and switching
**keeps the history** — "now explain that like a teacher" works mid-dialog.

The registry is hardcoded in `backend/modes.py` (16 modes) and served to the UI by
`GET /api/modes`, so the titles and hints live in one place:

| mode | tools | default thinking |
|---|---|---|
| `assistant` — general help | auto | — |
| `text-only` — answers from its own knowledge, no lookups | off | low |
| `teacher` — step by step, checks you followed | auto | medium |
| `plain-language` — same thing, said simply | auto | low |
| `examiner` — quizzes one question at a time | auto | high |
| `solver` — works the problem through and verifies it | auto | high |
| `fact-check` — verifies claims against sources, verdict each | **on** | high |
| `research` — several sources, synthesised with links | **on** | high |
| `devils-advocate` — argues the strongest case against you | auto | medium |
| `editor` — fixes the text, preserves your voice | off | low |
| `translator` — translates only, keeps tone and terms | off | low |
| `condense` — shrinks the text without losing facts | off | low |
| `brainstorm` — many options, no pruning | auto | high |
| `planner` — turns a goal into ordered steps and risks | auto | high |
| `programmer` — working code, edge cases covered | auto | high |
| `critic` — leads with the worst problems and how to fix them | auto | high |

- `auto` honours the tools toggle in the composer; `on` always attaches tools and
  **locks the toggle**; `off` never attaches them.
- Switching into **Fact-check** asks for confirmation first, because verifying a
  claim-heavy message can spend the whole tool budget (`TOOL_MAX_ITER`) and truncate
  the answer.
- `translator` drops the base "reply in the user's language" rule, since it must answer
  in the *target* language instead.

Three ways to switch, all going through the same store action so they cannot drift:

1. the mode pill in the composer bar
2. a slash command — `/teacher`, `/fact`, `/translate` … (`/translate <text>` switches
   *and* sends the text; the command never reaches the bubble or the history)
3. the chips on the empty-chat screen

## API

All of it behind the auth cookie.

| method | path | what |
|---|---|---|
| `POST` | `/api/auth/login` \| `/logout` | cookie in / out (`/api/auth/me` to check) |
| `POST` | `/api/chat` | NDJSON turn stream (`delta` → `thinking` → `tools` → `usage` → `done`) |
| `GET` | `/api/modes` | the mode registry, with the warning text filled in |
| `GET` | `/api/models` | available models |
| `GET` `POST` | `/api/sessions` | list / create (`title`, `model`, `mode`) |
| `GET` `PATCH` `DELETE` | `/api/sessions/{id}` | read / rename & re-mode (both partial) / delete |
| `GET` | `/api/sessions/{id}/export.md` | the conversation as Markdown |
| `GET` | `/api/stats/summary` \| `/timeseries` \| `/top-models` \| `/tools` \| `/sessions` | dashboard data |
| `GET` | `/healthz` | liveness, no auth |

`POST /api/chat` body: `{model, content, use_tools, think?, mode?, session_id?, quote?}`.
Omitting `mode` keeps the session's stored mode; sending one persists it. An unknown
mode is a `422` rather than a silent fallback.

## Smoke-test with curl

```bash
curl -sc cookies.txt -X POST localhost:8000/api/auth/login \
     -d '{"password":"<password from .env>"}' -H 'content-type: application/json'
curl -sb cookies.txt -X POST localhost:8000/api/chat -N \
     -d '{"model":"gpt-oss:120b","content":"hi","use_tools":false}' \
     -H 'content-type: application/json'
curl -sb cookies.txt localhost:8000/api/models
curl -sb cookies.txt localhost:8000/api/modes
curl -sb cookies.txt localhost:8000/api/stats/summary
```

`-N` is required: the response is line-by-line NDJSON, and every turn is a separate
upstream call with its own real token counts.

## Data and backup

All state lives in `data/chat.db` (SQLite, WAL). A backup is a copy of the file,
preferably after a checkpoint:

```bash
sqlite3 data/chat.db "PRAGMA wal_checkpoint;"
cp data/chat.db ~/backups/chat-$(date +%F).db
```

Schema changes go through the `user_version` migrations in `backend/db.py` and apply
automatically on startup, so an older database upgrades in place.

## Development

```bash
./dev.sh                                       # backend + vite dev, one Ctrl+C
.venv/bin/python -m unittest discover -s tests  # tests (stubbed upstream, no API key)
npm --prefix frontend run build                 # typecheck + production build
```

`./dev.sh` runs uvicorn and the Vite dev server together — open
**http://localhost:5173**; `/api` is proxied to the backend, and frontend edits reload
live. The backend runs without `--reload`, so restart `./dev.sh` after changing Python.

## Production

Real HTTPS out front through a caddy/nginx reverse proxy in front of uvicorn, plus
`COOKIE_SECURE=true` in `.env`.
