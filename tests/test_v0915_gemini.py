"""v0.9.15: Gemini (Google AI Studio) provider, image understanding, no free image generation."""
import io
import json
import struct
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest

from agent import __version__, i18n, llm, uploads, userconfig
from agent.harness_settings import WELCOME_PAGE
from agent.llm import LLMError, OpenAICompatible, classify_http, friendly, make_llm
from agent.userconfig import PRESETS, UserConfig, detect_provider


def _png(w=8, h=8):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


class FakeGemini(ThreadingHTTPServer):
    def __init__(self, port=0, model="gemini-3.8-flash"):
        this = self
        this.calls, this.status, this.body, this.auth = [], 200, None, None

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                this.auth = self.headers.get("Authorization")
                this.calls.append((self.path, json.loads(raw or b"{}")))
                if this.status != 200:
                    self.send_response(this.status)
                    self.send_header("Content-Type", "application/json")
                    if this.status == 429:
                        self.send_header("Retry-After", "2")
                    self.end_headers()
                    self.wfile.write(this.body or b'{"error":{"message":"RESOURCE_EXHAUSTED: rate limit"}}')
                    return
                data = json.loads(raw or b"{}")
                nimg = 0
                for m in data.get("messages") or []:
                    c = m.get("content")
                    if isinstance(c, list):
                        nimg += sum(1 for p in c if isinstance(p, dict) and p.get("type") == "image_url")
                msg = {"role": "assistant", "content": f"ok images={nimg} model={data.get('model')}"}
                if data.get("tools"):
                    msg["content"] = "I can use tools."
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"choices": [{"message": msg}],
                                             "usage": {"prompt_tokens": 10, "completion_tokens": 4}}).encode())
        super().__init__(("127.0.0.1", port), H)
        self.server_port = self.server_address[1]


@pytest.fixture
def gem():
    s = FakeGemini()
    Thread(target=s.serve_forever, daemon=True).start()
    yield s
    s.shutdown()
    s.server_close()


def test_preset_and_version():
    assert PRESETS["gemini"]["model"] == "gemini-3.8-flash" == llm.PROVIDERS["gemini"]["model"]
    assert PRESETS["gemini"]["key"] is True and PRESETS["gemini"]["prefix"] == "AIza"
    assert "v1beta/openai" in PRESETS["gemini"]["base_url"]
    assert detect_provider("AIzaSyDummyKeyForTestsOnly12") == "gemini"
    assert userconfig.AppControl.key_class("gemini", "gemini-3.8-flash") == (2, True)
    assert __version__ == "0.9.15"


def test_chat_and_tools_and_key_not_logged(gem, capsys):
    key = "AIzaSySECRETKEYNEVERLOG"
    client = OpenAICompatible(f"http://127.0.0.1:{gem.server_port}", "gemini-3.8-flash", key, retries=0)
    rep = client.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "x", "parameters": {}}}])
    assert "I can use tools" in (rep.message.get("content") or "")
    assert gem.auth == f"Bearer {key}"
    assert key not in capsys.readouterr().out + capsys.readouterr().err
    assert key not in repr(client)


def test_image_parts_sent_to_the_model(gem, tmp_path):
    png = _png()
    # save() needs a workspace; build the saved rec like uploads.save would
    rec = {"name": "pic.png", "path": "uploads/t/pic.png", "bytes": len(png), "sha256": "x", "text": False,
           "_image_mime": "image/png", "_image_b64": __import__("base64").b64encode(png).decode()}
    content = uploads.llm_content("what is this?", [rec])
    assert isinstance(content, list) and content[0]["type"] == "text"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "shown to the model" in uploads.describe("what is this?", [rec])
    client = OpenAICompatible(f"http://127.0.0.1:{gem.server_port}", "gemini-3.8-flash", "AIzaxx", retries=0)
    assert "images=1" in (client.chat([{"role": "user", "content": content}]).message["content"])
    pub = uploads.public([rec])
    assert "_image_b64" not in pub[0]


def test_png_magic_and_plain_text():
    assert uploads.image_mime(_png()) == "image/png"
    assert uploads.image_mime(b"not an image") is None
    assert "hello" in uploads.plain_text([{"type": "text", "text": "hello"}, {"type": "image_url", "image_url": {}}])


def test_rate_limit_is_classified_and_explained():
    assert classify_http(429, "RESOURCE_EXHAUSTED: rate limit") == "rate_limit"
    e = LLMError("too many requests", status=429, code="rate_limit")
    fr = friendly(e, "fr")
    assert "réessaie" in fr.lower() or "limite" in fr.lower()
    assert "AIza" not in fr


def test_make_llm_uses_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaTESTONLY")
    monkeypatch.delenv("AGENT_BASE_URL", raising=False)
    monkeypatch.delenv("AGENT_MODEL", raising=False)
    monkeypatch.delenv("AGENT_API_KEY", raising=False)
    c = make_llm("gemini")
    assert c.model == "gemini-3.8-flash" and "generativelanguage.googleapis.com" in c.base_url


def test_welcome_has_three_simple_choices_and_no_image_generation():
    assert 'simple ? ["gemini","groq","ollama"]' in WELCOME_PAGE
    assert "gem.useAll" in WELCOME_PAGE and "gem.imagesNote" in WELCOME_PAGE
    assert "create_image" not in WELCOME_PAGE
    for k in ("wiz.choice.gemini", "gem.guide", "gem.g.1", "gem.useAll", "gem.imagesNote"):
        assert i18n.EN[k] and i18n.FR[k] and i18n.EN[k] != i18n.FR[k]


def test_saving_gemini_uses_image_category(tmp_path, monkeypatch):
    from agent.userconfig import AppControl, SecretStore
    cfg = UserConfig(tmp_path)
    c = AppControl(cfg, SecretStore(tmp_path / "secrets.json", use_keyring=False), home=str(tmp_path))
    c.save_provider({"provider": "gemini", "name": "Gemini", "categories": ["text", "code", "image"],
                    "key": "AIzaSyDummyKeyForTestsOnly99"})
    p = c.providers_view()[0]
    assert p["provider"] == "gemini" and set(p["categories"]) >= {"text", "code", "image"}
    assert p["model"] == "gemini-3.8-flash"
    sec = (tmp_path / "secrets.json").read_text()
    assert "AIzaSyDummyKeyForTestsOnly99" in sec  # stored, not printed
    assert c.secrets.get(p["id"]) == "AIzaSyDummyKeyForTestsOnly99"
