"""High-level operations used by the CLI: build collections, convert them, write the catalog."""

from __future__ import annotations

import json
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from bs4 import BeautifulSoup

from . import __version__, families
from .chm_metadata import find_sitemap, read_system
from .classification import classify
from .converter import CollectionConverter, ConversionStats
from .encoding import read_text
from .extraction import extract
from .markdown import extract_title
from .models import ChmFile, ChmMetadata, Collection, Installation, to_jsonable
from .safety import display_root, redact
from .versioning import document_version, resolve_installed_version

SCHEMA_VERSION = 1
Progress = Callable[[str], None]


# --------------------------------------------------------------------------- metadata
def _fill_from_extraction(meta: ChmMetadata, extracted: Path) -> ChmMetadata:
    if not meta.contents_file:
        hhc = find_sitemap(extracted, None, ".hhc")
        meta.contents_file = hhc.name if hhc else None
    if not meta.index_file:
        hhk = find_sitemap(extracted, None, ".hhk") if any(extracted.rglob("*.hhk")) else None
        meta.index_file = hhk.name if hhk else None
    if meta.default_topic:
        topic = extracted / meta.default_topic.replace("\\", "/").lstrip("/")
        if topic.is_file():
            text, _ = read_text(topic)
            soup = BeautifulSoup(text, "html.parser")
            meta.welcome_title = extract_title(soup)
            for tag in soup.find_all(["script", "style", "head"]):
                tag.decompose()
            meta.welcome_text = " ".join(soup.get_text(" ").split())[:4000]
    return meta


def read_metadata(chm: Path, seven_zip: str) -> ChmMetadata:
    """Read #SYSTEM, sitemap names and the welcome page without extracting the whole CHM."""
    with tempfile.TemporaryDirectory(prefix="navhelp-") as tmp:
        work = Path(tmp)
        extract(chm, work, seven_zip, patterns=["#SYSTEM", "*.hhc", "*.hhk"])
        meta = read_system(work)
        if meta.default_topic:
            extract(chm, work, seven_zip, patterns=[meta.default_topic.replace("/", "\\").lstrip("\\")])
        return _fill_from_extraction(meta, work)


# --------------------------------------------------------------------------- collections
def group_by_content(files: list[ChmFile]) -> list[list[ChmFile]]:
    groups: dict[str, list[ChmFile]] = defaultdict(list)
    for item in files:
        groups[item.sha256].append(item)
    return sorted(groups.values(), key=lambda g: (g[0].path.name.casefold(), g[0].relative_path.casefold()))


def build_collection(chms: list[ChmFile], meta: ChmMetadata) -> Collection:
    rel_dirs = [str(Path(c.relative_path).parent) for c in chms]
    result = classify(chms[0].path.name, meta, rel_dirs)
    family = families.get(result.family_id)
    installations = [Installation(c, resolve_installed_version(c, family)) for c in chms]
    doc_version, doc_evidence = document_version(meta)
    return Collection(
        sha256=chms[0].sha256, file_name=chms[0].path.name, size=chms[0].size,
        installations=installations, classification=result, metadata=meta,
        document_version=doc_version, document_version_evidence=doc_evidence,
    )


def collection_version_status(collection: Collection) -> str:
    statuses = {i.version.status for i in collection.installations}
    for status in ("conflicting", "unknown", "inferred"):
        if status in statuses:
            return status
    return "confirmed"


def inspect_groups(groups: list[list[ChmFile]], seven_zip: str, progress: Progress | None = None) -> list[Collection]:
    collections = []
    for group in groups:
        if progress:
            progress(f"Reading {group[0].path.name} ({group[0].sha256[:12]})")
        collections.append(build_collection(group, read_metadata(group[0].path, seven_zip)))
    return collections


# --------------------------------------------------------------------------- manifest
def installation_record(inst: Installation, hide_roots: bool) -> dict:
    return {
        "root": display_root(inst.chm.root, hide_roots),
        "relative_path": inst.chm.relative_path,
        "installed_version": inst.version.installed_version,
        "version_status": inst.version.status,
        "candidates": inst.version.candidates,
        "evidence": to_jsonable(inst.version.evidence),
    }


def build_manifest(collection: Collection, stats: ConversionStats | None, hide_roots: bool) -> dict:
    family = families.get(collection.classification.family_id)
    meta = collection.metadata
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "navitaire-help-exporter", "version": __version__},
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "collection_id": collection.collection_id,
        "family_id": family.family_id,
        "product": collection.classification.product,
        "domain": family.domain,
        "classification": {
            "status": collection.classification.status,
            "score": collection.classification.score,
            "runner_up": collection.classification.runner_up,
            "evidence": to_jsonable(collection.classification.evidence),
        },
        "installed_versions": collection.installed_versions,
        "version_status": collection_version_status(collection),
        "document_version": collection.document_version,
        "document_version_evidence": to_jsonable(collection.document_version_evidence),
        "source": {
            "file_name": collection.file_name,
            "sha256": collection.sha256,
            "size": collection.size,
            "chm_title": meta.title,
            "default_topic": meta.default_topic,
            "contents_file": meta.contents_file,
            "index_file": meta.index_file,
            "lcid": meta.lcid,
        },
        "installations": [installation_record(i, hide_roots) for i in collection.installations],
        "content": None if stats is None else {
            "topics": stats.topics,
            "assets": stats.assets,
            "toc_entries": stats.toc_entries,
            "keywords": stats.keywords,
            "failed_topics": stats.failed_topics,
        },
        "diagnostics": None if stats is None else dict(sorted(stats.diagnostics.items())),
    }


