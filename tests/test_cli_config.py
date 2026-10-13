"""CLI config: the .env mini-parser and the url/password resolution ladder.

No backend imports here — pure unit tests. find_project is patched so the
resolution tests never read the developer's real .env.
"""

import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest import mock

from chatty_cli.config import ConfigError, load_env, resolve


def _fake_project(env_pairs: dict[str, str] | None = None):
    """A tmp project (env + backend markers); returns (root, find_project patch)."""
    root = Path(tempfile.mkdtemp())
    (root / "backend").mkdir()
    (root / "backend" / "app.py").write_text("", encoding="utf-8")
    (root / ".env").write_text(
        "".join(f"{k}={v}\n" for k, v in (env_pairs or {}).items()), encoding="utf-8"
    )
    patch = mock.patch("chatty_cli.config.find_project", return_value=root)
    return root, patch


class EnvParserTests(unittest.TestCase):
    def test_parses_pairs_strips_quotes_keeps_inline_hash(self):
        f = Path(tempfile.mkdtemp()) / ".env"
        f.write_text(
            '# generated\nAUTH_PASSWORD="p#x"\nEMPTY=\nAPP_PORT=8001\n  SPACED = v \n',
            encoding="utf-8",
        )
        env = load_env(f)
        self.assertEqual(env["AUTH_PASSWORD"], "p#x")   # inline # is data, not a comment
        self.assertEqual(env["EMPTY"], "")
        self.assertEqual(env["APP_PORT"], "8001")
        self.assertEqual(env["SPACED"], "v")

    def test_missing_file_is_empty(self):
        self.assertEqual(load_env(Path("/nonexistent/.env")), {})


class ResolveTests(unittest.TestCase):
    """Each case: cleared env, redirected stdout/stderr, stdin never a tty —

    so nothing here can reach the developer's real .env, PATH or terminal.
    """

    def setUp(self):
        self.out, self.err = StringIO(), StringIO()
        self._stdout = mock.patch("sys.stdout", new=self.out)
        self._stderr = mock.patch("sys.stderr", new=self.err)
        self._stdin = mock.patch("sys.stdin", new=StringIO())
        for p in (self._stdout, self._stderr, self._stdin):
            p.start()

    def tearDown(self):
        for p in (self._stdin, self._stderr, self._stdout):
            p.stop()

    def test_url_flag_beats_env_beats_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            c = resolve(url_flag="http://flag:1")
            self.assertEqual(c.url, "http://flag:1")
            c = resolve()      # no env, no flag: the default
            self.assertEqual(c.url, "http://localhost:8000")
        with mock.patch.dict(os.environ, {"CHATTY_URL": "http://env:2"}, clear=True):
            c = resolve()
            self.assertEqual(c.url, "http://env:2")

    def test_url_file_only_under_a_project(self):
        root, patch = _fake_project({"AUTH_PASSWORD": "pw"})
        (root / ".run").mkdir()
        (root / ".run" / "chatty.url").write_text("http://localhost:8123\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=True):
            with patch:
                c = resolve()
        self.assertEqual(c.url, "http://localhost:8123")

    def test_password_flag_beats_env_beats_project_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with _fake_project({"AUTH_PASSWORD": "pw-env"})[1]:
                c = resolve(password_flag="pw-flag")
                self.assertEqual(c.password, "pw-flag")
                c = resolve()
                self.assertEqual(c.password, "pw-env")
        with mock.patch.dict(os.environ, {"CHATTY_PASSWORD": "pw-var"}, clear=True):
            with _fake_project({"AUTH_PASSWORD": "pw-env"})[1]:
                c = resolve()
            self.assertEqual(c.password, "pw-var")

    def test_piped_stdin_without_any_password_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch("chatty_cli.config.find_project", return_value=None):
                with self.assertRaises(ConfigError):
                    resolve()

    def test_tty_flag_reflects_stdout(self):
        # sys.stdout is already a StringIO here (setUp) — isatty() is False
        with mock.patch.dict(os.environ, {"CHATTY_PASSWORD": "pw"}, clear=True):
            with mock.patch("chatty_cli.config.find_project", return_value=None):
                c = resolve()
        self.assertFalse(c.tty)

    def test_bad_url_scheme_is_a_friendly_error(self):
        with mock.patch.dict(os.environ, {"CHATTY_URL": "ftp://x"}, clear=True):
            with mock.patch("chatty_cli.config.find_project", return_value=None):
                with self.assertRaises(ConfigError):
                    resolve()


if __name__ == "__main__":
    unittest.main()