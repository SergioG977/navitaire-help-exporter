"""Shared fixtures. Every fixture is synthetic: no Navitaire content is used in tests."""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

HHC = """<!DOCTYPE HTML PUBLIC "-//IETF//DTD HTML//EN">
<HTML><BODY>
<UL>
<LI> <OBJECT type="text/sitemap"><param name="Name" value="Welcome"><param name="Local" value="Welcome.html"></OBJECT>
<LI> <OBJECT type="text/sitemap"><param name="Name" value="Tasks"></OBJECT>
<UL>
<LI> <OBJECT type="text/sitemap"><param name="Name" value="Doing A Thing"><param name="Local" value="sub/Doing_A_Thing.html#Step"></OBJECT>
</UL>
</UL>
</BODY></HTML>
"""

HHK = """<HTML><BODY><UL>
<LI> <OBJECT type="text/sitemap"><param name="Name" value="thing"><param name="Local" value="sub/Doing_A_Thing.html"></OBJECT>
<UL><LI> <OBJECT type="text/sitemap"><param name="Name" value="doing"><param name="Local" value="sub/Doing_A_Thing.html"></OBJECT></UL>
</UL></BODY></HTML>
"""

WELCOME = """<html><head><title>Welcome</title></head><body>
<img id="collapseImage" style="display:none" src="images/collapse.gif">
<div id="pagetop"><span id="projecttitle">Sample Project</span>
<span id="feedbacklink"><a href="mailto:someone@example.invalid">Send Feedback</a></span></div>
<div id="mainbody">
<p>Welcome to Sample Product version 9.8.7.</p>
<p>See <a href="sub/Doing_A_Thing.html#Step">doing a thing</a> and <a href="Missing.html">a missing page</a>.</p>
<p>Also <a href="sub/doing a thing.html">loosely named link</a> and <a href="12345678-1234-1234-1234-123456789abc">id</a>.</p>
<p><img src="images/pic.png" alt="A picture"></p>
</div>
<div id="nonscrollingpagefooter">Copyright notice</div>
</body></html>
"""

TOPIC = """<html><head><title>Doing A Thing</title></head><body><div id="mainbody">
<h2 id="Step">Step one</h2><p>Text with <a href="../Welcome.html">back link</a>.</p>
<pre class="xml">&lt;a&gt;1&lt;/a&gt;</pre>
<table><tr><th>Field</th><th>Meaning</th></tr><tr><td>A</td><td>First</td></tr></table>
</div></body></html>
"""


def system_blob(title: str, contents: str, index: str, default: str) -> bytes:
    def record(code: int, text: str) -> bytes:
        data = text.encode("cp1252") + b"\0"
        return struct.pack("<HH", code, len(data)) + data

    return struct.pack("<I", 3) + record(0, contents) + record(1, index) + record(2, default) + record(3, title) \
        + struct.pack("<HH", 4, 4) + struct.pack("<I", 1033)


@pytest.fixture
def extracted(tmp_path: Path) -> Path:
    """A folder that looks like a CHM extracted by 7-Zip."""
    root = tmp_path / "extracted"
    (root / "sub").mkdir(parents=True)
    (root / "images").mkdir()
    (root / "Welcome.html").write_text(WELCOME, encoding="utf-8")
    (root / "sub" / "Doing_A_Thing.html").write_text(TOPIC, encoding="utf-8")
    (root / "images" / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "images" / "collapse.gif").write_bytes(b"GIF89a")
    (root / "Sample.hhc").write_text(HHC, encoding="cp1252")
    (root / "Sample.hhk").write_text(HHK, encoding="cp1252")
    (root / "#SYSTEM").write_bytes(system_blob("Sample Help", "Sample.hhc", "Sample.hhk", "Welcome.html"))
    return root


@pytest.fixture
def install_tree(tmp_path: Path) -> Path:
    """A fake Navitaire installation root containing empty placeholder CHM files."""
    root = tmp_path / "Navitaire"
    files = [
        "NAV1/GoNow/9.1.0.100/GoNow Native1WayCommunication/GoNow.chm",
        "NewSkies/R9.3/Navitaire NAV1/Client Suite/SkySpeed Reservation Manager/SkySpeedHelp.chm",
        "NewSkies/R9.3/Navitaire NAV1/Client Suite/Management Console/Plugins/A/Navitaire.NewSkies.UI.Win.SkyManagerHelp.chm",
        "NewSkies/R9.3/Navitaire NAV1/Client Suite/Management Console/Navitaire.NewSkies.UI.Win.SkyManagerHelp.chm",
        "ConfigCaptain/Help/Captain.chm",
        "navitairete/5.0/TE.chm",
        "GovernmentSecurity/R9.4/readme.txt",
    ]
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"ITSF" + rel.encode() if "SkyManagerHelp" not in rel else b"ITSF-same-content")
    return root
