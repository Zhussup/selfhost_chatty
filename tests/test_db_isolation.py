"""The suite must never touch the real database.

Regression guard: db.DB_PATH used to stay bound to data/chat.db because it is
computed at import time, while tests/base.py set CHAT_DB_PATH too late — so the
per-test DELETEs in fresh_db() wiped the user's real conversations.
"""

import tempfile
import unittest
from pathlib import Path

from backend import db
from tests import base
from tests.base import BaseTestCase

PROD_DB = (Path(__file__).resolve().parent.parent / "data" / "chat.db").resolve()


class DbIsolationTests(BaseTestCase):
    def test_bound_to_temp_db_not_production(self):
        bound = db.DB_PATH.resolve()
        self.assertNotEqual(bound, PROD_DB, "tests are pointed at the production database")
        self.assertTrue(
            bound.is_relative_to(Path(tempfile.gettempdir()).resolve()),
            f"test DB should live under the temp dir, got {bound}",
        )

    def test_guard_refuses_production_path(self):
        original = db.DB_PATH
        db.DB_PATH = PROD_DB  # simulate the import-order drift that caused the data loss
        try:
            with self.assertRaises(RuntimeError):
                base.fresh_db()
        finally:
            db.DB_PATH = original


if __name__ == "__main__":
    unittest.main()
