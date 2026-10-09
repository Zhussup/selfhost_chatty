"""SQLite layer: one shared connection (WAL), DDL with user_version migrations, q()/qx() helpers."""

import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from backend.config import ROOT

DATA_DIR = ROOT / "data"
def _db_path() -> Path:
    override = os.environ.get("CHAT_DB_PATH")
    if override:
        return Path(override)
    return DATA_DIR / "chat.db"

DB_PATH = _db_path()

_conn: sqlite3.Connection | None = None
_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


DDL = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT 'New chat',
  model TEXT NOT NULL DEFAULT '',
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_upd ON sessions(updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('system','user','assistant','tool')),
  sort INTEGER NOT NULL,
  content TEXT NOT NULL DEFAULT '',
  thinking TEXT NOT NULL DEFAULT '',
  tool_calls_json TEXT,
  tool_call_id TEXT,
  tool_name TEXT,
  error TEXT,
  model TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, sort);

-- Image attachments for a user message. Bytes are stored raw (no base64): the
-- browser uploads base64 inside the /api/chat JSON, the server decodes once, and
-- encodes again only when talking to Ollama. ON DELETE CASCADE covers session
-- delete, edit-and-resend and regenerate — there is nothing on disk to clean up.
CREATE TABLE IF NOT EXISTS message_images (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  mime TEXT NOT NULL DEFAULT '',
  name TEXT NOT NULL DEFAULT '',
  width INTEGER NOT NULL DEFAULT 0,
  height INTEGER NOT NULL DEFAULT 0,
  bytes BLOB NOT NULL,
  sort INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_message_images_msg ON message_images(message_id, sort);

CREATE TABLE IF NOT EXISTS requests (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  message_id TEXT,
  model TEXT NOT NULL,
  iter INTEGER NOT NULL DEFAULT 1,
  prompt_tokens INTEGER NOT NULL DEFAULT 0,
  cached_tokens INTEGER NOT NULL DEFAULT 0,
  completion_tokens INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'ok',
  duration_ms INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requests_created ON requests(created_at);
CREATE INDEX IF NOT EXISTS idx_requests_model ON requests(model, created_at);

CREATE TABLE IF NOT EXISTS tool_calls (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  message_id TEXT,
  name TEXT NOT NULL,
  args_json TEXT,
  ok INTEGER NOT NULL DEFAULT 1,
  ms INTEGER NOT NULL DEFAULT 0,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tool_created ON tool_calls(created_at);

CREATE TABLE IF NOT EXISTS notes (
  id TEXT PRIMARY KEY,
  content TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
"""

MIGRATIONS: dict[int, str] = {
    # 2: ALTER TABLE statements as schema evolves go here, keyed by target version.
    # Kept out of DDL on purpose: init() always runs DDL first, so a fresh DB
    # (user_version 0) reaches this step too — an ALTER on top of a column that
    # DDL already created would fail with "duplicate column name".
    # NOT NULL in ADD COLUMN needs the DEFAULT (SQLite requirement).
    2: "ALTER TABLE messages ADD COLUMN quote TEXT NOT NULL DEFAULT ''",
    3: "ALTER TABLE sessions ADD COLUMN mode TEXT NOT NULL DEFAULT 'assistant'",
    # Same CREATE TABLE IF NOT EXISTS text as DDL: init() always runs DDL first, so on
    # an old DB the table already exists by the time this step runs — idempotent, and
    # user_version still advances for anyone reading the pragma.
    4: (
        "CREATE TABLE IF NOT EXISTS message_images ("
        "id TEXT PRIMARY KEY,"
        "message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,"
        "mime TEXT NOT NULL DEFAULT '',"
        "name TEXT NOT NULL DEFAULT '',"
        "width INTEGER NOT NULL DEFAULT 0,"
        "height INTEGER NOT NULL DEFAULT 0,"
        "bytes BLOB NOT NULL,"
        "sort INTEGER NOT NULL DEFAULT 0,"
        "created_at INTEGER NOT NULL"
        ");"
        "CREATE INDEX IF NOT EXISTS idx_message_images_msg ON message_images(message_id, sort);"
    ),
}


def init() -> None:
    global _conn
    if _conn is None:
        _conn = _connect()
    _conn.executescript(DDL)
    version = _conn.execute("PRAGMA user_version").fetchone()[0]
    latest = max([1] + list(MIGRATIONS.keys()))
    for step in range(version + 1, latest + 1):
        sql = MIGRATIONS.get(step)
        if sql:
            _conn.executescript(sql)
    _conn.execute(f"PRAGMA user_version={latest}")
    _conn.commit()


def reset_for_tests(db_path: Path) -> None:
    """Point the layer at a fresh test DB (imports must read CHAT_DB_PATH before init)."""
    global _conn, DB_PATH
    if _conn is not None:
        _conn.close()
    _conn = None
    DB_PATH = Path(db_path)


def conn() -> sqlite3.Connection:
    if _conn is None:
        init()
    return _conn  # type: ignore[return-value]


def now() -> int:
    return int(time.time())


def new_id() -> str:
    return uuid.uuid4().hex


def q(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    """SELECT — returns rows."""
    with _lock:
        return conn().execute(sql, params).fetchall()


def one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    rows = q(sql, params)
    return rows[0] if rows else None


def qx(sql: str, params: tuple = ()) -> None:
    """Write — commits immediately."""
    with _lock:
        conn().execute(sql, params)
        conn().commit()