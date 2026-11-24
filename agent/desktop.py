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
- No terminal needed: the browser opens on the chat (first launch: a welcome wizard to pick the language and
  paste an API key, or try demo mode). Everything is configured in the page (Settings); the ⏻ Quit button stops
  the server cleanly, ↻ Restart applies the settings that need it.
- Messages always go to data/app.log in the desktop builds (Mac: ~/AutonomousAgent/data/app.log, Windows:
  %USERPROFILE%\\AutonomousAgent\\data\\app.log). Any start error also opens a plain page (data/start-error.html).
- v0.9.13: double-clicking while the SAME version runs opens the browser on it; an OLDER (or other) version still
  running is asked to quit and this one takes over (agent/instance.py); a busy port -> another free port.
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
# Enlève le '#' devant UNE ligne de fournisseur, colle ta clé, puis relance l'application.
# This file stays on your computer; it is outside the agent's workspace.
# Ce fichier reste sur ton ordinateur ; il est hors de l'espace de travail de l'agent.

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
# Plusieurs clés avec limites : copie providers.example.yaml en providers.yaml dans ce dossier.

# IDC mode (finite deliberation, append-only commitments) on by default for new conversations
# Mode IDC (délibération finie, engagements en ajout seul) activé par défaut pour les nouvelles conversations
# AGENT_IDC=1

# Use it from your phone (remote mode: sign-in required, pairing QR code in this window and at /connect)
# L'utiliser depuis le téléphone (mode distant : connexion obligatoire, QR code ici et sur /connect)
# AGENT_REMOTE=1
# Tunnel started for you / tunnel lancé pour toi : tailscale (recommended / recommandé) | cloudflared
# AGENT_TUNNEL=tailscale
# Or the address you already expose / ou l'adresse que tu exposes déjà :
# AGENT_REMOTE_URL=https://my-computer.my-tailnet.ts.net/
# Fixed access token (24+ characters; otherwise one is generated in data/remote-token)
# AGENT_HARNESS_TOKEN=

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
        src = res / name if (res / name).is_file() else res / "docs" / "examples" / name   # repo: docs/examples
        if not paths[key].exists() and src.is_file():
            shutil.copyfile(src, paths[key])
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
            if os.name == "posix":      # v0.9.13: a port just freed by the old copy (TIME_WAIT) is usable
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
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
    """macOS, only with AGENT_TERMINAL=1: reopen the double-clicked .app in Terminal to watch the logs."""
    if sys.platform != "darwin" or not getattr(sys, "frozen", False) or os.environ.get("AGENT_NO_TERMINAL") == "1":
        return False
    if os.environ.get("AGENT_TERMINAL") != "1":
        return False
    if sys.stdin is not None and sys.stdin.isatty():
        return False
    try:
        subprocess.run(["open", "-a", "Terminal", sys.executable], check=True, timeout=20)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def ensure_streams(log_path: Path) -> Path | None:
    """Windowed build (no console): sys.stdout / sys.stderr are None; send messages to a log file."""
    if sys.stdout is not None and sys.stderr is not None:
        return None
    log_path.parent.mkdir(parents=True, exist_ok=True)
    f = open(log_path, "a", encoding="utf-8", buffering=1)   # noqa: SIM115 - lives as long as the process
    if sys.stdout is None:
        sys.stdout = f
    if sys.stderr is None:
        sys.stderr = f
    return log_path


def running_instance(port: int = PREFERRED_PORT, timeout: float = 1.5) -> str | None:
    """URL of an autonomous-agent already listening on this port, else None (kept for compatibility)."""
    if os.environ.get("AGENT_PORT"):
        return None
    from . import instance
    info = instance.probe(port, timeout)
    return info["url"] if info else None


# ------------------------------------------------------------------ v0.9.13: log file + start error page
LOG_MAX = 2_000_000
_SECRET_RE = None


class _Tee:
    """Writes to the log file and, when there is one, to the console too."""

    def __init__(self, f, other):
        self.f, self.other = f, other

    def write(self, s):
        try:
            self.f.write(s)
        except (OSError, ValueError):
            pass
        if self.other is not None:
            try:
                self.other.write(s)
            except (OSError, ValueError):
                pass
        return len(s)

    def flush(self):
        for x in (self.f, self.other):
            try:
                if x is not None:
                    x.flush()
            except (OSError, ValueError):
                pass

    def isatty(self):
        return bool(self.other is not None and getattr(self.other, "isatty", lambda: False)())


