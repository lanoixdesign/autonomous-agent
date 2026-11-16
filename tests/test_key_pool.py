"""v0.7 "several keys": bulk key entry, key pool (one key per swarm agent, least busy, failover),
task-specific keys (role -> task type, then General, then any key), parallelism = working keys,
and no key ever leaks (responses, files, audit, graph)."""
import json
import threading
import time

import pytest

from agent.audit import AuditLog
from agent.keys import TASKS, mask, KeyEntry, KeyRouter, KeysExhausted, role_task
from agent.llm import CALLER, LLMError, LLMReply, RoutedLLM
from agent.loop import Budget
from agent.permissions import Permissions
from agent.swarm import SwarmConfig
from agent.userconfig import AppControl, SecretStore, UserConfig
from test_settings_ui import app, fake  # noqa: F401  (fixtures)

S = {n: f"gsk_{n}_" + "x" * 20 + n.upper() for n in ("a", "b", "c", "d")}
BIG = Budget(max_steps=200, max_tool_calls=200, max_tokens=10 ** 7)


def key(name, tasks=(), prio=10, **limits):
    return KeyEntry(name, ["text", "code"], base_url=f"http://{name}", models={"*": "m-" + name}, priority=prio,
                    limits=limits, secret_fn=lambda n=name: S.get(n) or f"gsk_{n}_" + "y" * 20, source="ui", tasks=list(tasks))


def router(tmp_path, *keys, audit=False):
    return KeyRouter(list(keys), tmp_path / "usage.json", AuditLog(tmp_path / "audit.jsonl") if audit else None)


# ------------------------------------------------------------------------- role -> task type
@pytest.mark.parametrize("task,expected", [
    ("Researcher: collect three facts about bees", "research"), ("Chercheur : rassembler les sources", "research"),
    ("Summarize the report", "research"), ("Writer: draft the newsletter", "writing"),
    ("Rédacteur : rédige l'e-mail", "writing"), ("Coder: write the Python script", "code"),
    ("Développeur : corriger le bug", "code"), ("Analyst: compare the two offers", "analysis"),
    ("Analyste : évaluer les risques", "analysis"), ("Look at this screenshot", "vision"),
    ("", "general"), ("Do the thing", "general"),
])
def test_role_task(task, expected):
    assert role_task(task) == expected and expected in TASKS


# ------------------------------------------------------------------------- pool allocation
def test_each_agent_gets_its_own_key_and_keeps_it(tmp_path):
    r = router(tmp_path, key("a"), key("b"), key("c"))
    got = {}
    for h in ("t:root.1", "t:root.2", "t:root.3"):
        lease = r.acquire("text", holder=h, label=h[2:])
        got[h] = lease.name
        lease.commit(1, 1)
    assert sorted(got.values()) == ["a", "b", "c"]               # one key per agent
    for h, k in got.items():                                     # sticky: the same agent keeps its key
        lease = r.acquire("text", holder=h)
        assert lease.name == k
        lease.commit(1, 1)
    st = {k["name"]: k for k in r.status()["keys"]}
    assert {a for k in st.values() for a in k["agents"]} == {"root.1", "root.2", "root.3"}
    assert all(len(k["agents"]) == 1 for k in st.values())


def test_fewer_keys_than_agents_share_the_least_busy(tmp_path):
    r = router(tmp_path, key("a"), key("b"))
    names = []
    for i in range(1, 5):
        lease = r.acquire("text", holder=f"t:root.{i}", label=f"root.{i}")
        names.append(lease.name)
        lease.commit(1, 1)
    assert names.count("a") == 2 and names.count("b") == 2      # shared evenly, nobody blocked
    r.release_holder("t:root.1")
    r.release_holder("t:root.3")                                 # both holders of "a" (a, b, a, b)
    assert r.acquire("text", holder="t:root.5").name == "a"     # the freed key is now the least busy


def test_no_holder_keeps_plain_priority_order(tmp_path):
    r = router(tmp_path, key("a", prio=1), key("b", prio=2))
    assert [r.acquire("text").name for _ in range(3)] == ["a", "a", "a"]


