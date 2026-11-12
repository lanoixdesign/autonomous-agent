import json
import os
import subprocess
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent.audit import AuditLog
from agent.keys import KeyEntry, KeyRouter, KeysExhausted, mask, parse
from agent.llm import LLMError, LLMReply, MockLLM, RoutedLLM
from agent.loop import Budget
from agent.media import ImageGenerator, ProviderError

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    monkeypatch.setenv("KEY_A", "sk-aaaaaaaaaaaaaaaaaaaaAAAA")
    monkeypatch.setenv("KEY_B", "sk-bbbbbbbbbbbbbbbbbbbbBBBB")
    monkeypatch.setenv("KEY_IMG", "sk-iiiiiiiiiiiiiiiiiiiiIIII")
    monkeypatch.delenv("KEY_MISSING", raising=False)


def entries(**limits_a):
    return [
        KeyEntry("a", ["text", "code"], "KEY_A", base_url="http://a", models={"*": "m-a"}, priority=1, limits=limits_a),
        KeyEntry("b", ["text"], "KEY_B", base_url="http://b", models={"text": "m-b"}, priority=2),
        KeyEntry("img", ["image"], "KEY_IMG", base_url="http://i", models={"image": "gpt-image"}, priority=1,
                 limits={"images_per_day": 3}),
    ]


def audit_of(tmp_path):
    p = tmp_path / "audit.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_category_routing_and_priority(tmp_path):
    r = KeyRouter(entries(), tmp_path / "usage.json")
    lease = r.acquire("text")
    assert (lease.name, lease.model, lease.base_url, lease.api_key) == ("a", "m-a", "http://a", "sk-aaaaaaaaaaaaaaaaaaaaAAAA")
    lease.commit(10, 5)
    assert r.acquire("code").name == "a"
    img = r.acquire("image", images=1)
    assert (img.name, img.model) == ("img", "gpt-image")
    with pytest.raises(KeysExhausted, match="audio_tts"):
        r.acquire("audio_tts")


def test_failover_on_limit_and_audit_once(tmp_path):
    r = KeyRouter(entries(requests_per_day=2), tmp_path / "usage.json", AuditLog(tmp_path / "audit.jsonl"))
    assert [r.acquire("text").name for _ in range(4)] == ["a", "a", "b", "b"]
    hits = [l for l in audit_of(tmp_path) if l.get("event") == "key_limit"]
    assert len(hits) == 1 and hits[0]["entry"] == "a" and "requests_per_day" in hits[0]["reason"]


def test_token_and_cost_limits_are_never_exceeded(tmp_path):
    e = [KeyEntry("t", ["text"], "KEY_A", base_url="http://a", models={"*": "m"},
                  limits={"tokens_per_day": 1000, "cost_per_day": 1.0},
                  pricing={"input_per_1m": 100.0, "output_per_1m": 1000.0})]
    r = KeyRouter(e, tmp_path / "usage.json")
    lease = r.acquire("text", prompt_tokens=600)
    # completion capped by tokens (1000-600=400) and by cost ((1.0-0.06)/1000 per token -> 940): 400
    assert lease.max_completion_tokens == 400
    with pytest.raises(KeysExhausted):          # everything left is reserved by the in-flight call
        r.acquire("text", prompt_tokens=10)
    lease.commit(600, 300)                      # real usage: 900 tokens, 0.36 cost
    lease2 = r.acquire("text", prompt_tokens=50)
    assert lease2.max_completion_tokens == 50    # 1000 - 900 - 50
    lease2.commit(50, 50)
    with pytest.raises(KeysExhausted, match="token or cost limit"):
        r.acquire("text", prompt_tokens=1)
    u = json.loads((tmp_path / "usage.json").read_text())["keys"]["t"]
    assert u["tokens_day"] == 1000 and u["cost_day"] <= 1.0


def test_image_limit_and_media_stub(tmp_path):
    r = KeyRouter(entries(), tmp_path / "usage.json")
    gen = ImageGenerator(r)
    with pytest.raises(NotImplementedError):
        gen.generate("cat")
    seen = []
    out = gen.generate("cat", n=2, call=lambda lease, prompt, size, n: seen.append((lease.model, lease.api_key)) or "png")
    assert out == "png" and seen == [("gpt-image", "sk-iiiiiiiiiiiiiiiiiiiiIIII")]
    with pytest.raises(KeysExhausted, match="images_per_day"):
        gen.generate("dog", n=2, call=lambda *a: "png")     # 2 + 2 > 3
    gen.generate("dog", n=1, call=lambda *a: "png")
    assert {k["name"]: k for k in r.status()["keys"]}["img"]["limits"]["images_per_day"]["remaining"] == 0


class FakeClient:
    """Fake OpenAI-compatible client: behaviour chosen per key."""
    def __init__(self, plan, calls):
        self.plan, self.calls = plan, calls

    def __call__(self, base_url, model, key, max_tokens):
        plan, calls = self.plan, self.calls

        class C:
            def chat(self, messages, tools=None):
                calls.append((key, model, max_tokens))
                what = plan[key]
                if isinstance(what, Exception):
                    raise what
                return LLMReply({"role": "assistant", "content": what}, 100, 20)
        return C()


