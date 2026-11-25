"""v0.9.17: agent tiles are logo mascots with eyes; welcome and empty chat too."""
from agent import __version__, i18n
from agent.harness_chat import CHAT_PAGE
from agent.harness_settings import WELCOME_PAGE


def test_mascot_is_the_logo_with_eyes_and_states():
    assert CHAT_PAGE.count('class="mascot"') + CHAT_PAGE.count("class=\"mascot\"") >= 1 or "class=\"mascot\"" in CHAT_PAGE or 'class="mascot"' in CHAT_PAGE
    # JS template uses backticks; the SVG is in MASCOT
    assert "class=\"mascot\"" in CHAT_PAGE or "class='mascot'" in CHAT_PAGE or 'class="mascot"' in CHAT_PAGE
    assert "atileblink" in CHAT_PAGE and "atilelook" in CHAT_PAGE
    assert "prefers-reduced-motion" in CHAT_PAGE
    assert 'toggle("working"' in CHAT_PAGE and 'toggle("idle"' in CHAT_PAGE
    assert "done .happy" in CHAT_PAGE and "error .sad" in CHAT_PAGE
    assert 'class="ring"' in CHAT_PAGE and 'class="face"' in CHAT_PAGE and 'class="pupil"' in CHAT_PAGE


def test_welcome_and_empty_chat_have_the_mascot():
    assert 'class="mascot"' in WELCOME_PAGE and 'data-i18n="wiz.hi"' in WELCOME_PAGE
    assert "home-mascot" in CHAT_PAGE and 't("home.hi")' in CHAT_PAGE
    assert i18n.EN["home.hi"] != i18n.FR["home.hi"] and "tu" in i18n.FR["home.hi"]
    assert i18n.EN["wiz.hi"] != i18n.FR["wiz.hi"]
    assert __version__ == "0.9.17"
