"""Read compiled CHM metadata (#SYSTEM) and HTML Help sitemap files (.hhc/.hhk)."""

from __future__ import annotations

import posixpath
import struct
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

from .encoding import read_text
from .models import ChmMetadata

# #SYSTEM record codes documented by the HTML Help community (chmspec).
_SYSTEM_CODES = {0: "contents_file", 1: "index_file", 2: "default_topic", 3: "title", 6: "compiled_file"}


def parse_system(data: bytes) -> ChmMetadata:
    """Parse the binary ``#SYSTEM`` stream. Unknown or malformed records are ignored."""
    meta = ChmMetadata()
    pos = 4  # DWORD version header
    while pos + 4 <= len(data):
        code, length = struct.unpack_from("<HH", data, pos)
        pos += 4
        chunk = data[pos : pos + length]
        pos += length
        if code in _SYSTEM_CODES:
            value = chunk.split(b"\0", 1)[0].decode("cp1252", errors="replace").strip()
            if value:
                setattr(meta, _SYSTEM_CODES[code], value)
        elif code == 4 and len(chunk) >= 4:
            meta.lcid = struct.unpack_from("<I", chunk, 0)[0]
    return meta


def read_system(extracted: Path) -> ChmMetadata:
    system = extracted / "#SYSTEM"
    if not system.is_file():
        return ChmMetadata()
    return parse_system(system.read_bytes())


def normalize_local(local: str) -> str | None:
    """Normalise a sitemap ``Local`` value into a lowercase-insensitive internal POSIX path."""
    if not local:
        return None
    value = local.strip()
    lower = value.lower()
    if "::" in value and (lower.startswith("ms-its:") or lower.startswith("mk:@msitstore:")):
        value = value.split("::", 1)[1]
    elif ":" in value.split("/", 1)[0]:
        return None  # external URL or other scheme
    value = unquote(value.split("#", 1)[0].split("?", 1)[0]).replace("\\", "/").lstrip("/")
    value = posixpath.normpath(value) if value else ""
    return value or None


class _SitemapParser(HTMLParser):
    """Stream parser tolerant of the unclosed <LI> tags typical of .hhc/.hhk files."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: list[dict] = []
        self.stack: list[list[dict]] = []
        self.params: list[tuple[str, str]] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {k.lower(): (v or "") for k, v in attrs}
        if tag == "ul":
            if not self.stack:
                self.stack.append(self.root)
            else:
                current = self.stack[-1]
                children = current[-1].setdefault("children", []) if current else current
                self.stack.append(children)
        elif tag == "object" and attr.get("type", "").lower() == "text/sitemap":
            self.params = []
        elif tag == "param" and self.params is not None:
            self.params.append((attr.get("name", "").lower(), attr.get("value", "")))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "ul" and len(self.stack) > 1:
            self.stack.pop()
        elif tag == "object" and self.params is not None:
            names = [v for k, v in self.params if k == "name"]
            locals_ = [v for k, v in self.params if k == "local"]
            node = {"title": names[0].strip() if names else "", "locals": locals_}
            (self.stack[-1] if self.stack else self.root).append(node)
            self.params = None


def parse_sitemap(path: Path) -> list[dict]:
    """Return a nested ``[{title, locals, children}]`` tree from a .hhc or .hhk file."""
    text, _ = read_text(path)
    parser = _SitemapParser()
    parser.feed(text)
    parser.close()
    return parser.root


def find_sitemap(extracted: Path, declared: str | None, suffix: str) -> Path | None:
    """Locate the declared contents/index file, else the first ``*.hhc``/``*.hhk`` at top level."""
    if declared:
        candidate = extracted / declared.replace("\\", "/").lstrip("/")
        if candidate.is_file():
            return candidate
    matches = sorted(p for p in extracted.iterdir() if p.is_file() and p.suffix.lower() == suffix)
    if not matches:
        matches = sorted(p for p in extracted.rglob(f"*{suffix}") if p.is_file())
    return matches[0] if matches else None