def test_limits_are_still_never_exceeded_and_agent_moves_on(tmp_path):
    r = router(tmp_path, key("a", requests_per_minute=1), key("b"))
    assert r.acquire("text", holder="t:root.1").name == "a"
    assert r.acquire("text", holder="t:root.1").name == "b"     # a is at its limit: fail over, no overshoot
    r2 = router(tmp_path / "x", key("a", requests_per_day=1))
    r2.acquire("text", holder="t:1")
    with pytest.raises(KeysExhausted):
        r2.acquire("text", holder="t:2")


# ------------------------------------------------------------------------- task-specific keys
def test_role_based_selection_then_general_then_any(tmp_path):
    r = router(tmp_path, key("fast", ["research", "analysis"], prio=1), key("strong", ["writing", "code"], prio=2),
               key("gen", ["general"], prio=3))
    pick = lambda task, h: r.acquire("text", holder=h, task=task).name   # noqa: E731
    assert pick("research", "t:1") == "fast"
    assert pick("writing", "t:2") == "strong"
    assert pick("code", "t:3") == "strong"                        # matching key even if busy
    assert pick("vision", "t:4") == "gen"                         # nobody tagged vision -> General
    assert pick("general", "t:5") == "gen"
    r2 = router(tmp_path / "2", key("fast", ["research"]), key("strong", ["writing"]))
    assert r2.acquire("text", holder="t:1", task="vision").name in ("fast", "strong")   # no General -> any key
    assert r2.acquire("text", holder="t:2", task="code").name in ("fast", "strong")


def test_untagged_keys_count_as_general(tmp_path):
    r = router(tmp_path, key("res", ["research"], prio=1), key("plain", prio=2))
    assert r.acquire("text", holder="t:1", task="writing").name == "plain"
    assert r.acquire("text", holder="t:2", task="research").name == "res"


def test_matching_key_over_limit_falls_back(tmp_path):
    r = router(tmp_path, key("res", ["research"], requests_per_minute=1), key("gen", ["general"]))
    assert r.acquire("text", holder="t:1", task="research").name == "res"
    assert r.acquire("text", holder="t:1", task="research").name == "gen"


# ------------------------------------------------------------------------- failover in the chat backend
class FakeClient:
    def __init__(self, calls, fail):
        self.calls, self.fail = calls, fail

    def __call__(self, base_url, model, key, max_tokens):
        outer = self

        class C:
            def chat(self, messages, tools=None):
                outer.calls.append(key)
                status = outer.fail.get(key)
                if status:
                    raise LLMError(f"HTTP {status}", status=status)
                return LLMReply({"role": "assistant", "content": "ok"}, 3, 2)
        return C()


@pytest.mark.parametrize("status", [429, 500, 401, 403])
def test_rate_limit_or_key_error_fails_over_to_another_key(tmp_path, status):
    r = router(tmp_path, key("a", prio=1), key("b", prio=2), audit=True)
    calls = []
    llm = RoutedLLM(r, "text", client_factory=FakeClient(calls, {S["a"]: status}))
    tok = CALLER.set({"holder": "t:root.1", "task": "research", "label": "root.1"})
    try:
        reply = llm.chat([{"role": "user", "content": "hi"}])
    finally:
        CALLER.reset(tok)
    assert reply.key == "b" and calls == [S["a"], S["b"]]
    assert reply.key_mask == mask(S["b"]) and S["b"] not in json.dumps(reply.__dict__, default=str)
    assert r.holders()["t:root.1"]["key"] == "b"                 # the agent now uses b
    st = {k["name"]: k for k in r.status()["keys"]}
    assert st["a"]["cooldown_s"] > 0                             # a rests, others keep working


def test_bad_request_is_not_a_key_problem(tmp_path):
    r = router(tmp_path, key("a", prio=1), key("b", prio=2))
    calls = []
    llm = RoutedLLM(r, "text", client_factory=FakeClient(calls, {S["a"]: 400}))
    with pytest.raises(LLMError):
        llm.chat([{"role": "user", "content": "hi"}])
    assert calls == [S["a"]]


