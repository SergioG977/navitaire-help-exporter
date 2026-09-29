import json
from pathlib import Path

import pytest

from navitaire_help.chm_metadata import normalize_local, parse_sitemap, read_system
from navitaire_help.converter import CollectionConverter
from navitaire_help.markdown import html_to_markdown
from navitaire_help.models import ChmFile, Classification, Collection, Installation, VersionResult
from navitaire_help.pipeline import _collection_readme, _fill_from_extraction, build_manifest, write_catalog
from navitaire_help.safety import UnsafeOutputError, ensure_safe_output
from navitaire_help.validate import validate_output


def test_system_file(extracted: Path):
    meta = read_system(extracted)
    assert meta.title == "Sample Help"
    assert meta.contents_file == "Sample.hhc"
    assert meta.default_topic == "Welcome.html"
    assert meta.lcid == 1033


def test_sitemap_tree(extracted: Path):
    tree = parse_sitemap(extracted / "Sample.hhc")
    assert [n["title"] for n in tree] == ["Welcome", "Tasks"]
    assert tree[1]["children"][0]["locals"] == ["sub/Doing_A_Thing.html#Step"]


@pytest.mark.parametrize(("value", "expected"), [
    ("sub\\A%20B.html#x", "sub/A B.html"),
    ("ms-its:Other.chm::/Topic.htm", "Topic.htm"),
    ("https://example.invalid/", None),
])
def test_normalize_local(value, expected):
    assert normalize_local(value) == expected


def test_chrome_removed_and_links_kept():
    html = ("<div id='pagetop'>Banner</div><div id='i-header-content'>New banner</div>"
            "<div id='mainbody'><p>Body <a href='x.html'>x</a></p></div>"
            "<div id='i-footer-content'><a href='mailto:a@example.invalid'>Send Feedback</a></div>")
    result = html_to_markdown(html, lambda h: "x.md", lambda s: None)
    assert "Banner" not in result.markdown and "New banner" not in result.markdown
    assert "Send Feedback" not in result.markdown
    assert "[x](x.md)" in result.markdown


def _collection(extracted: Path) -> Collection:
    meta = _fill_from_extraction(read_system(extracted), extracted)
    chm = ChmFile(path=Path("C:/fake/Sample.chm"), root=Path("C:/fake"), size=1, sha256="ab" * 32)
    return Collection(
        sha256=chm.sha256, file_name="Sample.chm", size=1,
        installations=[Installation(chm, VersionResult("9.8.7", "confirmed", ["9.8.7"]))],
        classification=Classification("gonow", "GoNow", "classified", 5),
        metadata=meta,
    )


def test_full_collection(extracted: Path, tmp_path: Path):
    output = tmp_path / "out"
    collection = _collection(extracted)
    dest = output / "gonow" / collection.sha256[:12]
    stats, topics = CollectionConverter(extracted, dest, collection).run()
    manifest = build_manifest(collection, stats, hide_roots=True)
    (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (dest / "README.md").write_text(_collection_readme(manifest), encoding="utf-8")
    write_catalog(output)

    assert stats.topics == 2 and stats.failed_topics == 0
    assert stats.toc_entries == 3 and stats.keywords == 2
    welcome = (dest / "topics" / "Welcome.md").read_text(encoding="utf-8")
    assert welcome.startswith("---\ntitle: \"Welcome\"")
    assert "Send Feedback" not in welcome and "Copyright notice" not in welcome
    assert "(sub/Doing_A_Thing.md#Step)" in welcome
    assert "(sub/Doing_A_Thing.md)" in welcome  # loose name resolution
    assert "![A picture](../assets/images/pic.png)" in welcome
    topic = (dest / "topics" / "sub" / "Doing_A_Thing.md").read_text(encoding="utf-8")
    assert '<a id="Step"></a>' in topic
    assert "(../Welcome.md)" in topic and "```xml" in topic
    assert "toc_path: [\"Tasks\", \"Doing A Thing\"]" in topic
    assert (dest / "assets" / "images" / "pic.png").is_file()

    diagnostics = manifest["diagnostics"]
    assert diagnostics["broken-link"] == 1 and diagnostics["unresolved-topic-id"] == 1
    assert manifest["installations"][0]["root"] == "<root>"

    report = validate_output(output)
    assert report.ok, report.errors
    assert report.topics == 2


def test_validate_detects_missing_topic(extracted: Path, tmp_path: Path):
    test_full_collection(extracted, tmp_path)
    next((tmp_path / "out").rglob("Welcome.md")).unlink()
    assert not validate_output(tmp_path / "out").ok


def test_output_inside_root_is_rejected(tmp_path: Path):
    with pytest.raises(UnsafeOutputError):
        ensure_safe_output(tmp_path / "root" / "out", [tmp_path / "root"])


def test_output_inside_unignored_repo_is_rejected(tmp_path: Path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(UnsafeOutputError):
        ensure_safe_output(tmp_path / "repo" / "out", [])