def log_path(home: Path) -> Path:
    return home / "data" / "app.log"


def setup_log(home: Path) -> Path | None:
    """Every message goes to data/app.log in the desktop builds (Finder / Explorer give no console), and when
    there is no console at all. Rotated at 2 MB (app.log.1)."""
    if not (getattr(sys, "frozen", False) or sys.stdout is None or sys.stderr is None
            or os.environ.get("AGENT_LOG_FILE") == "1"):
        return None
    p = log_path(home)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() and p.stat().st_size > LOG_MAX:
            os.replace(p, p.with_name("app.log.1"))
        f = open(p, "a", encoding="utf-8", buffering=1)   # noqa: SIM115 - lives as long as the process
    except OSError:
        return None
    sys.stdout = _Tee(f, sys.stdout)
    sys.stderr = _Tee(f, sys.stderr)
    return p


def _redact(text: str) -> str:
    import re
    return re.sub(r"(gsk_|sk-|sk_|xai-|AIza|ghp_|github_pat_)[A-Za-z0-9_\-]{6,}", r"\1••••", text)


def error_page(home: Path, lang: str, detail: str) -> Path | None:
    """A plain page explaining what to do, opened in the browser (nothing on screen otherwise)."""
    import html
    from . import __version__
    L = lambda key, **kw: html.escape(i18n.t(lang, key, **kw))   # noqa: E731
    log = log_path(home)
    tail = ""
    try:
        tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
    except OSError:
        pass
    body = _redact((detail or "").strip() + ("\n\n--- app.log ---\n" + tail if tail else ""))
    page = f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{L("desktop.err.title")}</title>
