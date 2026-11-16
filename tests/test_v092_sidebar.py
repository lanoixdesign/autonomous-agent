"""v0.9.2: the top tab bar became one calm left sidebar (icons-only option, phone drawer)."""
import pytest

from agent import theme
from agent.harness_chat import CHAT_PAGE
from agent.harness_connect import CONNECT_PAGE
from agent.harness_dev import DEV_PAGE
from agent.harness_help import HELP_PAGE
from agent.harness_page import PAGE
from agent.harness_settings import SETTINGS_PAGE
from agent import i18n

PAGES = {"chat": CHAT_PAGE, "dashboard": PAGE, "settings": SETTINGS_PAGE, "connect": CONNECT_PAGE,
         "dev": DEV_PAGE, "help": HELP_PAGE}


@pytest.mark.parametrize("name", list(PAGES))
def test_one_sidebar_with_every_destination(name):
    page = PAGES[name]
    assert page.count('id="sidenav"') == 1 and page.count('id="lang"') == 1
    side = page.split('<aside id="sidenav"', 1)[1].split("</aside>", 1)[0]
    for k in ("chat", "dashboard", "dev", "settings", "connect", "help"):
        assert f'data-nav="{k}"' in side, k
    foot = side.split('class="sn-foot"', 1)[1]
    for item in ('data-nav="help"', "data-theme-btn", 'id="snmode"', 'id="lang"', 'id="snquit"'):
        assert item in foot, item                           # secondary items grouped at the bottom
    assert 'class="sn-collapse"' in side and 'aria-expanded' in side
    assert 'class="back"' not in page and 'class="tabs"' not in page.split("</aside>", 1)[1]   # no top tab bar


@pytest.mark.parametrize("name", [n for n in PAGES if n != "chat"])
def test_page_header_is_just_a_title_and_the_phone_menu_button(name):
    hdr = PAGES[name].split('<header class="apphead', 1)[1].split("</header>", 1)[0]
    assert "data-sn-open" in hdr and hdr.count("<h1") == 1
    assert "data-theme-btn" not in hdr and 'id="lang"' not in hdr


def test_chat_is_sidebar_conversation_input():
    top = CHAT_PAGE.split('<div id="top">', 1)[1].split('<div id="ratebar"', 1)[0]
    assert 'class="tabs"' not in top and 'id="filesbtn"' not in top and 'id="brand"' not in top
    side = CHAT_PAGE.split('<aside id="sidenav"', 1)[1].split("</aside>", 1)[0]
    assert 'id="convs"' in side and 'id="new"' in side and 'id="filesbtn"' in side
    assert '<details class="adv"><summary data-i18n="ui.advanced">' in side    # critic / IDC defaults folded


def test_collapse_is_remembered_and_keyboard_friendly():
    js, css = theme.NAV_JS, theme.NAV_CSS
    assert 'localStorage.setItem("navMini"' in js and 'localStorage.getItem("navMini")' in theme.THEME_HEAD
    assert 'setAttribute("aria-current", "page")' in js and 'e.key === "Escape"' in js
    assert "html.sn-mini" in css and "clip:rect(0 0 0 0)" in css     # icons only, labels still read by screen readers
    assert 'aria-hidden="true"' in theme.ICONS["chat"]


def test_phone_drawer_and_calm_marking():
    css = theme.NAV_CSS
    mobile = css[css.index("@media (max-width:760px)"):]
    assert "translateX(-102%)" in mobile and "html.sn-open .sidenav{transform:none}" in mobile
    assert "rgba(var(--accent-rgb),.16)" in css and "gradient" not in css and "box-shadow" not in css


def test_strings_exist_in_both_languages():
    for k in ("nav.menu", "nav.collapse", "nav.theme", "nav.modeSimple", "nav.modeExpert", "nav.modeTip", "nav.quit"):
        assert i18n.EN.get(k) and i18n.FR.get(k), k
