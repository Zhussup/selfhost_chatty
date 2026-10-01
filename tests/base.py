"""Shared test setup: fresh temp DB per test class, settings import."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# point the DB layer at a temp file BEFORE any backend import initializes it
_TMPDIR = tempfile.mkdtemp(prefix="shc_tests_")
os.environ["CHAT_DB_PATH"] = str(Path(_TMPDIR) / "test_chat.db")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db, config  # noqa: E402


def fresh_db() -> None:
    """Reset the test database content (SQL cleanup; one shared connection)."""
    db.init()
    with db._lock:
        db.conn().executescript(
            "DELETE FROM messages; DELETE FROM requests; DELETE FROM tool_calls; DELETE FROM notes; DELETE FROM sessions;"
        )
        db.conn().commit()


class BaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        fresh_db()