"""Local MCP server (stdio) exposing the converted Navitaire help and the navhelp operations.

Start with ``navhelp mcp --knowledge .\\knowledge`` (requires the optional extra: ``pip install ".[mcp]"``).

Tools
    Query (read-only):  list_collections, search_topics, get_topic, get_toc, lookup_keyword,
                        compare_topic, get_asset
    Operations:         scan_installations, inspect_installations (read-only on the installations),
                        rebuild_search_index (writes only the disposable search cache),
                        convert_help (writes the knowledge folder; only with --allow-convert)

Design rules
    * stdio only: no network listener, no outbound calls.
    * Every path argument is confined to the knowledge folder (see knowledge.py).
    * convert_help can only write to the knowledge folder the server was started with, and goes through the same
      safety checks as ``navhelp convert`` (never inside an installation root, never un-ignored inside Git).
    * User profile paths are redacted from every result.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
from pathlib import Path
from typing import Any

from . import __version__, families
from .config import Settings, load_settings
from .discovery import scan
from .extraction import ExtractionError, find_7zip
from .knowledge import KnowledgeBase, KnowledgeError
from .pipeline import (
    build_manifest,
    collection_version_status,
    convert_group,
    group_by_content,
    inspect_groups,
    write_catalog,
)
from .safety import UnsafeOutputError, display_root, ensure_safe_output, redact
from .validate import validate_output

try:
    from mcp.server.mcpserver import Image, MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
    from mcp.types import ToolAnnotations
except ImportError:  # pragma: no cover - exercised only without the optional extra
    MCPServer = None  # type: ignore[assignment,misc]

log = logging.getLogger("navhelp.mcp")

INSTRUCTIONS = """\
Navitaire help converted to Markdown by navhelp (products: GoNow, SkySpeed, Fare Manager, Schedule Manager,
New Skies Management Console and plug-ins, GSS Management Console, Device Manager).

How to research:
1. list_collections to see families and installed versions. Each collection is one distinct help file.
2. search_topics (filter by family and version; version="latest" = highest installed) or lookup_keyword for the
   original CHM keyword index. Use get_toc to browse.
