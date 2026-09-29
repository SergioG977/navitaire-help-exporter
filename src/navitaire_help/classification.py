"""Evidence-weighted classification of a CHM into a Navitaire help family."""

from __future__ import annotations

import re
from pathlib import PureWindowsPath

from .families import FAMILIES, UNKNOWN, Family
from .models import ChmMetadata, Classification, Evidence

# Relative weight of each signal. Compiled metadata beats file names; paths are weak.
WEIGHTS = {"chm-title": 4, "filename": 3, "welcome-title": 2, "contents-file": 2, "install-path": 1}
MIN_SCORE = 3
MIN_MARGIN = 2


def _matches(patterns: tuple[str, ...], text: str | None) -> str | None:
    if not text:
        return None
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return pattern
    return None


def _signals(file_name: str, metadata: ChmMetadata, relative_dirs: list[str]) -> list[tuple[str, str]]:
    signals = [("filename", file_name)]
    if metadata.title:
        signals.append(("chm-title", metadata.title))
    if metadata.welcome_title:
        signals.append(("welcome-title", metadata.welcome_title))
    if metadata.contents_file:
        signals.append(("contents-file", PureWindowsPath(metadata.contents_file).stem))
    for rel in relative_dirs:
        signals.append(("install-path", rel))
    return signals


def _score(family: Family, signals: list[tuple[str, str]]) -> tuple[int, list[Evidence]]:
    score = 0
    evidence: list[Evidence] = []
    seen: set[str] = set()
    for source, value in signals:
        if source == "filename":
            patterns = family.filename
        elif source == "install-path":
            patterns = family.path
        else:
            patterns = family.title
        hit = _matches(patterns, value)
        # Count each signal type once per family so repeated paths cannot dominate.
        if hit and source not in seen:
            seen.add(source)
            weight = WEIGHTS[source]
            score += weight
            evidence.append(Evidence(source=source, value=value, detail=f"matches /{hit}/", weight=weight))
    return score, evidence


def classify(file_name: str, metadata: ChmMetadata, relative_dirs: list[str] | None = None) -> Classification:
    """Classify a CHM from its name, compiled metadata and installation folders."""
    signals = _signals(file_name, metadata, relative_dirs or [])
    ranked = sorted(
        ((family, *_score(family, signals)) for family in FAMILIES),
        key=lambda item: item[1],
        reverse=True,
    )
    best, best_score, best_evidence = ranked[0]
    runner, runner_score, _ = ranked[1]

    if best_score < MIN_SCORE:
        return Classification(UNKNOWN.family_id, UNKNOWN.product, "unknown", best_score,
                              runner_up=best.family_id if best_score else None, evidence=best_evidence)
    status = "classified" if best_score - runner_score >= MIN_MARGIN else "ambiguous"
    return Classification(best.family_id, best.product, status, best_score,
                          runner_up=runner.family_id if runner_score else None, evidence=best_evidence)
