"""Convert one extracted CHM into a self-contained Markdown collection folder.

Layout written under *dest*::

    README.md                 collection overview (product, versions, entry points)
    toc.md / toc.json         original table of contents (.hhc)
    topics/<internal path>.md one Markdown file per HTML topic, with YAML front matter
    assets/<internal path>    images and attachments referenced by topics
    indexes/topics.json       topic metadata (title, path, breadcrumbs, headings, keywords)
    indexes/keywords.json     original keyword index (.hhk)
    indexes/keywords.md       keyword index for humans
    diagnostics/links.json    broken / cross-help / name-resolved links
    diagnostics/conversion.json  collisions, failed topics, unresolved TOC entries
"""

from __future__ import annotations

import json
import posixpath
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, unquote

from .chm_metadata import find_sitemap, normalize_local, parse_sitemap
from .encoding import read_text
from .markdown import html_to_markdown
from .models import Collection

HTML_EXT = {".htm", ".html"}
ASSET_EXT = {".png", ".gif", ".jpg", ".jpeg", ".bmp", ".svg", ".webp", ".ico", ".pdf"}
_SCHEME = re.compile(r"^[a-z][a-z0-9+.\-]*:", re.IGNORECASE)


def _key(rel: str) -> str:
    """Case-insensitive lookup key for an internal path, without extension."""
    return posixpath.splitext(rel)[0].casefold()


_GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _loose(rel: str) -> str:
    """Name key tolerant of the space/underscore/hyphen variations found in Navitaire links."""
    return re.sub(r"[\s_\-]+", "_", posixpath.basename(_key(rel))).strip("_")


def _quote(rel: str) -> str:
    return quote(rel, safe="/._-~")


@dataclass
class ConversionStats:
    topics: int = 0
    assets: int = 0
    toc_entries: int = 0
    keywords: int = 0
    failed_topics: int = 0
    diagnostics: Counter = field(default_factory=Counter)


