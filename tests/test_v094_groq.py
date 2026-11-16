"""v0.9.4: a free Groq key must never loop on "limit reached, retrying in 30 s".

Root cause seen on a Mac: the embedded Python had no HTTPS certificate list, every call failed with
CERTIFICATE_VERIFY_FAILED, and that network error was handled like a rate limit (30 s pause, forever-ish).
Bodies below are real Groq answers (organisation id removed)."""
import json
import ssl
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent import i18n, llm, tlsca
from agent.keys import KeyEntry, KeyRouter
from agent.llm import LLMError, RoutedLLM, classify_http, friendly
from agent.loop import compact_messages

TOO_LARGE = ('{"error":{"message":"Request too large for model `openai/gpt-oss-20b` in organization `org_x` service '
             'tier `on_demand` on tokens per minute (TPM): Limit 8000, Requested 12122, please reduce your message '
             'size and try again.","type":"tokens","code":"rate_limit_exceeded"}}')
TPD = ('{"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_x` service tier '
       '`on_demand` on tokens per day (TPD): Limit 200000, Used 199800, Requested 2100. Please try again in '
       '7m12.48s.","type":"tokens","code":"rate_limit_exceeded"}}')
TPM = ('{"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_x` on tokens '
       'per minute (TPM): Limit 8000, Used 6000, Requested 3000. Please try again in 7.5s.","code":"rate_limit_exceeded"}}')
GONE = '{"error":{"message":"The model `llama3-70b-8192` has been decommissioned","code":"model_decommissioned"}}'
BADKEY = '{"error":{"message":"Invalid API Key","type":"invalid_request_error","code":"invalid_api_key"}}'


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("KEY_G", "gsk_" + "t" * 48 + "y99K")


CLOCK = [1_000_000.0]


@pytest.fixture
def pauses(monkeypatch):
    seen = []

    def pause(s):                       # a pause moves the router's clock forward instead of sleeping
        seen.append(s)
        CLOCK[0] += s
        return True
    monkeypatch.setattr(llm, "_pause", pause)
    return seen


class Groq(BaseHTTPRequestHandler):
    """Answers like Groq: `plan(body) -> (status, body, headers)`."""
    plan = None
    seen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        raw = self.rfile.read(int(self.headers["Content-Length"]))
        body = json.loads(raw)
        Groq.seen.append({"bytes": len(raw), "tools": len(body.get("tools") or []), "max_tokens": body.get("max_tokens")})
        status, data, headers = Groq.plan(body, raw)
        data = data.encode() if isinstance(data, str) else data
        self.send_response(status)
        for k, v in {"Content-Type": "application/json", "x-ratelimit-limit-tokens": "8000",
                     "x-ratelimit-remaining-tokens": "7000", "x-ratelimit-reset-tokens": "7.5s", **headers}.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


OK = json.dumps({"choices": [{"message": {"role": "assistant", "content": "Bonjour !"}}],
                 "usage": {"prompt_tokens": 1800, "completion_tokens": 20}})


@pytest.fixture
def groq(tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Groq)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    Groq.seen = []
    url = f"http://127.0.0.1:{srv.server_address[1]}/openai/v1"
    router = KeyRouter([KeyEntry("groq", ["text"], "KEY_G", provider="groq", base_url=url,
                                 models={"*": "openai/gpt-oss-20b"})], tmp_path / "usage.json",
                        clock=lambda: CLOCK[0])
    yield router
    srv.shutdown()
    srv.server_close()


def run_agent(make_agent, router, text="tu peux te connecter à mon google ?"):
    agent = make_agent(RoutedLLM(router))
    events = []
    agent.on_event = lambda kind, data: events.append((kind, data))
    return agent.run(text), events


# ------------------------------------------------------------------ the exact request works
def test_default_free_groq_request_works_and_fits_the_tpm(make_agent, groq, pauses):
    Groq.plan = lambda body, raw: (200, OK, {})
    res, _ = run_agent(make_agent, groq)
    assert res.stop_reason == "final" and res.answer == "Bonjour !" and not pauses
    # prompt + max_tokens must fit Groq's 8000 tokens per minute (Groq counts max_tokens in the request)
    assert Groq.seen[0]["max_tokens"] <= 8000 * 0.9 - Groq.seen[0]["bytes"] // 3 + 50
    assert groq.status()["keys"][0]["rate"]["source"] == "provider"      # counter from the real headers


# ------------------------------------------------------------------ certificates (the root cause)
def test_certificate_error_stops_at_once_with_a_clear_message(make_agent, groq, pauses, monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError(ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] certificate "
                                                                    "verify failed: unable to get local issuer"))
    monkeypatch.setattr("agent.netguard.open_url", boom)
    res, events = run_agent(make_agent, groq)
    assert res.stop_reason == "llm_error" and not pauses
    assert "certificat" in res.answer or "certificate" in res.answer
    assert not any(k == "keys" and d.get("action") == "wait" for k, d in events)


def test_ensure_ca_uses_the_bundled_list_when_the_system_has_none(monkeypatch, tmp_path):
    pem = tmp_path / "cacert.pem"
    pem.write_text("x" * 5000)
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(tlsca, "system_ok", lambda: False)
    monkeypatch.setattr(tlsca, "_certifi", lambda: str(pem))
    st = tlsca.ensure_ca(tmp_path)
    assert st == {"source": "bundled", "file": str(pem)}
    import os
    assert os.environ["SSL_CERT_FILE"] == str(pem)


