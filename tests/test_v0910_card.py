"""v0.9.10: the approval card shows only the sentence, Allow / Refuse and a discreet checkbox; the explanation
and the technical details are in one folded "Details"."""
import re

from agent import i18n
from agent.harness_chat import CHAT_PAGE


def _card_js():
    a = CHAT_PAGE.index("async function popups(){")
    return CHAT_PAGE[a:CHAT_PAGE.index("\n}\n", a)]


def test_main_view_is_title_buttons_and_checkbox():
    js = _card_js()
    assert "c.append(q);" in js
    assert 't("card.question")' not in js and '"q2"' not in js and '"ctop"' not in js
    # the explanation is no longer appended to the card itself, only inside the details
    assert 'c.append(el("p","hint"' not in js and 'why.append(el("p","hint"' in js
    assert 'keep.type="checkbox"' in js and 't("card.rememberHere")' in js
    # one checkbox in both modes, no row of "always allow" buttons
    assert 't("card.alwaysHere")' not in js


def test_one_folded_details_with_the_explanation_first():
    js = _card_js()
    assert js.count('el("details"') == 1 and 'el("summary",null,t("card.details"))' in js
    i = js.index("det.append(sum, why,")
    assert js.index('"card.techTool"', i) > i and "JSON.stringify(a.args" in js[i:]
    assert 't("hint.mcp",{service:a.service})' in js            # connected services
    assert 'tr("hint",a.category)' in js                          # built-in tools
    assert 't("card.safety")' in js and js.index('t("card.safety")') < i
    # screen readers: the card is labelled by the sentence and described by the explanation
    assert 'aria-labelledby",q.id' in js and 'aria-describedby",why.id' in js
    assert js.index("c.append(det)") > js.index("c.append(b)")


def test_details_labels_in_both_languages():
    assert i18n.EN["card.details"] == "Details" and i18n.FR["card.details"] == "Détails"
    assert "ta sécurité" in i18n.FR["card.safety"] and "vous" not in i18n.FR["card.safety"]
    for k in ("card.alwaysApp", "card.rememberHere", "hint.mcp", "hint.write"):
        assert i18n.EN.get(k) and i18n.FR.get(k), k
    for d in (i18n.EN, i18n.FR):
        for cat in ("read", "write", "network", "execute", "send", "spend"):
            if "hint." + cat in i18n.EN:
                assert d.get("hint." + cat), cat


def test_advanced_mode_keeps_until_closed_inside_details():
    js = _card_js()
    assert 'if(!SIMPLE()){ const rs=el("button","linkbtn",t("card.alwaysApp"))' in js and "det.append(rs)" in js
    assert re.search(r'answer\("approve","session"\)', js)