# ------------------------------------------------------------------------- swarm: one key per child, by role
class RoleLLM:
    """Root spawns three role children in parallel; records which key served which agent, and overlap."""

    def __init__(self, tasks, delay=0.12):
        self.tasks, self.delay = tasks, delay
        self.lock = threading.Lock()
        self.active = self.peak = 0
        self.by_agent: dict[str, set] = {}

    def __call__(self, base_url, model, key, max_tokens):
        outer = self

        class C:
            def chat(self, messages, tools=None):
                who = (CALLER.get() or {}).get("label")
                with outer.lock:
                    outer.by_agent.setdefault(who, set()).add(key)
                task = messages[1]["content"]
                if task == "root":
                    if not any(m["role"] == "tool" for m in messages):
                        args = {"tasks": outer.tasks, "allowed_tools": ["read_file"]}
                        return LLMReply({"role": "assistant", "content": None, "tool_calls": [
                            {"id": "s", "type": "function", "function": {"name": "spawn_agents",
                                                                         "arguments": json.dumps(args)}}]}, 1, 1)
                    return LLMReply({"role": "assistant", "content": "root done"}, 1, 1)
                with outer.lock:
                    outer.active += 1
                    outer.peak = max(outer.peak, outer.active)
                time.sleep(outer.delay)
                with outer.lock:
                    outer.active -= 1
                return LLMReply({"role": "assistant", "content": "done"}, 1, 1)
        return C()


def test_swarm_children_get_role_matched_keys_in_parallel(make_agent, tmp_path):
    r = router(tmp_path, key("a", ["research"]), key("b", ["writing"]), key("c", ["code"]), key("d", ["general"]))
    tasks = ["Researcher: collect facts", "Writer: draft the email", "Coder: write the script"]
    fake = RoleLLM(tasks)
    events = []
    agent = make_agent(RoutedLLM(r, "text", client_factory=fake), perms=Permissions.from_dict({"defaults": {"delegate": "allow"}}),
                       budget=BIG, swarm=SwarmConfig(max_parallel=8, max_children=5, pool_size=lambda: r.usable("text")),
                       on_event=lambda k, d: events.append((k, d)))
    res = agent.run("root")
    assert res.answer == "root done" and fake.peak == 3
    assert fake.by_agent["root"] == {S["d"]}
    assert fake.by_agent["root.1"] == {S["a"]} and fake.by_agent["root.2"] == {S["b"]} and fake.by_agent["root.3"] == {S["c"]}
    steps = {d.get("agent", "root"): d for k, d in events if k == "step"}
    assert steps["root.1"]["key"] == "a" and steps["root.1"]["key_task"] == "research" and steps["root.1"]["key_match"]
    assert steps["root.2"]["key_mask"] == mask(S["b"])
    assert not any(s in json.dumps(events, default=str) for s in S.values())   # no secret in any event
    assert r.holders() == {}                                      # every agent gave its key back at the end


def test_parallelism_follows_the_number_of_working_keys(make_agent, tmp_path):
    r = router(tmp_path, key("a"), key("b"))
    fake = RoleLLM([f"t{i}" for i in range(4)])
    agent = make_agent(RoutedLLM(r, "text", client_factory=fake), perms=Permissions.from_dict({"defaults": {"delegate": "allow"}}),
                       budget=BIG, swarm=SwarmConfig(max_parallel=8, max_children=5, pool_size=lambda: r.usable("text")))
    assert agent.run("root").answer == "root done"
    assert fake.peak == 2                                        # 2 keys -> 2 at a time, the others queue
    assert all(len(v) == 1 for v in fake.by_agent.values())


