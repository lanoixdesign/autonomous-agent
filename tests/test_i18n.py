"""EN/FR user interface: dictionaries complete, pages served in both languages, no hardcoded UI text."""
import builtins
import json
import re
import subprocess
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pytest

from agent import i18n
from agent.cli import make_confirm
from agent.harness import TERMINAL, render_page
from agent.harness_chat import CHAT_PAGE
from agent.harness_page import PAGE
from agent.keys import LIMIT_MAP
from agent.llm import MockLLM
from agent.permissions import CATEGORIES

from test_harness import call, finished, server  # noqa: F401  (fixture)

REPO = Path(__file__).resolve().parent.parent
from agent.harness_connect import CONNECT_PAGE  # noqa: E402

from agent.harness_settings import SETTINGS_PAGE, WELCOME_PAGE  # noqa: E402

PAGES = {"chat": CHAT_PAGE, "dashboard": PAGE, "connect": CONNECT_PAGE, "settings": SETTINGS_PAGE,
         "welcome": WELCOME_PAGE}


def test_same_keys_and_placeholders_in_both_languages():
    assert set(i18n.EN) == set(i18n.FR)
    for k in i18n.EN:
        assert i18n.EN[k].strip() and i18n.FR[k].strip(), k
        ph = lambda s: sorted(set(i18n.PLACEHOLDER_RE.findall(s)))
        assert ph(i18n.EN[k]) == ph(i18n.FR[k]), k
    assert set(i18n.ui_strings()) == {"en", "fr"}
    assert not any(k.startswith(("cli.", "export.")) for k in i18n.ui_strings()["fr"])


def test_domain_values_all_have_labels():
    for c in CATEGORIES:
        assert f"cat.{c}" in i18n.EN
    for s in TERMINAL + ("queued", "running", "cancelling", "pending", "approved", "denied", "expired",
                         "auto-approved", "final", "max_steps", "max_tokens", "max_tool_calls"):
        assert f"status.{s}" in i18n.EN, s
    for f in list(LIMIT_MAP) + ["requests_per_minute"]:
        assert f"limit.{f}" in i18n.EN, f
    assert i18n.FR["cat.send"] == "envoi" and i18n.FR["cat.spend"] == "dépense"


@pytest.mark.parametrize("name", PAGES)
def test_every_key_used_by_the_pages_exists(name):
    page = PAGES[name]
    used = set(re.findall(r'data-i18n(?:-title|-placeholder|-doc)?="([^"]+)"', page))
    used |= set(re.findall(r'\bt\("([^"]+)"', page))
    used |= {m for m in re.findall(r'\bt\(\s*[^()"]*\?\s*"([^"]+)"\s*:\s*"([^"]+)"', page) for m in m}
    assert len(used) > 25
    missing = sorted(k for k in used if k not in i18n.EN)
    assert not missing, missing
    prefixes = set(re.findall(r'\btr\("([a-z.]+)"', page))
    assert prefixes and all(any(k.startswith(p + ".") for k in i18n.EN) for p in prefixes)