class CollectionConverter:
    def __init__(self, extracted: Path, dest: Path, collection: Collection) -> None:
        self.src = extracted
        self.dest = dest
        self.collection = collection
        self.stats = ConversionStats()
        self.link_issues: list[dict] = []
        self.conversion_issues: list[dict] = []

        self.html_files: list[str] = []
        self.asset_files: list[str] = []
        for path in sorted(extracted.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(extracted).as_posix()
            if any(part.startswith(("#", "$")) for part in rel.split("/")):
                continue
            ext = path.suffix.lower()
            if ext in HTML_EXT:
                self.html_files.append(rel)
            elif ext in ASSET_EXT:
                self.asset_files.append(rel)

        self.md_by_key: dict[str, str] = {}
        self.md_by_stem: dict[str, list[str]] = defaultdict(list)
        self.md_by_loose: dict[str, list[str]] = defaultdict(list)
        self.topic_md: dict[str, str] = {}
        used: set[str] = set()
        for rel in self.html_files:
            md = "topics/" + posixpath.splitext(rel)[0] + ".md"
            if md.casefold() in used:
                base, n = md[:-3], 2
                while f"{base}__{n}.md".casefold() in used:
                    n += 1
                self.conversion_issues.append({"type": "collision", "topic": rel, "renamed_to": f"{base}__{n}.md"})
                md = f"{base}__{n}.md"
            used.add(md.casefold())
            self.topic_md[rel] = md
            self.md_by_key.setdefault(_key(rel), md)
            self.md_by_stem[posixpath.basename(_key(rel))].append(md)
            self.md_by_loose[_loose(rel)].append(md)

        self.asset_by_key = {rel.casefold(): "assets/" + rel for rel in self.asset_files}
        self.asset_by_name: dict[str, list[str]] = defaultdict(list)
        for rel in self.asset_files:
            self.asset_by_name[posixpath.basename(rel).casefold()].append("assets/" + rel)

        self.toc: list[dict] = []
        self.toc_title: dict[str, str] = {}
        self.breadcrumbs: dict[str, list[str]] = {}
        self.keywords_by_md: dict[str, list[str]] = defaultdict(list)
        self.keyword_index: list[dict] = []

    # ------------------------------------------------------------------ resolution
    def _lookup_topic(self, internal: str) -> tuple[str | None, str | None]:
        md = self.md_by_key.get(_key(internal))
        if md:
            return md, None
        candidates = self.md_by_stem.get(posixpath.basename(_key(internal)), [])
        if len(candidates) == 1:
            return candidates[0], "resolved-by-name"
        if candidates:
            return None, "ambiguous-link"
        loose = self.md_by_loose.get(_loose(internal), [])
        if len(loose) == 1:
            return loose[0], "resolved-by-name"
        if _GUID.match(posixpath.basename(internal)):
            return None, "unresolved-topic-id"  # HelpStudio topic GUID never resolved when the CHM was built
        return None, "broken-link" if not loose else "ambiguous-link"

    def _lookup_asset(self, internal: str) -> tuple[str | None, str | None]:
        asset = self.asset_by_key.get(internal.casefold())
        if asset:
            return asset, None
        candidates = self.asset_by_name.get(posixpath.basename(internal).casefold(), [])
        if len(candidates) == 1:
            return candidates[0], "resolved-by-name"
        return None, "missing-asset"

    def _internal_path(self, current_rel: str, path: str) -> str:
        path = unquote(path).replace("\\", "/")
        if path.startswith("/"):
            return posixpath.normpath(path.lstrip("/"))
        joined = posixpath.normpath(posixpath.join(posixpath.dirname(current_rel), path))
        if joined.startswith("../"):
            joined = posixpath.normpath(path)
        return joined

    def _record(self, kind: str, topic: str, href: str) -> None:
        self.stats.diagnostics[kind] += 1
        self.link_issues.append({"type": kind, "topic": topic, "href": href})

    def resolve(self, href: str, current_rel: str, current_md: str, image: bool = False) -> str | None:
        raw = href.strip()
        if not raw:
            self._record("empty-link", current_rel, href)
            return None
        lower = raw.lower()
        if lower.startswith(("javascript:", "vbscript:", "mailto:", "file:")):
            return None
        if lower.startswith(("ms-its:", "mk:@msitstore:", "its:")) and "::" in raw:
            chm_part, inner = raw.split("::", 1)
            chm_name = posixpath.basename(chm_part.replace("\\", "/").split(":")[-1]).casefold()
            if chm_name and chm_name != self.collection.file_name.casefold():
                self._record("cross-help-link", current_rel, raw)
                return None
            raw = inner
        elif _SCHEME.match(raw):
            return raw if lower.startswith(("http://", "https://")) else None

        if raw.startswith("#"):
            return "#" + quote(unquote(raw[1:]), safe="._-~")
        path, _, fragment = raw.partition("#")
        path = path.split("?", 1)[0]
        if not path:
            return "#" + quote(unquote(fragment), safe="._-~") if fragment else None
        internal = self._internal_path(current_rel, path)
        ext = posixpath.splitext(internal)[1].lower()

        if image or ext in ASSET_EXT:
            target, issue = self._lookup_asset(internal)
        else:
            target, issue = self._lookup_topic(internal)
        if issue:
            self._record(issue, current_rel, href)
        if not target:
            return None
        out = _quote(posixpath.relpath(target, posixpath.dirname(current_md)))
        if fragment:
            out += "#" + quote(unquote(fragment), safe="._-~")
        return out

    # ------------------------------------------------------------------ toc / index
    def _load_toc(self) -> None:
        meta = self.collection.metadata
        hhc = find_sitemap(self.src, meta.contents_file, ".hhc")
        if not hhc:
            self.conversion_issues.append({"type": "missing-toc"})
            return

        def walk(nodes: list[dict], trail: list[str]) -> list[dict]:
            out = []
            for node in nodes:
                title = node.get("title") or "(untitled)"
                entry: dict = {"title": title}
                local = normalize_local(node["locals"][0]) if node.get("locals") else None
                if local:
                    md, issue = self._lookup_topic(local)
                    if md:
                        entry["path"] = md
                        self.toc_title.setdefault(md, title)
                        self.breadcrumbs.setdefault(md, trail + [title])
                    else:
                        self.conversion_issues.append({"type": "toc-target-missing", "title": title, "local": local})
                self.stats.toc_entries += 1
                children = walk(node.get("children", []), trail + [title])
                if children:
                    entry["children"] = children
                out.append(entry)
            return out

        self.toc = walk(parse_sitemap(hhc), [])

    def _load_keywords(self) -> None:
        hhk = find_sitemap(self.src, self.collection.metadata.index_file, ".hhk")
        if not hhk:
            return

        def walk(nodes: list[dict], parent: str | None) -> None:
            for node in nodes:
                title = node.get("title", "").strip()
                if not title:
                    continue
                keyword = f"{parent}, {title}" if parent else title
                targets = []
                for local in node.get("locals", []):
                    internal = normalize_local(local)
                    md = self._lookup_topic(internal)[0] if internal else None
                    if md and md not in targets:
                        targets.append(md)
                        self.keywords_by_md[md].append(keyword)
                if targets:
                    self.keyword_index.append({"keyword": keyword, "topics": targets})
                    self.stats.keywords += 1
                walk(node.get("children", []), keyword)

        walk(parse_sitemap(hhk), None)

    # ------------------------------------------------------------------ writing
    def _front_matter(self, fields: dict) -> str:
        lines = ["---"]
        for key, value in fields.items():
            if value is None or value == [] or value == "":
                continue
            lines.append(f"{key}: {json.dumps(value, ensure_ascii=False)}")
        lines.append("---")
        return "\n".join(lines) + "\n\n"

    def _write(self, rel: str, text: str) -> None:
        path = self.dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")

    def _toc_markdown(self) -> str:
        c = self.collection
        lines = [f"# {c.classification.product} - Table of contents", ""]

        def walk(nodes: list[dict], depth: int) -> None:
            for node in nodes:
                indent = "  " * depth
                if node.get("path"):
                    lines.append(f"{indent}- [{node['title']}]({_quote(node['path'])})")
                else:
                    lines.append(f"{indent}- {node['title']}")
                walk(node.get("children", []), depth + 1)

        walk(self.toc, 0)
        return "\n".join(lines) + "\n"

    def run(self) -> tuple[ConversionStats, list[dict]]:
        self.dest.mkdir(parents=True, exist_ok=True)
        self._load_toc()
        self._load_keywords()
        c = self.collection

        for rel in self.asset_files:
            target = self.dest / "assets" / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(self.src / rel, target)
            self.stats.assets += 1

        topics: list[dict] = []
        for rel in self.html_files:
            md = self.topic_md[rel]
            try:
                text, _encoding = read_text(self.src / rel)
                result = html_to_markdown(
                    text,
                    lambda href, r=rel, m=md: self.resolve(href, r, m),
                    lambda src, r=rel, m=md: self.resolve(src, r, m, image=True),
                )
            except Exception as exc:  # keep converting the rest; report the failure
                self.stats.failed_topics += 1
                self.conversion_issues.append({"type": "topic-failed", "topic": rel, "error": type(exc).__name__})
                continue

            title = self.toc_title.get(md) or result.html_title or posixpath.basename(posixpath.splitext(rel)[0])
            body = result.markdown
            first = next((line for line in body.splitlines() if line.strip()), "")
            if not first.startswith("# "):
                body = f"# {title}\n\n{body}"
            front = self._front_matter({
                "title": title,
                "collection_id": c.collection_id,
                "family_id": c.classification.family_id,
                "product": c.classification.product,
                "installed_versions": c.installed_versions,
                "document_version": c.document_version,
                "source_chm": c.file_name,
                "source_topic": rel,
                "toc_path": self.breadcrumbs.get(md, []),
                "keywords": sorted(set(self.keywords_by_md.get(md, []))),
            })
            self._write(md, front + body)
            self.stats.topics += 1
            topics.append({
                "title": title,
                "path": md,
                "source_topic": rel,
                "toc_path": self.breadcrumbs.get(md, []),
                "headings": result.headings,
                "keywords": sorted(set(self.keywords_by_md.get(md, []))),
            })

        self._write("toc.json", json.dumps(self.toc, indent=2, ensure_ascii=False))
        self._write("toc.md", self._toc_markdown())
        self._write("indexes/topics.json", json.dumps(topics, indent=2, ensure_ascii=False))
        self._write("indexes/keywords.json", json.dumps(self.keyword_index, indent=2, ensure_ascii=False))
        kw_lines = [f"# {c.classification.product} - Keyword index", ""]
        for item in sorted(self.keyword_index, key=lambda k: k["keyword"].casefold()):
            links = ", ".join(f"[{i + 1}](../{_quote(p)})" for i, p in enumerate(item["topics"]))
            kw_lines.append(f"- {item['keyword']}: {links}")
        self._write("indexes/keywords.md", "\n".join(kw_lines) + "\n")
        self._write("diagnostics/links.json", json.dumps(self.link_issues, indent=2, ensure_ascii=False))
        self._write("diagnostics/conversion.json", json.dumps(self.conversion_issues, indent=2, ensure_ascii=False))
        for issue in self.conversion_issues:
            self.stats.diagnostics[issue["type"]] += 1
        return self.stats, topics