# ------------------------------------------------------------------------- bulk entry (AppControl)
@pytest.fixture
def control(tmp_path, monkeypatch):
    monkeypatch.delenv("AGENT_KEY_TEST", raising=False)
    state = tmp_path / "state"
    tested = []

    def prober(base, secret):
        tested.append(secret)
        time.sleep(0.2)
        if "BAD" in secret:
            return {"ok": False, "code": "invalid", "http_status": 401}
        return {"ok": True, "code": "ok", "http_status": 200, "models": 3}
    c = AppControl(UserConfig(state), SecretStore(state / "secrets.json", use_keyring=False), prober=prober,
                   home=str(state))
    c.router.audit = AuditLog(state / "audit.jsonl")
    c.tested = tested
    return c


GROQ1, GROQ2, GROQBAD = "gsk_" + "1" * 30, "gsk_" + "2" * 30, "gsk_" + "BAD" * 10
OAI, ORT = "sk-proj-" + "o" * 30 + "OAI1", "sk-or-v1-" + "r" * 30


def test_parse_bulk_lines():
    rows = AppControl.parse_bulk(f"""
# my keys
{GROQ1}
Groq perso: {GROQ2}
OPENAI_API_KEY={OAI}
export OPENROUTER_API_KEY="{ORT}"
openrouter : sk-xyz-{'q' * 20}
mystery: abcdefghijklmnopqrstuv
{GROQ1}
hi
""")
    got = [(r["label"], r["provider"], r.get("code")) for r in rows]
    assert got == [("", "groq", None), ("Groq perso", "groq", None), ("OPENAI_API_KEY", "openai", None),
                   ("OPENROUTER_API_KEY", "openrouter", None), ("openrouter", "openrouter", None),
                   ("mystery", None, "unknown_provider"), ("", "groq", "duplicate"), ("", None, "format")]
    assert rows[1]["key"] == GROQ2
    assert AppControl.parse_bulk("\n".join(f"gsk_{i:030d}" for i in range(60)))[-1]["code"] == "too_many"


def test_bulk_add_tests_all_at_once_saves_valid_and_never_leaks(control, tmp_path):
    t0 = time.monotonic()
    res = control.bulk_add(f"{GROQ1}\nGroq perso: {GROQ2}\n{GROQBAD}\nOPENAI_API_KEY={OAI}\nwhat: nope-nope-nope")
    assert time.monotonic() - t0 < 0.6                            # 4 probes of 0.2 s ran at the same time
    by = {r["line"]: r for r in res["results"]}
    assert [by[i]["ok"] for i in range(1, 6)] == [True, True, False, True, False]
    assert by[3]["code"] == "invalid" and by[5]["code"] == "unknown_provider"
    assert (by[1]["name"], by[2]["name"], by[4]["name"]) == ("Groq", "Groq perso", "OpenAI")
    assert res["saved"] == 3 and res["failed"] == 2 and res["parallel"] == 3
    assert {p["name"] for p in control.providers_view()} == {"Groq", "Groq perso", "OpenAI"}
    assert control.secrets.get(by[2]["id"]) == GROQ2              # stored in the secret store, like v0.5
    # never unmasked: response, providers file, settings, audit
    blob = json.dumps(res) + (tmp_path / "state" / "providers-ui.json").read_text()
    audit = tmp_path / "state" / "audit.jsonl"
    blob += audit.read_text() if audit.exists() else ""
    blob += json.dumps(control.view()) + json.dumps(control.pool_view()) + json.dumps(control.propose_tasks())
    for s in (GROQ1, GROQ2, GROQBAD, OAI):
        assert s not in blob
    assert by[1]["key"] == "gsk_••••1111"
    # pasting again: already saved, not duplicated; second groq gets a unique name
    again = control.bulk_add(f"{GROQ1}\ngsk_{'3' * 30}")
    assert again["results"][0]["code"] == "already_saved" and again["results"][1]["name"] == "Groq 2"


def test_bulk_add_offline_mode_checks_format_only(control, monkeypatch):
    monkeypatch.setenv("AGENT_KEY_TEST", "offline")
    res = control.bulk_add(f"{GROQ1}\ngsk_x")
    assert [r["code"] for r in res["results"]] == ["offline", "format"] and control.tested == []


