"""v0.9.11: my own AI on my computer with Ollama (mock HTTP server, no real Ollama needed)."""
import socket
import urllib.error

import pytest

from agent import i18n, ollama
from agent.harness_settings import WELCOME_PAGE
from agent.llm import PROVIDERS, LLMError, OpenAICompatible, friendly
from agent.userconfig import PRESETS
from fake_ollama import FakeOllama
from test_settings_ui import app, post  # noqa: F401  (fixtures)


@pytest.fixture
def fo():
    f = FakeOllama()
    yield f
    f.close()


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_defaults_and_address_forms():
    assert PRESETS["ollama"]["base_url"] == "http://localhost:11434/v1" and PRESETS["ollama"]["key"] is False
    assert PRESETS["ollama"]["model"] == ollama.RECOMMENDED == "qwen2.5:7b" == PROVIDERS["ollama"]["model"]
    for a in ("", None, "localhost:11434", "http://localhost:11434/", "http://localhost:11434/v1", "http://localhost:11434/api"):
        assert ollama.root(a) == "http://localhost:11434", a
    assert ollama.chat_url("https://pc.tail1234.ts.net:11434/v1/") == "https://pc.tail1234.ts.net:11434/v1"


def test_check_lists_models_and_tool_support(fo):
    r = ollama.check(fo.address + "/v1")
    assert r["ok"] and r["code"] == "ok" and r["address"] == fo.address and r["base_url"] == fo.address + "/v1"
    tools = {m["name"]: m["tools"] for m in r["models"]}
    assert tools == {"qwen2.5:7b": True, "llama3.1:8b": True, "gemma:2b": False}
    assert r["has_recommended"] and r["recommended"] == "qwen2.5:7b"


def test_check_plain_codes(fo):
    fo.models.clear()
    assert ollama.check(fo.address)["code"] == "no_models"
    assert ollama.check(f"http://127.0.0.1:{_free_port()}", timeout=2)["code"] == "unreachable"
    assert ollama.check("http://exa mple")["code"] == "bad_url"
    assert ollama.check("ftp://x")["code"] == "bad_url"


def test_check_not_ollama(fake_http):
    assert ollama.check(fake_http)["code"] == "not_ollama"


@pytest.fixture
def fake_http():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>hello</html>")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_tool_support_from_old_ollama():
    assert ollama.tool_support({"capabilities": ["completion"]}) is False
    assert ollama.tool_support({"template": "{{ if .Tools }}…{{ end }}"}) is True
    assert ollama.tool_support({}) is None


def test_chat_goes_through_the_openai_endpoint_without_a_key(fo):
    llm = OpenAICompatible(fo.address + "/v1", "qwen2.5:7b", None, retries=0)
    tools = [{"type": "function", "function": {"name": "read_file", "description": "x", "parameters": {"type": "object"}}}]
    rep = llm.chat([{"role": "user", "content": "salut"}], tools)
    assert "qwen2.5:7b" in (rep.message.get("content") or "")
    assert fo.calls[-1]["tools"] and fo.auth[-1] == ""          # tools sent, no Authorization header


def test_a_model_without_tools_gets_a_plain_message(fo):
    llm = OpenAICompatible(fo.address + "/v1", "gemma:2b", None, retries=2)
    tools = [{"type": "function", "function": {"name": "read_file", "description": "x", "parameters": {"type": "object"}}}]
    with pytest.raises(LLMError) as ei:
        llm.chat([{"role": "user", "content": "salut"}], tools)
    assert ei.value.code == "no_tools" and len(fo.calls) == 1   # not retried
    msg = friendly(ei.value, "fr")
    assert "gemma:2b" in msg and "outils" in msg and "qwen2.5:7b" in msg and "vous" not in msg


def test_ollama_not_started_says_so():
    llm = OpenAICompatible(f"http://localhost:{_free_port()}/v1", "qwen2.5:7b", None, retries=0, timeout=2)
    e = LLMError("cannot reach http://localhost:11434/v1: refused", code="network", host="localhost")
    assert "Ollama" in friendly(e, "fr") and "Lance Ollama" in friendly(e, "fr")
    assert "Start Ollama" in friendly(e, "en")
    with pytest.raises(LLMError) as ei:
        llm.chat([{"role": "user", "content": "x"}], [])
    assert ei.value.code == "network"


def test_welcome_offers_two_simple_choices():
    assert 'simple ? ["gemini","groq","ollama"] : WPROVS' in WELCOME_PAGE
    assert 'id="olcheck"' in WELCOME_PAGE and 'data-i18n="ol.check"' in WELCOME_PAGE and 'id="olmodel"' in WELCOME_PAGE
    assert '"/app/ollama/check"' in WELCOME_PAGE and 'provider:"ollama"' in WELCOME_PAGE
    assert i18n.FR["wiz.choice.groq"] == "Clé Groq gratuite"
    assert i18n.FR["wiz.choice.ollama"] == "Mon IA sur mon ordinateur (Ollama)"
    assert i18n.FR["ol.check"] == "Vérifier"
    for k in ("no_models", "unreachable", "not_ollama", "bad_url"):
        assert "{address}" in i18n.EN["ol.code." + k] or k in ("no_models", "bad_url")
        assert i18n.FR["ol.code." + k] and "vous" not in i18n.FR["ol.code." + k]


def test_check_route_and_saved_ollama_hides_the_key_banner(app, fo):  # noqa: F811
    base, h, control = app()
    st, r = post(base, "/app/ollama/check", {"address": fo.address})
    assert st == 200 and r["code"] == "ok" and len(r["models"]) == 3
    assert control.effective_mode() == "demo"                  # nothing yet: the chat shows the key banner
    st, saved = post(base, "/app/providers", {"provider": "ollama", "name": "Ollama", "categories": ["text", "code"],
                                              "base_url": r["base_url"], "model": "qwen2.5:7b"})
    assert st == 201, saved
    st, _ = post(base, "/app/setup", {"demo": False, "done": True})
    assert st == 200
    assert control.effective_mode() == "ui" and not control.first_run()   # no banner, no wizard
    p = [x for x in control.providers_view() if x["provider"] == "ollama"][0]
    assert p["base_url"] == fo.address + "/v1" and p["model"] == "qwen2.5:7b"


def test_check_route_needs_csrf(app):  # noqa: F811
    from test_harness import call
    base, _, _ = app()
    st, _ = call(base, "POST", "/app/ollama/check", {"address": "http://127.0.0.1:1"})
    assert st == 403


def test_page_scripts_parse():
    """A typo in a page script breaks the whole page: parse them with node when it is installed."""
    import re
    import shutil
    import subprocess
    import tempfile
    from agent.harness import render_page
    from agent.harness_settings import SETTINGS_PAGE
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    for page in (WELCOME_PAGE, SETTINGS_PAGE):
        for js in re.findall(r"<script>(.*?)</script>", render_page(page, "fr").decode(), re.S):
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(js)
            r = subprocess.run([node, "--check", f.name], capture_output=True, text=True)
            assert r.returncode == 0, r.stderr[:500]
