import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def cli(*args, cwd, env=None, stdin=""):
    e = {**os.environ, "AGENT_PROVIDER": "mock", **(env or {})}
    return subprocess.run([sys.executable, "-m", "agent", *args], cwd=cwd, env={**e, "PYTHONPATH": str(REPO)},
                          capture_output=True, text=True, input=stdin, timeout=60)


def test_run_mock_end_to_end(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    r = cli("run", "list the files", "--workspace", str(tmp_path), "--offline", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "a.txt" in r.stdout and "[final]" in r.stderr
    audit = (tmp_path / ".agent" / "audit.jsonl").read_text().splitlines()
    assert json.loads(audit[0])["tool"] == "list_files"


def test_run_with_script_and_permissions_file(tmp_path):
    script = tmp_path / "s.json"
    script.write_text(json.dumps([{"tool": "shell", "args": {"command": "echo hi > out.txt"}}, {"content": "ok"}]))
    perms = tmp_path / "p.json"
    perms.write_text(json.dumps({"defaults": {"execute": "allow"}}))
    ws = tmp_path / "w"
    r = cli("run", "go", "-w", str(ws), "-p", str(perms), cwd=tmp_path, env={"AGENT_MOCK_SCRIPT": str(script)})
    assert r.returncode == 0, r.stderr
    assert (ws / "out.txt").read_text().strip() == "hi"


def test_memory_commands(tmp_path):
    assert cli("memory", "add", "remember the milk", "-w", str(tmp_path), cwd=tmp_path).returncode == 0
    assert "milk" in cli("memory", "recall", "milk", "-w", str(tmp_path), cwd=tmp_path).stdout
    assert "forgot 1" in cli("memory", "forget", "milk", "-w", str(tmp_path), cwd=tmp_path).stdout


def test_chat_mode_with_piped_input(tmp_path):
    r = cli("chat", "-w", str(tmp_path), "--offline", cwd=tmp_path, stdin="hello\n/exit\n")
    assert r.returncode == 0 and "agent> [mock]" in r.stdout


def test_missing_key_is_a_clean_error(tmp_path):
    env = {k: "" for k in ("GROQ_API_KEY", "AGENT_API_KEY")}
    r = cli("run", "x", "--provider", "groq", "-w", str(tmp_path), cwd=tmp_path, env=env)
    assert r.returncode == 2 and "GROQ_API_KEY" in r.stderr
