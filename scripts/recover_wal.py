#!/usr/bin/env python3
"""Best-effort recovery of deleted rows from a SQLite WAL.

The test suite used to wipe the real data/chat.db (see tests/base.py), so rows the
app deleted are still sitting in old WAL frames and freed pages. This walks the
`sessions`/`messages` b-trees over *every historical image* of each page (main file
+ all WAL frames), so subtrees that are unreachable from the current root are
recovered too.

Read-only with respect to the input: it copies the snapshot to a temp dir and works
there. Nothing is written back to the live database — output goes to --out.

    python scripts/recover_wal.py data/snapshots/<ts> --out data/recovered.db
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import struct
import sys
import tempfile
from pathlib import Path

WAL_MAGIC = (0x377F0682, 0x377F0683)
# b-tree page types
LEAF_TABLE, INTERIOR_TABLE = 0x0D, 0x05

# Column order as created by backend/db.py (quote is added by migration 2).
SCHEMAS = {
    "sessions": ["id", "title", "model", "created_at", "updated_at"],
    "messages": [
        "id", "session_id", "role", "sort", "content", "thinking", "tool_calls_json",
        "tool_call_id", "tool_name", "error", "model", "created_at", "quote",
    ],
}


def be(buf: bytes, off: int, n: int) -> int:
    return int.from_bytes(buf[off:off + n], "big")


def varint(buf: bytes, off: int) -> tuple[int, int]:
    """SQLite variable-length integer. Returns (value, bytes_consumed)."""
    value = 0
    for i in range(9):
        if off + i >= len(buf):
            raise ValueError("varint runs past end of buffer")
        byte = buf[off + i]
        if i == 8:
            value = (value << 8) | byte
            return value, 9
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, i + 1
    raise ValueError("malformed varint")


def read_page_size(db_path: Path) -> int:
    with open(db_path, "rb") as f:
        head = f.read(100)
    if head[:16] != b"SQLite format 3\x00":
        raise ValueError(f"{db_path} is not a SQLite database")
    size = be(head, 16, 2)
    return 65536 if size == 1 else size


def load_pages(db_path: Path, wal_path: Path | None) -> dict[int, list[bytes]]:
    """page number -> list of historical images, oldest first."""
    ps = read_page_size(db_path)
    pages: dict[int, list[bytes]] = {}

    raw = db_path.read_bytes()
    for pno in range(1, len(raw) // ps + 1):
        pages.setdefault(pno, []).append(raw[(pno - 1) * ps:pno * ps])

    if wal_path and wal_path.exists():
        wal = wal_path.read_bytes()
        if len(wal) >= 32 and be(wal, 0, 4) in WAL_MAGIC:
            frame_size = 24 + ps
            for off in range(32, len(wal) - frame_size + 1, frame_size):
                pno = be(wal, off, 4)
                if pno == 0:  # padding past the last commit
                    continue
                page = wal[off + 24:off + 24 + ps]
                pages.setdefault(pno, []).append(page)
    return pages


class Reader:
    """Splices a table b-tree over every historical page version."""

    def __init__(self, pages: dict[int, list[bytes]], page_size: int, reserved: int):
        self.pages = pages
        self.page_size = page_size
        self.usable = page_size - reserved

    def payload(self, cell: bytes, payload_size: int, local: int) -> bytes:
        """Follow the overflow chain when a row spills past the page."""
        if local >= payload_size:
            return cell[:payload_size]
        overflow = be(cell, local, 4)
        out = bytearray(cell[:local])
        guard = 0
        while overflow and len(out) < payload_size and guard < 10_000:
            guard += 1
            versions = self.pages.get(overflow)
            if not versions:
                break
            page = versions[-1]
            nxt = be(page, 0, 4)
            out += page[4:self.usable]
            overflow = nxt
        return bytes(out[:payload_size])

    def record(self, payload: bytes) -> list[object]:
        hdr_size, k = varint(payload, 0)
        types, off = [], k
        while off < hdr_size:  # serial types run until the declared header size
            t, step = varint(payload, off)
            types.append(t)
            off += step
        values, off = [], hdr_size
        for t in types:
            if t == 0:
                values.append(None); continue
            if t <= 6:
                size = (1, 2, 3, 4, 6, 8)[t - 1]
                values.append(int.from_bytes(payload[off:off + size], "big", signed=True))
                off += size
            elif t == 7:
                values.append(struct.unpack(">d", payload[off:off + 8])[0]); off += 8
            elif t == 8:
                values.append(0)
            elif t == 9:
                values.append(1)
            elif t >= 12:
                size = (t - 12) // 2 if t % 2 == 0 else (t - 13) // 2
                chunk = payload[off:off + size]
                values.append(chunk.decode("utf-8", "replace") if t % 2 else chunk)
                off += size
            else:
                raise ValueError(f"reserved serial type {t}")
        return values

    def walk(self, root: int) -> list[list[object]]:
        rows: list[list[object]] = []
        seen: set[tuple[int, int]] = set()
        stack: list[tuple[int, int]] = [(root, v) for v in range(len(self.pages.get(root, [])))]
        while stack:
            pno, ver = stack.pop()
            if (pno, ver) in seen:
                continue
            seen.add((pno, ver))
            images = self.pages.get(pno)
            if not images or ver >= len(images):
                continue
            page = images[ver]
            ptype = page[0]
            ncell = be(page, 3, 2)
            if ptype == INTERIOR_TABLE:
                for i in range(ncell):
                    child = be(page, be(page, 12 + 2 * i, 2), 4)
                    stack.extend((child, v) for v in range(len(self.pages.get(child, []))))
                right = be(page, 8, 4)
                stack.extend((right, v) for v in range(len(self.pages.get(right, []))))
            elif ptype == LEAF_TABLE:
                for i in range(ncell):
                    cell_off = be(page, 8 + 2 * i, 2)
                    size, k = varint(page, cell_off)
                    _, k2 = varint(page, cell_off + k)  # rowid
                    body = cell_off + k + k2
                    if size > self.usable - 35:
                        min_local = ((self.usable - 12) * 32 // 255) - 23
                        local = min_local + (size - min_local) % (self.usable - 4)
                        if local > self.usable - 35:
                            local = min_local
                    else:
                        local = size
                    try:
                        rows.append(self.record(self.payload(page[body:], size, local)))
                    except (ValueError, IndexError):
                        continue
        return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("snapshot", type=Path, help="dir or db path holding chat.db + chat.db-wal")
    ap.add_argument("--out", type=Path, default=Path("data/recovered.db"))
    args = ap.parse_args()

    snap = args.snapshot
    if snap.is_dir():
        db_path, wal_path = snap / "chat.db", snap / "chat.db-wal"
    else:
        db_path, wal_path = snap, snap.with_name(snap.name + "-wal")
    if not db_path.exists():
        print(f"no database at {db_path}", file=sys.stderr)
        return 1

    # Byte-level pass first, straight from the snapshot: opening the database with
    # sqlite3 checkpoints its WAL on close, which would destroy the frames we are
    # here to read. The temp copy below is only for querying sqlite_master.
    reserved = be(db_path.read_bytes(), 20, 1)
    page_size = read_page_size(db_path)
    pages = load_pages(db_path, wal_path)
    print(f"pages: {len(pages)} distinct ({sum(len(v) for v in pages.values())} versions), page_size={page_size}")

    tmp = Path(tempfile.mkdtemp(prefix="shc_recover_"))
    shutil.copy2(db_path, tmp / "chat.db")
    if wal_path.exists():
        shutil.copy2(wal_path, tmp / "chat.db-wal")

    conn = sqlite3.connect(tmp / "chat.db")
    roots = dict(conn.execute("SELECT name, rootpage FROM sqlite_master WHERE type='table'"))
    conn.close()

    reader = Reader(pages, page_size, reserved)
    recovered: dict[str, dict[str, list[object]]] = {}
    for table, root in roots.items():
        if table not in SCHEMAS or not root:
            continue
        cols = SCHEMAS[table]
        found: dict[str, list[object]] = {}
        for row in reader.walk(root):
            if len(row) < 2 or not isinstance(row[0], str) or len(row[0]) != 32:
                continue
            values = list(row[:len(cols)]) + [""] * (len(cols) - len(row))
            found.setdefault(row[0], values)
        recovered[table] = found
        print(f"{table}: recovered {len(found)} rows")

    out_path = args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    out = sqlite3.connect(out_path)
    out.executescript(
        """
        CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, model TEXT,
                               created_at INTEGER, updated_at INTEGER);
        CREATE TABLE messages (id TEXT PRIMARY KEY, session_id TEXT, role TEXT, sort INTEGER,
                               content TEXT, thinking TEXT, tool_calls_json TEXT,
                               tool_call_id TEXT, tool_name TEXT, error TEXT, model TEXT,
                               created_at INTEGER, quote TEXT);
        """
    )
    for table, rows in recovered.items():
        cols = SCHEMAS[table]
        out.executemany(
            f"INSERT OR IGNORE INTO {table} ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
            [[v if isinstance(v, (str, int, float, type(None))) else str(v) for v in r] for r in rows.values()],
        )
    out.commit()

    sessions = out.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    msgs = out.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    print(f"\nwrote {out_path}: {sessions} sessions, {msgs} messages")
    for sid, title, upd in out.execute(
        "SELECT id, substr(title,1,60), updated_at FROM sessions ORDER BY updated_at DESC LIMIT 15"
    ):
        print(f"  {sid[:8]}  {title}")
    out.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
