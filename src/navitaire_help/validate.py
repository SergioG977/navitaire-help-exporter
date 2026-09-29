"""Check that an output folder is complete, consistent and free of personal paths."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

REQUIRED_MANIFEST_KEYS = (
    "schema_version", "collection_id", "family_id", "product", "installed_versions",
    "version_status", "source", "installations", "content",
)
REQUIRED_FRONT_MATTER = ("title", "collection_id", "family_id", "product", "source_topic")
_USER_PATH = re.compile(r"[A-Za-z]:\\{1,2}Users\\{1,2}[^\\\"/]+", re.IGNORECASE)


@dataclass
class ValidationReport:
    collections: int = 0
    topics: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _front_matter(text: str) -> dict[str, str] | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    fields = {}
    for line in text[4:end].splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def validate_output(output: Path) -> ValidationReport:
    report = ValidationReport()
    if not output.is_dir():
        report.errors.append(f"Output folder not found: {output}")
        return report

    catalog_path = output / "catalog.json"
    catalog_paths: set[str] = set()
    if catalog_path.is_file():
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            catalog_paths = {c["path"] for c in catalog.get("collections", [])}
        except (json.JSONDecodeError, KeyError, TypeError):
            report.errors.append("catalog.json is not valid")
    else:
        report.warnings.append("catalog.json not found")

    for leftover in output.glob("*/.*.partial"):
        report.warnings.append(f"Interrupted conversion left {leftover.relative_to(output)}")

    for manifest_path in sorted(output.glob("*/*/manifest.json")):
        report.collections += 1
        folder = manifest_path.parent
        rel = folder.relative_to(output).as_posix()
        raw = manifest_path.read_text(encoding="utf-8")
        if _USER_PATH.search(raw):
            report.errors.append(f"{rel}: manifest contains a user profile path")
        try:
            manifest = json.loads(raw)
        except json.JSONDecodeError:
            report.errors.append(f"{rel}: manifest.json is not valid JSON")
            continue
        missing = [k for k in REQUIRED_MANIFEST_KEYS if k not in manifest]
        if missing:
            report.errors.append(f"{rel}: manifest missing {', '.join(missing)}")
            continue
        if catalog_paths and rel not in catalog_paths:
            report.warnings.append(f"{rel}: not listed in catalog.json (run convert again to refresh it)")
        if manifest["version_status"] in ("conflicting", "unknown"):
            report.warnings.append(f"{rel}: installed version is {manifest['version_status']}")

        topics = sorted((folder / "topics").rglob("*.md")) if (folder / "topics").is_dir() else []
        report.topics += len(topics)
        expected = (manifest.get("content") or {}).get("topics", 0)
        if len(topics) != expected:
            report.errors.append(f"{rel}: {len(topics)} topic files, manifest says {expected}")
        for topic in topics:
            text = topic.read_text(encoding="utf-8")
            fields = _front_matter(text)
            if fields is None:
                report.errors.append(f"{rel}: {topic.relative_to(folder).as_posix()} has no front matter")
                continue
            absent = [k for k in REQUIRED_FRONT_MATTER if k not in fields]
            if absent:
                report.errors.append(f"{rel}: {topic.relative_to(folder).as_posix()} missing {', '.join(absent)}")
            elif json.loads(fields["collection_id"]) != manifest["collection_id"]:
                report.errors.append(f"{rel}: {topic.relative_to(folder).as_posix()} belongs to another collection")

        for required in ("toc.md", "README.md", "indexes/topics.json"):
            if not (folder / required).is_file():
                report.errors.append(f"{rel}: {required} missing")

        diagnostics = manifest.get("diagnostics") or {}
        broken = sum(diagnostics.get(k, 0) for k in ("broken-link", "missing-asset", "unresolved-topic-id",
                                                        "ambiguous-link"))
        if broken:
            report.warnings.append(f"{rel}: {broken} unresolved links/assets (see diagnostics/links.json)")
        if (manifest.get("content") or {}).get("failed_topics"):
            report.errors.append(f"{rel}: {manifest['content']['failed_topics']} topics failed to convert")

    for missing in sorted(catalog_paths - {p.parent.relative_to(output).as_posix()
                                           for p in output.glob('*/*/manifest.json')}):
        report.errors.append(f"catalog.json references missing collection {missing}")
    if report.collections == 0:
        report.errors.append("No collections found")
    return report
