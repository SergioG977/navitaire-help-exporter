"""Command-line interface: ``navhelp scan | inspect | convert | validate | families``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, families
from .config import ConfigError, Settings, load_settings
from .discovery import scan, single_file
from .extraction import ExtractionError, find_7zip
from .models import ChmFile, to_jsonable
from .pipeline import (
    build_manifest,
    collection_version_status,
    convert_group,
    group_by_content,
    inspect_groups,
    write_catalog,
)
from .safety import UnsafeOutputError, display_root, ensure_safe_output, redact
from .validate import validate_output

EXIT_OK, EXIT_ERROR, EXIT_USAGE = 0, 1, 2


def _print(message: str = "", *, err: bool = False) -> None:
    print(redact(message), file=sys.stderr if err else sys.stdout, flush=True)


def _settings(args: argparse.Namespace) -> Settings:
    settings = load_settings(args.config)
    if getattr(args, "root", None):
        settings.roots = [Path(r) for r in args.root]
    if getattr(args, "no_default_excludes", False):
        settings.exclude = []
    if getattr(args, "exclude", None):
        settings.exclude = [*settings.exclude, *args.exclude]
    if getattr(args, "output", None):
        settings.output = Path(args.output)
    if getattr(args, "seven_zip", None):
        settings.seven_zip = args.seven_zip
    if getattr(args, "include_unknown", False):
        settings.include_unknown = True
    return settings


def _collect(args: argparse.Namespace, settings: Settings) -> list[ChmFile]:
    if getattr(args, "chm", None):
        return [single_file(Path(p)) for p in args.chm]
    result = scan(settings.roots, settings.exclude, settings.follow_links)
    for warning in result.warnings:
        _print(f"warning: {warning}", err=True)
    if args.verbose:
        for folder in result.excluded:
            _print(f"excluded: {folder}", err=True)
        for link in result.skipped_links:
            _print(f"skipped link: {link}", err=True)
    return result.files


def _progress(args: argparse.Namespace):
    return (lambda msg: _print(msg, err=True)) if args.verbose else None


# --------------------------------------------------------------------------- commands
def cmd_families(args: argparse.Namespace) -> int:
    for fam in families.FAMILIES:
        _print(f"{fam.family_id:30} {fam.product:32} {fam.domain}")
    return EXIT_OK


def cmd_scan(args: argparse.Namespace) -> int:
    settings = _settings(args)
    files = _collect(args, settings)
    groups = group_by_content(files)
    if args.json:
        data = [{"sha256": g[0].sha256, "file_name": g[0].path.name, "size": g[0].size,
                 "installations": [{"root": display_root(c.root, args.hide_roots),
                                    "relative_path": c.relative_path} for c in g]} for g in groups]
        _print(json.dumps({"files": len(files), "distinct": len(groups), "groups": data}, indent=2))
        return EXIT_OK
    _print(f"Roots: {', '.join(display_root(r, args.hide_roots) for r in settings.roots)}")
    _print(f"Excluded folders: {', '.join(settings.exclude) or '(none)'}")
    _print(f"Found {len(files)} CHM files, {len(groups)} distinct by content.\n")
    for group in groups:
        _print(f"{group[0].path.name}  [{group[0].sha256[:12]}]  {len(group)} location(s)")
        for chm in group:
            _print(f"    {chm.relative_path}")
    return EXIT_OK


def cmd_inspect(args: argparse.Namespace) -> int:
    settings = _settings(args)
    seven_zip = find_7zip(settings.seven_zip)
    groups = group_by_content(_collect(args, settings))
    collections = inspect_groups(groups, seven_zip, _progress(args))
    if args.json:
        _print(json.dumps([build_manifest(c, None, args.hide_roots) for c in collections], indent=2,
                          ensure_ascii=False))
        return EXIT_OK
    header = f"{'FAMILY':30} {'CLASS':10} {'INSTALLED VERSIONS':28} {'VERSION':11} {'HELP STATES':11} FILE"
    _print(header)
    _print("-" * len(header))
    for c in collections:
        versions = ", ".join(c.installed_versions) or "-"
        _print(f"{c.classification.family_id:30} {c.classification.status:10} {versions:28} "
               f"{collection_version_status(c):11} {c.document_version or '-':11} {c.file_name}")
        if args.verbose:
            for ev in c.classification.evidence:
                _print(f"    class  <- {ev.source}: {ev.value} ({ev.detail})")
            for inst in c.installations:
                _print(f"    {inst.version.status:10} {inst.version.installed_version or '-':14} {inst.chm.relative_path}")
                for ev in inst.version.evidence:
                    _print(f"        {ev.source}: {ev.value} {ev.detail}")
    return EXIT_OK


def cmd_convert(args: argparse.Namespace) -> int:
    settings = _settings(args)
    output = settings.output.expanduser()
    ensure_safe_output(output, settings.roots if not args.chm else [], args.allow_unignored_output)
    seven_zip = find_7zip(settings.seven_zip)
    groups = group_by_content(_collect(args, settings))
    if not groups:
        _print("No CHM files found.", err=True)
        return EXIT_ERROR

    selected = set(args.family or [])
    unknown_ids = selected - set(families.BY_ID) - {"unknown"}
    if unknown_ids:
        _print(f"Unknown family id(s): {', '.join(sorted(unknown_ids))}. Run 'navhelp families'.", err=True)
        return EXIT_USAGE

    output.mkdir(parents=True, exist_ok=True)
    failures = 0
    counts: dict[str, int] = {}
    for index, group in enumerate(groups, 1):
        label = f"[{index}/{len(groups)}] {group[0].path.name} ({group[0].sha256[:12]})"
        try:
            outcome = convert_group(group, output, seven_zip, force=args.force, hide_roots=args.hide_roots,
                                    family_filter=selected, include_unknown=settings.include_unknown)
        except (ExtractionError, OSError) as exc:
            failures += 1
            counts["failed"] = counts.get("failed", 0) + 1
            _print(f"{label}: FAILED - {exc}", err=True)
            continue
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
        c = outcome.collection
        versions = ", ".join(c.installed_versions) or "unknown version"
        detail = f" -> {outcome.path.relative_to(output).as_posix()}" if outcome.path else f" ({outcome.message})"
        _print(f"{label}: {outcome.status} {c.classification.family_id} {versions}{detail}")
        if outcome.status == "partial":
            failures += 1

    entries = write_catalog(output)
    summary = ", ".join(f"{k}: {v}" for k, v in sorted(counts.items()))
    _print(f"\n{summary}. Catalog lists {len(entries)} collection(s): {output / 'catalog.md'}")

    if args.validate:
        report = validate_output(output)
        _report(report)
        if not report.ok:
            return EXIT_ERROR
    return EXIT_ERROR if failures else EXIT_OK


def _report(report) -> None:
    for warning in report.warnings:
        _print(f"warning: {warning}")
    for error in report.errors:
        _print(f"error: {error}", err=True)
    _print(f"Validated {report.collections} collection(s), {report.topics} topic(s): "
           f"{'OK' if report.ok else 'FAILED'} ({len(report.errors)} errors, {len(report.warnings)} warnings)")


def cmd_validate(args: argparse.Namespace) -> int:
    settings = _settings(args)
    report = validate_output(Path(args.path) if args.path else settings.output.expanduser())
    if args.json:
        _print(json.dumps(to_jsonable(report.__dict__), indent=2))
    else:
        _report(report)
    return EXIT_OK if report.ok else EXIT_ERROR


def cmd_mcp(args: argparse.Namespace) -> int:
    try:
        from .mcp_server import MCPServer, run
    except ImportError as exc:  # pragma: no cover
        raise ConfigError(f"MCP server unavailable: {exc}") from exc
    if MCPServer is None:
        _print('error: the MCP extra is not installed. Run: python -m pip install ".[mcp]"', err=True)
        return EXIT_USAGE
    settings = _settings(args)
    knowledge = Path(args.knowledge).expanduser() if args.knowledge else settings.output.expanduser()
    return run(knowledge.resolve(), args.config, args.allow_convert)


# --------------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="navhelp",
        description="Discover installed Navitaire CHM help, identify product and version, convert to Markdown.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", help="TOML configuration file (see config/navhelp.example.toml)")
    common.add_argument("-v", "--verbose", action="store_true", help="show evidence and progress details")

    source = argparse.ArgumentParser(add_help=False)
    source.add_argument("--root", action="append", metavar="DIR",
                        help="folder to search recursively (repeatable; default C:\\Program Files (x86)\\Navitaire)")
    source.add_argument("--exclude", action="append", metavar="REL_DIR",
                        help="extra folder to skip, relative to the root (repeatable)")
    source.add_argument("--no-default-excludes", action="store_true",
                        help="do not skip ConfigCaptain and NavitaireTE")
    source.add_argument("--chm", action="append", metavar="FILE", help="process this CHM file instead of scanning")
    source.add_argument("--seven-zip", metavar="EXE", help="path to 7z.exe")
    source.add_argument("--hide-roots", action="store_true", help="replace root folders with <root> in output")

    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("families", parents=[common], help="list recognised help families")
    p.set_defaults(func=cmd_families)

    p = sub.add_parser("scan", parents=[common, source], help="list CHM files found (no extraction)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("inspect", parents=[common, source], help="identify product and version of each CHM")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_inspect)

    p = sub.add_parser("convert", parents=[common, source], help="convert CHM files to Markdown collections")
    p.add_argument("-o", "--output", metavar="DIR", help="output folder (default ~\\NavitaireHelp)")
    p.add_argument("--family", action="append", metavar="ID", help="convert only this family (repeatable)")
    p.add_argument("--include-unknown", action="store_true", help="also convert unrecognised CHM files")
    p.add_argument("--force", action="store_true", help="re-convert collections that are already up to date")
    p.add_argument("--validate", action="store_true", help="run 'validate' after converting")
    p.add_argument("--allow-unignored-output", action="store_true",
                   help="allow writing inside a Git repository folder that is not git-ignored (not recommended)")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("validate", parents=[common], help="check a converted output folder")
    p.add_argument("path", nargs="?", help="output folder (default from configuration)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("mcp", parents=[common], help="run the local MCP server (stdio) over a converted folder")
    p.add_argument("-k", "--knowledge", metavar="DIR",
                   help="converted output folder to serve (default: conversion.output from the configuration)")
    p.add_argument("--allow-convert", action="store_true",
                   help="expose the convert_help tool, which writes into the knowledge folder")
    p.set_defaults(func=cmd_mcp)
    return parser


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ConfigError, UnsafeOutputError, ExtractionError, FileNotFoundError) as exc:
        _print(f"error: {exc}", err=True)
        return EXIT_USAGE
    except KeyboardInterrupt:
        _print("Interrupted.", err=True)
        return 130


if __name__ == "__main__":
    sys.exit(main())
