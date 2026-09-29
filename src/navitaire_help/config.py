"""Settings: built-in defaults, optional TOML file, command-line overrides."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_ROOT = r"C:\Program Files (x86)\Navitaire"
# Installation folders under the Navitaire root that must not be searched.
DEFAULT_EXCLUDES = ["ConfigCaptain", "NavitaireTE"]
DEFAULT_OUTPUT = str(Path.home() / "NavitaireHelp")


class ConfigError(ValueError):
    """Raised for invalid configuration files or values."""


@dataclass
class Settings:
    roots: list[Path] = field(default_factory=lambda: [Path(DEFAULT_ROOT)])
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    follow_links: bool = False
    output: Path = field(default_factory=lambda: Path(DEFAULT_OUTPUT))
    seven_zip: str | None = None
    include_unknown: bool = False


def _expand(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def load_settings(config_path: str | None = None) -> Settings:
    """Return defaults, updated with values from *config_path* when given."""
    settings = Settings()
    if not config_path:
        return settings

    path = _expand(config_path)
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"Configuration file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Invalid TOML in {path}: {exc}") from exc

    discovery = data.get("discovery", {})
    conversion = data.get("conversion", {})
    if not isinstance(discovery, dict) or not isinstance(conversion, dict):
        raise ConfigError("[discovery] and [conversion] must be tables")

    if "roots" in discovery:
        roots = discovery["roots"]
        if not isinstance(roots, list) or not all(isinstance(r, str) for r in roots):
            raise ConfigError("discovery.roots must be a list of strings")
        settings.roots = [_expand(r) for r in roots]
    if "exclude" in discovery:
        exclude = discovery["exclude"]
        if not isinstance(exclude, list) or not all(isinstance(e, str) for e in exclude):
            raise ConfigError("discovery.exclude must be a list of strings")
        settings.exclude = list(exclude)
    if "follow_links" in discovery:
        settings.follow_links = bool(discovery["follow_links"])

    if conversion.get("output"):
        settings.output = _expand(str(conversion["output"]))
    if conversion.get("seven_zip"):
        settings.seven_zip = str(conversion["seven_zip"])
    if "include_unknown" in conversion:
        settings.include_unknown = bool(conversion["include_unknown"])
    return settings
