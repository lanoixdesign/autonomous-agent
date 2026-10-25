import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.audit import AuditLog  # noqa: E402
from agent.loop import Agent, Budget  # noqa: E402
from agent.memory import Memory  # noqa: E402
from agent.permissions import Permissions  # noqa: E402
from agent.skills import SkillLibrary  # noqa: E402
from agent.tools import ToolContext, default_registry  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def ws(tmp_path):
    w = tmp_path / "ws"
    w.mkdir()
    (w / "hello.txt").write_text("hello world\nsecond line\n")
    (w / ".env").write_text("SECRET=1\n")
    return w


@pytest.fixture
def ctx(ws, tmp_path):
    return ToolContext(workspace=ws, memory=Memory(tmp_path / "state" / "memory"),
                       skills=SkillLibrary([REPO / "skills"]))


@pytest.fixture
def make_agent(ctx, tmp_path):
    def _make(llm, perms=None, confirm=None, budget=None, **kw):
        kwargs = dict(budget=budget or Budget(), **kw)
        if confirm is not None:
            kwargs["confirm"] = confirm
        return Agent(llm, default_registry(enable_web=True, enable_github=True), perms or Permissions(),
                     AuditLog(tmp_path / "state" / "audit.jsonl"), ctx, **kwargs)
    return _make
