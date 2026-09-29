"""Text decoding for legacy help content.

Adapted from DTDucas/chm-converter (MIT): chardet detection with fallbacks.
"""

from __future__ import annotations

import re
from pathlib import Path

import chardet

_FALLBACKS = ["utf-8", "cp1252", "gb18030", "latin-1"]
_META_CHARSET = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?([A-Za-z0-9_\-]+)""", re.IGNORECASE)


def decode_bytes(raw: bytes) -> tuple[str, str]:
    """Return ``(text, encoding)`` for *raw* HTML/text bytes."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", errors="replace"), "utf-16"

    declared = _META_CHARSET.search(raw[:4096])
    candidates: list[str] = []
    if declared:
        candidates.append(declared.group(1).decode("ascii", errors="ignore"))
    detected = chardet.detect(raw[:20000])
    if detected.get("encoding") and (detected.get("confidence") or 0) >= 0.7:
        candidates.append(detected["encoding"])
    candidates += _FALLBACKS

    for enc in candidates:
        try:
            return raw.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace"), "latin-1"


def read_text(path: Path) -> tuple[str, str]:
    return decode_bytes(Path(path).read_bytes())
