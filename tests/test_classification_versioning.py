from pathlib import Path

import pytest

from navitaire_help import families
from navitaire_help.classification import classify
from navitaire_help.models import ChmFile, ChmMetadata
from navitaire_help.versioning import (
    UninstallEntry,
    document_version,
    normalize_version,
    registry_version,
    resolve_installed_version,
)


@pytest.mark.parametrize(("name", "rel", "expected"), [
    ("GoNow.chm", r"NAV1\GoNow\9.1.0.100\GoNow Native1WayCommunication", "gonow"),
    ("SkySpeedHelp.chm", r"NewSkies\R9.3\Navitaire NAV1\Client Suite\SkySpeed Reservation Manager", "skyspeed"),
    ("SkyFareHelp.chm", r"NewSkies\R9.3\Navitaire NAV1\Client Suite\Fare Manager", "skyfare"),
    ("SkyScheduleHelp.chm", r"NewSkies\R9.3\Navitaire NAV1\Client Suite\Schedule Manager", "skyschedule"),
    ("Navitaire.NewSkies.UI.Win.SkyManagerHelp.chm", r"NewSkies\R9.1\Navitaire NAV1\Client Suite\Management Console",
     "newskies-management-console"),
    ("Navitaire.GovernmentSecurity.GSSManagementConsole.Help.chm",
     r"GovernmentSecurity\R9.4\Navitaire NAV1\Management Console", "gss-management-console"),
    ("DeviceManager.chm", r"NAV1\DeviceManager\9.2.0.10\DeviceManager Simulators", "device-manager"),
    ("Rules.chm", r"x\SkyManagerPlugins\Navitaire.Ncs.Rules.Management", "ncs-rules"),
])
def test_known_families(name, rel, expected):
    result = classify(name, ChmMetadata(), [rel])
    assert result.family_id == expected
    assert result.status == "classified"


def test_unknown_file():
    assert classify("Something.chm", ChmMetadata(), ["Other"]).family_id == "unknown"


def test_title_evidence_beats_generic_name():
    result = classify("help.chm", ChmMetadata(title="GoNow Agent Help"), [])
    assert result.family_id == "gonow"


def test_normalize_version():
    assert normalize_version("9.3.0.200+0123abcdef") == "9.3.0.200"
    assert normalize_version("R9.3") == "9.3"
    assert normalize_version("") is None


def test_registry_version_from_display_name_when_display_version_empty():
    entry = UninstallEntry("NewSkies Client Suite Navitaire NAV1 9.3.0.200", "", "Navitaire", r"C:\x")
    assert registry_version(entry) == "9.3.0.200"


def _chm(tmp_path: Path, rel: str) -> ChmFile:
    path = tmp_path / "root" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return ChmFile(path=path, root=tmp_path / "root", size=1, sha256="0" * 64)


def test_registry_confirms_version(tmp_path: Path):
    chm = _chm(tmp_path, "NewSkies/R9.3/Suite/Fare Manager/SkyFareHelp.chm")
    entries = (UninstallEntry("Suite 9.3.0.200", "", "Navitaire", str(tmp_path / "root" / "NewSkies" / "R9.3" / "Suite")),)
    result = resolve_installed_version(chm, families.get("skyfare"), entries)
    assert result.status == "confirmed" and result.installed_version == "9.3.0.200"


def test_path_only_is_inferred(tmp_path: Path):
    chm = _chm(tmp_path, "NAV1/GoNow/9.0.0.50/app/GoNow.chm")
    result = resolve_installed_version(chm, families.get("gonow"), ())
    assert result.status == "inferred" and result.installed_version == "9.0.0.50"


def test_conflicting_authoritative_sources(tmp_path: Path):
    chm = _chm(tmp_path, "a/b/GoNow.chm")
    base = str(tmp_path / "root" / "a")
    entries = (UninstallEntry("GoNow 9.1.0.100", "9.1.0.100", "Navitaire", base),
               UninstallEntry("GoNow 9.0", "9.0.0.50", "Navitaire", base + "\\b"))
    # Longest matching location wins, so the result is the nested entry rather than a conflict.
    assert resolve_installed_version(chm, families.get("gonow"), entries).installed_version == "9.0.0.50"


def test_no_evidence_is_unknown(tmp_path: Path):
    chm = _chm(tmp_path, "a/GoNow.chm")
    assert resolve_installed_version(chm, families.get("gonow"), ()).status == "unknown"


def test_document_version_is_separate():
    version, evidence = document_version(ChmMetadata(contents_file="9.1.0 build.hhc"))
    assert version == "9.1.0" and evidence[0].source == "contents-file"