def _collection_readme(manifest: dict) -> str:
    versions = ", ".join(manifest["installed_versions"]) or "unknown"
    content = manifest["content"] or {}
    return (
        f"# {manifest['product']} help\n\n"
        f"- Collection: `{manifest['collection_id']}`\n"
        f"- Family: `{manifest['family_id']}` - {manifest['domain']}\n"
        f"- Installed versions: {versions} ({manifest['version_status']})\n"
        f"- Version stated in the help content: {manifest['document_version'] or 'not stated'}\n"
        f"- Source file: `{manifest['source']['file_name']}` (SHA-256 `{manifest['source']['sha256'][:12]}...`)\n"
        f"- Topics: {content.get('topics', 0)}, assets: {content.get('assets', 0)}\n\n"
        "Start with [toc.md](toc.md) (original table of contents) or "
        "[indexes/keywords.md](indexes/keywords.md) (original keyword index).\n"
        "Metadata for tools: `manifest.json`, `indexes/topics.json`, `indexes/keywords.json`.\n\n"
        "> Proprietary Navitaire documentation. Do not commit it to source control or share it outside "
        "authorised channels.\n"
    )


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(redact(json.dumps(data, indent=2, ensure_ascii=False)) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- conversion
@dataclass
class ConvertOutcome:
    collection: Collection
    status: str  # converted | unchanged | partial | skipped | failed
    path: Path | None = None
    message: str = ""


def convert_group(group: list[ChmFile], output: Path, seven_zip: str, *, force: bool, hide_roots: bool,
                  family_filter: set[str], include_unknown: bool) -> ConvertOutcome:
    # Classify from a partial extraction first; only extract everything when converting.
    collection = build_collection(group, read_metadata(group[0].path, seven_zip))
    family_id = collection.classification.family_id

    if family_filter and family_id not in family_filter:
        return ConvertOutcome(collection, "skipped", message="family not selected")
    if family_id == "unknown" and not include_unknown:
        return ConvertOutcome(collection, "skipped", message="unknown family (use --include-unknown)")

    dest = output / family_id / collection.sha256[:12]
    manifest_path = dest / "manifest.json"
    if manifest_path.is_file() and not force:
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = {}
        if previous.get("tool", {}).get("version") == __version__ \
                and previous.get("installed_versions") == collection.installed_versions:
            previous["installations"] = [installation_record(i, hide_roots) for i in collection.installations]
            _write_json(manifest_path, previous)
            return ConvertOutcome(collection, "unchanged", dest)

    with tempfile.TemporaryDirectory(prefix="navhelp-") as tmp:
        work = Path(tmp) / "chm"
        extract(group[0].path, work, seven_zip)
        staging = output / family_id / f".{collection.sha256[:12]}.partial"
        if staging.exists():
            shutil.rmtree(staging)
        stats, _topics = CollectionConverter(work, staging, collection).run()
        manifest = build_manifest(collection, stats, hide_roots)
        _write_json(staging / "manifest.json", manifest)
        (staging / "README.md").write_text(_collection_readme(manifest), encoding="utf-8", newline="\n")
        if dest.exists():
            shutil.rmtree(dest)
        staging.rename(dest)
        status = "partial" if stats.failed_topics else "converted"
        return ConvertOutcome(collection, status, dest)


# --------------------------------------------------------------------------- catalog
def write_catalog(output: Path) -> list[dict]:
    """Rebuild ``catalog.json`` / ``catalog.md`` from every manifest present under *output*."""
    entries = []
    for manifest_path in sorted(output.glob("*/*/manifest.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries.append({
            "collection_id": manifest["collection_id"],
            "family_id": manifest["family_id"],
            "product": manifest["product"],
            "installed_versions": manifest["installed_versions"],
            "version_status": manifest["version_status"],
            "document_version": manifest["document_version"],
            "file_name": manifest["source"]["file_name"],
            "topics": (manifest.get("content") or {}).get("topics", 0),
            "path": manifest_path.parent.relative_to(output).as_posix(),
        })
    entries.sort(key=lambda e: (e["family_id"], e["installed_versions"][-1:] or [""], e["collection_id"]))
    _write_json(output / "catalog.json", {"schema_version": SCHEMA_VERSION, "collections": entries})

    lines = [
        "# Navitaire help catalog", "",
        "Generated by navitaire-help-exporter. Each row is one distinct help file (by content hash).",
        "Pick the collection whose *installed versions* match the product version you are asking about;",
        "never combine answers from different collections without saying so.", "",
        "| Family | Product | Installed versions | Status | Help states | Topics | Collection |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for e in entries:
        versions = ", ".join(e["installed_versions"]) or "unknown"
        lines.append(f"| {e['family_id']} | {e['product']} | {versions} | {e['version_status']} | "
                     f"{e['document_version'] or '-'} | {e['topics']} | [{e['path']}]({e['path']}/README.md) |")
    lines += ["", "> Proprietary Navitaire documentation. Keep this folder out of source control.", ""]
    (output / "catalog.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return entries
