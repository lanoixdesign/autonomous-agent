"""v0.9.9 "really simple": Simple mode by default, fewer items, plain French for connected services."""
import json
import re

from agent import i18n, mcp
from agent.harness import _service, render_page
from agent.harness_chat import CHAT_PAGE
from agent.harness_connect import CONNECT_PAGE
from agent.harness_settings import SETTINGS_PAGE, WELCOME_PAGE
from agent.theme import APPROVAL_JS, NAV_HTML, SIMPLE_CSS
from agent.userconfig import AppControl, SecretStore, UserConfig


def _control(tmp_path, settings=None):
    if settings is not None:
        (tmp_path / "settings.json").write_text(json.dumps(settings))
    cfg = UserConfig(tmp_path)
    return AppControl(cfg, SecretStore(tmp_path / "secrets.json", use_keyring=False), home=str(tmp_path))


# ---------------------------------------------------------------- Simple is the default, also for existing users
def test_simple_is_the_default_for_new_and_existing_users(tmp_path):
    assert _control(tmp_path / "new").ui_mode() == "simple"
    old = tmp_path / "old"; old.mkdir()
    assert _control(old, {"lang": "fr", "theme": "dark", "trace": "technical"}).ui_mode() == "simple"
    odd = tmp_path / "odd"; odd.mkdir()
    assert _control(odd, {"ui_mode": "something"}).ui_mode() == "simple"


def test_an_explicit_advanced_choice_is_kept(tmp_path):
    assert _control(tmp_path, {"ui_mode": "expert"}).ui_mode() == "expert"


def test_pages_say_simple_before_the_first_paint():
    for page in (CHAT_PAGE, CONNECT_PAGE, SETTINGS_PAGE, WELCOME_PAGE):
        html = render_page(page, "fr").decode()
        head = html.split("</head>")[0]
        assert 'setAttribute("data-ui","simple")' in head and SIMPLE_CSS in head
        assert '<html lang="fr">' in html
    assert 'setAttribute("data-ui","expert")' in render_page(CHAT_PAGE, ui="expert").decode()
    assert 'setAttribute("data-ui","simple")' in render_page(CHAT_PAGE, ui=None).decode()


# ---------------------------------------------------------------- what Simple mode hides (everything stays in Advanced)
def _hidden():
    rules = SIMPLE_CSS.split("{display:none!important}")[0]
    return [r.replace("html[data-ui=simple] ", "").strip() for r in rules.split(",")]


def test_simple_sidebar_keeps_only_the_essentials():
    h = _hidden()
    for sel in (".sidenav a[data-nav=dashboard]", ".sidenav a[data-nav=dev]", "#filesbtn", ".sn-foot [data-theme-btn]",
                "#snmode", ".sn-lang", ".sn-opts details.adv", ".conv small"):
        assert sel in h, sel
    for keep in ("chat", "settings", "connect"):
        assert f'data-nav="{keep}"' in NAV_HTML and not any(f"data-nav={keep}]" in x for x in h)
    assert i18n.FR["nav.connect"] == "Services" and i18n.EN["nav.connect"] == "Services"
    assert i18n.FR["connect.heading"] == "Services"
    # the items still exist (Advanced mode shows them)
    for x in ('data-nav="dashboard"', 'data-nav="dev"', 'id="filesbtn"', 'id="snmode"', 'class="sn-lang"'):
        assert x in CHAT_PAGE


def test_simple_chat_top_bar_and_folder_line():
    h = _hidden()
    for sel in ("#title", "#status", "#mode", "#expmd", "#expjson", "body[data-page=chat] #stopall", "#folderline"):
        assert sel in h, sel
    assert 'id="cancel"' in CHAT_PAGE and 'id="demobadge"' not in CHAT_PAGE
    # one kind key banner, to the key step of the assistant
    assert 'id="keybanner"' in CHAT_PAGE and 'href="/welcome#key"' in CHAT_PAGE
    assert '$("keybanner").hidden=APP.mode!=="demo"' in CHAT_PAGE
    assert 'location.hash==="#key"?2:1' in WELCOME_PAGE
    # export and the folder: in the conversation's ⋯ menu
    assert 'id="cmexport"' in CHAT_PAGE and 'id="cmfolder"' in CHAT_PAGE
    assert i18n.FR["conv.export"] == "Exporter (Markdown)"


def test_conversation_list_shows_a_discreet_dot_only():
    assert 'el("i","busy")' in CHAT_PAGE and ".conv .busy{" in SIMPLE_CSS
    assert ".conv small" in _hidden()