3. get_topic to read a topic (or one section) before stating anything. Page long topics with next_offset.
4. compare_topic to see how a topic changed between installed versions.
Always cite the 'citation' path and the collection's installed_versions. Never mix versions without saying so.
The content is proprietary Navitaire documentation: summarise and cite; do not reproduce long passages.
"""


def _redacted(data: Any) -> Any:
    """Apply profile-path redaction to every string in a JSON-compatible structure."""
    return json.loads(redact(json.dumps(data, ensure_ascii=False)))


class NavhelpTools:
    """Plain Python implementation of every tool; the MCP layer only adapts errors and registration."""

    def __init__(self, knowledge: Path, settings: Settings, allow_convert: bool = False) -> None:
        self.kb = KnowledgeBase(knowledge)
        self.settings = settings
        self.allow_convert = allow_convert
        self._convert_lock = threading.Lock()

    # ------------------------------------------------------------------ query
    def list_collections(self, family: str | None = None, version: str | None = None) -> dict:
        infos = self.kb.select(family, version)
        known = {f.family_id: f for f in families.FAMILIES}
        return {"knowledge_root": redact(str(self.kb.root)), "collections": [
            {**i.public(), "domain": known[i.family_id].domain if i.family_id in known else None} for i in infos]}

    def search_topics(self, query: str, family: str | None = None, version: str | None = None,
                      collection_id: str | None = None, limit: int = 10) -> dict:
        return self.kb.search(query, family, version, collection_id, limit)

    def get_topic(self, collection_id: str, path: str, section: str | None = None, offset: int = 0,
                  max_chars: int = 12000) -> dict:
        return self.kb.get_topic(collection_id, path, section, offset, max_chars)

    def get_toc(self, collection_id: str, under: str | None = None, depth: int = 2) -> dict:
        return self.kb.get_toc(collection_id, under, depth)

    def lookup_keyword(self, keyword: str, family: str | None = None, version: str | None = None,
                       collection_id: str | None = None, exact: bool = False, limit: int = 50) -> dict:
        return self.kb.lookup_keyword(keyword, family, version, collection_id, exact, limit)

    def compare_topic(self, topic: str, family: str | None = None, collection_ids: list[str] | None = None,
                      context_lines: int = 3) -> dict:
        return self.kb.compare_topic(topic, family, collection_ids, context_lines)

    def rebuild_search_index(self) -> dict:
        return self.kb.rebuild_index()

    # ------------------------------------------------------------------ operations
    def _files(self, roots: list[str] | None):
        roots_paths = [Path(r) for r in roots] if roots else self.settings.roots
        result = scan(roots_paths, self.settings.exclude, self.settings.follow_links)
        return roots_paths, result

    def scan_installations(self, roots: list[str] | None = None) -> dict:
        roots_paths, result = self._files(roots)
        groups = group_by_content(result.files)
        return _redacted({
            "roots": [display_root(r, False) for r in roots_paths],
            "excluded_folders": self.settings.exclude,
            "files": len(result.files), "distinct": len(groups), "warnings": result.warnings,
            "groups": [{"file_name": g[0].path.name, "sha256": g[0].sha256[:12], "size": g[0].size,
                        "locations": [c.relative_path for c in g]} for g in groups],
        })

    def inspect_installations(self, roots: list[str] | None = None, evidence: bool = False) -> dict:
        _, result = self._files(roots)
        seven_zip = find_7zip(self.settings.seven_zip)
        collections = inspect_groups(group_by_content(result.files), seven_zip)
        rows = []
        for c in collections:
            row = {"family_id": c.classification.family_id, "product": c.classification.product,
                   "classification": c.classification.status, "installed_versions": c.installed_versions,
                   "version_status": collection_version_status(c), "document_version": c.document_version,
                   "file_name": c.file_name, "collection_id": c.collection_id}
            if evidence:
                manifest = build_manifest(c, None, hide_roots=False)
                row["classification_evidence"] = manifest["classification"]["evidence"]
                row["installations"] = manifest["installations"]
            rows.append(row)
        return _redacted({"collections": rows, "warnings": result.warnings})

    def convert_help(self, families_filter: list[str] | None = None, force: bool = False,
                     include_unknown: bool = False, validate: bool = True) -> dict:
        if not self.allow_convert:
            raise KnowledgeError("convert_help is disabled. Start the server with --allow-convert, "
                                 "or run: navhelp convert --output <knowledge folder> --validate")
        selected = set(families_filter or [])
        unknown_ids = selected - set(families.BY_ID) - {"unknown"}
        if unknown_ids:
            raise KnowledgeError(f"Unknown family id(s): {', '.join(sorted(unknown_ids))}")
        output = self.kb.root
        if not self._convert_lock.acquire(blocking=False):
            raise KnowledgeError("A conversion is already running")
        try:
            ensure_safe_output(output, self.settings.roots)
            seven_zip = find_7zip(self.settings.seven_zip)
            groups = group_by_content(self._files(None)[1].files)
            if not groups:
                raise KnowledgeError("No CHM files found under the configured roots")
            output.mkdir(parents=True, exist_ok=True)
            outcomes = []
            for group in groups:
                try:
                    outcome = convert_group(group, output, seven_zip, force=force, hide_roots=False,
                                            family_filter=selected,
                                            include_unknown=include_unknown or self.settings.include_unknown)
                except (ExtractionError, OSError) as exc:
                    outcomes.append({"file_name": group[0].path.name, "status": "failed", "error": str(exc)})
                    continue
                c = outcome.collection
                outcomes.append({"file_name": c.file_name, "status": outcome.status,
                                 "family_id": c.classification.family_id, "installed_versions": c.installed_versions,
                                 "path": outcome.path.relative_to(output).as_posix() if outcome.path else None,
                                 "message": outcome.message or None})
            entries = write_catalog(output)
            result: dict = {"output": str(output), "collections_in_catalog": len(entries), "outcomes": outcomes}
            if validate:
                report = validate_output(output)
                result["validation"] = {"ok": report.ok, "collections": report.collections, "topics": report.topics,
                                        "errors": report.errors, "warnings": report.warnings[:50]}
            return _redacted(result)
        finally:
            self._convert_lock.release()


# --------------------------------------------------------------------------- MCP registration
_READ_ONLY = {"read_only_hint": True, "destructive_hint": False, "idempotent_hint": True, "open_world_hint": False}


def create_server(knowledge: Path, settings: Settings | None = None, allow_convert: bool = False):
    if MCPServer is None:
        raise RuntimeError('The MCP extra is not installed. Run: python -m pip install ".[mcp]"')
    tools = NavhelpTools(knowledge, settings or Settings(), allow_convert)
    server = MCPServer(name="navhelp", title="Navitaire help (navhelp)", version=__version__,
                       instructions=INSTRUCTIONS)

    def call(func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (KnowledgeError, UnsafeOutputError, ExtractionError, FileNotFoundError) as exc:
            raise ToolError(redact(str(exc))) from None

    def read_only(title: str) -> ToolAnnotations:
        return ToolAnnotations(title=title, **_READ_ONLY)

    @server.tool(annotations=read_only("List help collections"))
    def list_collections(family: str | None = None, version: str | None = None) -> dict:
        """List converted help collections (one per distinct CHM) with product, family and installed versions.

        family: family id such as gonow, skyspeed, skyfare, skyschedule, newskies-management-console,
        gss-management-console, device-manager. version: installed version prefix (9.1 matches 9.1.0.200) or
        "latest" for the highest installed version of each family.
        """
        return call(tools.list_collections, family, version)

    @server.tool(annotations=read_only("Search help topics"))
    def search_topics(query: str, family: str | None = None, version: str | None = None,
                      collection_id: str | None = None, limit: int = 10) -> dict:
        """Full-text search (ranked) over topic titles, headings, keywords, breadcrumbs and body.

        Words are combined with AND; if nothing matches the search falls back to OR ('matched' says which).
        Use "quoted phrases" and prefix* wildcards. Filter with family, version ("latest" or a prefix) or
        collection_id. Returns citations to pass to get_topic.
        """
        return call(tools.search_topics, query, family, version, collection_id, limit)

    @server.tool(annotations=read_only("Read a help topic"))
    def get_topic(collection_id: str, path: str, section: str | None = None, offset: int = 0,
                  max_chars: int = 12000) -> dict:
        """Read one topic as Markdown with its metadata (title, breadcrumbs, keywords, headings).

        path: the citation or path returned by other tools (topics/x.md, <family>/<hash>/topics/x.md) or the
        original source_topic (x.html). section: heading title or anchor to return only that section.
        Long topics are paged: call again with offset=next_offset.
        """
        return call(tools.get_topic, collection_id, path, section, offset, max_chars)

    @server.tool(annotations=read_only("Browse the table of contents"))
    def get_toc(collection_id: str, under: str | None = None, depth: int = 2) -> dict:
        """Return the original table of contents of a collection, or the subtree under an entry.

        under: an entry title or breadcrumb such as "Tasks > Boarding". depth: levels to expand (1-10);
        deeper levels are summarised with children_count.
        """
        return call(tools.get_toc, collection_id, under, depth)

    @server.tool(annotations=read_only("Look up the keyword index"))
    def lookup_keyword(keyword: str, family: str | None = None, version: str | None = None,
                       collection_id: str | None = None, exact: bool = False, limit: int = 50) -> dict:
        """Search the original CHM keyword index (F1 help index). By default every word must appear in the
        keyword; exact=true requires the whole keyword to match. Returns the topics linked to each keyword."""
        return call(tools.lookup_keyword, keyword, family, version, collection_id, exact, limit)

    @server.tool(annotations=read_only("Compare a topic across versions"))
    def compare_topic(topic: str, family: str | None = None, collection_ids: list[str] | None = None,
                      context_lines: int = 3) -> dict:
        """Compare the same topic across collections (installed versions) with a unified diff.

        topic: a citation (<family>/<hash>/topics/x.md), a source_topic (x.html) or a topic title.
        Give family (all its collections, ordered by version) or an explicit list of collection_ids.
        """
        return call(tools.compare_topic, topic, family, collection_ids, context_lines)

    @server.tool(annotations=read_only("Get an image or attachment"))
    def get_asset(collection_id: str, path: str):
        """Return an image referenced by a topic (for example ../assets/images/x.png) so it can be viewed.
        Non-image attachments are described (size, citation) but not returned."""
        file, mime, meta = call(tools.kb.asset, collection_id, path)
        if mime is None or mime == "image/svg+xml":
            return {**meta, "note": "Not an image that can be returned inline; open the citation path locally."}
        return Image(path=file)

    @server.tool(annotations=ToolAnnotations(title="Rebuild the search index", read_only_hint=False,
                                             destructive_hint=False, idempotent_hint=True, open_world_hint=False))
    def rebuild_search_index() -> dict:
        """Rebuild the full-text search cache (<knowledge>/.navhelp-index). It is rebuilt automatically when the
        catalog changes; use this only if search results look stale."""
        return call(tools.rebuild_search_index)

    @server.tool(annotations=read_only("Scan installed CHM files"))
    def scan_installations(roots: list[str] | None = None) -> dict:
        """Find CHM help files under the Navitaire installation roots (default C:\\Program Files (x86)\\Navitaire)
        without opening them; groups duplicates by content hash. Read-only."""
        return call(tools.scan_installations, roots)

    @server.tool(annotations=read_only("Identify product and version of installed CHM files"))
    def inspect_installations(roots: list[str] | None = None, evidence: bool = False) -> dict:
        """Identify the product and installed version of each distinct CHM (reads CHM metadata with 7-Zip into a
        temporary folder, the Windows registry and executable version resources). Read-only on installations.
        evidence=true adds the classification and version evidence."""
        return call(tools.inspect_installations, roots, evidence)

    if allow_convert:
        @server.tool(annotations=ToolAnnotations(title="Convert installed help to Markdown", read_only_hint=False,
                                                 destructive_hint=False, idempotent_hint=True,
                                                 open_world_hint=False))
        def convert_help(families: list[str] | None = None, force: bool = False, include_unknown: bool = False,
                         validate: bool = True) -> dict:
            """Convert installed CHM help into the knowledge folder this server reads (incremental: unchanged
            collections are skipped unless force=true), rebuild the catalog and validate it. Can take several
            minutes; restrict with families (e.g. ["gonow"]) when possible."""
            return call(tools.convert_help, families, force, include_unknown, validate)

    return server


def run(knowledge: Path, config: str | None = None, allow_convert: bool = False) -> int:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)  # stdout is the MCP channel
    settings = load_settings(config)
    server = create_server(knowledge, settings, allow_convert)
    server.run("stdio")
    return 0
