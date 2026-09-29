"""HTML topic -> Markdown.

Table normalisation, generic cleanup and ``<pre>`` preservation are adapted from
DTDucas/chm-converter (MIT). Link/image rewriting is delegated to callbacks so
the converter can resolve targets against the whole collection.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable
from dataclasses import dataclass

import html2text
from bs4 import BeautifulSoup, Tag

REMOVE_TAGS = ["script", "style", "link", "meta", "iframe", "object", "embed", "noscript",
               "input", "button", "form", "select", "textarea", "head"]

_CLASS_LANG = {
    "csharp": "csharp", "cs": "csharp", "vb": "vb", "cpp": "cpp", "xml": "xml", "html": "xml",
    "json": "json", "python": "python", "java": "java", "javascript": "javascript", "js": "javascript",
    "sql": "sql", "powershell": "powershell", "bash": "bash",
}
_HEADING_NO_SPACE = re.compile(r"^(#{1,6})([^\s#])", re.MULTILINE)

# Innovasys HelpStudio page chrome used by every Navitaire help file: banner with the
# project title, the mailto "Send Feedback" link, footers and copyright bar. The topic
# body lives in div#mainbody and is kept intact (including collapsible sections).
# Two template generations exist: the classic one (div#pagetop / div#mainbody) and the
# newer one (div#i-header-content / div#i-body-content / div#i-footer-content).
CHROME_IDS = ("pagetop", "feedbacklink", "pagefooter", "nonscrollingpagefooter",
              "i-before-header-content", "i-header-content", "i-after-header-content", "i-footer-content")
_HIDDEN = re.compile(r"display\s*:\s*none", re.IGNORECASE)


def remove_chrome(soup: BeautifulSoup) -> None:
    for element_id in CHROME_IDS:
        for tag in soup.find_all(id=element_id):
            tag.decompose()
    # Feedback links point to an internal mailbox; drop them wherever they appear.
    for a in soup.find_all("a", href=True):
        if str(a["href"]).strip().lower().startswith("mailto:"):
            a.decompose()
    # Script-only images: hidden preloads and expand/collapse toggles.
    for img in soup.find_all("img"):
        classes = img.get("class") or []
        if _HIDDEN.search(str(img.get("style", ""))) or "toggle" in classes or img.get("name") == "toggleSwitch":
            img.decompose()


@dataclass
class TopicResult:
    markdown: str
    html_title: str | None
    headings: list[str]


LinkResolver = Callable[[str], str | None]


def extract_title(soup: BeautifulSoup) -> str | None:
    tag = soup.find("title")
    if tag and tag.get_text(strip=True):
        return " ".join(tag.get_text().split())
    for level in range(1, 4):
        heading = soup.find(f"h{level}")
        if heading and heading.get_text(strip=True):
            return " ".join(heading.get_text().split())
    return None


def _fix_table_block(lines: list[str]) -> list[str]:
    rows = []
    for line in lines:
        cells = [c.strip() for c in line.split("|")]
        if cells and cells[0] == "":
            cells = cells[1:]
        if cells and cells[-1] == "":
            cells = cells[:-1]
        rows.append(cells)
    width = max((len(r) for r in rows), default=0)
    out = []
    for i, row in enumerate(rows):
        if i == 1 and all(re.fullmatch(r":?-{1,}:?", c or "-") for c in row):
            continue  # original separator row, re-emitted below
        row = row + [""] * (width - len(row))
        out.append("| " + " | ".join(row) + " |")
        if i == 0:
            out.append("| " + " | ".join(["---"] * width) + " |")
    return out


def fix_tables(text: str) -> str:
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        if "|" in lines[i] and i + 1 < len(lines) and re.match(r"^[\s\-|:]+$", lines[i + 1]) \
                and "-" in lines[i + 1]:
            block = []
            while i < len(lines) and "|" in lines[i]:
                block.append(lines[i])
                i += 1
            out.extend(_fix_table_block(block))
            out.append("")
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out)


def clean_markdown(text: str) -> str:
    text = text.replace("\r\n", "\n")
    text = _HEADING_NO_SPACE.sub(r"\1 \2", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?m)^(---\s*\n){2,}", "---\n", text)
    return text.strip() + "\n"


def _mark_anchors(soup: BeautifulSoup) -> dict[str, str]:
    """Replace named anchors with placeholders so html2text keeps them as ``<a id>``."""
    anchors: dict[str, str] = {}

    def placeholder(name: str) -> str:
        key = f"NAVHELPANCHOR{len(anchors)}X"
        anchors[key] = f'<a id="{html.escape(name, quote=True)}"></a>'
        return key

    for tag in soup.find_all("a"):
        name = tag.get("name") or (tag.get("id") if not tag.get("href") else None)
        if not name:
            continue
        tag.insert_before(soup.new_string(placeholder(str(name))))
        if tag.get("href"):
            del tag["name"]
        else:
            tag.unwrap()
    for tag in soup.find_all(re.compile(r"^h[1-6]$")):
        if tag.get("id"):
            tag.insert(0, soup.new_string(placeholder(str(tag["id"]))))
    return anchors


def _mark_code(soup: BeautifulSoup) -> dict[str, str]:
    blocks: dict[str, str] = {}
    for pre in soup.find_all("pre"):
        classes = " ".join(pre.get("class", [])).lower()
        lang = next((v for k, v in _CLASS_LANG.items() if k in classes.split()), "text")
        key = f"NAVHELPCODE{len(blocks)}X"
        body = pre.get_text().strip("\n")
        fence = "````" if "```" in body else "```"
        blocks[key] = f"\n{fence}{lang}\n{body}\n{fence}\n"
        pre.replace_with(soup.new_string(key))
    return blocks


def html_to_markdown(source: str, resolve_link: LinkResolver, resolve_image: LinkResolver) -> TopicResult:
    soup = BeautifulSoup(source, "html.parser")
    title = extract_title(soup)
    for tag in soup.find_all(REMOVE_TAGS):
        tag.decompose()
    remove_chrome(soup)

    anchors = _mark_anchors(soup)

    for a in soup.find_all("a", href=True):
        target = resolve_link(str(a["href"]))
        if target is None:
            a.unwrap()
            continue
        a.attrs = {"href": target}
        if not a.get_text(strip=True) and not a.find("img"):
            a.decompose()

    for img in soup.find_all("img"):
        if not isinstance(img, Tag):
            continue
        src = resolve_image(str(img.get("src", "")))
        alt = " ".join(str(img.get("alt", "")).split())
        if src is None:
            if alt:
                img.replace_with(soup.new_string(f"[image: {alt}]"))
            else:
                img.decompose()
        else:
            img.attrs = {"src": src, "alt": alt}

    code = _mark_code(soup)

    converter = html2text.HTML2Text()
    converter.body_width = 0
    converter.unicode_snob = True
    converter.single_line_break = False
    converter.ignore_images = False
    converter.ignore_links = False
    converter.inline_links = True
    converter.wrap_links = False
    converter.pad_tables = False
    markdown = converter.handle(str(soup))

    for key, value in anchors.items():
        markdown = markdown.replace(key, value)
    for key, value in code.items():
        markdown = markdown.replace(key, value)
    markdown = clean_markdown(fix_tables(markdown))

    headings = [line.lstrip("#").strip() for line in markdown.splitlines() if re.match(r"^#{1,6} ", line)]
    headings = [re.sub(r'<a id="[^"]*"></a>', "", h).strip() for h in headings]
    return TopicResult(markdown=markdown, html_title=title, headings=[h for h in headings if h])