def test_bulk_add_rejects_empty(control):
    from agent.userconfig import SettingsError
    with pytest.raises(SettingsError):
        control.bulk_add("\n# nothing\n")


# ------------------------------------------------------------------------- proposal + tagging
def test_propose_fast_free_for_research_strong_for_writing_and_code(control, monkeypatch):
    monkeypatch.setenv("AGENT_KEY_TEST", "offline")
    control.bulk_add(f"{GROQ1}\n{OAI}")
    oai = next(p for p in control.providers_view() if p["provider"] == "openai")
    control.set_tasks({oai["id"]: {"tasks": [], "model": "gpt-4o"}})
    prop = {p["name"]: p for p in control.propose_tasks()}
    assert prop["Groq"]["tasks"] == ["research", "analysis"] and prop["Groq"]["why"] == "fast_free"
    assert prop["OpenAI"]["tasks"] == ["writing", "code", "vision", "general"] and prop["OpenAI"]["why"] == "strong"
    assert all(GROQ1 not in json.dumps(p) and OAI not in json.dumps(p) for p in prop.values())


def test_propose_spreads_jobs_over_similar_keys(control, monkeypatch):
    monkeypatch.setenv("AGENT_KEY_TEST", "offline")
    control.bulk_add("\n".join(f"gsk_{c * 30}" for c in "123"))
    prop = control.propose_tasks()
    assert [p["tasks"] for p in prop] == [["research", "analysis", "general"], ["writing"], ["code"]]
    assert {p["why"] for p in prop} == {"spread"}
    control.cfg.providers[:] = control.cfg.providers[:1]
    assert control.propose_tasks()[0]["tasks"] == ["research", "writing", "code", "analysis", "general"]


def test_set_tasks_validates_and_reaches_the_router(control, monkeypatch):
    from agent.userconfig import SettingsError
    monkeypatch.setenv("AGENT_KEY_TEST", "offline")
    control.bulk_add(f"{GROQ1}\n{GROQ2}")
    a, b = control.providers_view()
    control.set_tasks({a["id"]: ["research"], b["id"]: {"tasks": ["writing", "code"], "model": "llama-3.3-70b-versatile"}})
    ents = {e.name: e for e in control.router.entries}
    assert ents[a["name"]].tasks == ["research"] and ents[b["name"]].tasks == ["writing", "code"]
    assert ents[b["name"]].model_for("text") == "llama-3.3-70b-versatile"
    assert control.router.acquire("text", holder="h1", task="code").name == b["name"]
    for bad in ({a["id"]: ["cooking"]}, {"nope": ["research"]}, {a["id"]: {"tasks": [], "model": "a b"}}, {}):
        with pytest.raises(SettingsError):
            control.set_tasks(bad)
    with pytest.raises(SettingsError):
        control.save_provider({"tasks": ["cooking"]}, a["id"])
    assert control.save_provider({"tasks": ["vision"]}, a["id"])["tasks"] == ["vision"]


def test_parallel_setting(control, monkeypatch):
    from agent.userconfig import SettingsError
    monkeypatch.setenv("AGENT_KEY_TEST", "offline")
    assert control.parallel_limit("text", 3) == 3                 # no key yet: the default
    control.bulk_add(f"{GROQ1}\n{GROQ2}\n{OAI}")
    assert control.parallel_limit("text", 3) == 3 and control.view()["parallel"]["keys"] == 3
    control.update({"parallel": 2})
    assert control.parallel_limit("text") == 2
    control.update({"parallel": 6})
    assert control.parallel_limit("text") == 6                    # more than keys: they share
    control.update({"parallel": "auto"})
    assert control.parallel_limit("text") == 3
    with pytest.raises(SettingsError):
        control.update({"parallel": 99})
    control.update({"demo": True})
    assert control.parallel_limit("text", 3) == 3


