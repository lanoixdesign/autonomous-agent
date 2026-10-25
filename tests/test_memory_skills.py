from agent.memory import Memory
from agent.skills import SkillLibrary, parse_skill_file


def test_memory_persists_and_recalls(tmp_path):
    m = Memory(tmp_path / "mem")
    m.write("Prefers answers in French", kind="profile")
    m.write("Release 0.2 planned for next week", tags=["release"])
    m.write("The CI runs on GitHub Actions")
    m2 = Memory(tmp_path / "mem")  # reopen: durable
    hits = m2.recall("release planning")
    assert hits and "Release 0.2" in hits[0]["text"]
    assert m2.recall("French")[0]["kind"] == "profile"
    assert "French" in m2.context()


def test_forget_by_text_and_id(tmp_path):
    m = Memory(tmp_path / "mem")
    e = m.write("temporary note one")
    m.write("keep me")
    m.write("Lives in a profile line", kind="profile")
    assert m.forget(e["id"]) == 1
    assert m.forget("profile line") == 1
    assert [x["text"] for x in m.entries()] == ["keep me"]
    assert m.profile_lines() == []


def test_memory_redacts_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_TOKEN", "tok_abcdefghijkl")
    m = Memory(tmp_path / "mem")
    m.write("my key is tok_abcdefghijkl and gsk_ABCDEFGHIJKLMNOPQRSTUV")
    raw = (tmp_path / "mem" / "journal.jsonl").read_text()
    assert "tok_abcdefghijkl" not in raw and "gsk_ABCDEF" not in raw


def test_skill_frontmatter_and_invalid_skipped(tmp_path):
    d = tmp_path / "skills"
    (d / "good").mkdir(parents=True)
    (d / "good" / "SKILL.md").write_text("---\nname: good\ndescription: Does good things\n---\n# Body\nstep 1\n")
    (d / "bad").mkdir()
    (d / "bad" / "SKILL.md").write_text("no frontmatter here")
    lib = SkillLibrary([d])
    assert lib.names() == ["good"]
    assert lib.load("good").startswith("# Body")
    assert "good: Does good things" in lib.index()
    meta, body = parse_skill_file("---\nname: x\ndescription: \"quoted\"\n---\nB")
    assert meta == {"name": "x", "description": "quoted"} and body == "B"


def test_shipped_skills_are_valid():
    from pathlib import Path
    lib = SkillLibrary([Path(__file__).resolve().parent.parent / "skills"])
    assert lib.names() == ["code-review", "release-notes", "research"]
