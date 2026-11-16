"""v0.9: self-evaluation (Critic), handoffs between agents, semantic memory (embeddings in SQLite, hybrid
recall, keyword fallback) and the business API connector (masked secret, confinement, risk categories)."""
import json

import pytest

from agent import critic, i18n
from agent.apis import ApiRegistry, endpoints
from agent.apis import TOOLS as API_TOOLS
from agent.harness import Task
from agent.llm import LLMError, LLMReply
from agent.loop import Budget
from agent.memory import Memory
from agent.permissions import Permissions
from agent.skills import SkillLibrary
from agent.swarm import MAX_HANDOFFS, SwarmConfig
from agent.tools import ToolContext, ToolError
from agent.userconfig import SecretStore
from agent.vectors import RouterEmbedder, VectorIndex, cosine, pack, unpack

from test_settings_ui import app, call, post  # noqa: F401  (fixture)

ALLOW = Permissions.from_dict({"defaults": {"delegate": "allow", "write": "allow", "read": "allow"}})
BIG = Budget(max_steps=30, max_tool_calls=30, max_tokens=10 ** 7)
SECRET = "Bearer sk-test-0123456789abcdef"


def say(text):
    return LLMReply({"role": "assistant", "content": text}, 1, 1)


def call_tool(name, args, cid="c1"):
    return LLMReply({"role": "assistant", "content": None, "tool_calls": [
        {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}, 1, 1)


def is_critic(messages):
    return "You are the Critic" in str(messages[0].get("content"))


# ------------------------------------------------------------------------- 1. Critic
class CriticLLM:
    """The worker writes draft 1, then (after a [Critic] note) draft 2; the Critic follows a script."""

    def __init__(self, verdicts):
        self.verdicts, self.critic_calls, self.drafts = list(verdicts), [], 0

    def chat(self, messages, tools=None):
        if is_critic(messages):
            self.critic_calls.append(messages)
            assert tools == []
            return say(self.verdicts.pop(0))
        self.drafts += 1
        return say(f"brouillon {self.drafts}")


def test_parse_verdicts():
    assert critic.parse('{"verdict":"ok","score":9,"issues":[]}') == {"ok": True, "score": 9.0, "issues": [], "readable": True}
    v = critic.parse('Voici: {"verdict":"revise","score":3,"issues":["il manque la 3e phrase"]}')
    assert not v["ok"] and v["issues"] == ["il manque la 3e phrase"] and v["score"] == 3.0
    assert critic.parse("je ne sais pas")["ok"] is True                 # unreadable never blocks
    assert critic.parse('{"verdict":"revise"}')["issues"] == ["(no detail)"]
    m = critic.revise_message(["x"], "fr")
    assert m["role"] == "user" and m["content"].startswith("[Critic]") and "French" in m["content"]


def test_critic_off_by_default(make_agent):
    llm = CriticLLM([])
    agent = make_agent(llm)
    assert agent.critic_rounds == 0
    assert agent.run("Écris deux phrases").answer == "brouillon 1" and not llm.critic_calls


def test_critic_revises_then_accepts(make_agent):
    llm = CriticLLM(['{"verdict":"revise","score":4,"issues":["une seule phrase au lieu de deux"]}',
                     '{"verdict":"ok","score":9,"issues":[]}'])
    events = []
    agent = make_agent(llm, on_event=lambda k, d: events.append((k, d)))
    agent.critic_rounds = 2
    res = agent.run("Écris deux phrases sur la mer")
    assert res.answer == "brouillon 2" and res.stop_reason == "final" and len(llm.critic_calls) == 2
    req = llm.critic_calls[0][1]["content"]
    assert "Écris deux phrases" in req and "brouillon 1" in req and "French" in llm.critic_calls[0][0]["content"]
    assert any(m["role"] == "user" and "une seule phrase" in str(m["content"]) for m in agent.messages)
    crit = [d for k, d in events if k == "critic"]
    assert [c["ok"] for c in crit] == [False, True] and crit[0]["critic"] == "root.critic1" and crit[1]["max"] == 2
    finals = [d for k, d in events if k == "assistant" and d.get("final")]
    assert [f["content"] for f in finals] == ["brouillon 2"]          # the first draft never shown as final
    assert any(d.get("draft") for k, d in events if k == "assistant")


def test_critic_rounds_are_limited(make_agent):
    llm = CriticLLM(['{"verdict":"revise","issues":["a"]}'] * 5)
    agent = make_agent(llm)
    agent.critic_rounds = 1
    res = agent.run("Do it")
    assert len(llm.critic_calls) == 1 and res.answer == "brouillon 2"


def test_critic_error_never_blocks(make_agent):
    class Boom(CriticLLM):
        def chat(self, messages, tools=None):
            if is_critic(messages):
                raise LLMError("rate limited")
            return super().chat(messages, tools)
    agent = make_agent(Boom([]))
    agent.critic_rounds = 2
    assert agent.run("Do it").answer == "brouillon 1"


def test_critic_node_in_graph_and_plain_trace():
    t = Task("go")
    t.new_turn("go")
    t.on_audit({"event": "critic", "agent": "root", "critic": "root.critic1", "round": 1, "max": 2, "ok": False,
                "score": 4, "issues": ["manque"], "lang": "fr"})
    g = t.graph()
    node = next(a for a in g["agents"] if a["id"] == "root.critic1")
    assert node["critic"] and node["status"] == "revise" and node["score"] == 4
    assert node["task"] == "Critique : vérifier la réponse (tour 1)"
    assert g["failed"] == 0                                    # "to fix" is not a failure
    for lang in ("en", "fr"):
        for k in ("critic.task", "trace.criticOk", "trace.criticRevise", "status.revise", "critic.toggle",
                  "simple.handoff", "apis.title", "mem.semantic"):
            assert i18n.t(lang, k) != k
    assert i18n.t("fr", "critic.toggle") == "Vérifier la réponse avant de l'envoyer"
    from agent.harness_chat import CHAT_PAGE
    from agent.harness_settings import SETTINGS_PAGE
    assert 'id="critdef"' in CHAT_PAGE and "trace.criticRevise" in CHAT_PAGE and 'id="criton"' in SETTINGS_PAGE


def test_settings_critic_validation(app):  # noqa: F811
    base, h, control = app()
    st, s = call(base, "GET", "/settings")
    assert st == 200 and s["critic"] is False and s["critic_rounds"] == 2
    st, s = call(base, "POST", "/settings", {"critic": True, "critic_rounds": 3})
    assert st == 200 and s["critic"] is True and s["critic_rounds"] == 3
    for bad in ({"critic": "yes"}, {"critic_rounds": 0}, {"critic_rounds": 4}, {"critic_rounds": True}):
        assert call(base, "POST", "/settings", bad)[0] == 400
    st, hl = call(base, "GET", "/health")
    assert hl["critic"] == {"enabled": True, "rounds": 3}


# ------------------------------------------------------------------------- 2. handoffs
class RelayLLM:
    """root -> Codeur -> Testeur -> Critique; each hands over, the Critique answers."""

    def __init__(self):
        self.seen = {}

    def chat(self, messages, tools=None):
        task = messages[1]["content"]
        role = next((r for r in ("Critique", "Testeur", "Codeur") if task.startswith(r + ":")), "root")
        self.seen.setdefault(role, {"task": task, "tools": sorted(t["function"]["name"] for t in tools or [])})
        done = any(m["role"] == "tool" for m in messages)
        if role == "root":
            n = sum(m["role"] == "tool" for m in messages)
            if n == 0:
                return call_tool("write_file", {"path": "app.py", "content": "print(1)"}, "w")
            return call_tool("handoff", {"to": "Codeur", "brief": "termine app.py"}, "h0") if n == 1 else say("??")
        nxt = {"Codeur": "Testeur", "Testeur": "Critique"}.get(role)
        if nxt and not done:
            return call_tool("handoff", {"to": nxt, "brief": f"à toi après {role}"}, "h1")
        return say("Tout est vérifié : app.py affiche 1." if role == "Critique" else "??")


def test_handoff_chain_answer_and_context(make_agent, ws, tmp_path):
    llm = RelayLLM()
    agent = make_agent(llm, perms=ALLOW, budget=BIG, swarm=SwarmConfig(max_depth=2, max_children=6))
    res = agent.run("Crée app.py qui affiche 1 puis fais-le tester")
    assert res.answer == "Tout est vérifié : app.py affiche 1." and res.stop_reason == "final"
    assert set(llm.seen) == {"root", "Codeur", "Testeur", "Critique"}
    cod = llm.seen["Codeur"]["task"]
    assert "Crée app.py" in cod and "write_file" in cod and "Handed over by root" in cod
    assert "handoff" in llm.seen["Critique"]["tools"]             # beyond max_depth thanks to handoffs
    log = [json.loads(x) for x in (tmp_path / "state" / "audit.jsonl").read_text().splitlines()]
    spawns = [e for e in log if e.get("event") == "spawn"]
    assert len(spawns) == 3 and all(e.get("handoff") for e in spawns)
    t = Task("x")
    t.new_turn("x")
    for e in spawns:
        t.on_audit(e)
    assert all(a["handoff"] for a in t.graph()["agents"] if a["id"] != "root")


def test_handoffs_are_limited(make_agent, tmp_path):
    class Loop:
        def chat(self, messages, tools=None):
            if any(m["role"] == "tool" for m in messages):
                obs = [m["content"] for m in messages if m["role"] == "tool"][-1]
                return say("fin:" + obs[:60])
            n = str(messages[1]["content"]).count("Handed over by")
            return call_tool("handoff", {"to": f"Role{n}", "brief": "continue"}, "h")
    agent = make_agent(Loop(), perms=ALLOW, budget=BIG, swarm=SwarmConfig(max_depth=1, max_children=20, child_max_steps=30))
    res = agent.run("go")
    assert res.stop_reason == "final" and MAX_HANDOFFS == 4
    log = [json.loads(x) for x in (tmp_path / "state" / "audit.jsonl").read_text().splitlines()]
    assert sum(1 for e in log if e.get("event") == "spawn" and e.get("handoff")) == MAX_HANDOFFS
    assert "no more hand-overs" in json.dumps(log)


def test_no_handoff_to_the_same_role(make_agent):
    class Same:
        def chat(self, messages, tools=None):
            obs = [m["content"] for m in messages if m["role"] == "tool"]
            if obs:
                return say("fin: " + obs[-1][-120:])
            return call_tool("handoff", {"to": "Codeur", "brief": "écris app.py"}, "h")
    agent = make_agent(Same(), perms=ALLOW, budget=BIG, swarm=SwarmConfig(max_depth=1))
    res = agent.run("Passe la main au Codeur")
    assert res.stop_reason == "final" and "you ARE the Codeur" in res.answer


def test_handoff_answer_is_checked_by_the_critic(make_agent):
    class L:
        def __init__(self):
            self.critic = 0

        def chat(self, messages, tools=None):
            if is_critic(messages):
                self.critic += 1
                return say('{"verdict":"ok","score":8,"issues":[]}')
            if messages[1]["content"].startswith("Testeur:"):
                return say("tests ok")
            if any(m["role"] == "tool" for m in messages):
                return say("??")
            return call_tool("handoff", {"to": "Testeur", "brief": "lance les tests"}, "h")
    llm = L()
    agent = make_agent(llm, perms=ALLOW, budget=BIG, swarm=SwarmConfig(max_depth=1))
    agent.critic_rounds = 1
    assert agent.run("teste").answer == "tests ok" and llm.critic == 1


# ------------------------------------------------------------------------- 3. semantic memory
TOPICS = {"car": ("voiture", "véhicule", "car", "peugeot"), "cat": ("chat", "cat", "félin", "minou"),
          "money": ("budget", "argent", "euros", "money")}


class FakeEmbed:
    model = "fake-embed"

    def __init__(self):
        self.calls = 0

    def __call__(self, texts):
        self.calls += 1
        out = []
        for t in texts:
            low = t.lower()
            out.append([1.0 if any(w in low for w in ws) else 0.0 for ws in TOPICS.values()] + [0.05])
        return out


def test_vector_helpers(tmp_path):
    v = [0.1, -2.0, 3.5]
    assert unpack(pack(v)) == pytest.approx(v)
    assert cosine([1, 0], [1, 0]) == pytest.approx(1) and cosine([1, 0], [0, 1]) == 0 and cosine([], [1]) == 0
    ix = VectorIndex(tmp_path / "v.sqlite3")
    ix.put("a", "txt", "m", v)
    assert ix.get("a", "txt", "m") == pytest.approx(v) and ix.get("a", "other text", "m") is None
    assert ix.get("a", "txt", "other-model") is None and ix.count() == 1


def test_hybrid_recall_finds_by_meaning(tmp_path):
    mem = Memory(tmp_path / "m")
    mem.write("Ma Peugeot bleue est garée au parking B")
    mem.write("Le minou s'appelle Tigrou")
    mem.write("Réunion lundi à 10h")
    assert not any("Peugeot" in h["text"] for h in mem.recall("véhicule")) and mem.last_mode == "keyword"
    emb = FakeEmbed()
    mem.embedder = emb
    hits = mem.recall("véhicule")
    assert mem.last_mode == "hybrid" and hits[0]["text"].startswith("Ma Peugeot") and hits[0]["how"] == "hybrid"
    assert all("Réunion" not in h["text"] for h in hits)
    n = emb.calls
    mem.recall("félin")                                 # stored vectors are reused: only the query is embedded
    assert emb.calls == n + 1 and mem.recall("félin")[0]["text"].startswith("Le minou")
    assert mem.status()["semantic"] and mem.status()["model"] == "fake-embed" and mem.status()["vectors"] == 3


def test_recall_falls_back_to_keywords_when_embeddings_fail(tmp_path):
    mem = Memory(tmp_path / "m")
    mem.write("Le projet s'appelle Orion")
    mem.embedder = lambda texts: None
    assert mem.recall("Orion")[0]["text"] == "Le projet s'appelle Orion" and mem.last_mode == "keyword"

    def boom(texts):
        raise RuntimeError("down")
    mem.embedder = boom
    assert mem.recall("Orion") and mem.last_mode == "keyword"


def test_memory_recall_tool_says_how(ctx):
    from agent.tools.builtin import TOOLS
    tool = next(t for t in TOOLS if t.name == "memory_recall")
    ctx.memory.write("Ma voiture est une Peugeot")
    assert "(keywords)" in tool.func(ctx, {"query": "Peugeot"})
    ctx.memory.embedder = FakeEmbed()
    assert "(meaning + keywords)" in tool.func(ctx, {"query": "véhicule"})


class _Entry:
    def __init__(self, cats):
        self.categories, self.enabled = set(cats), True


class _Lease:
    def __init__(self, entry):
        self.entry, self.base_url, self.model, self.api_key = entry, "http://x/v1", "emb-1", "k"
        self.done = None

    def commit(self, *a):
        self.done = "commit"

    def fail(self, *a):
        self.done = "fail"

    def release(self):
        self.done = "release"


class _Router:
    def __init__(self, entries):
        self.entries, self.leases = entries, []

    def acquire(self, category, prompt_tokens=0, label=None):
        assert category == "embeddings"
        lease = _Lease(next(e for e in self.entries if "embeddings" in e.categories))
        self.leases.append(lease)
        return lease


def test_router_embedder_only_uses_embeddings_keys():
    calls = []

    def embed(base, model, key, texts):
        calls.append((base, model, texts))
        return [[1.0, 0.0] for _ in texts], 5
    chat_only = RouterEmbedder(lambda: _Router([_Entry({"general"})]), embed)
    assert not chat_only.available() and chat_only(["a"]) is None and not calls
    r = _Router([_Entry({"general"}), _Entry({"embeddings"})])
    e = RouterEmbedder(lambda: r, embed)
    assert e.available() and e(["a", "b"]) == [[1.0, 0.0], [1.0, 0.0]] and e.model == "emb-1"
    assert r.leases[0].done == "commit"
    assert RouterEmbedder(lambda: None, embed)(["a"]) is None


# ------------------------------------------------------------------------- 4. business APIs
class FakeFetch:
    def __init__(self, spec=None):
        self.spec, self.calls = spec, []

    def __call__(self, method, url, headers, data, limit):
        self.calls.append((method, url, dict(headers), data))
        if url.endswith("openapi.json"):
            return 200, json.dumps(self.spec or {})
        return 200, json.dumps({"echo": headers.get("Authorization"), "url": url, "token": SECRET.split(" ")[1]})


SPEC = {"paths": {"/customers": {"get": {"summary": "List customers"}, "post": {"summary": "Create"}},
                  "/invoices/{id}": {"delete": {"operationId": "deleteInvoice"}}}}


@pytest.fixture
def reg(tmp_path):
    perms = Permissions()
    sec = SecretStore(tmp_path / "s" / "secrets.json", use_keyring=False)
    f = FakeFetch(SPEC)
    r = ApiRegistry(tmp_path / "s", sec, perms, fetch=f)
    r.fetch_calls, r.permissions = f.calls, perms
    return r


def test_save_masks_and_never_stores_the_secret_in_apis_json(reg, tmp_path):
    v = reg.save({"name": "CRM", "base_url": "https://crm.example.com/api/v1/", "auth_value": SECRET,
                  "openapi_url": "https://crm.example.com/openapi.json", "auto_get": True})
    assert v["auth_set"] and SECRET not in json.dumps(v) and v["auth_mask"] and v["endpoints"] == 3
    assert SECRET not in (tmp_path / "s" / "apis.json").read_text()
    assert reg.items[0]["endpoints"][0] == "GET /customers — List customers"
    assert reg.permissions.api_auto_get == {"crm"}
    v2 = reg.save({"name": "CRM", "base_url": "https://crm.example.com/api/v1", "auto_get": False}, v["id"])
    assert v2["auth_set"] and reg.permissions.api_auto_get == set()       # empty value keeps the secret
    with pytest.raises(ValueError):
        reg.save({"name": "crm", "base_url": "https://x.example.com"})        # duplicate name
    for bad in ({"name": "", "base_url": "https://a.b"}, {"name": "A", "base_url": "ftp://a.b"},
                {"name": "B", "base_url": "https://a.b?x=1"}, {"name": "C", "base_url": "https://a.b", "auth_header": "Bad: h"}):
        with pytest.raises(ValueError):
            reg.save(bad)
    reg.delete(v["id"])
    assert reg.items == [] and reg.secrets.get("api:" + v["id"]) is None


def test_url_confinement(reg):
    reg.save({"name": "CRM", "base_url": "https://crm.example.com/api/v1"})
    a = reg.items[0]
    assert reg.url_for(a, "/customers", {"city": "Paris"}) == "https://crm.example.com/api/v1/customers?city=Paris"
    assert reg.url_for(a, "customers/3") == "https://crm.example.com/api/v1/customers/3"
    for bad in ("https://evil.example.com/x", "//evil.example.com/x", "../../admin", "/a/../../../admin", "file:///etc/passwd"):
        with pytest.raises(ToolError):
            reg.url_for(a, bad)


def test_call_sends_the_header_and_redacts_the_secret(reg):
    reg.save({"name": "CRM", "base_url": "https://crm.example.com", "auth_value": SECRET})
    out = reg.call("crm", "GET", "/customers")
    method, url, headers, _ = reg.fetch_calls[-1]
    assert headers["Authorization"] == SECRET and url == "https://crm.example.com/customers"
    assert out.startswith("HTTP 200 GET /customers") and SECRET not in out and SECRET.split(" ")[1] not in out
    with pytest.raises(ToolError):
        reg.call("nope", "GET", "/")


def test_api_tools_categories_and_approvals(reg, ws):
    reg.save({"name": "CRM", "base_url": "https://crm.example.com"})
    reg.save({"name": "Shop", "base_url": "https://shop.example.com", "spends": True})
    tools = {t.name: t for t in API_TOOLS}
    assert {n: t.category for n, t in tools.items()} == {"api_list": "read", "api_get": "network",
                                                        "api_send": "send", "api_pay": "spend"}
    p = reg.permissions
    get = tools["api_get"]
    assert p.decide("api_get", "network", get.subject_kind, get.subject({"api": "CRM"})).mode == "ask"
    reg.save({"name": "CRM", "base_url": "https://crm.example.com", "auto_get": True}, reg.items[0]["id"])
    assert p.decide("api_get", "network", get.subject_kind, get.subject({"api": "CRM"})).mode == "allow"
    assert p.decide("api_get", "network", get.subject_kind, get.subject({"api": "Shop"})).mode == "ask"
    assert p.decide("api_send", "send", "api", "crm").mode == "ask"
    pay = tools["api_pay"]
    assert p.decide("api_pay", "spend", pay.subject_kind, "shop").mode == "deny"      # default: no spending
    for m in ("ask", "allow"):                                                         # even "allow" asks
        assert Permissions.from_dict({"defaults": {"spend": m}}).decide("api_pay", "spend", pay.subject_kind,
                                                                         "shop").mode == "ask"
    loose = Permissions.from_dict({"defaults": {"network": "allow"}})
    loose.api_auto_get = set()
    assert loose.decide("api_get", "network", "api_get", "crm").mode == "ask"   # not ticked: still asks
    ctx = ToolContext(workspace=ws, memory=None, skills=None, apis=reg)
    with pytest.raises(ToolError):
        tools["api_send"].func(ctx, {"api": "Shop", "method": "POST", "path": "/orders"})   # must use api_pay
    with pytest.raises(ToolError):
        tools["api_pay"].func(ctx, {"api": "CRM", "method": "POST", "path": "/x"})
    with pytest.raises(ToolError):
        tools["api_send"].func(ctx, {"api": "CRM", "method": "GET", "path": "/x"})
    assert "HTTP 200 POST /orders" in tools["api_pay"].func(ctx, {"api": "Shop", "method": "POST", "path": "/orders",
                                                                 "body": {"qty": 1}})
    assert json.loads(reg.fetch_calls[-1][3]) == {"qty": 1}
    listing = tools["api_list"].func(ctx, {})
    assert "CRM: https://crm.example.com (reads without asking)" in listing and "api_pay" in listing
    with pytest.raises(ToolError):
        tools["api_list"].func(ToolContext(workspace=ws, memory=None, skills=None), {})


def test_endpoints_parsing():
    assert endpoints(SPEC) == ["GET /customers — List customers", "POST /customers — Create",
                               "DELETE /invoices/{id} — deleteInvoice"]
    assert endpoints({"paths": {"/x": "bad"}}) == [] and endpoints({}) == []


def test_apis_http_endpoints(app, tmp_path):  # noqa: F811
    base, h, control = app()
    assert call(base, "GET", "/app/apis")[0] == 404                          # not wired in this mode
    control.apis = ApiRegistry(tmp_path / "state", control.secrets, control.perms, fetch=FakeFetch(SPEC))
    st, r = post(base, "/app/apis", {"name": "CRM", "base_url": "https://crm.example.com", "auth_value": SECRET})
    assert st == 201 and r["auth_set"] and SECRET not in json.dumps(r)
    st, lst = call(base, "GET", "/app/apis")
    assert st == 200 and lst["apis"][0]["name"] == "CRM" and SECRET not in json.dumps(lst)
    assert call(base, "POST", "/app/apis", {"name": "X", "base_url": "https://x.y"})[0] == 403      # no CSRF
    st, e = post(base, "/app/apis", {"name": "Bad", "base_url": "nope"})
    assert st == 400 and e["code"] == "bad_url"
    st, r = post(base, f"/app/apis/{r['id']}", {"name": "CRM", "base_url": "https://crm.example.com", "auto_get": True})
    assert st == 200 and r["auto_get"] and r["auth_set"]
    assert post(base, "/app/apis/ffffffffff/delete")[0] == 404
    assert post(base, f"/app/apis/{r['id']}/delete")[0] == 200
    assert call(base, "GET", "/app/apis")[1]["apis"] == []
    audit = (tmp_path / "state" / "audit.jsonl").read_text()
    assert "settings_api" in audit and SECRET not in audit
    from agent.harness_connect import CONNECT_PAGE
    assert 'id="apiform"' in CONNECT_PAGE and "X-CSRF-Token" in CONNECT_PAGE


def test_api_tools_are_given_only_when_an_api_exists(tmp_path, ws):
    import argparse
    from agent import cli
    from agent.audit import AuditLog
    sec = SecretStore(tmp_path / "s" / "secrets.json", use_keyring=False)
    reg = ApiRegistry(tmp_path / "s", sec, Permissions(), fetch=FakeFetch())
    ctx = ToolContext(workspace=ws, memory=Memory(tmp_path / "m"), skills=SkillLibrary([]), apis=reg)
    args = argparse.Namespace(offline=True, provider="mock", model=None, base_url=None, max_steps=5, max_tokens=1000,
                              max_tool_calls=5, swarm=False, max_depth=0, lang="en", _router=None, keys=None)
    a = cli.new_agent(args, Permissions(), ctx, AuditLog(tmp_path / "a.jsonl"), lambda *x: True, lambda *x: None)
    assert "api_get" not in a.registry.tools
    reg.save({"name": "CRM", "base_url": "https://crm.example.com"})
    a = cli.new_agent(args, Permissions(), ctx, AuditLog(tmp_path / "a.jsonl"), lambda *x: True, lambda *x: None)
    assert {"api_list", "api_get", "api_send", "api_pay"} <= set(a.registry.tools)