<style>body{{font:16px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;background:#f6f6f4;color:#23262b;margin:0}}
main{{max-width:640px;margin:48px auto;background:#fff;border:1px solid #e3e3e0;border-radius:14px;padding:28px 32px}}
h1{{font-size:22px;margin:0 0 10px}} li{{margin:6px 0}} code{{background:#f0f0ee;padding:1px 5px;border-radius:5px;
word-break:break-all}} details{{margin-top:18px;color:#5b616b}} pre{{white-space:pre-wrap;font-size:12px;
background:#f6f6f4;padding:12px;border-radius:8px;max-height:320px;overflow:auto}}
@media (prefers-color-scheme:dark){{body{{background:#1d1f23;color:#e6e7ea}} main{{background:#25282d;
border-color:#34373d}} code,pre{{background:#1d1f23}} details{{color:#a4a9b2}}}}</style></head><body><main>
<h1>{L("desktop.err.title")}</h1><p>{L("desktop.err.lead", version=__version__, home=str(home))}</p>
<h2 style="font-size:16px">{L("desktop.err.todo")}</h2><ol><li>{L("desktop.err.s1")}</li>
<li>{L("desktop.err.s2")}</li><li>{L("desktop.err.s3")}</li><li>{L("desktop.err.s4", log=str(log))}</li></ol>
<details><summary>{L("desktop.err.detail")}</summary><pre>{html.escape(body)}</pre></details></main></body></html>"""
    try:
        out = home / "data" / "start-error.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(page, encoding="utf-8")
    except OSError:
        return None
    if os.environ.get("AGENT_NO_BROWSER") != "1":
        try:
            webbrowser.open(out.as_uri())
        except Exception:  # noqa: BLE001
            pass
    return out


def main(argv: list[str] | None = None) -> int:
    if reopen_in_terminal():
        return 0
    home = home_dir()
    logged = setup_log(home)
    lang = "en"
    try:
        lang = system_lang()
    except Exception:  # noqa: BLE001
        pass
    try:
        return _main(home, logged, argv)
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:  # noqa: BLE001 - any start error: logged + a page, never a silent exit
        import traceback
        detail = traceback.format_exc()
        print(detail, file=sys.stderr)
        error_page(home, os.environ.get("AGENT_LANG") or lang, detail)
        return 1


def _take_over(paths: dict[str, Path], L) -> tuple[str | None, bool]:
    """(URL to open instead of starting, False) when the same version runs; else (None, port_still_taken)."""
    from . import __version__, instance
    log = lambda m: print(m, file=sys.stderr)   # noqa: E731
    if os.environ.get("AGENT_PORT"):
        return None, False
    info = instance.find(paths["data"], [PREFERRED_PORT], log)
    if info is None:
        return None, False
    if info.get("version") == __version__ and not info.get("stopping"):
        return info["url"], False
    print(L("desktop.replacing", old=info.get("version") or "?", new=__version__), file=sys.stderr)
    if instance.stop(info, log):
        print(L("desktop.replaced", old=info.get("version") or "?"), file=sys.stderr)
        return None, False
    return None, True


def _main(home: Path, logged: Path | None, argv: list[str] | None) -> int:
    from . import __version__, instance
    from .cli import load_dotenv, main as cli_main
    from .userconfig import UserConfig

    print(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} autonomous-agent {__version__} "
          f"({sys.platform}, python {sys.version.split()[0]}) {sys.executable}", file=sys.stderr)
    from .tlsca import ensure_ca
    try:
        ensure_ca(home / "data")     # v0.9.4: HTTPS certificates (the embedded macOS Python has none)
    except Exception as e:  # noqa: BLE001 - HTTPS to the AI may fail later, but the app must open
        print(f"warning: certificates: {e}", file=sys.stderr)
    paths = prepare_home(home)
    load_dotenv(paths["env"])
    cfg = UserConfig(paths["data"])
    if isinstance(cfg.get("lang"), str) and not os.environ.get("AGENT_LANG"):
        os.environ["AGENT_LANG"] = cfg.get("lang")          # chosen in the page (Settings / welcome wizard)
    explicit_lang = bool(os.environ.get("AGENT_LANG")) and not cfg.get("lang")
    lang = system_lang()
    os.environ.setdefault("AGENT_LANG", lang)
    L = lambda key, **kw: i18n.t(lang, key, **kw)   # noqa: E731
    backend, mode = pick_provider(paths)
    if logged:
        print(L("desktop.logs", path=logged), file=sys.stderr)
    if "/AppTranslocation/" in str(sys.executable):
        print(L("desktop.translocated"), file=sys.stderr)
    same, taken = _take_over(paths, L)
    if same:
        print(L("desktop.sameVersion", version=__version__, url=same), file=sys.stderr)
        if os.environ.get("AGENT_NO_BROWSER") != "1":
            webbrowser.open(same)
        return 0
    if mode == "demo" and (cfg.providers or cfg.get("demo")):
        mode = "settings"            # keys (or demo mode) chosen in the Settings page
    try:
        port = free_port()
    except OSError as e:
        print(L("desktop.error", error=e), file=sys.stderr)
        error_page(home, lang, L("desktop.error", error=e))
        return _pause(2, L)
    if taken or (port != PREFERRED_PORT and not os.environ.get("AGENT_PORT")):
        print(L("desktop.otherPort", port=port), file=sys.stderr)
    url = f"http://127.0.0.1:{port}/"
    if explicit_lang:          # otherwise the page follows the browser language (and its saved EN|FR choice)
        url += f"?lang={lang}"
    print(L("desktop.banner"), file=sys.stderr)
    print(L("desktop.home", home=home), file=sys.stderr)
    if mode == "keys":
        print(L("desktop.keysFile", path=paths["providers"]), file=sys.stderr)
    elif mode == "demo":
        print(L("desktop.demo", env=paths["env"], home=home), file=sys.stderr)
    if os.environ.get("AGENT_HARNESS_TOKEN") and os.environ.get("AGENT_REMOTE", "") not in ("1", "true", "yes", "on"):
        print(L("desktop.token"), file=sys.stderr)
    print(L("desktop.url", url=url), file=sys.stderr)
    print(L("desktop.stop"), file=sys.stderr)
    token = instance.new_token()
    os.environ[instance.TOKEN_ENV] = token
    instance.write(paths["data"], port, __version__, token)
    threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    try:
        code = cli_main(build_argv(paths, port, backend) + list(argv or []))
    finally:
        instance.remove(paths["data"], only_pid=os.getpid())
    if code:
        print(L("desktop.error", error=f"exit code {code}"), file=sys.stderr)
        error_page(home, lang, L("desktop.error", error=f"exit code {code}"))
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
