from pathlib import Path

from navitaire_help.discovery import scan
from navitaire_help.pipeline import group_by_content


def test_scan_excludes_default_folders_case_insensitively(install_tree: Path):
    result = scan([install_tree], ["ConfigCaptain", "NavitaireTE"])
    names = sorted(f.relative_path.replace("\\", "/") for f in result.files)
    assert all("ConfigCaptain" not in n and "navitairete" not in n.lower() for n in names)
    assert len(names) == 4
    assert sorted(e.casefold() for e in result.excluded) == ["configcaptain", "navitairete"]


def test_scan_without_excludes_finds_everything(install_tree: Path):
    assert len(scan([install_tree], []).files) == 6


def test_nested_exclude_path(install_tree: Path):
    result = scan([install_tree], ["NewSkies\\R9.3"])
    assert all(not f.relative_path.startswith("NewSkies") for f in result.files)


def test_duplicates_are_grouped_by_hash(install_tree: Path):
    groups = group_by_content(scan([install_tree], ["ConfigCaptain", "NavitaireTE"]).files)
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 1, 2]


def test_missing_root_is_a_warning(tmp_path: Path):
    result = scan([tmp_path / "nope"], [])
    assert result.files == [] and result.warnings
