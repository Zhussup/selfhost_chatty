"""Where the URL and the password come from: flags > env > local project > prompt.

Works the same whether run from the repo venv (`python -m chatty_cli`) or from
a pip-installed wheel: the project is found by its markers (.env + backend/),
not by where the code lives.
"""

import getpass
import os
import sys
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_URL = "http://localhost:8000"


class ConfigError(Exception):
    """A friendly stop instead of a traceback, with an actionable hint."""


@dataclass
class Config:
    url: str          # no trailing slash
    password: str
    tty: bool         # stdout is a terminal → rich styling; else raw pipe-ready text


def load_env(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE pairs: strip paired quotes only, keep inline `#` — a
    generated AUTH_PASSWORD may contain it."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # 'a#b' stays 'a#b'; quoted "a#b" too. Only paired wrapping quotes go.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def find_project() -> Path | None:
    """The project root, known by its own markers — works no matter how this
    package was installed. `CHATTY_DIR` wins; otherwise walk up from cwd."""
    env = os.environ.get("CHATTY_DIR")
    start = Path(env) if env else Path.cwd()
    for cand in [start, *start.parents][:5]:
        if (cand / ".env").is_file() and (cand / "backend" / "app.py").is_file():
            return cand
    return None


def resolve(url_flag: str | None = None, password_flag: str | None = None) -> Config:
    """One Config per invocation (see the module docstring for the ladder)."""
    project = find_project()

    url = url_flag or os.environ.get("CHATTY_URL")
    if not url and project:
        url_file = project / ".run" / "chatty.url"
        if url_file.is_file():
            url = url_file.read_text(encoding="utf-8").strip()
    if not url:
        url = _DEFAULT_URL
    url = url.rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise ConfigError(
            f"bad url: {url} — pass --url http://host:port or set CHATTY_URL"
        )

    password = password_flag
    if password is None:
        password = os.environ.get("CHATTY_PASSWORD") or ""
        if password:
            print("[chatty-cli] password: from CHATTY_PASSWORD", file=sys.stderr)
    if not password and project:
        password = load_env(project / ".env").get("AUTH_PASSWORD", "")
        if password:
            print(f"[chatty-cli] password: from {project}/.env", file=sys.stderr)
    if not password:
        # getpass reads the terminal (not piped stdin) and mutes the echo;
        # with piped stdin there is no safe way to ask — fail loudly instead.
        if sys.stdin.isatty():
            password = getpass.getpass("chatty password: ")
        else:
            raise ConfigError(
                "no password found — pass --password, set CHATTY_PASSWORD, "
                "or run from a checkout that has .env"
            )
    return Config(url=url, password=password, tty=_out_is_tty())


def _out_is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except ValueError:      # closed/redirected stdout in odd embedding contexts
        return False