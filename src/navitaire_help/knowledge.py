"""Read-only query engine over a folder written by ``navhelp convert`` (the *knowledge* folder).

Used by the MCP server (``navhelp mcp``) but has no MCP dependency, so it can be tested and reused directly.

* Everything is read from ``catalog.json``, ``manifest.json``, ``toc.json``, ``indexes/*.json`` and ``topics/*.md``.
* Full-text search uses SQLite FTS5 (standard library). The index is a disposable cache stored in
  ``<knowledge>/.navhelp-index/`` and rebuilt automatically when the catalog or any topic index changes.
* Every path received from a caller is resolved inside its collection folder; anything else is rejected.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import posixpath
import re
import sqlite3
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import unquote

from .safety import redact

INDEX_SCHEMA = 1
INDEX_DIR_NAME = ".navhelp-index"
IMAGE_TYPES = {".png": "image/png", ".gif": "image/gif", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".bmp": "image/bmp", ".ico": "image/x-icon", ".svg": "image/svg+xml"}
MAX_ASSET_BYTES = 5 * 1024 * 1024

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ANCHOR = re.compile(r'<a id="([^"]*)"></a>')
_FENCE = re.compile(r"^\s*(```|~~~)")
_QUERY_TOKEN = re.compile(r'"([^"]+)"|([\w]+\*?)', re.UNICODE)
_WORD = re.compile(r"\w+", re.UNICODE)


class KnowledgeError(ValueError):
    """A request that cannot be answered (unknown collection, missing topic, invalid path...)."""


@dataclass(frozen=True)
class CollectionInfo:
    collection_id: str
    family_id: str
    product: str
    installed_versions: list[str]
    version_status: str
    document_version: str | None
    file_name: str
    topics: int
    path: str  # relative to the knowledge root, e.g. "gonow/0123456789ab"

    def public(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- helpers
def version_key(version: str | None) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version or "")) or (-1,)


def _collection_key(info: CollectionInfo) -> tuple[int, ...]:
    return max((version_key(v) for v in info.installed_versions), default=(-1,))


def version_matches(requested: str, installed: list[str]) -> bool:
    """``9.1`` matches ``9.1.0.200``; ``9.1.0.200`` matches only itself."""
    req = requested.strip().lower().lstrip("rv")
    return any(v == req or v.startswith(req + ".") for v in installed)


def split_front_matter(text: str) -> tuple[dict, str]:
    """Return (front matter, body). Values are JSON encoded by the converter."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fields: dict = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        try:
            fields[key.strip()] = json.loads(value.strip())
        except json.JSONDecodeError:
            fields[key.strip()] = value.strip()
    return fields, text[end + 5:].lstrip("\n")


def sections(body: str) -> list[dict]:
    """Headings of a Markdown body with their anchors and line span (code fences are ignored)."""
    lines = body.splitlines()
    found: list[dict] = []
    pending: list[str] = []
    in_fence = False
    for number, line in enumerate(lines):
        if _FENCE.match(line):
            in_fence = not in_fence
            pending = []
            continue
        if in_fence:
            continue
        match = _HEADING.match(line)
        if match:
            text = _ANCHOR.sub("", match.group(2)).strip()
            anchors = pending + _ANCHOR.findall(match.group(2))
            found.append({"level": len(match.group(1)), "title": text, "anchors": anchors, "start": number})
            pending = []
        elif _ANCHOR.fullmatch(line.strip()):
            pending.extend(_ANCHOR.findall(line))
        elif line.strip():
            pending = []
    for index, item in enumerate(found):
        item["end"] = next((later["start"] for later in found[index + 1:] if later["level"] <= item["level"]),
                           len(lines))
    return found


def _fts_query(query: str, operator: str) -> str:
    parts = []
    for phrase, word in _QUERY_TOKEN.findall(query):
        if phrase:
            words = _WORD.findall(phrase)
            if words:
                parts.append('"' + " ".join(words) + '"')
        elif word:
            star = word.endswith("*")
            term = word.rstrip("*")
            if term:
                parts.append(f'"{term}"' + ("*" if star else ""))
    return f" {operator} ".join(parts)