def test_ensure_ca_leaves_a_working_system_alone(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.setattr(tlsca, "system_ok", lambda: True)
    assert tlsca.ensure_ca()["source"] == "system"
    import os
    assert "SSL_CERT_FILE" not in os.environ


def test_build_ships_certifi():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    spec = (root / "packaging" / "autonomous-agent.spec").read_text()
    assert 'collect_data_files("certifi")' in spec and '"certifi"' in spec
    assert '"bundled": true' in (root / "packaging" / "smoke.sh").read_text()
    for wf in ("ci.yml", "release.yml"):
        assert "certifi==" in (root / ".github" / "workflows" / wf).read_text()


# ------------------------------------------------------------------ network errors: never 30 s forever
def test_network_error_is_retried_briefly_then_explained(make_agent, groq, pauses, monkeypatch):
    def down(*a, **k):
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
    monkeypatch.setattr("agent.netguard.open_url", down)
    res, events = run_agent(make_agent, groq)
    assert res.stop_reason == "llm_error"
    assert "joindre" in res.answer or "cannot reach" in res.answer
    assert len(pauses) <= llm.NET_RETRIES and all(p <= llm.NET_COOLDOWN + 0.01 for p in pauses)
    waits = [d for k, d in events if k == "keys" and d.get("action") == "wait"]
    assert all(d.get("reason") == "network" for d in waits)


# ------------------------------------------------------------------ request too large (413)
def test_too_large_is_shortened_automatically(make_agent, groq, pauses):
    Groq.plan = lambda body, raw: (200, OK, {}) if len(body.get("tools") or []) <= 10 else (413, TOO_LARGE, {"retry-after": "31"})
    res, events = run_agent(make_agent, groq)
    assert res.stop_reason == "final" and res.answer == "Bonjour !" and not pauses
    assert any(d.get("action") == "shrink" for k, d in events if k == "keys")
    assert Groq.seen[-1]["tools"] <= 10 < Groq.seen[0]["tools"]


def test_too_large_stops_with_an_explanation_not_a_pause(make_agent, groq, pauses):
    Groq.plan = lambda body, raw: (413, TOO_LARGE, {"retry-after": "31"})
    res, events = run_agent(make_agent, groq)
    assert res.stop_reason == "llm_error" and not pauses
    assert "8000" in res.answer and ("trop longue" in res.answer or "too long" in res.answer)
    assert len(Groq.seen) <= 4


def test_compact_messages_never_starts_on_a_tool_answer():
    msgs = [{"role": "system", "content": "S" * 5000}, {"role": "user", "content": "q1"},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function",
                                                                    "function": {"name": "x", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "1", "content": "T" * 9000},
            {"role": "assistant", "content": "a"}, {"role": "user", "content": "q2"}]
    out = compact_messages(msgs, 600, keep=3, system_chars=1000)
    assert out[0]["role"] == "system" and len(out[0]["content"]) < 1100
    assert out[1]["role"] != "tool" and out[-1]["content"] == "q2"
    assert all(len(m.get("content") or "") < 700 for m in out[1:] if m["role"] == "tool")


# ------------------------------------------------------------------ daily limit, bad key, model gone
def test_daily_limit_stops_with_the_time_it_comes_back(make_agent, groq, pauses):
    Groq.plan = lambda body, raw: (429, TPD, {"retry-after": "433"})
    res, _ = run_agent(make_agent, groq)
    assert res.stop_reason == "llm_error" and not pauses
    assert ("Limite du jour" in res.answer or "Daily limit" in res.answer) and ":" in res.answer
    assert "gsk_" in res.answer and "tttttttt" not in res.answer             # masked key only


def test_invalid_key_is_said_plainly(make_agent, groq, pauses):
    Groq.plan = lambda body, raw: (401, BADKEY, {})
    res, _ = run_agent(make_agent, groq)
    assert res.stop_reason == "llm_error" and not pauses
    assert "Réglages" in res.answer or "Settings" in res.answer


def test_decommissioned_model_is_explained(make_agent, groq, pauses):
    Groq.plan = lambda body, raw: (400, GONE, {})
    res, _ = run_agent(make_agent, groq)
    assert res.stop_reason == "llm_error" and "gpt-oss-20b" in res.answer and not pauses


def test_classification_of_real_groq_errors():
    assert classify_http(413, TOO_LARGE) == "too_large"
    assert classify_http(429, TPD) == "daily_limit"
    assert classify_http(429, TPM) == "rate_limit"
    assert classify_http(429, TOO_LARGE.replace("Requested 12122", "Requested 9000")) == "too_large"
    assert classify_http(401, BADKEY) == "key_invalid"
    assert classify_http(400, GONE) == "model_unavailable"
    assert classify_http(503, "busy") == "server"


@pytest.mark.parametrize("lang", ["fr", "en"])
def test_friendly_messages_exist_in_both_languages(lang):
    for code in ("tls", "network", "too_large", "daily_limit", "key_invalid", "model_unavailable", "rate_limit"):
        msg = friendly(LLMError("x Limit 8000", code=code, retry_after=60, key_mask="gsk_…y99K",
                                host="api.groq.com", model="m"), lang)
        assert msg and "{" not in msg
    for k in ("kw.waitNet", "kw.shrink", "kw.net"):
        assert i18n.t(lang, k) != k
    if lang == "fr":
        assert "vous" not in " ".join(i18n.FR[k] for k in i18n.FR if k.startswith("err."))


def test_rate_bar_shows_network_and_shrink_messages():
    from agent.ratebar import RATE_JS as JS
    assert "kw.waitNet" in JS and "kw.shrink" in JS
