"""CHM extraction through 7-Zip.

7-Zip discovery is adapted from DTDucas/chm-converter (MIT). Invocation is
synchronous, uses an argument list (no shell) and verifies that nothing was
written outside the destination folder.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from pathlib import Path


class ExtractionError(RuntimeError):
    pass


def find_7zip(explicit: str | None = None) -> str:
    """Return a usable 7-Zip executable or raise :class:`ExtractionError`."""
    if explicit:
        if Path(explicit).is_file():
            return explicit
        raise ExtractionError(f"Configured 7-Zip executable not found: {explicit}")

    if platform.system() == "Windows":
        for default in (r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"):
            if os.path.exists(default):
                return default
        names = ("7z", "7za", "7zz")
    else:
        names = ("7z", "7zz", "7za")
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    raise ExtractionError("7-Zip not found. Install it from https://www.7-zip.org/ or set conversion.seven_zip.")


def extract(chm: Path, destination: Path, seven_zip: str, patterns: list[str] | None = None,
            timeout: int = 600) -> None:
    """Extract *chm* (optionally only *patterns*) into *destination*."""
    destination.mkdir(parents=True, exist_ok=True)
    args = [seven_zip, "x", "-y", "-bd", "-bso0", "-bsp0", str(chm), f"-o{destination}"]
    if patterns:
        args += ["-r", "--", *patterns]
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ExtractionError(f"7-Zip timed out extracting {chm.name}") from exc
    except OSError as exc:
        raise ExtractionError(f"Cannot run 7-Zip: {exc}") from exc
    # Exit code 1 means "warning" (for instance, a pattern matched nothing).
    if proc.returncode not in (0, 1):
        message = proc.stderr.decode(errors="replace").strip().splitlines()
        raise ExtractionError(f"7-Zip failed on {chm.name}: {message[-1] if message else proc.returncode}")

    base = destination.resolve()
    for dirpath, _dirs, files in os.walk(destination):
        for name in files:
            target = (Path(dirpath) / name).resolve()
            if base != target and base not in target.parents:
                raise ExtractionError(f"Unsafe path extracted from {chm.name}; aborting")
