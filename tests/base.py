"""Shared test setup: fresh temp DB per test class, settings import."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# point the DB layer at a temp file BEFORE any backend import initializes it
_TMPDIR = tempfile.mkdtemp(prefix="shc_tests_")
_TEST_DB = Path(_TMPDIR) / "test_chat.db"
os.environ["CHAT_DB_PATH"] = str(_TEST_DB)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, db  # noqa: E402

_PROD_DB = (Path(__file__).resolve().parent.parent / "data" / "chat.db").resolve()

# Setting the env var above is not enough: db.DB_PATH is bound at import time, and
# test modules that import backend.* before this file have already bound it to the
# real data/chat.db. Rebind explicitly so the suite can never reach production data.
db.reset_for_tests(_TEST_DB)


def fresh_db() -> None:
    """Reset the test database content (SQL cleanup; one shared connection)."""
    # Last line of defence — a wipe here once destroyed the user's real conversations.
    if db.DB_PATH.resolve() == _PROD_DB:
        raise RuntimeError(f"refusing to wipe the production DB from tests: {db.DB_PATH}")
    db.init()
    with db._lock:
        db.conn().executescript(
            "DELETE FROM message_images; DELETE FROM messages; DELETE FROM requests; "
            "DELETE FROM tool_calls; DELETE FROM notes; DELETE FROM sessions;"
        )
        db.conn().commit()


class BaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        fresh_db()