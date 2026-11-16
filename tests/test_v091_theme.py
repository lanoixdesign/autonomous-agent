"""v0.9.1 calm theme: WCAG AA contrast for the theme tokens, no glow/neon left."""
import re

import pytest

from agent import theme


def _block(selector):
    m = re.search(re.escape(selector) + r"\{([^}]*)\}", theme.BASE_CSS)
    assert m, selector
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", m.group(1)))


DARK = _block(":root")
LIGHT = {**DARK, **_block("html[data-theme=light]")}


def _lum(hexc):
    def ch(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(hexc[i:i + 2]) for i in (1, 3, 5))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT = ["text", "strong", "soft", "muted", "accent-text", "ok", "warn", "bad"]
SURF = ["bg", "panel", "panel2", "chip"]
PAIRS = [(f, s) for f in TEXT for s in SURF]


@pytest.mark.parametrize("name,tok", [("dark", DARK), ("light", LIGHT)])
@pytest.mark.parametrize("fg,bg", PAIRS)
def test_text_tokens_meet_wcag_aa(name, tok, fg, bg):
    assert ratio(tok[fg], tok[bg]) >= 4.5, (name, fg, bg, round(ratio(tok[fg], tok[bg]), 2))


@pytest.mark.parametrize("tok", [DARK, LIGHT])
def test_button_text_on_accent(tok):
    assert ratio("#FFFFFF", tok["accent"]) >= 4.5


def test_day_theme_is_light_and_night_is_not_pure_black():
    assert _lum(LIGHT["bg"]) > 0.85 and _lum(LIGHT["panel"]) > 0.85
    assert DARK["bg"].upper() != "#000000" and _lum(DARK["bg"]) > 0.005


def test_accent_is_muted():
    import colorsys
    for tok in (DARK, LIGHT):
        r, g, b = (int(tok["accent"][i:i + 2], 16) / 255 for i in (1, 3, 5))
        assert colorsys.rgb_to_hls(r, g, b)[2] <= 0.5  # saturation


def test_calm_layer_removes_effects():
    c = theme.CALM_CSS
    for rule in ("box-shadow:none!important", "text-shadow:none!important", "filter:none!important",
                 "backdrop-filter:none!important"):
        assert rule in c.replace(" ", ""), rule
    import pathlib
    for f in pathlib.Path(theme.__file__).parent.glob("*.py"):
        src = f.read_text(encoding="utf-8")
        for bad in ("linear-gradient", "radial-gradient", "drop-shadow", "backdrop-filter:blur", "#00D4FF"):
            assert bad not in src, (f.name, bad)
        assert not re.search(r"box-shadow:\s*0 0 \d", src), f.name


def test_calm_layer_injected_on_every_page():
    from agent import harness
    html = harness.render_page("<html><head><title>x</title></head><body></body></html>").decode()
    assert theme.CALM_CSS.strip()[:40] in html


def report():
    for name, tok in (("dark", DARK), ("light", LIGHT)):
        for fg, bg in PAIRS:
            print(name, fg, "on", bg, round(ratio(tok[fg], tok[bg]), 2))
        print(name, "white on accent", round(ratio("#FFFFFF", tok["accent"]), 2))


if __name__ == "__main__":
    report()
