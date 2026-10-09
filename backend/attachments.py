"""Image attachment validation: base64 -> bytes, with the mime sniffed from the
payload rather than trusted from the wire.

The client downscales and re-encodes before sending, so everything here is a
guard for a stale or hostile client. Nothing in this module touches the DB or
FastAPI on purpose — it is pure, and unit-tested directly.
"""

import base64
import binascii
import struct
from typing import Any

from backend.config import settings


class ImageError(Exception):
    """Rejected attachment. `code` becomes the NDJSON error code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_PNG = b"\x89PNG\r\n\x1a\n"


def sniff_mime(raw: bytes) -> str:
    """Identify the format from magic bytes. "" when unrecognised."""
    if raw.startswith(_PNG):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(raw) >= 12 and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp"
    return ""


def _png_size(raw: bytes) -> tuple[int, int]:
    if len(raw) < 24:
        return 0, 0
    return struct.unpack(">II", raw[16:24])


def _gif_size(raw: bytes) -> tuple[int, int]:
    if len(raw) < 10:
        return 0, 0
    return struct.unpack("<HH", raw[6:10])


def _jpeg_size(raw: bytes) -> tuple[int, int]:
    """Walk the segment chain to the first SOF marker (frame header)."""
    i = 2
    end = len(raw)
    while i + 9 < end:
        if raw[i] != 0xFF:
            i += 1
            continue
        marker = raw[i + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            i += 2
            continue
        seg_len = struct.unpack(">H", raw[i + 2 : i + 4])[0]
        # SOF0..SOF15, minus the non-frame markers DHT(C4), JPG(C8), DAC(CC)
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", raw[i + 5 : i + 9])
            return width, height
        i += 2 + seg_len
    return 0, 0


def _webp_size(raw: bytes) -> tuple[int, int]:
    if len(raw) < 30:
        return 0, 0
    fourcc = raw[12:16]
    if fourcc == b"VP8X":  # extended: canvas size is 24-bit minus-one, little-endian
        w = int.from_bytes(raw[24:27], "little") + 1
        h = int.from_bytes(raw[27:30], "little") + 1
        return w, h
    if fourcc == b"VP8 " and raw[23:26] == b"\x9d\x01\x2a":  # lossy keyframe
        w, h = struct.unpack("<HH", raw[26:30])
        return w & 0x3FFF, h & 0x3FFF
    return 0, 0  # VP8L needs bit-unpacking — not worth it, dimensions are optional


_SIZERS = {
    "image/png": _png_size,
    "image/jpeg": _jpeg_size,
    "image/gif": _gif_size,
    "image/webp": _webp_size,
}


def parse_dimensions(raw: bytes, mime: str) -> tuple[int, int]:
    """Best-effort (width, height); (0, 0) when the format hides them."""
    sizer = _SIZERS.get(mime)
    if sizer is None:
        return 0, 0
    try:
        return sizer(raw)
    except (struct.error, IndexError):
        return 0, 0


def _decode_one(item: Any, total: int) -> dict[str, Any]:
    data = getattr(item, "data", "") or ""
    # A client that sends a data: URL is being sloppy, not hostile — accept it.
    if data.startswith("data:"):
        _, _, data = data.partition(",")
    try:
        raw = base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise ImageError("image_invalid", "image is not valid base64") from None
    if len(raw) > settings.image_max_bytes:
        raise ImageError(
            "image_invalid",
            f"image is larger than {settings.image_max_bytes // 1_000_000} MB",
        )
    if total + len(raw) > settings.image_max_total_bytes:
        raise ImageError("image_invalid", "attached images exceed the total size limit")

    mime = sniff_mime(raw)
    if not mime:
        raise ImageError("image_invalid", "unsupported image format (use PNG, JPEG, GIF or WebP)")

    width, height = parse_dimensions(raw, mime)
    if not width and getattr(item, "width", None):
        width = int(item.width or 0)  # client hint, only when we could not read it
    if not height and getattr(item, "height", None):
        height = int(item.height or 0)

    name = (getattr(item, "name", None) or "").strip()[:200]
    return {
        "mime": mime,
        "name": name,
        "width": width or 0,
        "height": height or 0,
        "bytes": raw,
        "b64": base64.b64encode(raw).decode("ascii"),  # normalized, for upstream
    }


def decode_images(items: list[Any]) -> list[dict[str, Any]]:
    """Validate every attachment and return storage-ready records.

    Raises ImageError on the first problem; nothing is written until this passes.
    """
    if len(items) > settings.image_max_count:
        raise ImageError("image_invalid", f"at most {settings.image_max_count} images per message")
    out: list[dict[str, Any]] = []
    total = 0
    for item in items:
        record = _decode_one(item, total)
        total += len(record["bytes"])
        out.append(record)
    return out
