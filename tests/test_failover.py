"""v0.8.1: automatic switch to a backup key (429 / quota / timeout / 5xx), pauses when every key rests
(never a failed task for a short cooldown), the fatal "every key refused" path, swarm helpers, and the
"tokens left per minute" counter (provider headers, local estimate, /keys/rate, pages)."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent.keys import KeyEntry, KeyRouter, mask, parse_duration, parse_ratelimit
from agent.llm import CALLER, LLMError, LLMReply, OpenAICompatible, RoutedLLM
from agent.loop import Budget
from agent.permissions import Permissions
from agent.swarm import SwarmConfig

from test_harness import call, finished
from test_harness_plus import make  # noqa: F401  (fixture)

S = {n: f"gsk_{n}_" + "z" * 20 + n.upper() + "9" for n in ("a", "b", "c")}
BIG = Budget(max_steps=50, max_tool_calls=50, max_tokens=10 ** 7)


def key(name, tasks=(), prio=10, cats=("text",), **kw):
    return KeyEntry(name, list(cats), base_url=kw.pop("base_url", f"http://{name}"), models={"*": "m-" + name},
                    priority=prio, secret_fn=lambda n=name: S.get(n) or f"gsk_{n}_" + "w" * 22, source="ui", tasks=list(tasks), **kw)


class Plan:
    """Fake client factory: per key, a list of outcomes consumed in order (last one repeats).
    An outcome is a string (answer), an int (HTTP status), None (timeout) or a dict (LLMError kwargs)."""

    def __init__(self, plan, answer=None):
        self.plan, self.calls, self.lock, self.answer = {k: list(v) for k, v in plan.items()}, [], threading.Lock(), answer

    def __call__(self, base_url, model, secret, max_tokens):
        outer = self

        class C:
            def chat(self, messages, tools=None):
                with outer.lock:
                    outer.calls.append((secret, (CALLER.get() or {}).get("label")))
                    seq = outer.plan.get(secret) or ["ok"]
                    what = seq.pop(0) if len(seq) > 1 else seq[0]
                if what is None:
                    raise LLMError("cannot reach: timed out")
                if isinstance(what, int):
                    raise LLMError(f"HTTP {what}", status=what)
                if isinstance(what, dict):
                    raise LLMError("HTTP 429 rate limit", **what)
                if outer.answer:
                    return outer.answer(messages, secret)
                return LLMReply({"role": "assistant", "content": what}, 10, 5)
        return C()


def run_chat(llm, label="root", task="general", events=None, cancel=None):
    ev = events if events is not None else []
    tok = CALLER.set({"holder": "t:" + label, "task": task, "label": label, "cancel": cancel,
                      "notify": lambda k, d: ev.append((k, d))})
    try:
        return llm.chat([{"role": "user", "content": "hi"}])
    finally:
        CALLER.reset(tok)


# ------------------------------------------------------------------ failover
@pytest.mark.parametrize("bad", [429, {"status": 429, "retry_after": 20}, 503, None, 408])
def test_switches_at_once_to_the_backup_key(tmp_path, bad):
    r = KeyRouter([key("a", prio=1), key("b", prio=2)], tmp_path / "u.json")
    plan = Plan({S["a"]: [bad], S["b"]: ["from b"]})
    ev = []
    t0 = time.time()
    reply = run_chat(RoutedLLM(r, "text", client_factory=plan), events=ev)
    assert reply.message["content"] == "from b" and reply.key == "b" and time.time() - t0 < 1
    assert [c[0] for c in plan.calls] == [S["a"], S["b"]]
    sw = [d for k, d in ev if k == "switch"][0]
    assert sw["key_mask"] == mask(S["a"]) and sw["to_mask"] == mask(S["b"]) and sw["backup_kind"] == "same"
    assert not any(s in json.dumps(ev) for s in S.values())          # masked keys only
    assert {k["name"]: k for k in r.status()["keys"]}["a"]["cooldown_s"] > 0


def test_backup_tagged_for_another_task_then_another_category(tmp_path):
    # a: research key (rate limited) -> b: writing-only key (another task type) is still used
    r = KeyRouter([key("a", ["research"], prio=1), key("b", ["writing"], prio=2)], tmp_path / "u.json")
    plan = Plan({S["a"]: [429], S["b"]: ["b"]})
    ev = []
    assert run_chat(RoutedLLM(r, "text", client_factory=plan), "root.1", "research", ev).key == "b"
    assert [d for k, d in ev if k == "switch"][0]["backup_kind"] == "other_task"
    # a: text key (rate limited) -> c: a key saved for "code" only, as a last resort
    r2 = KeyRouter([key("a", prio=1), key("c", prio=2, cats=("code",))], tmp_path / "u2.json")
    plan2 = Plan({S["a"]: [429], S["c"]: ["c"]})
    ev2 = []
    reply = run_chat(RoutedLLM(r2, "text", client_factory=plan2), events=ev2)
    assert reply.key == "c" and [d for k, d in ev2 if k == "switch"][0]["backup_kind"] == "other_category"
    # while a is fine, the code-only key is never used for text
    r3 = KeyRouter([key("a", prio=1), key("c", prio=2, cats=("code",))], tmp_path / "u3.json")
    assert run_chat(RoutedLLM(r3, "text", client_factory=Plan({}))).key == "a"


def test_waits_when_every_key_is_paused_then_resumes(tmp_path):
    r = KeyRouter([key("a")], tmp_path / "u.json")                 # ONE key, like a free Groq key
    plan = Plan({S["a"]: [{"status": 429, "retry_after": 0.6}, "after the pause"]})
    ev = []
    t0 = time.time()
    reply = run_chat(RoutedLLM(r, "text", client_factory=plan), events=ev)
    assert reply.message["content"] == "after the pause" and 0.5 <= time.time() - t0 < 5
    kinds = [k for k, _ in ev]
    assert "wait" in kinds and kinds[-1] == "resume"
    w = [d for k, d in ev if k == "wait"][0]
    assert 0.5 <= w["seconds"] <= 0.6 and w["key_mask"] == mask(S["a"]) and w["status"] == 429


def test_waits_are_capped_and_counted(tmp_path):
    r = KeyRouter([key("a"), key("b")], tmp_path / "u.json")
    plan = Plan({S["a"]: [{"status": 429, "retry_after": 0.5}], S["b"]: [{"status": 429, "retry_after": 0.5}]})
    llm = RoutedLLM(r, "text", client_factory=plan, max_waits=2)
    ev = []
    with pytest.raises(LLMError) as ei:
        run_chat(llm, events=ev)
    assert ei.value.code == "keys_exhausted" and [k for k, _ in ev].count("wait") == 2 and ev[-1][0] == "exhausted"


def test_long_cooldown_is_not_waited_for(tmp_path):
    r = KeyRouter([key("a")], tmp_path / "u.json")
    plan = Plan({S["a"]: [{"status": 429, "retry_after": 3600}]})   # e.g. a daily quota
    t0 = time.time()
    with pytest.raises(LLMError, match="cooling down"):
        run_chat(RoutedLLM(r, "text", client_factory=plan))
    assert time.time() - t0 < 1


def test_every_key_refused_is_fatal_with_a_clear_message(tmp_path, make_agent):
    r = KeyRouter([key("a", prio=1), key("b", prio=2)], tmp_path / "u.json")
    plan = Plan({S["a"]: [401], S["b"]: [403]})
    llm = RoutedLLM(r, "text", client_factory=plan)
    ev = []
    with pytest.raises(LLMError) as ei:
        run_chat(llm, events=ev)
    assert ei.value.code == "keys_refused" and "refused" in str(ei.value) and len(plan.calls) == 2
    assert ev[-1][0] == "refused"
    res = make_agent(llm, budget=Budget()).run("hello")             # no waiting: refused keys are set aside
    assert res.stop_reason == "llm_error" and "refused" in res.answer and len(plan.calls) == 2
    r.replace_entries([key("a", prio=1), key("b", prio=2)])          # keys edited in Settings: new chance
    plan.plan[S["a"]] = ["fixed"]
    assert run_chat(llm).message["content"] == "fixed"


def test_cancel_during_a_pause_stops_quickly(tmp_path, make_agent):
    r = KeyRouter([key("a")], tmp_path / "u.json")
    plan = Plan({S["a"]: [{"status": 429, "retry_after": 30}]})
    cancel = threading.Event()
    agent = make_agent(RoutedLLM(r, "text", client_factory=plan), budget=Budget(), cancel=cancel)
    threading.Timer(0.4, cancel.set).start()
    t0 = time.time()
    res = agent.run("hello")
    assert res.stop_reason == "cancelled" and time.time() - t0 < 5


class SwarmPlan(Plan):
    """Root spawns helpers; each helper answers "done"; outcomes per key come from the plan first."""

    def __init__(self, plan, tasks):
        super().__init__(plan, answer=self.reply)
        self.tasks = tasks

    def reply(self, messages, secret):
        if messages[1]["content"] == "root":
            if not any(m["role"] == "tool" for m in messages):
                args = {"tasks": self.tasks, "allowed_tools": ["read_file"]}
                return LLMReply({"role": "assistant", "content": None, "tool_calls": [
                    {"id": "s", "type": "function", "function": {"name": "spawn_agents", "arguments": json.dumps(args)}}]}, 1, 1)
            return LLMReply({"role": "assistant", "content": "root done"}, 1, 1)
        return LLMReply({"role": "assistant", "content": "helper done"}, 1, 1)


def test_swarm_helper_fails_over_mid_task_without_losing_progress(make_agent, tmp_path):
    r = KeyRouter([key("a", ["research"], prio=1), key("b", ["general"], prio=2)], tmp_path / "u.json")
    # call 1 (root, on b): spawn. call 2 (helper root.1 on a): 429 -> switches to b. Root continues.
    plan = SwarmPlan({S["a"]: [429], S["b"]: ["ok"]}, ["Researcher: collect facts"])
    events = []
    agent = make_agent(RoutedLLM(r, "text", client_factory=plan), perms=Permissions.from_dict({"defaults": {"delegate": "allow"}}),
                       budget=BIG, swarm=SwarmConfig(max_parallel=4, max_children=3, pool_size=lambda: r.usable("text")),
                       on_event=lambda k, d: events.append((k, d)))
    res = agent.run("root")
    assert res.stop_reason == "final" and res.answer == "root done"
    sw = [d for k, d in events if k == "keys" and d["action"] == "switch"]
    assert sw and sw[0]["agent"] == "root.1" and sw[0]["key_mask"] == mask(S["a"]) and sw[0]["to_mask"] == mask(S["b"])
    assert ("helper done" in json.dumps([m for m in agent.messages if m["role"] == "tool"]))
    assert not any(s in json.dumps(events, default=str) for s in S.values())


def test_single_key_swarm_waits_instead_of_stopping(make_agent, tmp_path):
    """The real v0.8.0 bug: one free key, a 429 with a short Retry-After stopped the whole swarm."""
    r = KeyRouter([key("a")], tmp_path / "u.json")
    plan = SwarmPlan({S["a"]: ["ok", {"status": 429, "retry_after": 0.5}, "ok"]},
                     ["Researcher: collect facts", "Writer: draft"])
    events = []
    agent = make_agent(RoutedLLM(r, "text", client_factory=plan), perms=Permissions.from_dict({"defaults": {"delegate": "allow"}}),
                       budget=BIG, swarm=SwarmConfig(max_parallel=4, max_children=3, pool_size=lambda: r.usable("text")),
                       on_event=lambda k, d: events.append((k, d)))
    res = agent.run("root")
    assert res.stop_reason == "final" and res.answer == "root done"
    acts = [d["action"] for k, d in events if k == "keys"]
    assert "wait" in acts and "resume" in acts


# ------------------------------------------------------------------ tokens left per minute
def test_parse_ratelimit_headers_and_durations():
    assert parse_duration("7.66s") == 7.66 and parse_duration("2m59.56s") == 179.56
    assert parse_duration("1h2m3s") == 3723 and parse_duration("120ms") == 0.12 and parse_duration("4") == 4
    assert parse_duration("soon") is None and parse_duration(None) is None
    h = {"X-RateLimit-Limit-Tokens": "8000", "x-ratelimit-remaining-tokens": "5200", "x-ratelimit-reset-tokens": "12s",
         "x-ratelimit-limit-requests": "1000", "x-ratelimit-remaining-requests": "998", "x-ratelimit-reset-requests": "2m52.8s",
         "content-type": "application/json"}
    assert parse_ratelimit(h) == {"tokens_limit": 8000, "tokens_remaining": 5200, "tokens_reset_s": 12,
                                  "requests_limit": 1000, "requests_remaining": 998, "requests_reset_s": 172.8}
    assert parse_ratelimit({"x-ratelimit-remaining-tokens": "abc"}) == {} and parse_ratelimit(None) == {}


def test_rate_counter_provider_headers_then_estimate(tmp_path):
    now = [1_800_000_000.0]
    r = KeyRouter([key("g", base_url="https://api.groq.com/openai/v1"), key("o")], tmp_path / "u.json", clock=lambda: now[0])
    r.acquire("text").commit(700, 300)                              # 1000 tokens on g, no headers yet
    st = {k["name"]: k for k in r.status()["keys"]}
    assert st["g"]["rate"] == {"source": "estimate", "tokens_used": 1000, "tokens_limit": 8000,
                               "tokens_left": 7000, "tokens_reset_s": 60}
    assert st["o"]["rate"]["tokens_limit"] is None and st["o"]["rate"]["tokens_used"] == 0   # unknown limit
    now[0] += 61
    assert {k["name"]: k for k in r.status()["keys"]}["g"]["rate"]["tokens_left"] == 8000    # window rolled
    r.note_rate("g", {"x-ratelimit-limit-tokens": "8000", "x-ratelimit-remaining-tokens": "2000",
                      "x-ratelimit-reset-tokens": "10s", "x-ratelimit-limit-requests": "1000",
                      "x-ratelimit-remaining-requests": "990", "x-ratelimit-reset-requests": "1m"})
    rate = {k["name"]: k for k in r.status()["keys"]}["g"]["rate"]
    assert rate["source"] == "provider" and rate["tokens_left"] == 2000 and rate["tokens_reset_s"] == 10
    assert rate["requests_left"] == 990 and rate["requests_limit"] == 1000
    now[0] += 5                                                     # the provider refills steadily
    rate = {k["name"]: k for k in r.status()["keys"]}["g"]["rate"]
    assert rate["tokens_left"] == 5000 and rate["tokens_reset_s"] == 5
    assert r.rate_reset("g") == 5                                   # used as cooldown when a 429 has no Retry-After


class FakeAPI(BaseHTTPRequestHandler):
    mode = "ok"

    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if FakeAPI.mode == "429":
            body = json.dumps({"error": {"message": "Rate limit reached. Please try again in 1.5s."}}).encode()
            self.send_response(429)
            self.send_header("x-ratelimit-remaining-tokens", "0")
            self.send_header("x-ratelimit-limit-tokens", "8000")
        else:
            body = json.dumps({"choices": [{"message": {"content": "hi"}}],
                               "usage": {"prompt_tokens": 5, "completion_tokens": 2}}).encode()
            self.send_response(200)
            self.send_header("x-ratelimit-remaining-tokens", "7993")
            self.send_header("x-ratelimit-limit-tokens", "8000")
            self.send_header("x-ratelimit-reset-tokens", "52ms")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_openai_client_reads_rate_headers_and_try_again_hint():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeAPI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        c = OpenAICompatible(f"http://127.0.0.1:{srv.server_address[1]}/v1", "m", "gsk_" + "q" * 30, retries=0)
        FakeAPI.mode = "ok"
        reply = c.chat([{"role": "user", "content": "x"}])
        assert reply.ratelimit["x-ratelimit-remaining-tokens"] == "7993"
        assert parse_ratelimit(reply.ratelimit)["tokens_reset_s"] == 0.052
        FakeAPI.mode = "429"
        with pytest.raises(LLMError) as ei:
            c.chat([{"role": "user", "content": "x"}])
        assert ei.value.status == 429 and ei.value.retry_after == 1.5           # from "try again in 1.5s"
        assert ei.value.ratelimit["x-ratelimit-remaining-tokens"] == "0"
    finally:
        srv.shutdown()
        srv.server_close()


def test_keys_rate_endpoint_events_and_pages(make, tmp_path):
    r = KeyRouter([key("a", prio=1), key("b", prio=2, base_url="https://api.groq.com/openai/v1")], tmp_path / "u.json")
    plan = Plan({S["a"]: [429], S["b"]: ["fine"]})
    base, h = make(lambda: RoutedLLM(r, "text", client_factory=plan), key_router=r)
    tid = call(base, "POST", "/tasks", {"task": "hello"})[1]["id"]
    assert finished(base, tid)["status"] == "done"
    evs = call(base, "GET", f"/tasks/{tid}/events")[1]["events"]
    kev = [e for e in evs if e["kind"] == "keys"]
    assert [e["action"] for e in kev] == ["switch", "resume"]
    assert kev[0]["from_mask"] == mask(S["a"]) and kev[0]["to_mask"] == mask(S["b"]) and kev[0]["agent"] == "root"
    st, rv = call(base, "GET", "/keys/rate")
    assert st == 200 and [k["name"] for k in rv["keys"]] == ["a", "b"]
    kb = rv["keys"][1]
    assert kb["key"] == mask(S["b"]) and kb["rate"]["source"] == "estimate" and kb["rate"]["tokens_limit"] == 8000
    assert kb["rate"]["tokens_left"] < 8000 and rv["keys"][0]["cooldown_s"] > 0
    from agent.redact import redact
    assert redact(kev[0])["from_mask"] == mask(S["a"])               # stays readable in the saved history
    raw = json.dumps([evs, rv])
    assert not any(s in raw for s in S.values())
    import urllib.request
    chat = urllib.request.urlopen(base + "/").read().decode()
    dash = urllib.request.urlopen(base + "/dashboard").read().decode()
    assert 'id="ratebar"' in chat and "function rateBox" in chat and "/keys/rate" in chat and 'e.kind==="keys"' in chat
    assert 'id="rates"' in dash and "refreshRates" in dash


def test_strings_fr_en():
    from agent.i18n import t
    assert t("fr", "kw.switch", **{"from": "gsk_…43gO", "to": "gsk_…b2c3"}) == \
        "Limite atteinte sur la clé gsk_…43gO, je passe sur la clé de secours gsk_…b2c3…"
    assert t("fr", "kw.wait", s=4) == "Toutes les clés sont en pause, je reprends dans 4 s…"
    assert t("fr", "rate.tokens", left="5 200", limit="8 000") == "Tokens restants : 5 200 / 8 000 par minute"
    assert t("en", "rate.resetIn", s=12) == "back in 12 s" and t("fr", "rate.estimated") == "estimé"
    assert "deuxième clé" in t("fr", "set.keys.backupHint")