# ------------------------------------------------------------------------- swarm graph + HTTP routes
def test_graph_shows_masked_key_and_task_per_agent():
    from agent.harness import Task
    t = Task("go")
    t.on_audit({"event": "spawn", "agent": "root", "child": "root.1", "child_depth": 1,
                "task": "Researcher: collect facts", "budget": {"max_steps": 6}})
    t.on_progress("root.1", 1, 6, {"key": "Groq", "key_mask": "gsk_…1111", "key_task": "research", "key_match": True,
                                   "secret": GROQ1})
    t.on_progress("root.1", 2, 6, {"key": "Groq 2", "key_mask": "gsk_…2222", "key_task": "research", "key_match": False})
    a = next(x for x in t.graph()["agents"] if x["id"] == "root.1")
    assert (a["key"], a["key_mask"], a["key_task"], a["role"], a["keys"]) == ("Groq 2", "gsk_…2222", "research", "research", ["Groq", "Groq 2"])
    assert GROQ1 not in json.dumps(t.graph()) + json.dumps(t.events)


def test_http_bulk_tasks_pool_routes(app, monkeypatch):
    from test_settings_ui import call, post
    monkeypatch.setenv("AGENT_KEY_TEST", "offline")
    base, h, control = app()
    st, r = call(base, "POST", "/app/providers/bulk", {"text": GROQ1}, headers={})
    assert st == 403                                              # CSRF token required, like every settings change
    st, r = post(base, "/app/providers/bulk", {"text": f"Groq perso: {GROQ1}\n{OAI}\njunk"})
    assert st == 200 and r["saved"] == 2 and [x["ok"] for x in r["results"]] == [True, True, False]
    assert len(r["proposal"]) == 2 and GROQ1 not in json.dumps(r) and OAI not in json.dumps(r)
    st, p = post(base, "/app/providers/propose")
    assert st == 200 and {x["name"] for x in p["proposal"]} == {"Groq perso", "OpenAI"}
    gid = next(x["id"] for x in p["proposal"] if x["name"] == "Groq perso")
    st, t = post(base, "/app/providers/tasks", {"assign": {gid: ["research", "analysis"]}})
    assert st == 200 and next(x for x in t["providers"] if x["id"] == gid)["tasks"] == ["research", "analysis"]
    st, e = post(base, "/app/providers/tasks", {"assign": {gid: ["cooking"]}})
    assert st == 400 and e["code"] == "bad_task"
    st, pool = call(base, "GET", "/app/pool")
    assert st == 200 and pool["parallel"] == 2 and {k["name"] for k in pool["keys"]} == {"Groq perso", "OpenAI"}
    st, keys = call(base, "GET", "/keys")
    assert st == 200 and keys["parallel"] == 2 and GROQ1 not in json.dumps(keys) + json.dumps(pool)
    st, v = post(base, "/app/settings", {"parallel": 1})
    assert st == 200 and v["parallel"]["effective"] == 1


def test_pages_have_bulk_entry_jobs_and_simple_copy():
    from agent import i18n
    from agent.harness_chat import CHAT_PAGE
    from agent.harness_settings import SETTINGS_PAGE, WELCOME_PAGE
    for page in (SETTINGS_PAGE, WELCOME_PAGE):
        assert "makeBulk(" in page and "makeJobs(" in page and "/app/providers/bulk" in page
        assert "-webkit-text-security:disc" in page and 'b.type="password"' in page   # never shown in clear
    assert 'id="parsel"' in SETTINGS_PAGE and 'id="ftasks"' in SETTINGS_PAGE and 'id="wbulk"' in WELCOME_PAGE
    assert "keyLine(" in CHAT_PAGE and "swarm.keysUsed" in CHAT_PAGE
    assert i18n.FR["bulk.why"] == "Plus tu ajoutes de clés, plus tes assistants travaillent en même temps."
    assert i18n.EN["bulk.why"] == "The more keys you add, the more your assistants work at the same time."
    for k in TASKS:
        assert i18n.EN["task." + k] and i18n.FR["task." + k]
    assert i18n.FR["task.research"] == "Recherche & résumés" and i18n.FR["task.writing"] == "Rédaction"
