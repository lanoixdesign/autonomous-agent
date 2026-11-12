"""Double-click launcher (desktop builds): starts the harness on 127.0.0.1 and opens the chat.

    python -m agent.desktop          # same thing without the packaged build

- Everything the user owns lives in one folder, `~/AutonomousAgent` (or AGENT_HOME):
    .env                  API keys (created on first run, everything commented out)
    providers.yaml        optional: several keys with limits (copy providers.example.yaml)
    permissions.yaml      what the agent may do (copied from the defaults on first run)
    workspace/            the only folder the file tools can touch (chat attachments go here too)
    data/                 memory, audit log, conversations (SQLite), key usage
  Never inside the application bundle.
- Port 8765 if free (so the page keeps its saved language), else any free port (AGENT_PORT forces one).
- No API key and no providers.yaml -> demo mode with the offline `mock` model, and a message explaining
  where to put a key.
- Console messages follow the system language (AGENT_LANG=en|fr overrides). The web page follows the
  browser language and its EN|FR switch.
- The console window stays open: it shows the address and the logs; close it or press Ctrl+C to stop.
  On macOS, a double-clicked .app reopens itself in Terminal for that reason.
"""
from __future__ import annotations

import locale
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from . import i18n

KEY_VARS = (("groq", "GROQ_API_KEY"), ("openai", "OPENAI_API_KEY"), ("openrouter", "OPENROUTER_API_KEY"))
PREFERRED_PORT = 8765

ENV_TEMPLATE = """# autonomous-agent — API keys / clés d'API
# Remove the leading '#' of ONE provider line and paste your key, then restart the app.
# Enlevez le '#' devant UNE ligne de fournisseur, collez votre clé, puis relancez l'application.
# This file stays on your computer; it is outside the agent's workspace.
# Ce fichier reste sur votre ordinateur ; il est hors de l'espace de travail de l'agent.

# AGENT_PROVIDER=groq
# GROQ_API_KEY=
# AGENT_PROVIDER=openai
# OPENAI_API_KEY=
# AGENT_PROVIDER=openrouter
# OPENROUTER_API_KEY=
# Local model, no key / modèle local, sans clé : AGENT_PROVIDER=ollama

# Optional model / modèle facultatif
# AGENT_MODEL=

# Several keys with limits: copy providers.example.yaml to providers.yaml in this folder.
# Plusieurs clés avec limites : copiez providers.example.yaml en providers.yaml dans ce dossier.

# Language of this console (en | fr) / langue de cette console
# AGENT_LANG=fr
"""


