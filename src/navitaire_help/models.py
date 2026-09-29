"""Plain data structures shared by every stage of the pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Evidence:
    """A single observation used to classify a CHM or resolve a version."""

    source: str  # filename | chm-title | contents-file | default-topic | install-path | registry | executable
    value: str
    detail: str = ""
    weight: int = 0


@dataclass
class ChmFile:
    """A CHM file found on disk."""

    path: Path
    root: Path
    size: int
    sha256: str

    @property
    def relative_path(self) -> str:
        try:
            return str(self.path.relative_to(self.root))
        except ValueError:
            return self.path.name


@dataclass
class ChmMetadata:
    """Metadata read from inside a CHM (#SYSTEM file and table-of-contents files)."""

    title: str | None = None
    default_topic: str | None = None
    contents_file: str | None = None
    index_file: str | None = None
    compiled_file: str | None = None
    lcid: int | None = None
    welcome_title: str | None = None
    welcome_text: str = ""


@dataclass
class Classification:
    family_id: str
    product: str
    status: str  # classified | ambiguous | unknown
    score: int
    runner_up: str | None = None
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class VersionResult:
    installed_version: str | None
    status: str  # confirmed | inferred | conflicting | unknown
    candidates: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


@dataclass
class Installation:
    """One place where a given CHM (identified by hash) is installed."""

    chm: ChmFile
    version: VersionResult


@dataclass
class Collection:
    """All installations that share identical CHM content (same SHA-256)."""

    sha256: str
    file_name: str
    size: int
    installations: list[Installation]
    classification: Classification
    metadata: ChmMetadata
    document_version: str | None = None
    document_version_evidence: list[Evidence] = field(default_factory=list)

    @property
    def collection_id(self) -> str:
        return f"{self.classification.family_id}-{self.sha256[:12]}"

    @property
    def installed_versions(self) -> list[str]:
        from .versioning import sort_versions

        found = {i.version.installed_version for i in self.installations if i.version.installed_version}
        return sort_versions(found)


def to_jsonable(obj: Any) -> Any:
    """Convert dataclasses/paths recursively into JSON-serialisable values."""
    if hasattr(obj, "__dataclass_fields__"):
        return to_jsonable(asdict(obj))
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list | tuple | set):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj
