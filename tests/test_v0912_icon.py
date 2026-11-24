"""v0.9.12: the app logo replaces the default Python icon (builds, web UI, download site)."""
import base64
import os
import struct

from agent import icon_data, pwa

ROOT = os.path.join(os.path.dirname(__file__), "..")
A = os.path.join(ROOT, "assets")


def _png_size(b):
    assert b[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", b[16:24])


def test_icon_files_exist_and_have_the_right_formats():
    for name in ("icon.svg", "icon.png", "icon.icns", "icon.ico"):
        assert os.path.getsize(os.path.join(A, name)) > 300, name
    assert open(os.path.join(A, "icon.icns"), "rb").read(4) == b"icns"
    ico = open(os.path.join(A, "icon.ico"), "rb").read()
    assert ico[:4] == b"\x00\x00\x01\x00"
    count = struct.unpack("<H", ico[4:6])[0]
    sizes = {ico[6 + 16 * i] or 256 for i in range(count)}
    assert {16, 32, 48, 256} <= sizes
    assert _png_size(open(os.path.join(A, "icon.png"), "rb").read()) == (1024, 1024)


def test_spec_uses_the_icons():
    spec = open(os.path.join(ROOT, "packaging", "autonomous-agent.spec")).read()
    assert "icon=ICNS" in spec and '"icon.icns"' in spec
    assert "icon=ICO" in spec and '"icon.ico"' in spec


def test_web_ui_serves_the_logo():
    assert pwa.asset("/icon.svg")[1] == icon_data.SVG
    assert b"<circle" in icon_data.SVG and b"<rect" in icon_data.SVG
    for path, size in (("/favicon.png", 32), ("/icon-192.png", 192), ("/icon-512.png", 512),
                       ("/apple-touch-icon.png", 180)):
        ctype, body, _ = pwa.asset(path)
        assert ctype == "image/png" and _png_size(body) == (size, size)
    assert 'href="/favicon.png"' in pwa.HEAD


def test_site_uses_the_logo():
    html = open(os.path.join(ROOT, "docs", "site", "index.html"), encoding="utf-8").read()
    assert 'rel="icon" href="icon.svg"' in html and 'src="icon.svg"' in html
    for f in ("icon.svg", "favicon.png", "apple-touch-icon.png"):
        assert os.path.exists(os.path.join(ROOT, "docs", "site", f))
    assert base64.b64decode(icon_data.PNG_32) == open(os.path.join(ROOT, "docs", "site", "favicon.png"), "rb").read()