class TextNodes(HTMLParser):
    def __init__(self):
        super().__init__()
        self.texts, self.attrs, self.skip = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "title"):
            self.skip += 1
        a = dict(attrs)
        for at in ("title", "placeholder"):
            if at in a:
                self.attrs.append((tag, at, a))

    def handle_endtag(self, tag):
        if tag in ("script", "style", "title"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.texts.append(data.strip())


@pytest.mark.parametrize("name", PAGES)
def test_no_hardcoded_ui_text(name):
    page = PAGES[name]
    p = TextNodes()
    p.feed(page)
    allowed = {"autonomous-agent", "EN", "FR", "⇩ MD", "⇩ JSON", "📎", "—", "☰"}
    assert set(p.texts) <= allowed, set(p.texts) - allowed
    assert not p.attrs                   # titles/placeholders all come from data-i18n-*
    js = page[page.index("<script>"):]
    # no English sentence handed straight to the DOM from the script
    assert not re.findall(r'el\("[^"]*",\s*"[^"]*",\s*"[A-Za-z][^"]*"\)', js)
    assert not re.findall(r'textContent\s*=\s*"[A-Za-z]', js)
    assert not re.findall(r'confirm\("[A-Za-z]', js)


@pytest.mark.parametrize("path", ["/", "/chat", "/dashboard", "/connect", "/welcome"])
def test_pages_served_in_both_languages_with_switch(server, path):  # noqa: F811
    base, _ = server(lambda: MockLLM())
    for lang, word in (("fr", "Nouvelle"), ("en", "New")):
        html = urllib.request.urlopen(f"{base}{path}?lang={lang}").read().decode()
        assert f'<html lang="{lang}">' in html
        data = json.loads(re.search(r"const I18N = (\{.*?\});\n", html).group(1))
        assert data["fr"]["card.approve"] == "Approuver" and data["en"]["card.approve"] == "Approve"
        assert word in json.dumps(data, ensure_ascii=False)
        assert 'id="lang"' in html and 'data-lang="en"' in html and 'data-lang="fr"' in html
        # default from the browser, remembered choice, ?lang= override
        assert 'startsWith("fr")' in html and "localStorage" in html and 'get("lang")' in html
    plain = urllib.request.urlopen(f"{base}{path}").read().decode()
    assert '<html lang="en">' in plain and "/*I18N_DATA*/" not in plain
    # junk is normalised, never echoed
    assert '<html lang="en">' in urllib.request.urlopen(f"{base}{path}?lang=%22%3E%3Cx").read().decode()


def test_render_page_escapes_script_end():
    assert b"</script>" not in render_page(CHAT_PAGE).split(b"<script>", 1)[1][:-len(b"</script></body></html>\n")]


def test_markdown_export_in_french(server, ws):  # noqa: F811
    base, _ = server(lambda: MockLLM())
    tid = call(base, "POST", "/tasks", {"task": "what is here?"})[1]["id"]
    finished(base, tid)
    fr = urllib.request.urlopen(f"{base}/tasks/{tid}/export?format=md&lang=fr").read().decode()
    assert "## Consommation" in fr and "## Piste d'audit" in fr and "### Vous — tour 1" in fr
    assert "**Statut:** terminé" in fr and "| `list_files` (lecture) | autorisé |" in fr
    en = urllib.request.urlopen(f"{base}/tasks/{tid}/export?format=md").read().decode()
    assert "## Usage" in en and "## Audit trail" in en and "| `list_files` (read) | allowed |" in en


def test_cli_lang_flag_and_env(tmp_path):
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPO), "HOME": str(tmp_path)}
    run = lambda *a, **e: subprocess.run([sys.executable, "-m", "agent", "keys", "-w", str(tmp_path), *a],
                                         capture_output=True, text=True, env={**env, **e}, cwd=tmp_path)
    assert "single-key .env mode" in run().stderr
    assert "mode clé unique" in run("--lang", "fr").stderr
    assert "mode clé unique" in run(AGENT_LANG="fr_FR.UTF-8").stderr
    assert "single-key" in run("--lang", "en", AGENT_LANG="fr").stderr


def test_terminal_prompt_in_french(monkeypatch, capsys):
    asked = []
    monkeypatch.setattr(builtins, "input", lambda prompt: asked.append(prompt) or "t")
    confirm = make_confirm(True, "fr")
    assert confirm("write_file", "write", {"path": "x"}, "r") is True
    assert "[o]ui / [n]on / [t]oujours" in asked[0]
    assert confirm("write_file", "write", {"path": "y"}, "r") is True and len(asked) == 1   # remembered
    assert make_confirm(False, "fr")("shell", "execute", {}, "r") is False
    assert "pas de terminal" in capsys.readouterr().err
