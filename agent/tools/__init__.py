"""Tool registry. Every tool declares a risk category used by the permission model."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from ..memory import Memory
from ..permissions import CATEGORIES
from ..skills import SkillLibrary


class ToolError(Exception):
    """Expected tool failure; the message is returned to the model as the observation."""


@dataclass
class ToolContext:
    workspace: Path
    memory: Memory
    skills: SkillLibrary
    shell_timeout: int = 60
    max_output: int = 12000


@dataclass
class Tool:
    name: str
    description: str
    category: str
    parameters: dict
    func: Callable[[ToolContext, dict], str]
    subject_kind: str | None = None   # "path" | "command" | "url"
    subject_arg: str | Callable[[dict], str] | None = None

    def __post_init__(self):
        assert self.category in CATEGORIES, self.category

    def subject(self, args: dict) -> str | None:
        if self.subject_arg is None:
            return None
        if callable(self.subject_arg):
            return self.subject_arg(args)
        v = args.get(self.subject_arg)
        return None if v is None else str(v)

    def schema(self) -> dict:
        return {"type": "function", "function": {
            "name": self.name,
            "description": f"[{self.category}] {self.description}",
            "parameters": self.parameters}}


def params(required: list[str] | None = None, **props: Any) -> dict:
    return {"type": "object", "properties": props, "required": required or []}


def s(desc: str) -> dict:
    return {"type": "string", "description": desc}


@dataclass
class Registry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def add(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self.tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self.tools


def default_registry(enable_web: bool = True, enable_github: bool = True) -> Registry:
    from . import builtin, files, shell, web, github

    reg = Registry()
    for t in files.TOOLS + shell.TOOLS + builtin.TOOLS:
        reg.add(t)
    if enable_web:
        for t in web.TOOLS:
            reg.add(t)
    if enable_github:
        for t in github.TOOLS:
            reg.add(t)
    return reg
