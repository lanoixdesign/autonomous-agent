"""LLM backends: any OpenAI-compatible /chat/completions endpoint (urllib, no SDK), plus a mock."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import USER_AGENT
from .redact import redact

PROVIDERS: dict[str, dict[str, Any]] = {
    "groq": {"base_url": "https://api.groq.com/openai/v1", "key_env": "GROQ_API_KEY", "model": "openai/gpt-oss-120b"},
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY", "model": "gpt-4o-mini"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "key_env": "OPENROUTER_API_KEY", "model": "openai/gpt-4o-mini"},
    "ollama": {"base_url": "http://localhost:11434/v1", "key_env": None, "model": "llama3.1"},
    "custom": {"base_url": None, "key_env": "AGENT_API_KEY", "model": None},
}


class LLMError(Exception):
    def __init__(self, message: str, status: int | None = None, retry_after: float | None = None):
        super().__init__(message)
        self.status, self.retry_after = status, retry_after


@dataclass
class LLMReply:
    message: dict          # OpenAI-style assistant message (content, tool_calls)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0              # in the keys file currency, when the key router knows the pricing
    key: str | None = None         # name of the key that served the call (key router)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class OpenAICompatible:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: int = 120,
                 temperature: float = 0.2, retries: int = 2, max_tokens: int | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout = timeout
        self.temperature = temperature
        self.retries = retries
        self.max_tokens = max_tokens

    def __repr__(self) -> str:  # never show the key
        return f"OpenAICompatible(base_url={self.base_url!r}, model={self.model!r})"

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMReply:
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": self.temperature}
        if self.max_tokens:
            payload["max_tokens"] = self.max_tokens
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT, "Accept": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        data = json.dumps(payload).encode("utf-8")
        last = None
        for attempt in range(self.retries + 1):
            req = urllib.request.Request(self.base_url + "/chat/completions", data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    body = json.loads(r.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")[:800]
                try:
                    retry_after = float(e.headers.get("Retry-After")) if e.headers.get("Retry-After") else None
                except (TypeError, ValueError):
                    retry_after = None
                last = LLMError(f"HTTP {e.code} from {self.base_url}: {redact(detail, [self._api_key or ''])}",
                                status=e.code, retry_after=retry_after)
                if e.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise last
            except (urllib.error.URLError, TimeoutError) as e:
                last = LLMError(f"cannot reach {self.base_url}: {e}")
                if attempt == self.retries:
                    raise last
            time.sleep(2 ** attempt)
        try:
            msg = body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise LLMError(f"unexpected response: {str(body)[:300]}")
        usage = body.get("usage") or {}
        clean = {"role": "assistant", "content": msg.get("content")}
        if msg.get("tool_calls"):
            clean["tool_calls"] = [{"id": tc.get("id") or f"call_{i}", "type": "function",
                                    "function": {"name": tc["function"]["name"],
                                                 "arguments": tc["function"].get("arguments") or "{}"}}
                                   for i, tc in enumerate(msg["tool_calls"])]
        return LLMReply(clean, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))


class MockLLM:
    """Offline backend for tests and demos.

    With a `script` (list of steps), each call returns the next step:
      {"tool": "name", "args": {...}}   -> one tool call
      {"tools": [{"tool":..., "args":...}, ...]} -> several tool calls
      {"content": "text"}               -> final answer
    Without a script it runs a small default plan: list_files -> memory_recall -> answer
    that quotes what it observed. Token usage is estimated as chars/4.
    """

    def __init__(self, script: list[dict] | None = None):
        self.script = list(script) if script is not None else None
        self.calls = 0
        self.model = "mock"
        self._lock = threading.Lock()   # sub-agents may call one backend from several threads

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMReply:
        prompt_chars = sum(len(str(m.get("content") or "")) for m in messages)
        with self._lock:
            self.calls += 1
            calls_now = self.calls
            if self.script is not None:
                step = self.script.pop(0) if self.script else {"content": "(mock script exhausted)"}
            else:
                step = self._default(messages)
        if "content" in step:
            msg = {"role": "assistant", "content": step["content"]}
        else:
            calls = step.get("tools") or [step]
            msg = {"role": "assistant", "content": step.get("say"), "tool_calls": [
                {"id": f"mock_{calls_now}_{i}", "type": "function",
                 "function": {"name": c["tool"], "arguments": json.dumps(c.get("args", {}))}}
                for i, c in enumerate(calls)]}
        return LLMReply(msg, prompt_chars // 4, len(json.dumps(msg)) // 4)

    @staticmethod
    def _default(messages: list[dict]) -> dict:
        task = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        turn_start = max((i for i, m in enumerate(messages) if m["role"] == "user"), default=0)
        done = [m for m in messages[turn_start:] if m["role"] == "tool"]
        if len(done) == 0:
            return {"say": "Plan: 1) look at the workspace 2) check memory 3) answer.",
                    "tool": "list_files", "args": {"path": "."}}
        if len(done) == 1:
            return {"tool": "memory_recall", "args": {"query": task}}
        files = done[0]["content"].splitlines()
        return {"content": f"[mock] Task: {task!r}. Workspace has {len(files)} file(s): "
                           f"{', '.join(files[:5])}. Memory: {done[1]['content'][:120]}"}


def make_llm(provider: str | None = None, model: str | None = None) -> Any:
    provider = (provider or os.environ.get("AGENT_PROVIDER") or "mock").lower()
    if provider == "mock":
        script = None
        path = os.environ.get("AGENT_MOCK_SCRIPT")
        if path:
            with open(path, encoding="utf-8") as f:
                script = json.load(f)
        return MockLLM(script)
    if provider not in PROVIDERS:
        raise LLMError(f"unknown provider {provider!r}; choose one of: mock, {', '.join(PROVIDERS)}")
    cfg = PROVIDERS[provider]
    base = os.environ.get("AGENT_BASE_URL") or cfg["base_url"]
    if not base:
        raise LLMError("AGENT_BASE_URL is required for provider 'custom'")
    model = model or os.environ.get("AGENT_MODEL") or cfg["model"]
    if not model:
        raise LLMError("AGENT_MODEL (or --model) is required for provider 'custom'")
    key = os.environ.get("AGENT_API_KEY") or (os.environ.get(cfg["key_env"]) if cfg["key_env"] else None)
    if cfg["key_env"] and not key and provider != "custom":
        raise LLMError(f"missing API key: set {cfg['key_env']} (see .env.example)")
    return OpenAICompatible(base, model, key)


class RoutedLLM:
    """Chat backend that takes its key from a KeyRouter (agent/keys.py) for one category (text, code...).

    Per call: reserve a request on the best key (prompt tokens estimated generously at chars/3, and the
    completion capped with `max_tokens` to what the limits allow), call it, commit the real usage. On a
    429 / 5xx / network error the key cools down and the next key is tried; when no key is left the
    call fails with a clear LLMError (the agent loop stops with "llm_error")."""

    def __init__(self, router: Any, category: str = "text", client_factory: Any = None):
        self.router, self.category = router, category
        self.client_factory = client_factory or (lambda base_url, model, key, max_tokens: OpenAICompatible(
            base_url, model, key, retries=0, max_tokens=max_tokens))
        self.model = f"router:{category}"

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMReply:
        from .keys import KeysExhausted

        est_prompt = (len(json.dumps(messages, ensure_ascii=False)) + len(json.dumps(tools or []))) // 3 + 16
        errors = []
        while True:
            try:
                lease = self.router.acquire(self.category, prompt_tokens=est_prompt)
            except KeysExhausted as e:
                raise LLMError(str(e) + (f"; errors: {' | '.join(errors)}" if errors else ""))
            if not lease.base_url or not lease.model:
                lease.release()
                raise LLMError(f"key {lease.name}: base_url and a model for '{self.category}' are required")
            client = self.client_factory(lease.base_url, lease.model, lease.api_key, lease.max_completion_tokens)
            try:
                reply = client.chat(messages, tools)
            except LLMError as e:
                if e.status is not None and e.status != 429 and e.status < 500:
                    lease.fail(e.status)
                    raise   # a 4xx other than 429 is not a key problem: do not burn the other keys
                lease.fail(e.status, e.retry_after)
                errors.append(f"{lease.name}: {e}")
                continue
            except Exception:
                lease.fail(None)
                raise
            pt, ct = reply.prompt_tokens, reply.completion_tokens
            if not pt and not ct:   # provider did not report usage: keep the estimate
                pt, ct = est_prompt, len(json.dumps(reply.message)) // 3
            lease.commit(pt, ct)
            reply.cost, reply.key = lease.entry.cost(pt, ct), lease.name
            return reply


class SwitchLLM:
    """The chat backend chosen at EACH call from the Settings page (no restart needed):
    demo mode -> offline mock; keys saved in the Settings page for this category -> key router;
    otherwise the backend picked at start (.env key, providers.yaml, or the mock)."""

    def __init__(self, control: Any, category: str, fallback_factory: Any):
        self.control, self.category, self.fallback_factory = control, category, fallback_factory
        self._fallback = None
        self._mock = None
        self._routed = None
        self._lock = threading.Lock()

    @property
    def model(self) -> str:
        mode = self.control.backend_mode(self.category)
        return {"demo": "mock", "ui": f"settings:{self.category}"}.get(mode) or getattr(self._get_fallback(), "model", "?")

    def _get_fallback(self) -> Any:
        with self._lock:
            if self._fallback is None:
                self._fallback = self.fallback_factory()
            return self._fallback

    def current(self) -> Any:
        mode = self.control.backend_mode(self.category)
        if mode == "demo":
            with self._lock:
                self._mock = self._mock or MockLLM()
                return self._mock
        if mode == "ui":
            with self._lock:
                self._routed = self._routed or RoutedLLM(self.control.router, self.category)
                return self._routed
        return self._get_fallback()

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMReply:
        return self.current().chat(messages, tools)
