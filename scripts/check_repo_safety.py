"""Fail if files that could contain proprietary help content or secrets are tracked or staged.

Usage:
    python scripts/check_repo_safety.py            # check files tracked + staged by Git
    python scripts/check_repo_safety.py --staged   # check only staged files (pre-commit hook)

Exit code 0 = safe, 1 = problems found. Runs locally and in CI; it never sends data anywhere.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

FORBIDDEN_SUFFIXES = {
    ".chm", ".chw", ".chi", ".chq", ".hhc", ".hhk", ".hhp", ".saz",
    ".pfx", ".p12", ".pem", ".key", ".exe", ".dll", ".msi", ".zip", ".7z",
}
FORBIDDEN_PARTS = {"knowledge", "output", "extracted", "resources", "navitaire-help-output", "navitairehelp"}
ALLOWED_PREFIXES = ("tests/", "docs/", "src/", "scripts/", "config/", ".github/", ".kiro/")
MAX_BYTES = 512 * 1024

# Markers typical of converted/extracted Navitaire help or of machine-specific data.
CONTENT_PATTERNS = [
    (re.compile(r"Innovasys HelpStudio", re.IGNORECASE), "HelpStudio-generated HTML"),
    (re.compile(r"Navitaire\.Documentation@", re.IGNORECASE), "Navitaire documentation mailbox from help pages"),
    (re.compile(r"^collection_id: \"[a-z-]+-[0-9a-f]{12}\"", re.MULTILINE), "converted topic front matter"),
    (re.compile(r"[A-Za-z]:\\\\?Users\\\\?(?!<|\{|USERNAME|you|example)[A-Za-z0-9._-]{2,}", re.IGNORECASE),
     "personal Windows profile path"),
    (re.compile(r"(?i)(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"), "GitHub token"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
]
# Files that legitimately mention the markers above (they define or document them).
CONTENT_ALLOWLIST = {"scripts/check_repo_safety.py", "src/navitaire_help/validate.py", "src/navitaire_help/markdown.py"}


def git_files(staged_only: bool) -> list[str]:
    if staged_only:
        args = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"]
    else:
        args = ["git", "ls-files", "--cached", "--others", "--exclude-standard"]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout
    return [line.strip().replace("\\", "/") for line in out.splitlines() if line.strip()]


def check(files: list[str]) -> list[str]:
    problems = []
    for rel in files:
        path = Path(rel)
        if not path.is_file():
            continue
        lower = rel.lower()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            problems.append(f"{rel}: forbidden file type {path.suffix}")
            continue
        if any(part.lower() in FORBIDDEN_PARTS for part in path.parts[:-1]):
            problems.append(f"{rel}: inside a folder reserved for generated/proprietary content")
            continue
        if "/" in rel and not lower.startswith(ALLOWED_PREFIXES):
            problems.append(f"{rel}: unexpected folder (allowed: {', '.join(ALLOWED_PREFIXES)})")
        size = path.stat().st_size
        if size > MAX_BYTES:
            problems.append(f"{rel}: {size} bytes exceeds {MAX_BYTES} (generated content?)")
            continue
        if rel in CONTENT_ALLOWLIST:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            if not lower.endswith((".png", ".gif", ".ico")):
                problems.append(f"{rel}: binary file")
            continue
        for pattern, label in CONTENT_PATTERNS:
            if pattern.search(text):
                problems.append(f"{rel}: contains {label}")
    return problems


def main() -> int:
    staged = "--staged" in sys.argv
    problems = check(git_files(staged))
    for problem in problems:
        print(f"BLOCKED  {problem}", file=sys.stderr)
    if problems:
        print(f"\n{len(problems)} problem(s). Proprietary Navitaire content and secrets must never be committed.",
              file=sys.stderr)
        return 1
    print("Repository safety check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