def resources() -> Path:
    """Bundled read-only files (PyInstaller: sys._MEIPASS), else the repository root."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def home_dir() -> Path:
    return Path(os.environ.get("AGENT_HOME") or Path.home() / "AutonomousAgent").expanduser().resolve()


def system_lang() -> str:
    """AGENT_LANG, else the OS language (LANG/LC_*, Windows locale name, macOS AppleLocale)."""
    if os.environ.get("AGENT_LANG"):
        return i18n.normalize(os.environ["AGENT_LANG"])
    cands = [os.environ.get(v) for v in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE")]
    try:
        cands.append(locale.getlocale()[0])
    except ValueError:
        pass
    if sys.platform == "darwin":
        try:
            cands.append(subprocess.run(["defaults", "read", "-g", "AppleLocale"], capture_output=True,
                                        text=True, timeout=3).stdout.strip())
        except (OSError, subprocess.SubprocessError):
            pass
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(buf, 85):   # e.g. "fr-FR"
                cands.insert(0, buf.value)
        except (OSError, AttributeError):
            pass
    for c in cands:
        if c and c not in ("C", "POSIX", "C.UTF-8"):
            return i18n.normalize(c)     # "fr_FR", "fr-FR", "French_France" -> fr
    return "en"


def prepare_home(home: Path) -> dict[str, Path]:
    """Create the user folder and first-run files (never overwrites anything)."""
    paths = {"home": home, "workspace": home / "workspace", "data": home / "data", "env": home / ".env",
             "permissions": home / "permissions.yaml", "providers": home / "providers.yaml",
             "providers_example": home / "providers.example.yaml"}
    paths["workspace"].mkdir(parents=True, exist_ok=True)
    paths["data"].mkdir(parents=True, exist_ok=True)
    if not paths["env"].exists():
        paths["env"].write_text(ENV_TEMPLATE, encoding="utf-8")
        try:
            paths["env"].chmod(0o600)
        except OSError:
            pass
    res = resources()
    for name, key in (("permissions.yaml", "permissions"), ("providers.example.yaml", "providers_example")):
        if not paths[key].exists() and (res / name).is_file():
            shutil.copyfile(res / name, paths[key])
    return paths


def pick_provider(paths: dict[str, Path]) -> tuple[list[str], str]:
    """CLI options for the model backend + a mode label: keys | env | demo."""
    if paths["providers"].is_file():
        return ["--keys", str(paths["providers"])], "keys"
    if os.environ.get("AGENT_PROVIDER"):
        return [], "env"
    for provider, var in KEY_VARS:
        if os.environ.get(var):
            return ["--provider", provider], "env"
    return ["--provider", "mock"], "demo"


def free_port(host: str = "127.0.0.1") -> int:
    forced = os.environ.get("AGENT_PORT")
    if forced:
        return int(forced)
    for port in (PREFERRED_PORT, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
            except OSError:
                continue
            return s.getsockname()[1]
    raise OSError("no free port")


def build_argv(paths: dict[str, Path], port: int, backend: list[str]) -> list[str]:
    return ["serve", "--host", "127.0.0.1", "--port", str(port), "--workspace", str(paths["workspace"]),
            "--state-dir", str(paths["data"]), "--permissions", str(paths["permissions"]), *backend]


def open_when_ready(url: str, timeout: float = 30.0) -> None:
    """Wait for /health to answer (any HTTP status), then open the chat in the default browser."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            urllib.request.urlopen(url.split("?")[0].rstrip("/") + "/health", timeout=2).close()
        except urllib.error.HTTPError:
            pass          # 401 with a token: the server is up
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
            continue
        if os.environ.get("AGENT_NO_BROWSER") != "1":
            webbrowser.open(url)
        return


def reopen_in_terminal() -> bool:
    """macOS: a double-clicked .app has no console; reopen the same binary in Terminal (logs + Ctrl+C)."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False) or os.environ.get("AGENT_NO_TERMINAL") == "1":
        return False
    if sys.stdin is not None and sys.stdin.isatty():
        return False
    try:
        subprocess.run(["open", "-a", "Terminal", sys.executable], check=True, timeout=20)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def main(argv: list[str] | None = None) -> int:
    if reopen_in_terminal():
        return 0
    from .cli import load_dotenv, main as cli_main

    home = home_dir()
    paths = prepare_home(home)
    load_dotenv(paths["env"])
    explicit_lang = bool(os.environ.get("AGENT_LANG"))
    lang = system_lang()
    os.environ.setdefault("AGENT_LANG", lang)
    L = lambda key, **kw: i18n.t(lang, key, **kw)   # noqa: E731
    backend, mode = pick_provider(paths)
    try:
        port = free_port()
    except OSError as e:
        print(L("desktop.error", error=e), file=sys.stderr)
        return _pause(2, L)
    url = f"http://127.0.0.1:{port}/"
    if explicit_lang:          # otherwise the page follows the browser language (and its saved EN|FR choice)
        url += f"?lang={lang}"
    print(L("desktop.banner"), file=sys.stderr)
    print(L("desktop.home", home=home), file=sys.stderr)
    if mode == "keys":
        print(L("desktop.keysFile", path=paths["providers"]), file=sys.stderr)
    elif mode == "demo":
        print(L("desktop.demo", env=paths["env"], home=home), file=sys.stderr)
    if os.environ.get("AGENT_HARNESS_TOKEN"):
        print(L("desktop.token"), file=sys.stderr)
    print(L("desktop.url", url=url), file=sys.stderr)
    print(L("desktop.stop"), file=sys.stderr)
    threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    code = cli_main(build_argv(paths, port, backend) + list(argv or []))
    if code:
        return _pause(code, L)
    return code


def _pause(code: int, L) -> int:
    """Keep the window open after an error so the message can be read (double-click case)."""
    if getattr(sys, "frozen", False) and sys.stdin is not None and sys.stdin.isatty():
        try:
            input(L("desktop.pressEnter"))
        except (EOFError, KeyboardInterrupt):
            pass
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