def test_routed_llm_fails_over_on_429_and_cools_down(tmp_path):
    r = KeyRouter(entries(), tmp_path / "usage.json", AuditLog(tmp_path / "audit.jsonl"))
    calls = []
    plan = {"sk-aaaaaaaaaaaaaaaaaaaaAAAA": LLMError("HTTP 429", status=429, retry_after=120),
            "sk-bbbbbbbbbbbbbbbbbbbbBBBB": "from b"}
    llm = RoutedLLM(r, "text", client_factory=FakeClient(plan, calls))
    assert llm.chat([{"role": "user", "content": "hi"}]).message["content"] == "from b"
    assert [c[0][-4:] for c in calls] == ["AAAA", "BBBB"]
    st = {k["name"]: k for k in r.status()["keys"]}
    assert 115 <= st["a"]["cooldown_s"] <= 120
    # while a cools down, b is used directly
    calls.clear()
    llm.chat([{"role": "user", "content": "again"}])
    assert [c[0][-4:] for c in calls] == ["BBBB"]
    errs = [l for l in audit_of(tmp_path) if l.get("event") == "key_error"]
    assert errs[0]["entry"] == "a" and errs[0]["status"] == 429


def test_routed_llm_bad_request_does_not_burn_other_keys(tmp_path):
    r = KeyRouter(entries(), tmp_path / "usage.json")
    calls = []
    llm = RoutedLLM(r, "text", client_factory=FakeClient({"sk-aaaaaaaaaaaaaaaaaaaaAAAA": LLMError("HTTP 400", status=400)}, calls))
    with pytest.raises(LLMError, match="400"):
        llm.chat([{"role": "user", "content": "x"}])
    assert len(calls) == 1


def test_hard_stop_when_every_key_is_exhausted(tmp_path, make_agent):
    e = [KeyEntry("a", ["text"], "KEY_A", base_url="http://a", models={"*": "m"}, limits={"requests_per_day": 1}),
         KeyEntry("b", ["text"], "KEY_B", base_url="http://b", models={"*": "m"}, limits={"requests_per_day": 1}),
         KeyEntry("c", ["text"], "KEY_MISSING", base_url="http://c", models={"*": "m"})]
    r = KeyRouter(e, tmp_path / "usage.json")
    calls = []
    plan = {"sk-aaaaaaaaaaaaaaaaaaaaAAAA": LLMError("HTTP 503", status=503), "sk-bbbbbbbbbbbbbbbbbbbbBBBB": "ok"}
    llm = RoutedLLM(r, "text", client_factory=FakeClient(plan, calls))
    assert llm.chat([{"role": "user", "content": "x"}]).message["content"] == "ok"   # a: 503 -> b
    with pytest.raises(LLMError) as ei:
        llm.chat([{"role": "user", "content": "x"}])
    msg = str(ei.value)
    assert "no API key can serve category 'text'" in msg and "KEY_MISSING is not set" in msg
    assert "requests_per_day" in msg and len(calls) == 2
    res = make_agent(llm, budget=Budget()).run("hello")                  # the agent stops cleanly
    assert res.stop_reason == "llm_error" and "no API key" in res.answer


def test_usage_is_persisted_and_rolls_over(tmp_path):
    now = [1_800_000_000.0]
    r1 = KeyRouter(entries(requests_per_day=2, tokens_per_month=10_000), tmp_path / "usage.json", clock=lambda: now[0])
    r1.acquire("text").commit(100, 50)
    r1.acquire("text").commit(100, 50)
    r2 = KeyRouter(entries(requests_per_day=2, tokens_per_month=10_000), tmp_path / "usage.json", clock=lambda: now[0])
    assert r2.acquire("text").name == "b"                    # a's 2 requests survived the "restart"
    lim = {k["name"]: k for k in r2.status()["keys"]}["a"]["limits"]
    assert lim["requests_per_day"]["used"] == 2 and lim["tokens_per_month"]["used"] == 300
    now[0] += 86400                                          # next day: daily counters reset
    assert r2.acquire("text").name == "a"
    assert {k["name"]: k for k in r2.status()["keys"]}["a"]["limits"]["tokens_per_month"]["used"] == 300


def test_thread_safe_no_overshoot(tmp_path):
    r = KeyRouter([KeyEntry("a", ["text"], "KEY_A", base_url="http://a", models={"*": "m"},
                            limits={"requests_per_day": 37, "tokens_per_day": 10 ** 9})], tmp_path / "usage.json")
    ok, refused = [], []
    lock = threading.Lock()

    def worker():
        for _ in range(10):
            try:
                lease = r.acquire("text", prompt_tokens=5, max_completion_tokens=5)
            except KeysExhausted:
                with lock:
                    refused.append(1)
                continue
            lease.commit(5, 5)
            with lock:
                ok.append(1)
    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 37 and len(refused) == 120 - 37
    u = json.loads((tmp_path / "usage.json").read_text())["keys"]["a"]
    assert u["requests_day"] == 37 and u["tokens_day"] == 370


