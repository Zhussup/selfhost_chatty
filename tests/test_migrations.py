"""Schema migrations: an older database gains the attachment table in place."""

import unittest

from backend import db
from tests.base import BaseTestCase

_LATEST = 4
_IMAGE_COLUMNS = {
    "id",
    "message_id",
    "mime",
    "name",
    "width",
    "height",
    "bytes",
    "sort",
    "created_at",
}


class MigrationTests(BaseTestCase):
    def _user_version(self) -> int:
        return db.conn().execute("PRAGMA user_version").fetchone()[0]

    def _tables(self) -> set[str]:
        return {r["name"] for r in db.q("SELECT name FROM sqlite_master WHERE type='table'")}

    def test_fresh_db_lands_on_the_latest_version(self):
        db.init()
        self.assertEqual(self._user_version(), _LATEST)
        self.assertIn("message_images", self._tables())

    def test_v3_database_gains_the_images_table(self):
        # simulate a database created before attachments existed
        with db._lock:
            db.conn().executescript("DROP TABLE IF EXISTS message_images;")
            db.conn().execute("PRAGMA user_version=3")
            db.conn().commit()
        self.assertNotIn("message_images", self._tables())

        db.init()

        self.assertEqual(self._user_version(), _LATEST)
        self.assertIn("message_images", self._tables())
        columns = {r["name"] for r in db.q("PRAGMA table_info(message_images)")}
        self.assertEqual(columns, _IMAGE_COLUMNS)

    def test_images_cascade_when_their_message_goes(self):
        db.init()
        now = db.now()
        db.qx(
            "INSERT INTO sessions (id, title, model, created_at, updated_at) VALUES ('s','t','m',?,?)",
            (now, now),
        )
        db.qx(
            "INSERT INTO messages (id, session_id, role, sort, content, created_at) VALUES ('m1','s','user',1,'',?)",
            (now,),
        )
        db.qx(
            "INSERT INTO message_images (id, message_id, mime, bytes, created_at) VALUES ('i1','m1','image/png',?,?)",
            (b"\x89PNG", now),
        )
        db.qx("DELETE FROM messages WHERE id='m1'")
        # PRAGMA foreign_keys=ON is set per connection, so the cascade actually fires
        self.assertEqual(db.q("SELECT id FROM message_images"), [])


if __name__ == "__main__":
    unittest.main()
