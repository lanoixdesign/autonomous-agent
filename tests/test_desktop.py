"""Double-click launcher (agent/desktop.py): user folder, backend choice, port, language, end-to-end start."""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from agent import desktop, i18n

REPO = Path(__file__).resolve().parent.parent
KEY_ENV = ("AGENT_PROVIDER", "GROQ_API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "AGENT_MOCK_SCRIPT",
           "AGENT_LANG", "AGENT_PORT", "AGENT_HOME", "AGENT_HARNESS_TOKEN", "LC_ALL", "LC_MESSAGES", "LANG",
           "LANGUAGE")


@pytest.fixture
def clean_env(monkeypatch):
    for k in KEY_ENV:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_prepare_home_creates_folder_without_overwriting(tmp_path, clean_env):
    home = tmp_path / "AA"
    p = desktop.prepare_home(home)
    assert p["workspace"].is_dir() and p["data"].is_dir()
    env = p["env"].read_text()
    assert "GROQ_API_KEY" in env
    # nothing active: every non-empty line is a comment
    assert all(not ln.strip() or ln.lstrip().startswith("#") for ln in env.splitlines())
    assert p["permissions"].read_text() == (REPO / "permissions.yaml").read_text()
    assert p["providers_example"].is_file() and not p["providers"].exists()
    # the key file is outside the agent's workspace
    assert p["workspace"] not in p["env"].parents
    p["env"].write_text("GROQ_API_KEY=mine\n")
    p["permissions"].write_text("defaults: {}\n")
    desktop.prepare_home(home)
    assert p["env"].read_text() == "GROQ_API_KEY=mine\n" and p["permissions"].read_text() == "defaults: {}\n"


def test_home_dir_default_and_override(tmp_path, clean_env):
    assert desktop.home_dir() == (Path.home() / "AutonomousAgent").resolve()
    clean_env.setenv("AGENT_HOME", str(tmp_path / "x"))
    assert desktop.home_dir() == (tmp_path / "x").resolve()


def test_pick_provider(tmp_path, clean_env):
    p = desktop.prepare_home(tmp_path)
    assert desktop.pick_provider(p) == (["--provider", "mock"], "demo")
    clean_env.setenv("OPENAI_API_KEY", "k")
    assert desktop.pick_provider(p) == (["--provider", "openai"], "env")
    clean_env.setenv("GROQ_API_KEY", "k")
    assert desktop.pick_provider(p) == (["--provider", "groq"], "env")
    clean_env.setenv("AGENT_PROVIDER", "ollama")
    assert desktop.pick_provider(p) == ([], "env")
    p["providers"].write_text("providers: []\n")
    assert desktop.pick_provider(p) == (["--keys", str(p["providers"])], "keys")


def test_free_port(clean_env):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        busy = s.getsockname()[1]
        clean_env.setenv("AGENT_PORT", str(busy))
        assert desktop.free_port() == busy          # forced
    clean_env.delenv("AGENT_PORT")
    port = desktop.free_port()
    assert 0 < port < 65536


def test_build_argv(tmp_path, clean_env):
    p = desktop.prepare_home(tmp_path)
    argv = desktop.build_argv(p, 9000, ["--provider", "mock"])
    assert argv[:5] == ["serve", "--host", "127.0.0.1", "--port", "9000"]   # never exposed beyond localhost
    pairs = dict(zip(argv[5::2], argv[6::2]))
    assert pairs == {"--workspace": str(p["workspace"]), "--state-dir": str(p["data"]),
                     "--permissions": str(p["permissions"]), "--provider": "mock"}


@pytest.mark.parametrize("value,expected", [("fr_FR.UTF-8", "fr"), ("French_France", "fr"), ("fr-CA", "fr"),
                                            ("en_US.UTF-8", "en"), ("de_DE", "en")])
def test_system_lang_from_locale(value, expected, clean_env):
    clean_env.setenv("LANG", value)
    assert desktop.system_lang() == expected


def test_system_lang_override(clean_env):
    clean_env.setenv("LANG", "fr_FR.UTF-8")
    clean_env.setenv("AGENT_LANG", "en")
    assert desktop.system_lang() == "en"


def test_desktop_strings_are_bilingual_and_not_sent_to_pages():
    keys = [k for k in i18n.EN if k.startswith("desktop.")]
    assert keys and all(k in i18n.FR for k in keys)
    assert not any(k.startswith("desktop.") for k in i18n.ui_strings()["fr"])


def test_launcher_starts_harness_end_to_end(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if k not in KEY_ENV and k != "PYTHONPATH"}
    env.update(AGENT_HOME=str(tmp_path / "home"), AGENT_NO_BROWSER="1", AGENT_PORT=str(port),
               LANG="fr_FR.UTF-8", PYTHONPATH=str(REPO))
    proc = subprocess.Popen([sys.executable, "-m", "agent.desktop"], cwd=tmp_path, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        health = None
        for _ in range(100):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                    health = json.loads(r.read())
                break
            except OSError:
                time.sleep(0.2)
        assert health and health["status"] == "ok", "harness did not start"
        assert health["keys"]["provider"] == "mock"
        assert health["persistence"].startswith(str(tmp_path / "home" / "data"))
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            assert r.status == 200
    finally:
        proc.terminate()
        out, _ = proc.communicate(timeout=20)
    assert "mode DÉMO" in out and str(tmp_path / "home") in out
    assert (tmp_path / "home" / ".env").is_file() and (tmp_path / "home" / "workspace").is_dir()
