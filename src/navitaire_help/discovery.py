"""Find CHM files under configured roots, honouring exclusions, without following links."""

from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass, field
from pathlib import Path

from .models import ChmFile

_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


@dataclass
class ScanResult:
    files: list[ChmFile] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    skipped_links: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _norm(rel: str) -> str:
    return rel.replace("/", "\\").strip("\\").casefold()


def _is_link(entry: os.DirEntry) -> bool:
    """True for symbolic links and NTFS junctions/reparse points."""
    try:
        if entry.is_symlink():
            return True
        st = entry.stat(follow_symlinks=False)
        return bool(getattr(st, "st_file_attributes", 0) & _REPARSE_POINT)
    except OSError:
        return True


def sha256_of(path: Path, chunk: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while block := fh.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def scan(roots: list[Path], exclude: list[str], follow_links: bool = False) -> ScanResult:
    """Recursively search *roots* for ``*.chm`` files.

    *exclude* entries are folder paths relative to a root (``ConfigCaptain`` or
    ``NewSkies\\R9.1``), compared case-insensitively. Excluded folders are not
    entered at all.
    """
    result = ScanResult()
    excluded = {_norm(e) for e in exclude if e.strip()}

    for root in roots:
        root = Path(root)
        if not root.is_dir():
            result.warnings.append(f"Root not found or not a folder: {root}")
            continue

        stack: list[tuple[Path, str]] = [(root, "")]
        while stack:
            folder, rel = stack.pop()
            try:
                with os.scandir(folder) as it:
                    entries = sorted(it, key=lambda e: e.name.casefold())
            except PermissionError:
                result.warnings.append(f"Access denied: {rel or '.'}")
                continue
            except OSError as exc:
                result.warnings.append(f"Cannot read {rel or '.'}: {exc.strerror}")
                continue

            for entry in entries:
                child_rel = f"{rel}\\{entry.name}" if rel else entry.name
                if not follow_links and _is_link(entry):
                    result.skipped_links.append(child_rel)
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=follow_links)
                except OSError:
                    continue
                if is_dir:
                    if _norm(child_rel) in excluded:
                        result.excluded.append(child_rel)
                        continue
                    stack.append((Path(entry.path), child_rel))
                elif entry.name.casefold().endswith(".chm"):
                    path = Path(entry.path)
                    try:
                        result.files.append(
                            ChmFile(path=path, root=root, size=entry.stat().st_size, sha256=sha256_of(path))
                        )
                    except OSError as exc:
                        result.warnings.append(f"Cannot read {child_rel}: {exc.strerror}")

    result.files.sort(key=lambda f: (str(f.root).casefold(), f.relative_path.casefold()))
    return result


def single_file(path: Path, root: Path | None = None) -> ChmFile:
    """Describe one explicitly provided CHM file."""
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"CHM file not found: {path}")
    base = Path(root).resolve() if root else path.parent
    return ChmFile(path=path, root=base, size=path.stat().st_size, sha256=sha256_of(path))
