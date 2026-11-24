"""v0.9.4: a short beginner README; the technical documentation lives in docs/. No broken local links."""
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
DOCS = sorted([REPO / "README.md"] + list((REPO / "docs").glob("*.md")))
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")


@pytest.mark.parametrize("md", DOCS, ids=lambda p: str(p.relative_to(REPO)))
def test_local_links_and_images_exist(md):
    text = re.sub(r"```.*?```", "", md.read_text(encoding="utf-8"), flags=re.S)
    for target in LINK.findall(text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path = target.split("#", 1)[0]
        assert (md.parent / path).exists(), f"{md.name}: broken link {target}"


def test_readme_is_short_with_downloads_steps_and_screenshot():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert len(readme.splitlines()) < 120
    for f in ("macos-arm64.zip", "macos-intel.zip", "windows-x64.exe"):
        assert readme.count(f"releases/latest/download/AutonomousAgent-{f}") == 2      # EN + FR
    assert readme.count("docs/images/screenshot.png") == 2
    assert "## English" in readme and "## Français" in readme and "console.groq.com/keys" in readme
    assert "Get started in 3 steps" in readme and "Démarrer en 3 étapes" in readme


def test_repo_root_keeps_only_the_essentials():
    root = {p.name for p in REPO.iterdir() if not p.name.startswith(".") or p.name in (".env.example",)}
    root -= {"__pycache__", "dist", "build", "out"}
    root = {n for n in root if not n.endswith(".egg-info")}
    assert root <= {"README.md", "LICENSE", "pyproject.toml", "permissions.yaml", "agent", "skills", "tests",
                    "packaging", "docs", "assets"}, root
    for f in ("SECURITY.md", "examples/.env.example", "examples/providers.example.yaml", "changelog.md",
              "architecture.md", "permissions.md", "swarm.md", "tools.md", "development.md"):
        assert (REPO / "docs" / f).is_file(), f