def test_config_validation_and_masking():
    with pytest.raises(ValueError, match="key_env"):
        parse({"keys": [{"name": "x", "api_key": "sk-123"}]})
    with pytest.raises(ValueError, match="unknown limit"):
        parse({"keys": [{"name": "x", "limits": {"requests_per_week": 1}}]})
    with pytest.raises(ValueError, match="pricing"):
        parse({"keys": [{"name": "x", "limits": {"cost_per_day": 1}}]})
    e, cur = parse({"currency": "EUR", "keys": [{"name": "g", "provider": "groq", "key_env": "KEY_A", "model": "m",
                                                  "categories": "code"}]})
    assert e[0].base_url == "https://api.groq.com/openai/v1" and e[0].categories == ["code"] and cur == "EUR"
    assert mask("sk-aaaaaaaaaaaaaaaaaaaaAAAA") == "sk-a…AAAA" and mask("short") == "****" and mask(None) == "(not set)"


def test_masked_keys_in_status_api_and_ui(tmp_path):
    from agent.harness import Harness, make_server
    r = KeyRouter(entries(requests_per_day=5), tmp_path / "usage.json")
    r.acquire("text").commit(1, 1)
    h = Harness(lambda *a: None, tmp_path / "a.jsonl", key_router=r)
    srv = make_server(h, "127.0.0.1", 0, None, warn=lambda m: None)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        raw = urllib.request.urlopen(base + "/keys").read().decode()
        st = json.loads(raw)
        assert "aaaaaaaaaaaaaaaaaaaa" not in raw and "bbbbbbbbbbbbbbbbbbbb" not in raw
        a = {k["name"]: k for k in st["keys"]}["a"]
        assert a["key"] == "sk-a…AAAA" and a["key_env"] == "KEY_A"
        assert a["limits"]["requests_per_day"] == {"limit": 5.0, "used": 1, "remaining": 4.0}
        assert st["categories"]["text"] == ["a", "b"] and st["mode"] == "router"
        chat = urllib.request.urlopen(base + "/").read().decode()
        dash = urllib.request.urlopen(base + "/dashboard").read().decode()
        assert 'id="quota"' in chat and "API keys" in chat and 'id="keys"' in dash
    finally:
        srv.shutdown()
        srv.server_close()
    h2 = Harness(lambda *a: None, tmp_path / "a.jsonl")      # .env mode: endpoint still answers
    assert h2.key_router is None


# --------------------------------------------------------------- end to end with a fake provider

class FakeProvider(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        key = self.headers.get("Authorization", "")
        FakeProvider.seen.append((key[-4:], body.get("max_tokens"), body["model"]))
        if key.endswith("AAAA"):
            data = b'{"error": "rate limited"}'
            self.send_response(429)
            self.send_header("Retry-After", "30")
        else:
            data = json.dumps({"choices": [{"message": {"role": "assistant", "content": "hello from B"}}],
                               "usage": {"prompt_tokens": 12, "completion_tokens": 3}}).encode()
            self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_cli_end_to_end_with_providers_file(tmp_path):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeProvider)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    (tmp_path / "providers.yaml").write_text(f"""
keys:
  - name: first
    base_url: {url}
    key_env: KEY_A
    model: model-a
    categories: [text]
    priority: 1
    limits:
      tokens_per_day: 5000
  - name: second
    base_url: {url}
    key_env: KEY_B
    model: model-b
    categories: [text]
    priority: 2
""")
    env = {k: v for k, v in os.environ.items() if k != "AGENT_PROVIDER"}
    env["PYTHONPATH"] = str(REPO)
    try:
        r = subprocess.run([sys.executable, "-m", "agent", "run", "hi", "-w", str(tmp_path), "--offline", "-q"],
                           cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "hello from B"
        assert [s[0] for s in FakeProvider.seen] == ["AAAA", "BBBB"]
        assert FakeProvider.seen[0][1] <= 5000 and FakeProvider.seen[1][2] == "model-b"
        k = subprocess.run([sys.executable, "-m", "agent", "keys", "-w", str(tmp_path)], cwd=tmp_path, env=env,
                           capture_output=True, text=True, timeout=60)
        assert k.returncode == 0 and "sk-a…AAAA" in k.stdout and "aaaaaaaaaaaaaaaaaaaa" not in k.stdout
        assert "cooldown" in k.stdout and "tokens_per_day" in k.stdout
        usage = json.loads((tmp_path / ".agent" / "usage.json").read_text())["keys"]
        assert usage["second"]["tokens_day"] == 15 and usage["first"]["requests_day"] == 1
        assert usage["first"]["tokens_day"] == 0          # a 429 is not charged in tokens
    finally:
        srv.shutdown()
        srv.server_close()