def test_trace_and_composer_are_quiet():
    assert i18n.FR["trace.seeDetail"] == "Voir le détail"
    assert i18n.FR["chat.thinking"] == "L'agent travaille…" and i18n.FR["chat.waiting"] == "L'agent attend ta réponse"
    for sel in (".trhead .trsum", ".trhead .trpend"):
        assert sel in _hidden()
    assert i18n.FR["chat.input.placeholder"] == "Écris ta demande…"
    assert i18n.EN["chat.input.placeholder"] == "Write your request…"
    assert "#attach .lbl{display:none!important}" in SIMPLE_CSS
    assert 'data-i18n-title="chat.addFile.title"' in CHAT_PAGE


def test_services_screen_is_only_the_services():
    h = _hidden()
    for sel in ("#signed", "#pairing", "#apis", "#how", "#mcp details.adv"):
        assert sel in h, sel
    assert 'id="how"' in CONNECT_PAGE and 'data-preset="files"' in CONNECT_PAGE


def test_settings_hold_theme_language_and_mode():
    for x in ('name="theme"', 'id="langbtns"', 'name="uimode"'):
        assert x in SETTINGS_PAGE
    for sec in ("sandbox", "critic", "phone"):
        assert f'<section id="{sec}" class="card xp">' in SETTINGS_PAGE
    assert i18n.FR["set.ui.expert"] == "Avancé"


# ---------------------------------------------------------------- approval card: plain words, two buttons
def test_approval_card_has_two_buttons_and_a_discreet_checkbox():
    assert 't("card.rememberHere")' in CHAT_PAGE and 'keep.type="checkbox"' in CHAT_PAGE
    assert i18n.FR["card.rememberHere"] == "Ne plus me demander dans cette conversation"
    assert "#popups .card .ctop" in _hidden()
    assert "#log #popups{position:static" in SIMPLE_CSS and "margin:10px auto" in SIMPLE_CSS


def test_mcp_verbs_and_objects_from_tool_names():
    cases = {"write_file": ("write", "file", False), "read_text_file": ("read", "file", False),
             "list_directory": ("list", "folder", True), "create_issue": ("create", "issue", False),
             "search_repositories": ("search", "repo", True), "delete_branch": ("delete", "branch", False),
             "add_issue_comment": ("create", "comment", False), "move_file": ("move", "file", False),
             "createPullRequest": ("create", "pr", False), "Edit File": ("edit", "file", False),
             "send_email": ("send", "email", False), "frobnicate": ("", "", False)}
    for name, want in cases.items():
        assert mcp.action_keys(name) == want, name


def test_every_verb_and_object_is_translated():
    for v in set(mcp.VERBS.values()):
        for p in ("mcpv.", "mcpp."):
            assert i18n.EN.get(p + v) and i18n.FR.get(p + v), p + v
    for o in set(mcp.OBJECTS.values()):
        for k in ("mcpo." + o, "mcpo." + o + ".pl"):
            assert i18n.EN.get(k) and i18n.FR.get(k), k
    fr = " ".join(v for k, v in i18n.FR.items() if k.startswith(("mcpv.", "mcpo.", "mcpp.")))
    assert not re.search(r"\b(file|write|read|issue|repository)\b", fr)


def _sentence(lang, verb, obj, plural=False, service="Mes fichiers"):
    d = i18n.STRINGS[lang]
    o = d["mcpo." + obj + (".pl" if plural else "")] if obj else d["mcpo.some"]
    return d["human.mcpDo"].format(who=d["who.agent"], verb=d["mcpv." + verb], obj=o, service=service)


def test_french_approval_sentences():
    assert _sentence("fr", "write", "file") == "L'agent veut écrire un fichier dans Mes fichiers"
    assert _sentence("fr", "list", "folder", True) == "L'agent veut regarder les dossiers dans Mes fichiers"
    assert _sentence("fr", "create", "issue", service="GitHub") == "L'agent veut créer un ticket dans GitHub"
    assert _sentence("fr", "search", "") == "L'agent veut chercher quelque chose dans Mes fichiers"
    assert _sentence("en", "write", "file", service="My files") == "The agent wants to write a file in My files"
    assert i18n.FR["human.mcpUse"].format(who="L'agent", service="Mes fichiers") == "L'agent veut utiliser Mes fichiers"
    # the page builds the sentence from the keys, never from the server's English title
    assert 'kind+".mcpDo"' in APPROVAL_JS and 'kind+".mcpUse"' in APPROVAL_JS and "svc.action" not in APPROVAL_JS


def test_approval_carries_the_verb_and_object(tmp_path):
    server = {"id": "s1", "name": "Mes fichiers", "tools": [
        {"name": "write_file", "title": "Write File", "schema": {"type": "object"}},
        {"name": "frobnicate", "schema": {"type": "object"}}]}
    tools = mcp.make_tools(None, server)
    w, f = (t.name for t in tools)
    assert _service(w) == {"service": "Mes fichiers", "action": "Write File", "verb": "write", "obj": "file",
                           "plural": False}
    assert _service(f)["verb"] == "" and _service(f)["service"] == "Mes fichiers"
    assert _service("write_file") == {}
