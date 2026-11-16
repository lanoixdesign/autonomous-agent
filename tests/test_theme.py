"""v0.6 day / night theme: Settings choice (auto by default), a sun/moon button on every page, applied before the
first paint, remembered per browser, and a light palette that meets WCAG AA contrast."""
import json
import re
import shutil
import subprocess

import pytest

from agent import i18n
from agent.harness import render_page
from agent.harness_chat import CHAT_PAGE
from agent.harness_connect import CONNECT_PAGE
from agent.harness_help import HELP_PAGE
from agent.harness_page import PAGE
from agent.harness_settings import SETTINGS_PAGE, WELCOME_PAGE
from agent.theme import BASE_CSS, THEME_BTN, THEME_HEAD
from agent.llm import MockLLM

from test_harness import call, server  # noqa: F401  (fixture)
from test_settings_ui import app, post  # noqa: F401  (fixture)

NODE = pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
PAGES = {"chat": CHAT_PAGE, "dashboard": PAGE, "connect": CONNECT_PAGE, "settings": SETTINGS_PAGE,
         "welcome": WELCOME_PAGE, "help": HELP_PAGE}


def _vars(block):
    return dict(re.findall(r"--([a-z0-9-]+):([^;}]+)", block))


def palettes():
    dark = _vars(BASE_CSS.split(":root{", 1)[1].split("}", 1)[0])
    light = _vars(BASE_CSS.split("html[data-theme=light]{", 1)[1].split("}", 1)[0])
    return dark, light


def lum(hexc):
    h = hexc.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    ch = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    ch = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def test_light_palette_overrides_every_colour_variable():
    dark, light = palettes()
    colours = {k for k, v in dark.items() if v.strip().startswith(("#", "rgba"))}
    assert colours - set(light) == set(), colours - set(light)


@pytest.mark.parametrize("which", ["light", "dark"])
def test_text_colours_meet_wcag_aa(which):
    dark, light = palettes()
    pal = light if which == "light" else dark
    backgrounds = [pal["bg"], pal["panel"], pal["panel2"]] if which == "light" else [pal["bg"], pal["panel"]]
    for fg in ("text", "strong", "soft", "muted", "blue", "ok", "warn", "bad", "t-bad", "t-warn", "t-violet", "t-ok", "t-cyan"):
        for bg in backgrounds:
            assert ratio(pal[fg], bg) >= 4.5, (which, fg, pal[fg], bg, round(ratio(pal[fg], bg), 2))


def test_theme_setting_defaults_to_auto_is_validated_and_persisted(app, tmp_path):
    base, h, c = app()
    assert call(base, "GET", "/app/status")[1]["theme"] == "auto"
    st, v = post(base, "/app/settings", {"theme": "light"})
    assert st == 200 and v["theme"] == "light"
    assert json.loads((tmp_path / "state" / "settings.json").read_text())["theme"] == "light"
    assert call(base, "GET", "/app/status")[1]["theme"] == "light"
    st, r = post(base, "/app/settings", {"theme": "pink"})
    assert st == 400 and r["code"] == "bad_choice"


def test_pages_apply_the_theme_in_head_with_the_settings_default(app):
    base, h, c = app()
    post(base, "/app/settings", {"theme": "dark"})
    import urllib.request
    html = urllib.request.urlopen(urllib.request.Request(base + "/help", headers={"Accept": "text/html"})).read().decode()
    head = html.split("</head>", 1)[0]
    assert 'var D="dark"' in head and head.index("<script>") < head.index("<style>")      # before the first paint
    for name, p in PAGES.items():
        out = render_page(p, "fr", None, "nonsense").decode()
        assert 'var D="auto"' in out, name                                                   # unknown -> auto
        assert out.count("data-theme-btn") >= 1, name


def test_sun_moon_button_in_every_header_and_the_phone_menu():
    # v0.9.2: the theme switch lives in the sidebar's bottom group (also the phone drawer)
    for name in ("dashboard", "connect", "settings", "help", "chat"):
        side = PAGES[name].split('<aside id="sidenav"', 1)[1].split("</aside>", 1)[0]
        foot = side.split('class="sn-foot"', 1)[1]
        assert "data-theme-btn" in foot, name
    assert "data-theme-btn" in WELCOME_PAGE
    assert THEME_BTN.startswith("<button") and 'type="button"' in THEME_BTN


def test_settings_offers_day_night_auto_and_strings_exist():
    for v in ("light", "dark", "auto"):
        assert f'name="theme" value="{v}"' in SETTINGS_PAGE
    assert "setTheme" in SETTINGS_PAGE and "themechange" in SETTINGS_PAGE
    for k in ("set.theme", "set.theme.light", "set.theme.dark", "set.theme.auto", "set.theme.help", "tip.theme",
              "theme.toLight", "theme.toDark"):
        assert k in i18n.EN and k in i18n.FR and i18n.EN[k] != i18n.FR[k] or k == "set.theme.auto", k
    assert "Jour" in i18n.FR["set.theme.light"] and "Nuit" in i18n.FR["set.theme.dark"] and i18n.FR["set.theme.auto"] == "Automatique"


@NODE
def test_theme_script_follows_the_system_and_remembers_the_choice():
    js = THEME_HEAD.split("<script>", 1)[1].rsplit("</script>", 1)[0].replace('"__THEME_DEFAULT__"', '"auto"')
    harness = r"""
const store={}; let sysLight=false; const attrs={}; const listeners={};
global.localStorage={getItem:k=>k in store?store[k]:null,setItem:(k,v)=>{store[k]=String(v);}};
global.window=global; window.matchMedia=q=>({get matches(){return sysLight;},addEventListener:(e,f)=>{listeners.mq=f;}});
window.addEventListener=(e,f)=>{}; global.CustomEvent=class{constructor(n,o){this.type=n;this.detail=o&&o.detail;}};
global.document={documentElement:{setAttribute:(k,v)=>{attrs[k]=v;},getAttribute:k=>attrs[k]},
  querySelector:()=>null,querySelectorAll:()=>[],addEventListener:()=>{},dispatchEvent:()=>{}};
""" + js + r"""
const out=[]; out.push(attrs["data-theme"]);            // auto + dark system
sysLight=true; listeners.mq(); out.push(attrs["data-theme"]);   // the system switches to light
toggleTheme(); out.push(attrs["data-theme"], store.theme);      // the button: explicit dark, remembered
sysLight=false; listeners.mq(); sysLight=true; listeners.mq(); out.push(attrs["data-theme"]);   // explicit choice wins
setTheme("auto"); out.push(attrs["data-theme"], attrs["data-theme-pref"]);
setTheme("bogus"); out.push(store.theme);
console.log(JSON.stringify(out));
"""
    r = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True)
    assert json.loads(r.stdout) == ["dark", "light", "dark", "dark", "dark", "light", "auto", "auto"]


def test_never_caches_or_sends_the_theme_anywhere(server):
    base, h = server(lambda: MockLLM())
    assert call(base, "GET", "/health")[0] == 200
    assert "localStorage" in THEME_HEAD and "fetch(" not in THEME_HEAD                    # purely local, no network
