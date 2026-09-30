"""Knowledge query engine and MCP server, on synthetic collections only."""

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from navitaire_help.chm_metadata import read_system
from navitaire_help.config import Settings
from navitaire_help.converter import CollectionConverter
from navitaire_help.knowledge import KnowledgeBase, KnowledgeError, sections, version_matches
from navitaire_help.mcp_server import NavhelpTools, create_server
from navitaire_help.models import ChmFile, Classification, Collection, Installation, VersionResult
from navitaire_help.pipeline import _collection_readme, _fill_from_extraction, build_manifest, write_catalog


def _convert(extracted: Path, output: Path, sha: str, version: str) -> str:
    meta = _fill_from_extraction(read_system(extracted), extracted)
    chm = ChmFile(path=Path("C:/fake/Sample.chm"), root=Path("C:/fake"), size=1, sha256=sha * 32)
    collection = Collection(
        sha256=chm.sha256, file_name="Sample.chm", size=1,
        installations=[Installation(chm, VersionResult(version, "confirmed", [version]))],
        classification=Classification("gonow", "GoNow", "classified", 5), metadata=meta,
    )
    dest = output / "gonow" / collection.sha256[:12]
    stats, _ = CollectionConverter(extracted, dest, collection).run()
    manifest = build_manifest(collection, stats, hide_roots=True)
    (dest / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (dest / "README.md").write_text(_collection_readme(manifest), encoding="utf-8")
    return collection.collection_id


@pytest.fixture
def knowledge(extracted: Path, tmp_path: Path) -> tuple[Path, str, str]:
    output = tmp_path / "knowledge"
    old = _convert(extracted, output, "ab", "9.1.0.100")
    topic = extracted / "sub" / "Doing_A_Thing.html"
    topic.write_text(topic.read_text(encoding="utf-8").replace("First", "First and improved"), encoding="utf-8")
    new = _convert(extracted, output, "cd", "9.2.0.5")
    write_catalog(output)
    return output, old, new


def test_catalog_and_version_selection(knowledge):
    root, old, new = knowledge
    kb = KnowledgeBase(root)
    assert [c.collection_id for c in kb.collections()] == [old, new]
    assert [c.collection_id for c in kb.select(version="latest")] == [new]
    assert [c.collection_id for c in kb.select(family="gonow", version="9.1")] == [old]
    with pytest.raises(KnowledgeError, match="Available: 9.1.0.100, 9.2.0.5"):
        kb.select(version="8.0")
    with pytest.raises(KnowledgeError):
        kb.select(family="skyfare")


@pytest.mark.parametrize(("requested", "installed", "expected"), [
    ("9.1", ["9.1.0.200"], True), ("9.1.0.200", ["9.1.0.200"], True), ("9.1", ["9.10.0.1"], False),
    ("R9.1", ["9.1.0.1"], True),
])
def test_version_matches(requested, installed, expected):
    assert version_matches(requested, installed) is expected


def test_search_ranks_and_filters(knowledge):
    root, old, new = knowledge
    kb = KnowledgeBase(root)
    result = kb.search("step one", version="latest")
    assert result["matched"] == "all terms"
    assert result["results"][0]["citation"] == f"gonow/{new.split('-')[-1]}/topics/sub/Doing_A_Thing.md"
    assert result["collections_searched"] == [new]
    assert kb.search("improved")["results"][0]["collection_id"] == new
    fallback = kb.search("improved nonexistentword")
    assert fallback["matched"] == "any term" and fallback["results"]
    assert kb.search("nonexistentword")["results"] == []
    assert kb.search("impro*", collection_id=new)["results"]
    # Index is cached on disk and reused by a new instance.
    assert list((root / ".navhelp-index").glob("search-*.sqlite3"))
    assert KnowledgeBase(root).search("welcome")["results"]


def test_search_query_is_not_injectable(knowledge):
    kb = KnowledgeBase(knowledge[0])
    for query in ['title:"x" OR', "NEAR(a b)", "a AND OR NOT", "'; DROP TABLE topics; --", "***"]:
        try:
            kb.search(query)
        except KnowledgeError:
            pass
    assert kb.search("welcome")["results"]


def test_index_refreshes_when_catalog_changes(knowledge, extracted):
    root, old, new = knowledge
    kb = KnowledgeBase(root)
    assert kb.search("welcome")["results"]
    shutil.rmtree(root / "gonow" / old.split("-")[-1])
    write_catalog(root)
    assert {r["collection_id"] for r in kb.search("welcome")["results"]} == {new}


def test_get_topic_paths_sections_and_paging(knowledge):
    root, old, new = knowledge
    kb = KnowledgeBase(root)
    by_citation = kb.get_topic(new, f"gonow/{new.split('-')[-1]}/topics/sub/Doing_A_Thing.md")
    assert by_citation["title"] == "Doing A Thing"
    assert by_citation["toc_path"] == ["Tasks", "Doing A Thing"]
    assert kb.get_topic(new, "sub/doing_a_thing")["path"] == "topics/sub/Doing_A_Thing.md"
    assert kb.get_topic(new, "sub/Doing_A_Thing.html")["path"] == "topics/sub/Doing_A_Thing.md"
    section = kb.get_topic(new, "topics/sub/Doing_A_Thing.md", section="Step")
    assert section["section"] == "Step one" and "Field" in section["content"]
    assert not section["content"].startswith("---")
    paged = kb.get_topic(new, "topics/Welcome.md", max_chars=1000)
    assert paged["offset"] == 0
    with pytest.raises(KnowledgeError, match="Section"):
        kb.get_topic(new, "topics/Welcome.md", section="nope")


@pytest.mark.parametrize("path", [
    "../../catalog.json", "topics/../../../x.md", "C:/Windows/win.ini", "/etc/passwd", "topics/\0.md",
    "..\\..\\catalog.json", "manifest.json",
])
def test_paths_cannot_escape(knowledge, path):
    root, _, new = knowledge
    with pytest.raises(KnowledgeError):
        KnowledgeBase(root).get_topic(new, path)


def test_asset_confined_to_assets(knowledge):
    root, _, new = knowledge
    kb = KnowledgeBase(root)
    file, mime, meta = kb.asset(new, "../assets/images/pic.png")
    assert mime == "image/png" and file.name == "pic.png"
    assert meta["citation"].endswith("assets/images/pic.png")
    for bad in ("../manifest.json", "assets/../manifest.json", "../../catalog.json"):
        with pytest.raises(KnowledgeError):
            kb.asset(new, bad)


def test_toc_and_keywords(knowledge):
    root, _, new = knowledge
    kb = KnowledgeBase(root)
    toc = kb.get_toc(new, depth=1)
    assert [e["title"] for e in toc["entries"]] == ["Welcome", "Tasks"]
    assert toc["entries"][1]["children_count"] == 1
    sub = kb.get_toc(new, under="Tasks")
    assert sub["under"] == ["Tasks"] and sub["entries"][0]["citation"].endswith("Doing_A_Thing.md")
    keywords = kb.lookup_keyword("doing", collection_id=new)
    assert [r["keyword"] for r in keywords["results"]] == ["thing, doing"]
    assert kb.lookup_keyword("thing", version="latest", exact=True)["total"] == 1


def test_compare_topic(knowledge):
    root, old, new = knowledge
    kb = KnowledgeBase(root)
    result = kb.compare_topic("sub/Doing_A_Thing.html", family="gonow")
    assert [c["collection_id"] for c in result["collections"]] == [old, new]
    assert "+| A | First and improved |" in result["comparisons"][0]["diff"]
    same = kb.compare_topic("Welcome", family="gonow")
    assert same["comparisons"][0]["identical"]
    with pytest.raises(KnowledgeError):
        kb.compare_topic("Welcome", collection_ids=[new])


def test_sections_ignore_code_fences():
    body = "# A\n\n```\n# not a heading\n```\n\n<a id=\"x\"></a>\n## B\ntext\n# C\n"
    found = sections(body)
    assert [(s["title"], s["anchors"]) for s in found] == [("A", []), ("B", ["x"]), ("C", [])]
    assert found[0]["end"] == found[2]["start"]


def test_missing_catalog_is_explained(tmp_path):
    with pytest.raises(KnowledgeError, match="navhelp convert"):
        KnowledgeBase(tmp_path).collections()


def test_convert_disabled_by_default(knowledge):
    tools = NavhelpTools(knowledge[0], Settings())
    with pytest.raises(KnowledgeError, match="--allow-convert"):
        tools.convert_help()


def test_scan_tool_redacts_home(install_tree, tmp_path):
    tools = NavhelpTools(tmp_path, Settings(roots=[install_tree]))
    result = tools.scan_installations()
    assert result["files"] == 4 and result["distinct"] == 3
    assert "ConfigCaptain" in result["excluded_folders"]


# --------------------------------------------------------------------------- MCP protocol layer
def _run(coro):
    return asyncio.run(coro)


def test_mcp_tools_registered_and_annotated(knowledge):
    server = create_server(knowledge[0])
    tools = {t.name: t for t in _run(server.list_tools())}
    assert set(tools) == {"list_collections", "search_topics", "get_topic", "get_toc", "lookup_keyword",
                          "compare_topic", "get_asset", "rebuild_search_index", "scan_installations",
                          "inspect_installations"}
    assert tools["search_topics"].annotations.read_only_hint is True
    with_convert = {t.name for t in _run(create_server(knowledge[0], allow_convert=True).list_tools())}
    assert "convert_help" in with_convert


def test_mcp_call_and_errors(knowledge):
    root, _, new = knowledge
    server = create_server(root)
    ok = _run(server.call_tool("search_topics", {"query": "welcome", "version": "latest"}))
    assert not ok.is_error
    payload = ok.structured_content or json.loads(ok.content[0].text)
    assert payload["results"][0]["collection_id"] == new
    with pytest.raises(ToolError, match="escapes"):  # reported to the client as an is_error result
        _run(server.call_tool("get_topic", {"collection_id": new, "path": "../../catalog.json"}))
    image = _run(server.call_tool("get_asset", {"collection_id": new, "path": "assets/images/pic.png"}))
    assert not image.is_error and image.content[0].type == "image"
