"""Skills: folders `skills/<name>/SKILL.md` with a YAML-like frontmatter (name, description).

Only the index (name + description) goes into the system prompt; the body is loaded on demand
by the `load_skill` tool, so many skills cost almost no context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,63}$")


@dataclass
class Skill:
    name: str
    description: str
    path: Path

    def body(self) -> str:
        return parse_skill_file(self.path.read_text(encoding="utf-8"))[1]


def parse_skill_file(text: str) -> tuple[dict, str]:
    meta: dict = {}
    body = text
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            head = text[3:end]
            body = text[end + 4:].lstrip("\n")
            for line in head.splitlines():
                if ":" in line:
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


class SkillLibrary:
    def __init__(self, dirs: list[str | Path]):
        self.skills: dict[str, Skill] = {}
        for d in dirs:
            d = Path(d)
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*/SKILL.md")):
                meta, _ = parse_skill_file(f.read_text(encoding="utf-8"))
                name = meta.get("name") or f.parent.name
                if not NAME_RE.match(name) or not meta.get("description"):
                    continue  # invalid skills are skipped, never half-loaded
                self.skills.setdefault(name, Skill(name, meta["description"], f))  # first dir wins

    def names(self) -> list[str]:
        return sorted(self.skills)

    def index(self) -> str:
        return "\n".join(f"- {s.name}: {s.description}" for s in sorted(self.skills.values(), key=lambda s: s.name))

    def load(self, name: str) -> str:
        if name not in self.skills:
            raise KeyError(f"unknown skill {name!r}; available: {', '.join(self.names()) or 'none'}")
        return self.skills[name].body()