def _clean_rel(path: str) -> str:
    if "\0" in path:
        raise KnowledgeError("Invalid path")
    rel = unquote(path.strip()).replace("\\", "/")
    rel = rel.split("#", 1)[0]
    while rel.startswith("./"):
        rel = rel[2:]
    if not rel or rel.startswith("/") or re.match(r"^[A-Za-z]:", rel):
        raise KnowledgeError("Paths must be relative to the collection (for example topics/Welcome.md)")
    normalized = posixpath.normpath(rel)
    if normalized == ".." or normalized.startswith("../"):
        raise KnowledgeError("Path escapes the collection folder")
    return normalized


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


# --------------------------------------------------------------------------- knowledge base
class KnowledgeBase:
    def __init__(self, root: Path, index_dir: Path | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.index_dir = Path(index_dir).expanduser().resolve() if index_dir else self.root / INDEX_DIR_NAME
        self._lock = threading.RLock()
        self._catalog_stamp: tuple | None = None
        self._catalog: list[CollectionInfo] = []
        self._json_cache: dict[Path, tuple[tuple, object]] = {}
        self._conn: sqlite3.Connection | None = None
        self._conn_fingerprint: str | None = None

    # ------------------------------------------------------------------ catalog
    def _display_root(self) -> str:
        return redact(str(self.root))

    def collections(self) -> list[CollectionInfo]:
        catalog = self.root / "catalog.json"
        try:
            stat = catalog.stat()
        except FileNotFoundError:
            raise KnowledgeError(
                f"No catalog.json in {self._display_root()}. Convert the help first "
                "(navhelp convert --output .\\knowledge, or the convert_help tool)."
            ) from None
        stamp = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            if stamp != self._catalog_stamp:
                try:
                    data = json.loads(catalog.read_text(encoding="utf-8"))
                    entries = data["collections"]
                except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
                    raise KnowledgeError(f"catalog.json is not valid: {type(exc).__name__}") from None
                infos = []
                for e in entries:
                    folder = self.root / e["path"]
                    if not _inside(folder, self.root):
                        continue
                    infos.append(CollectionInfo(
                        collection_id=e["collection_id"], family_id=e["family_id"], product=e["product"],
                        installed_versions=list(e.get("installed_versions") or []),
                        version_status=e.get("version_status", "unknown"),
                        document_version=e.get("document_version"), file_name=e.get("file_name", ""),
                        topics=int(e.get("topics") or 0), path=e["path"],
                    ))
                infos.sort(key=lambda i: (i.family_id, _collection_key(i), i.collection_id))
                self._catalog, self._catalog_stamp = infos, stamp
            return list(self._catalog)

    def collection(self, collection_id: str) -> CollectionInfo:
        wanted = collection_id.strip().casefold()
        for info in self.collections():
            if info.collection_id.casefold() == wanted or info.path.casefold() == wanted:
                return info
        available = ", ".join(i.collection_id for i in self.collections()) or "(none)"
        raise KnowledgeError(f"Unknown collection '{collection_id}'. Available: {available}")

    def select(self, family: str | None = None, version: str | None = None,
               collection_id: str | None = None) -> list[CollectionInfo]:
        """Filter collections. ``version='latest'`` keeps the highest installed version of each family."""
        if collection_id:
            return [self.collection(collection_id)]
        infos = self.collections()
        if family:
            fam = family.strip().casefold()
            infos = [i for i in infos if i.family_id.casefold() == fam]
            if not infos:
                families = sorted({i.family_id for i in self.collections()})
                raise KnowledgeError(f"No collections for family '{family}'. Available: {', '.join(families)}")
        if version and version.strip().lower() == "latest":
            best: dict[str, CollectionInfo] = {}
            for info in infos:
                if info.family_id not in best or _collection_key(info) > _collection_key(best[info.family_id]):
                    best[info.family_id] = info
            infos = sorted(best.values(), key=lambda i: i.family_id)
        elif version:
            matched = [i for i in infos if version_matches(version, i.installed_versions)]
            if not matched:
                versions = sorted({v for i in infos for v in i.installed_versions}, key=version_key)
                raise KnowledgeError(f"No collection with installed version '{version}'. "
                                     f"Available: {', '.join(versions) or '(none)'}")
            infos = matched
        return infos

    def folder(self, info: CollectionInfo) -> Path:
        return self.root / info.path

    def _json(self, path: Path, default):
        try:
            stat = path.stat()
        except FileNotFoundError:
            return default
        stamp = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            cached = self._json_cache.get(path)
            if cached and cached[0] == stamp:
                return cached[1]
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return default
            self._json_cache[path] = (stamp, data)
            return data

    def topics_meta(self, info: CollectionInfo) -> list[dict]:
        return self._json(self.folder(info) / "indexes" / "topics.json", [])

    def citation(self, info: CollectionInfo, rel: str) -> str:
        return f"{info.path}/{rel}"

    # ------------------------------------------------------------------ path resolution
    def resolve_topic(self, info: CollectionInfo, path: str) -> str:
        """Return the topic path relative to the collection (``topics/...md``) or raise KnowledgeError.

        Accepts ``topics/x.md``, ``x.md``, a citation (``<family>/<hash>/topics/x.md``) or the original
        ``source_topic`` (``x.html``).
        """
        rel = _clean_rel(path)
        prefix = info.path.casefold() + "/"
        if rel.casefold().startswith(prefix):
            rel = rel[len(prefix):]
        meta = self.topics_meta(info)
        if posixpath.splitext(rel)[1].lower() in (".htm", ".html"):
            for topic in meta:
                if topic.get("source_topic", "").casefold() == rel.casefold():
                    return topic["path"]
            raise KnowledgeError(f"No topic with source_topic '{rel}' in {info.collection_id}")
        if not rel.casefold().startswith("topics/"):
            rel = "topics/" + rel
        if not rel.lower().endswith(".md"):
            rel += ".md"
        folder = self.folder(info)
        target = folder / rel
        if _inside(target, folder / "topics") and target.is_file():
            return target.resolve().relative_to(folder.resolve()).as_posix()
        for topic in meta:  # tolerate case differences
            if topic.get("path", "").casefold() == rel.casefold():
                return topic["path"]
        base = posixpath.basename(rel).casefold()
        suggestions = [t["path"] for t in meta if posixpath.basename(t.get("path", "")).casefold() == base][:5]
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else " Use search_topics or get_toc to find it."
        raise KnowledgeError(f"Topic '{path}' not found in {info.collection_id}.{hint}")

    def resolve_asset(self, info: CollectionInfo, path: str) -> Path:
        # Topics reference assets relative to themselves (../../assets/x.png): drop those leading parents.
        raw = path.strip().replace("\\", "/")
        while raw.startswith(("../", "./")):
            raw = raw[3:] if raw.startswith("../") else raw[2:]
        rel = _clean_rel(raw)
        prefix = info.path.casefold() + "/"
        if rel.casefold().startswith(prefix):
            rel = rel[len(prefix):]
        if not rel.casefold().startswith("assets/"):
            rel = "assets/" + rel
        folder = self.folder(info)
        target = folder / rel
        if not (_inside(target, folder / "assets") and target.is_file()):
            raise KnowledgeError(f"Asset '{path}' not found in {info.collection_id}")
        return target.resolve()

    # ------------------------------------------------------------------ search index
    def _fingerprint(self) -> str:
        digest = hashlib.sha256(f"schema={INDEX_SCHEMA}".encode())
        digest.update((self.root / "catalog.json").read_bytes())
        for info in self.collections():
            index = self.folder(info) / "indexes" / "topics.json"
            try:
                stat = index.stat()
                digest.update(f"{info.path}:{stat.st_mtime_ns}:{stat.st_size}".encode())
            except FileNotFoundError:
                digest.update(f"{info.path}:missing".encode())
        return digest.hexdigest()[:20]

    def _build(self, db: sqlite3.Connection) -> int:
        db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        db.execute(
            "CREATE VIRTUAL TABLE topics USING fts5("
            "title, headings, keywords, toc_path, body, "
            "collection_id UNINDEXED, family_id UNINDEXED, path UNINDEXED, "
            "tokenize = 'unicode61 remove_diacritics 2')"
        )
        count = 0
        for info in self.collections():
            folder = self.folder(info)
            rows = []
            for topic in self.topics_meta(info):
                rel = topic.get("path", "")
                file = folder / rel
                if not rel or not _inside(file, folder / "topics") or not file.is_file():
                    continue
                _, body = split_front_matter(file.read_text(encoding="utf-8", errors="replace"))
                body = _ANCHOR.sub("", body)
                rows.append((topic.get("title", ""), "\n".join(topic.get("headings", [])),
                             "\n".join(topic.get("keywords", [])), " > ".join(topic.get("toc_path", [])),
                             body, info.collection_id, info.family_id, rel))
            db.executemany("INSERT INTO topics VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            count += len(rows)
        db.execute("INSERT INTO meta VALUES ('complete', ?)", (str(count),))
        db.commit()
        return count

    def _open_index(self) -> sqlite3.Connection:
        fingerprint = self._fingerprint()
        if self._conn is not None and self._conn_fingerprint == fingerprint:
            return self._conn
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        conn: sqlite3.Connection | None = None
        try:
            self.index_dir.mkdir(parents=True, exist_ok=True)
            target = self.index_dir / f"search-{fingerprint}.sqlite3"
            if target.is_file():
                conn = sqlite3.connect(target, check_same_thread=False)
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone() \
                        or not conn.execute("SELECT value FROM meta WHERE key='complete'").fetchone():
                    conn.close()
                    conn = None
            if conn is None:
                tmp = self.index_dir / f"search-{fingerprint}.{os.getpid()}.{threading.get_ident()}.tmp"
                tmp.unlink(missing_ok=True)
                with sqlite3.connect(tmp) as build:
                    self._build(build)
                build.close()
                try:
                    os.replace(tmp, target)
                except OSError:  # another process published it first (Windows keeps open files locked)
                    tmp.unlink(missing_ok=True)
                conn = sqlite3.connect(target, check_same_thread=False)
            self._cleanup(target)
        except (OSError, sqlite3.Error):
            # Read-only knowledge folder or locked file: keep the index in memory for this process.
            if conn is not None:
                conn.close()
            conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._build(conn)
        self._conn, self._conn_fingerprint = conn, fingerprint
        return conn

    def _cleanup(self, keep: Path) -> None:
        for old in self.index_dir.glob("search-*"):
            if old.resolve() != keep.resolve():
                try:
                    old.unlink()
                except OSError:
                    pass  # still in use by another process; removed next time

    def rebuild_index(self) -> dict:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None
            for old in self.index_dir.glob("search-*") if self.index_dir.is_dir() else []:
                try:
                    old.unlink()
                except OSError:
                    pass
            conn = self._open_index()
            count = int(conn.execute("SELECT value FROM meta WHERE key='complete'").fetchone()[0])
            return {"topics_indexed": count, "collections": len(self.collections())}

    # ------------------------------------------------------------------ queries
    def search(self, query: str, family: str | None = None, version: str | None = None,
               collection_id: str | None = None, limit: int = 10) -> dict:
        if not query or not query.strip():
            raise KnowledgeError("Empty query")
        limit = max(1, min(int(limit), 50))
        infos = {i.collection_id: i for i in self.select(family, version, collection_id)}
        placeholders = ",".join("?" * len(infos))
        # Only "?" placeholders are interpolated; every value is bound as a parameter.
        sql = ("SELECT collection_id, path, title, toc_path, "  # noqa: S608
               "snippet(topics, -1, '**', '**', ' ... ', 24), bm25(topics, 10.0, 5.0, 5.0, 2.0, 1.0) AS rank "
               f"FROM topics WHERE topics MATCH ? AND collection_id IN ({placeholders}) ORDER BY rank LIMIT ?")
        matched = "all terms"
        with self._lock:
            conn = self._open_index()
            rows: list = []
            for operator in ("AND", "OR"):
                expression = _fts_query(query, operator)
                if not expression:
                    raise KnowledgeError("The query has no searchable words")
                try:
                    rows = conn.execute(sql, (expression, *infos, limit)).fetchall()
                except sqlite3.OperationalError as exc:
                    raise KnowledgeError(f"Invalid search query: {exc}") from None
                if rows or " " not in expression:
                    break
                matched = "any term"
        results = []
        for cid, path, title, toc_path, snippet, rank in rows:
            info = infos[cid]
            results.append({
                "title": title, "collection_id": cid, "family_id": info.family_id, "product": info.product,
                "installed_versions": info.installed_versions, "path": path, "citation": self.citation(info, path),
                "toc_path": toc_path.split(" > ") if toc_path else [], "snippet": " ".join(snippet.split()),
                "score": round(-rank, 3),
            })
        return {"query": query, "matched": matched if results else "none", "results": results,
                "collections_searched": sorted(infos)}

    def get_topic(self, collection_id: str, path: str, section: str | None = None,
                  offset: int = 0, max_chars: int = 12000) -> dict:
        info = self.collection(collection_id)
        rel = self.resolve_topic(info, path)
        text = (self.folder(info) / rel).read_text(encoding="utf-8", errors="replace")
        front, body = split_front_matter(text)
        heads = sections(body)
        selected = None
        if section:
            wanted = section.strip().lstrip("#").casefold()
            match = next((h for h in heads if h["title"].casefold() == wanted
                          or any(a.casefold() == wanted for a in h["anchors"])), None)
            match = match or next((h for h in heads if wanted in h["title"].casefold()), None)
            if match is None:
                titles = "; ".join(h["title"] for h in heads) or "(no headings)"
                raise KnowledgeError(f"Section '{section}' not found. Headings: {titles}")
            body = "\n".join(body.splitlines()[match["start"]:match["end"]])
            selected = match["title"]
        max_chars = max(1000, min(int(max_chars), 50000))
        offset = max(0, int(offset))
        chunk = body[offset:offset + max_chars]
        end = offset + len(chunk)
        return {
            "collection_id": info.collection_id, "installed_versions": info.installed_versions,
            "citation": self.citation(info, rel), "path": rel, "title": front.get("title"),
            "toc_path": front.get("toc_path", []), "keywords": front.get("keywords", []),
            "source_topic": front.get("source_topic"), "document_version": front.get("document_version"),
            "section": selected, "headings": [{"level": h["level"], "title": h["title"]} for h in heads],
            "content": chunk, "offset": offset, "total_chars": len(body),
            "next_offset": end if end < len(body) else None,
        }

    def get_toc(self, collection_id: str, under: str | None = None, depth: int = 2,
                max_nodes: int = 400) -> dict:
        info = self.collection(collection_id)
        toc = self._json(self.folder(info) / "toc.json", [])
        nodes, trail = toc, []
        if under:
            steps = [s.strip().casefold() for s in re.split(r"\s*>\s*", under) if s.strip()]
            found = _find_toc(toc, steps)
            if found is None:
                raise KnowledgeError(f"TOC entry '{under}' not found in {info.collection_id}")
            node, trail = found
            nodes = node.get("children", [])
        depth = max(1, min(int(depth), 10))
        budget = [max(1, min(int(max_nodes), 2000))]

        def shape(items: list[dict], level: int) -> list[dict]:
            out = []
            for item in items:
                if budget[0] <= 0:
                    break
                budget[0] -= 1
                entry: dict = {"title": item.get("title")}
                if item.get("path"):
                    entry["citation"] = self.citation(info, item["path"])
                children = item.get("children", [])
                if children and level < depth:
                    entry["children"] = shape(children, level + 1)
                elif children:
                    entry["children_count"] = len(children)
                out.append(entry)
            return out

        shaped = shape(nodes, 1)
        return {"collection_id": info.collection_id, "installed_versions": info.installed_versions,
                "under": trail, "entries": shaped, "truncated": budget[0] <= 0}

    def lookup_keyword(self, keyword: str, family: str | None = None, version: str | None = None,
                       collection_id: str | None = None, exact: bool = False, limit: int = 50) -> dict:
        if not keyword or not keyword.strip():
            raise KnowledgeError("Empty keyword")
        wanted = keyword.strip().casefold()
        words = [w.casefold() for w in _WORD.findall(keyword)]
        limit = max(1, min(int(limit), 200))
        results = []
        for info in self.select(family, version, collection_id):
            titles = {t.get("path"): t.get("title") for t in self.topics_meta(info)}
            for item in self._json(self.folder(info) / "indexes" / "keywords.json", []):
                name = item.get("keyword", "")
                folded = name.casefold()
                if (folded == wanted) if exact else all(w in folded for w in words):
                    results.append({
                        "keyword": name, "collection_id": info.collection_id,
                        "installed_versions": info.installed_versions,
                        "topics": [{"title": titles.get(p, posixpath.basename(p)), "citation": self.citation(info, p)}
                                   for p in item.get("topics", [])],
                    })
        results.sort(key=lambda r: (r["keyword"].casefold() != wanted, len(r["keyword"]), r["keyword"].casefold()))
        return {"keyword": keyword, "exact": exact, "total": len(results), "results": results[:limit]}

    def compare_topic(self, topic: str, family: str | None = None, collection_ids: list[str] | None = None,
                      context_lines: int = 3, max_diff_chars: int = 20000) -> dict:
        """Compare the same topic (matched by source_topic, then by title) across collections."""
        reference: tuple[CollectionInfo, dict] | None = None
        rel_topic = topic.strip().replace("\\", "/")
        for info in self.collections():
            if rel_topic.casefold().startswith(info.path.casefold() + "/"):
                path = self.resolve_topic(info, rel_topic)
                meta = next((t for t in self.topics_meta(info) if t.get("path") == path), None)
                if meta:
                    reference = (info, meta)
                    family = family or info.family_id
                break
        if collection_ids:
            candidates = [self.collection(c) for c in collection_ids]
        elif family:
            candidates = self.select(family=family)
        else:
            raise KnowledgeError("Give 'family' or 'collection_ids' (or a topic citation such as "
                                 "gonow/<hash>/topics/x.md)")
        candidates.sort(key=_collection_key)
        if len(candidates) < 2:
            raise KnowledgeError("At least two collections are needed to compare; only "
                                 f"{', '.join(c.collection_id for c in candidates) or 'none'} available")

        source = (reference[1].get("source_topic") if reference else None) or rel_topic
        title = reference[1].get("title") if reference else None
        found: list[tuple[CollectionInfo, dict | None]] = []
        for info in candidates:
            meta = self.topics_meta(info)
            hit = next((t for t in meta if t.get("source_topic", "").casefold() == source.casefold()), None)
            hit = hit or next((t for t in meta if t.get("path", "").casefold()
                               in (source.casefold(), ("topics/" + source).casefold())), None)
            hit = hit or next((t for t in meta if t.get("title", "").casefold() == (title or source).casefold()), None)
            found.append((info, hit))

        presence, bodies = [], []
        for info, hit in found:
            entry = {"collection_id": info.collection_id, "installed_versions": info.installed_versions,
                     "found": hit is not None}
            if hit:
                entry.update(title=hit.get("title"), citation=self.citation(info, hit["path"]))
                _, body = split_front_matter((self.folder(info) / hit["path"]).read_text(encoding="utf-8",
                                                                                         errors="replace"))
                bodies.append((info, hit, body))
            presence.append(entry)

        diffs, budget = [], max(1000, min(int(max_diff_chars), 100000))
        for (a_info, a_hit, a_body), (b_info, b_hit, b_body) in zip(bodies, bodies[1:], strict=False):
            diff = "\n".join(difflib.unified_diff(
                a_body.splitlines(), b_body.splitlines(), fromfile=self.citation(a_info, a_hit["path"]),
                tofile=self.citation(b_info, b_hit["path"]), lineterm="", n=max(0, min(int(context_lines), 10))))
            item = {"from": a_info.collection_id, "to": b_info.collection_id, "identical": not diff}
            if diff:
                item["diff"] = diff[:budget]
                item["truncated"] = len(diff) > budget
                budget = max(0, budget - len(diff))
            diffs.append(item)
        return {"topic": topic, "matched_by": "source_topic/title", "collections": presence, "comparisons": diffs}

    def asset(self, collection_id: str, path: str) -> tuple[Path, str | None, dict]:
        info = self.collection(collection_id)
        file = self.resolve_asset(info, path)
        size = file.stat().st_size
        mime = IMAGE_TYPES.get(file.suffix.lower())
        rel = file.relative_to(self.folder(info).resolve()).as_posix()
        meta = {"collection_id": info.collection_id, "citation": self.citation(info, rel), "size": size,
                "mime_type": mime}
        if size > MAX_ASSET_BYTES:
            raise KnowledgeError(f"Asset is {size} bytes, above the {MAX_ASSET_BYTES} byte limit")
        return file, mime, meta


def _find_toc(nodes: list[dict], steps: list[str]) -> tuple[dict, list[str]] | None:
    """Find a TOC node by a breadcrumb (``A > B``); a single title matches anywhere in the tree."""
    def walk(items: list[dict], trail: list[str]):
        for item in items:
            title = item.get("title", "")
            path = trail + [title]
            folded = [p.casefold() for p in path]
            if folded[-len(steps):] == steps:
                return item, path
            deeper = walk(item.get("children", []), path)
            if deeper:
                return deeper
        return None
    return walk(nodes, [])
