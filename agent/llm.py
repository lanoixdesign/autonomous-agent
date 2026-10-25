"""LLM backends: any OpenAI-compatible /chat/completions endpoint (urllib, no SDK), plus a mock."""
from __future__ import annotations

import json
import os
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
    pass


@dataclass
class LLMReply:
    message: dict          # OpenAI-style assistant message (content, tool_calls)
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class OpenAICompatible:
    def __init__(self, base_url: str, model: str, api_key: str | None = None, timeout: int = 120,
                 temperature: float = 0.2, retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._api_key = api_key
        self.timeout = timeout
        self.temperature = temperature
        self.retries = retries

    def __repr__(self) -> str:  # never show the key
        return f"OpenAICompatible(base_url={self.base_url!r}, model={self.model!r})"

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMReply:
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "temperature": self.temperature}
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
                last = LLMError(f"HTTP {e.code} from {self.base_url}: {redact(detail, [self._api_key or ''])}")
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

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMReply:
        self.calls += 1
        prompt_chars = sum(len(str(m.get("content") or "")) for m in messages)
        if self.script is not None:
            step = self.script.pop(0) if self.script else {"content": "(mock script exhausted)"}
        else:
            step = self._default(messages)
        if "content" in step:
            msg = {"role": "assistant", "content": step["content"]}
        else:
            calls = step.get("tools") or [step]
            msg = {"role": "assistant", "content": step.get("say"), "tool_calls": [
                {"id": f"mock_{self.calls}_{i}", "type": "function",
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
