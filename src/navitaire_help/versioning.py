"""Resolve the installed product version of a CHM and, separately, its documented version.

Order of trust for the *installed* version:

1. Windows "Uninstall" registry entry whose ``InstallLocation`` contains the CHM (read-only).
2. Version resource of a known product executable near the CHM (read-only).
3. Version-looking folder names in the installation path (``R9.3``, ``9.1.0.100``) -> *inferred* only.

The *document* version (text inside the help) is reported separately and never
used as the installed version, because help content is often older or newer.
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .families import Family
from .models import ChmFile, ChmMetadata, Evidence, VersionResult

_VERSION = re.compile(r"(?<![\d.])(\d+\.\d+(?:\.\d+){0,2})(?![\d.])")
_PATH_SEGMENT = re.compile(r"^[Rr]?(\d+(?:\.\d+)+)$")
_DOC_PATTERNS = (
    re.compile(r"\b(?:version|release|v\.)\s*(\d+\.\d+(?:\.\d+){0,2})\b", re.IGNORECASE),
    re.compile(r"\b(\d+\.\d+(?:\.\d+){0,2})\s+build\b", re.IGNORECASE),
)
_TRUSTED_PUBLISHERS = re.compile(r"navitaire|amadeus", re.IGNORECASE)


# --------------------------------------------------------------------------- helpers
def normalize_version(value: str | None) -> str | None:
    """Strip build metadata (``+commit``), prefixes and spaces; keep dotted numbers."""
    if not value:
        return None
    value = value.split("+", 1)[0].strip().lstrip("vVrR").replace(",", ".").replace(" ", "")
    match = re.match(r"\d+(?:\.\d+)*", value)
    return match.group(0) if match else None


def version_key(value: str) -> tuple[int, ...]:
    return tuple(int(p) for p in value.split(".") if p.isdigit())


def sort_versions(values) -> list[str]:
    return sorted({v for v in values if v}, key=version_key)


def compatible(a: str, b: str) -> bool:
    """True when one version is a prefix of the other (``9.3`` vs ``9.3.0.200``)."""
    ka, kb = version_key(a), version_key(b)
    n = min(len(ka), len(kb))
    return ka[:n] == kb[:n]


def _norm_path(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(path))).rstrip("\\/")


# --------------------------------------------------------------------------- registry
@dataclass(frozen=True)
class UninstallEntry:
    display_name: str
    display_version: str
    publisher: str
    install_location: str


@lru_cache(maxsize=1)
def uninstall_entries() -> tuple[UninstallEntry, ...]:
    """Read Navitaire/Amadeus entries from the Windows Uninstall keys. Empty elsewhere."""
    if sys.platform != "win32":
        return ()
    import winreg

    hives = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    found: list[UninstallEntry] = []
    for hive, key_path in hives:
        try:
            key = winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ)
        except OSError:
            continue
        with key:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(key, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(key, name) as sub:
                        values = {}
                        for field in ("DisplayName", "DisplayVersion", "Publisher", "InstallLocation"):
                            try:
                                values[field] = str(winreg.QueryValueEx(sub, field)[0] or "")
                            except OSError:
                                values[field] = ""
                except OSError:
                    continue
                if values["InstallLocation"] and _TRUSTED_PUBLISHERS.search(values["Publisher"]):
                    found.append(UninstallEntry(values["DisplayName"], values["DisplayVersion"],
                                                values["Publisher"], values["InstallLocation"]))
    return tuple(found)


def match_registry(chm_path: Path, entries: tuple[UninstallEntry, ...]) -> UninstallEntry | None:
    """Return the entry with the longest ``InstallLocation`` that contains *chm_path*."""
    target = _norm_path(chm_path)
    best: UninstallEntry | None = None
    for entry in entries:
        location = _norm_path(entry.install_location)
        if target.startswith(location + os.sep) and (
            best is None or len(location) > len(_norm_path(best.install_location))
        ):
            best = entry
    return best


def registry_version(entry: UninstallEntry) -> str | None:
    version = normalize_version(entry.display_version)
    if version:
        return version
    matches = _VERSION.findall(entry.display_name) + re.findall(r"\d+\.\d+\.\d+\.\d+", entry.display_name)
    return normalize_version(matches[-1]) if matches else None


# --------------------------------------------------------------------------- executables
def file_version_info(path: Path) -> dict[str, str]:
    """Return ProductVersion/FileVersion/ProductName/CompanyName from a PE version resource."""
    if sys.platform != "win32":
        return {}
    import ctypes
    from ctypes import wintypes

    ver = ctypes.WinDLL("version")
    ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    ver.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    ver.GetFileVersionInfoW.restype = wintypes.BOOL
    ver.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
                                   ctypes.POINTER(wintypes.UINT)]
    ver.VerQueryValueW.restype = wintypes.BOOL

    size = ver.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        return {}
    buffer = ctypes.create_string_buffer(size)
    if not ver.GetFileVersionInfoW(str(path), 0, size, buffer):
        return {}

    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    codes: list[tuple[int, int]] = []
    if ver.VerQueryValueW(buffer, "\\VarFileInfo\\Translation", ctypes.byref(pointer), ctypes.byref(length)) \
            and length.value >= 4:
        pair = ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ushort * 2)).contents
        codes.append((pair[0], pair[1]))
    codes += [(0x0409, 0x04B0), (0x0409, 0x04E4), (0x0000, 0x04B0)]

    info: dict[str, str] = {}
    for lang, codepage in codes:
        for field in ("ProductVersion", "FileVersion", "ProductName", "CompanyName"):
            if field in info:
                continue
            query = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\{field}"
            if ver.VerQueryValueW(buffer, query, ctypes.byref(pointer), ctypes.byref(length)) and length.value:
                info[field] = ctypes.wstring_at(pointer.value, length.value).rstrip("\0").strip()
    return info


def _search_dirs(start: Path, boundary: Path) -> list[Path]:
    dirs, current = [], start
    boundary_norm = _norm_path(boundary)
    while True:
        dirs.append(current)
        if _norm_path(current) == boundary_norm or current.parent == current:
            break
        if not _norm_path(current).startswith(boundary_norm):
            break
        current = current.parent
    return dirs


def executable_evidence(chm: ChmFile, family: Family, boundary: Path) -> list[Evidence]:
    if not family.executables:
        return []
    for folder in _search_dirs(chm.path.parent, boundary):
        found: list[Evidence] = []
        for exe in family.executables:
            candidate = folder / exe
            if not candidate.is_file():
                continue
            info = file_version_info(candidate)
            version = normalize_version(info.get("ProductVersion") or info.get("FileVersion"))
            if version and _TRUSTED_PUBLISHERS.search(info.get("CompanyName", "")):
                found.append(Evidence("executable", version, detail=f"{candidate.name} ({info.get('ProductName', '')})",
                                      weight=3))
        if found:
            return found
    return []


# --------------------------------------------------------------------------- path
def path_versions(chm: ChmFile) -> list[str]:
    parts = Path(chm.relative_path).parts[:-1]
    out = []
    for part in parts:
        match = _PATH_SEGMENT.match(part)
        if match:
            out.append(match.group(1))
    return out


# --------------------------------------------------------------------------- resolution
def resolve_installed_version(chm: ChmFile, family: Family,
                              entries: tuple[UninstallEntry, ...] | None = None) -> VersionResult:
    entries = uninstall_entries() if entries is None else entries
    evidence: list[Evidence] = []
    authoritative: list[str] = []

    entry = match_registry(chm.path, entries)
    if entry:
        version = registry_version(entry)
        if version:
            authoritative.append(version)
            evidence.append(Evidence("registry", version, detail=entry.display_name, weight=3))

    boundary = Path(entry.install_location) if entry else chm.root
    for item in executable_evidence(chm, family, boundary):
        authoritative.append(item.value)
        evidence.append(item)

    from_path = path_versions(chm)
    for value in from_path:
        evidence.append(Evidence("install-path", value, detail="version-like folder name", weight=1))

    candidates = sort_versions(authoritative + from_path)
    if authoritative:
        if all(compatible(a, b) for a in authoritative for b in authoritative):
            best = max(authoritative, key=lambda v: len(version_key(v)))
            for value in from_path:
                if not compatible(value, best):
                    evidence.append(Evidence("install-path", value, detail=f"disagrees with {best}", weight=0))
            return VersionResult(best, "confirmed", candidates, evidence)
        return VersionResult(None, "conflicting", candidates, evidence)
    if from_path:
        return VersionResult(from_path[-1], "inferred", candidates, evidence)
    return VersionResult(None, "unknown", candidates, evidence)


def document_version(metadata: ChmMetadata) -> tuple[str | None, list[Evidence]]:
    """Version text found inside the help itself (contents file name, title, welcome page)."""
    evidence: list[Evidence] = []
    sources = (
        ("contents-file", Path(metadata.contents_file).stem if metadata.contents_file else None),
        ("chm-title", metadata.title),
        ("welcome-title", metadata.welcome_title),
        ("welcome-text", metadata.welcome_text[:4000] if metadata.welcome_text else None),
    )
    for source, text in sources:
        if not text:
            continue
        for pattern in _DOC_PATTERNS:
            match = pattern.search(text)
            if match:
                evidence.append(Evidence(source, match.group(1), detail=match.group(0).strip(), weight=1))
                break
    return (evidence[0].value if evidence else None), evidence
