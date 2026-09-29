"""Guards that keep proprietary help content out of Git and out of installation folders."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


class UnsafeOutputError(RuntimeError):
    pass


def _enclosing_git_repo(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def ensure_safe_output(output: Path, roots: list[Path], allow_unignored: bool = False) -> None:
    """Refuse output locations that could leak or damage content.

    * inside a discovery root (for example ``C:\\Program Files (x86)\\Navitaire``)
    * inside a Git working tree, unless that location is git-ignored
    """
    target = output.resolve()
    for root in roots:
        root = Path(root).resolve()
        if target == root or root in target.parents:
            raise UnsafeOutputError(f"Output must not be inside a discovery root: {root}")

    repo = _enclosing_git_repo(target)
    if repo is None or allow_unignored:
        return
    git = shutil.which("git")
    if git:
        probe = target / "navhelp-probe.md"
        proc = subprocess.run([git, "-C", str(repo), "check-ignore", "-q", "--no-index", str(probe)],
                              capture_output=True, check=False)
        if proc.returncode == 0:
            return
    raise UnsafeOutputError(
        f"Output folder {target} is inside the Git repository {repo} and is not git-ignored. "
        "Choose a folder outside the repository or a git-ignored folder such as .\\knowledge."
    )


_HOME = str(Path.home())


def redact(text: str) -> str:
    """Replace the current user's profile folder with ``~`` (case-insensitive)."""
    if not _HOME or len(_HOME) < 4:
        return text
    return re.sub(re.escape(_HOME), "~", text, flags=re.IGNORECASE)


def display_root(root: Path, hide: bool) -> str:
    return "<root>" if hide else redact(os.path.normpath(str(root)))
