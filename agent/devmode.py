"""Developer mode: small projects in <work folder>/projects/<name>/, built by a "Coder" and checked by a
"Tester" (two swarm helpers), with a live preview (sandboxed iframe), tests that run in the sandbox and a
.zip download. Everything stays inside the work folder."""
from __future__ import annotations

import hashlib
import hmac
import io
import mimetypes
import os
import re
import secrets
import time
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

from . import sandbox

KINDS = ("web", "python")
ROOT = "projects"
MAX_PROJECTS = 200
ZIP_MAX = 50 * 1024 * 1024
SKIP = {"__pycache__", ".pytest_cache", ".tmp", ".git", "node_modules", ".venv"}
PREVIEW_CSP = ("sandbox allow-scripts allow-forms allow-modals; default-src 'self' data: blob:; "
               "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
               "font-src 'self' data:; media-src 'self' data: blob:; connect-src 'none'; form-action 'none'; "
               "frame-ancestors 'self'; base-uri 'none'")


class DevError(ValueError):
    def __init__(self, code: str, msg: str):
        super().__init__(msg)
        self.code = code
        self.params: dict = {}


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower().translate(str.maketrans(
        "àâäáãåçéèêëíìîïñóòôöõúùûüýÿœæ", "aaaaaaceeeeiiiinooooouuuuyyoa"))).strip("-")
    return s[:40]


T = {
    "en": {"title": "My website", "hello": "Hello!", "lead": "This page was created by your assistant. Ask it to change anything.",
           "button": "Click me", "clicked": "Thanks for clicking! ({n})", "footer": "Made with Autonomous Agent",
           "py_readme": "A small Python program.\n\nRun it: `python main.py`\nTest it: `python -m pytest` (or `python -m unittest`)\n",
           "greet": "Hello, {name}!", "world": "world", "doc": "Return a friendly greeting."},
    "fr": {"title": "Mon site", "hello": "Bonjour !", "lead": "Cette page a été créée par ton assistant. Demande-lui de changer ce que tu veux.",
           "button": "Clique ici", "clicked": "Merci pour le clic ! ({n})", "footer": "Fait avec Autonomous Agent",
           "py_readme": "Un petit programme Python.\n\nLancer : `python main.py`\nTester : `python -m pytest` (ou `python -m unittest`)\n",
           "greet": "Bonjour, {name} !", "world": "tout le monde", "doc": "Renvoie une salutation amicale."},
}


def template(kind: str, name: str, lang: str = "en") -> dict[str, str]:
    t = T.get(lang, T["en"])
    if kind == "web":
        return {
            "index.html": f"""<!doctype html>
<html lang="{lang}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{name}</title>
  <link rel="stylesheet" href="style.css">
</head>
<body>
  <main class="card">
    <h1>{t['hello']}</h1>
    <p>{t['lead']}</p>
    <button id="btn" type="button">{t['button']}</button>
    <p id="out" aria-live="polite"></p>
  </main>
  <footer>{t['footer']}</footer>
  <script src="script.js"></script>
</body>
</html>
""",
            "style.css": """:root { color-scheme: light dark; --bg: #f6f7fb; --fg: #1d2330; --card: #fff; --accent: #4f6bed; }
@media (prefers-color-scheme: dark) { :root { --bg: #12151c; --fg: #e8ebf2; --card: #1c212b; --accent: #8ea2ff; } }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: flex; flex-direction: column; align-items: center; justify-content: center;
       font-family: system-ui, -apple-system, "Segoe UI", sans-serif; background: var(--bg); color: var(--fg); padding: 24px; }
.card { background: var(--card); border-radius: 16px; padding: 32px; max-width: 520px; width: 100%;
        box-shadow: 0 8px 30px rgba(0,0,0,.08); text-align: center; }
h1 { margin-top: 0; }
button { background: var(--accent); color: #fff; border: 0; border-radius: 999px; padding: 12px 22px; font-size: 1rem; cursor: pointer; }
footer { margin-top: 18px; opacity: .6; font-size: .85rem; }
""",
            "script.js": f"""// {t['button']}
let clicks = 0;
document.getElementById("btn").addEventListener("click", () => {{
  clicks += 1;
  document.getElementById("out").textContent = {t['clicked']!r}.replace("{{n}}", clicks);
}});
""",
        }
    if kind == "python":
        mod = "main"
        return {
            "main.py": f'''"""{name}: {t['py_readme'].splitlines()[0]}"""


def greet(name: str) -> str:
    """{t['doc']}"""
    return f"{t['greet']}"


def main() -> None:
    print(greet("{t['world']}"))


if __name__ == "__main__":
    main()
''',
            "test_main.py": f'''import unittest

from {mod} import greet


class GreetTest(unittest.TestCase):
    def test_greet(self):
        self.assertEqual(greet("Ada"), "{t['greet'].replace('{name}', 'Ada')}")


if __name__ == "__main__":
    unittest.main()
''',
            "README.md": f"# {name}\n\n{t['py_readme']}",
        }
    raise DevError("bad_kind", "kind must be web or python")


class Projects:
    def __init__(self, workspace: Path | str, secret: bytes | None = None, deny: list[Path] | None = None):
        self.ws = Path(os.path.realpath(workspace))
        self.root = self.ws / ROOT
        self.secret = secret or secrets.token_bytes(32)
        self.deny = deny or []

    # ---------------------------------------------------------------- listing / creating
    def path(self, name: str) -> Path:
        if not name or slug(name) != name:
            raise DevError("bad_name", "unknown project")
        p = self.root / name
        if p.is_symlink() or not p.is_dir() or not sandbox.inside(self.root, p):
            raise DevError("no_project", "unknown project")
        return p

    @staticmethod
    def kind_of(p: Path) -> str:
        if (p / "index.html").is_file():
            return "web"
        if any(p.glob("*.py")):
            return "python"
        return "other"

    def _files(self, p: Path):
        for d, dirs, files in os.walk(p, followlinks=False):
            dirs[:] = sorted(x for x in dirs if x not in SKIP and not x.startswith(".") and not (Path(d) / x).is_symlink())
            for f in sorted(files):
                q = Path(d) / f
                if not q.is_symlink() and q.is_file() and not f.startswith("."):
                    yield q

    def info(self, p: Path) -> dict:
        files = list(self._files(p))
        kind = self.kind_of(p)
        mtime = max([q.stat().st_mtime for q in files] + [p.stat().st_mtime])
        return {"name": p.name, "kind": kind, "files": len(files), "bytes": sum(q.stat().st_size for q in files),
                "mtime": int(mtime), "path": f"{ROOT}/{p.name}",
                "list": [q.relative_to(p).as_posix() for q in files[:30]],
                "preview": self.preview_url(p.name) if kind == "web" else None,
                "tests": kind == "python" or kind == "web"}

    def list(self) -> list[dict]:
        if not self.root.is_dir():
            return []
        out = [self.info(p) for p in sorted(self.root.iterdir())[:MAX_PROJECTS]
               if p.is_dir() and not p.is_symlink() and not p.name.startswith(".") and slug(p.name) == p.name]
        out.sort(key=lambda x: -x["mtime"])
        return out

    def create(self, name: str, kind: str, lang: str = "en") -> dict:
        if kind not in KINDS:
            raise DevError("bad_kind", "kind must be web or python")
        s = slug(name)
        if not s:
            raise DevError("bad_name", "give the project a name (letters or numbers)")
        if self.root.is_symlink():
            raise DevError("bad_name", "the projects folder is a link")
        p = self.root / s
        if os.path.lexists(p):
            raise DevError("exists", f"a project named {s} already exists")
        lang = lang if lang in T else "en"
        files = template(kind, (name or s).strip()[:60], lang)
        p.mkdir(parents=True)
        for rel, text in files.items():
            (p / rel).write_text(text, encoding="utf-8")
        return self.info(p)

    # ---------------------------------------------------------------- preview
    def token(self, name: str) -> str:
        return hmac.new(self.secret, b"preview:" + name.encode(), hashlib.sha256).hexdigest()[:24]

    def preview_url(self, name: str) -> str:
        return f"/preview/{self.token(name)}/{name}/"

    def preview_file(self, token: str, name: str, rel: str) -> tuple[bytes, str]:
        """(body, content type) of a project file for the sandboxed preview, or DevError."""
        if not hmac.compare_digest(token, self.token(name)):
            raise DevError("no_project", "not found")
        p = self.path(name)
        rel = unquote(rel or "")
        if "\x00" in rel or rel.startswith(("/", "\\")) or any(x in ("..",) or x.startswith(".") for x in Path(rel).parts):
            raise DevError("not_found", "not found")
        target = p / rel if rel else p
        cur = p
        for part in Path(rel).parts:
            cur = cur / part
            if cur.is_symlink():
                raise DevError("not_found", "not found")
        if target.is_dir():
            target = target / "index.html"
        real = Path(os.path.realpath(target))
        if not sandbox.inside(p, real) or not real.is_file():
            raise DevError("not_found", "not found")
        if real.stat().st_size > 20 * 1024 * 1024:
            raise DevError("too_big", "file too large")
        ctype = mimetypes.guess_type(real.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        return real.read_bytes(), ctype

    # ---------------------------------------------------------------- zip
    def zip(self, name: str) -> tuple[bytes, str]:
        p = self.path(name)
        buf = io.BytesIO()
        total = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for q in self._files(p):
                total += q.stat().st_size
                if total > ZIP_MAX:
                    raise DevError("too_big", "project too large to download as .zip (50 MB)")
                z.write(q, f"{p.name}/{q.relative_to(p).as_posix()}")
        return buf.getvalue(), f"{p.name}.zip"

    # ---------------------------------------------------------------- tests (always in the sandbox)
    def test(self, name: str, timeout: int = 60) -> dict:
        p = self.path(name)
        kind = self.kind_of(p)
        t0 = time.monotonic()
        if kind == "web":
            problems = check_site(p)
            return {"ok": not problems, "kind": kind, "runner": "links", "problems": problems,
                    "output": "\n".join(problems) or "OK", "seconds": round(time.monotonic() - t0, 2)}
        if kind != "python":
            return {"ok": False, "kind": kind, "runner": None, "problems": ["no_code"], "output": "",
                    "seconds": 0}
        rel = f"{ROOT}/{p.name}"
        has_tests = any(p.rglob("test_*.py")) or any(p.rglob("*_test.py"))
        runner = "pytest" if _has_pytest() else "unittest"
        if not has_tests:
            cmd, runner = f"python -m compileall -q {rel}", "compile"
        elif runner == "pytest":
            cmd = f"python -m pytest -q -p no:cacheprovider --rootdir {rel} {rel}"
        else:
            cmd = f"python -m unittest discover -s {rel} -t {rel} -v"
        try:
            out = sandbox.run(self.ws, cmd, timeout=timeout, max_output=20000, deny=self.deny)
        except sandbox.SandboxError as e:
            return {"ok": False, "kind": kind, "runner": runner, "problems": [str(e)], "output": str(e),
                    "seconds": round(time.monotonic() - t0, 2)}
        code = int(out.split("\n", 1)[0].split("=", 1)[1])
        body = out.split("\n", 1)[1] if "\n" in out else ""
        return {"ok": code == 0, "kind": kind, "runner": runner, "exit": code, "output": body,
                "summary": _summary(body, runner), "seconds": round(time.monotonic() - t0, 2)}


_PYTEST: bool | None = None


def _has_pytest() -> bool:
    global _PYTEST
    if _PYTEST is None:
        import importlib.util
        exe = sandbox.python_exe()
        import sys
        _PYTEST = bool(exe == sys.executable and importlib.util.find_spec("pytest"))
    return _PYTEST


def _summary(out: str, runner: str) -> dict:
    passed = failed = 0
    m = re.search(r"(\d+) passed", out)
    if m:
        passed = int(m.group(1))
    m = re.search(r"(\d+) failed", out)
    if m:
        failed = int(m.group(1))
    m = re.search(r"(\d+) error", out)
    if m:
        failed += int(m.group(1))
    m = re.search(r"Ran (\d+) tests?", out)
    if m and runner == "unittest":
        total = int(m.group(1))
        f = re.search(r"FAILED \((?:failures=(\d+))?(?:, )?(?:errors=(\d+))?", out)
        failed = (int(f.group(1) or 0) + int(f.group(2) or 0)) if f else 0
        passed = total - failed
    return {"passed": passed, "failed": failed}


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.refs: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for k in ("href", "src"):
            v = a.get(k)
            if v and not (tag == "a" and k == "href" and v.startswith("#")):
                self.refs.append((tag, v))


def check_site(p: Path) -> list[str]:
    """Static website check: index.html exists, every local link / image / script / stylesheet exists."""
    problems: list[str] = []
    if not (p / "index.html").is_file():
        return ["missing index.html"]
    for page in sorted(p.rglob("*.html")):
        if any(x in SKIP for x in page.relative_to(p).parts):
            continue
        parser = _Links()
        try:
            parser.feed(page.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:  # noqa: BLE001
            problems.append(f"{page.relative_to(p).as_posix()}: cannot read ({e})")
            continue
        for tag, ref in parser.refs:
            u = urlparse(ref)
            if u.scheme in ("http", "https"):
                if tag in ("script", "link", "img"):
                    problems.append(f"{page.relative_to(p).as_posix()}: uses an internet file ({ref}) - blocked in the preview")
                continue
            if u.scheme or ref.startswith(("//", "mailto:", "tel:", "data:", "javascript:")):
                continue
            target = (page.parent / unquote(u.path)).resolve() if u.path else page
            if u.path.endswith("/") or (target.is_dir()):
                target = target / "index.html"
            if not sandbox.inside(p, target):
                problems.append(f"{page.relative_to(p).as_posix()}: link outside the project ({ref})")
            elif not target.exists():
                problems.append(f"{page.relative_to(p).as_posix()}: missing file {ref}")
    return problems


ROLE_NAMES = {"en": ("Coder", "Tester"), "fr": ("Codeur", "Testeur")}
OPEN_HOW = {
    "en": "in this app's Dev tab: the 👁 Preview button shows it, ⬇ Download the project (.zip) gives every file",
    "fr": "dans l'onglet Dév de l'application : le bouton 👁 Aperçu l'affiche, ⬇ Télécharger le projet (.zip) "
          "donne tous les fichiers",
}


def rules(project: str | None, kind: str | None, lang: str | None = None) -> str:
    """System-prompt rules for a developer-mode conversation (in English for the model; role names and the
    "how to open it" sentence in the user's language)."""
    lang = "fr" if str(lang or "").lower().startswith("fr") else "en"
    coder, tester = ROLE_NAMES[lang]
    where = f"projects/{project}/" if project else "projects/<short-name>/"
    k = {"web": "a static website (index.html, style.css, script.js; no internet files, no build step)",
         "python": "a Python program (main.py + test_main.py with unittest tests; standard library only)"}.get(
        kind or "", "a small project (static website or Python program, as the user asks)")
    folder = where.rstrip("/")
    return (
        "DEVELOPER MODE (beginner-friendly):\n"
        f"- The project lives in {where} and is {k}. Only create or change files inside it "
        f"(paths always start with {where}; writes anywhere else are refused).\n"
        "- Work as a small team with spawn_agent, one helper at a time (do not pass allowed_tools):\n"
        f"  1) spawn_agent with a task starting with '{coder}:' that writes the files in {where} with "
        "write_file / edit_file;\n"
        f"  2) then spawn_agent with a task starting with '{tester}:' that reads the files, runs the tests in the "
        f"sandbox (`python -m unittest discover -s {folder} -v` for Python; for a website `ls -R {folder}` and "
        "it checks every link and file exists) and reports problems in plain words;\n"
        "  3) if the Tester found problems, ask a Coder to fix them, then test again.\n"
        "- Shell: one simple command per call (no ; | > or cd; only `a && b`).\n"
        "- Finish with a short, friendly answer for a beginner: what was built, how to open it "
        f"({OPEN_HOW[lang]}), and what to try next. Never mention an IDE.\n")


def child_rules(project: str | None, lang: str | None = None) -> str:
    """What every helper (Coder / Tester) is told in developer mode."""
    if not project:
        return ""
    where = f"projects/{project}/"
    return ("DEVELOPER MODE helper:\n"
            f"- The project folder is {where}. Create and change files ONLY there (paths start with {where}); "
            "never write files at the top of the work folder.\n"
            f"- Shell: one simple command per call, paths from the work folder (e.g. `ls -R {where.rstrip('/')}`, "
            f"`python -m unittest discover -s {where.rstrip('/')} -v`); no ; | > or cd.\n")
