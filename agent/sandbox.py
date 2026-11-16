"""Sandbox mode ("Bac à sable") for the shell tool.

When it is on, a command never reaches a real shell:
- the command line is parsed with shlex; shell operators (; | & < > $ ` newline, parentheses) are refused;
- only an allowlist of simple commands is accepted. Most of them (ls, cat, head, tail, wc, grep, find,
  echo, pwd, mkdir, touch, rm, cp, mv, diff, sort, uniq, date, true) are implemented here in Python, so they
  behave the same on Windows, macOS and Linux and cannot be tricked into running something else;
- every path is resolved (symlinks followed) and must stay inside the work folder: no absolute system paths,
  no "..", no "~", no symlink that points outside;
- `python file.py`, `python -m pytest|unittest|py_compile|compileall|json.tool|doctest` and `pytest` run in
  a child process with: shell=False, a minimal environment (no keys, no tokens, HOME and TMPDIR inside the
  work folder), a Python audit hook that blocks network, other processes, native code (ctypes) and file
  access outside the work folder, CPU/memory/file-size limits (POSIX), a time limit and an output limit.

This is a strong guard-rail for an assistant that makes mistakes, not a hardened jail against a determined
attacker (see README, "Limitations")."""
from __future__ import annotations

import difflib
import fnmatch
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

MAX_TIMEOUT = 60
CPU_SECONDS = 60
MEM_BYTES = 1536 * 1024 * 1024
FILE_BYTES = 64 * 1024 * 1024
MAX_READ = 2 * 1024 * 1024
METACHARS = set(";|&<>`$()\n\r")
PY_MODULES = {"pytest", "unittest", "py_compile", "compileall", "json.tool", "doctest"}
BUILTINS = ("ls", "cat", "head", "tail", "wc", "grep", "find", "echo", "pwd", "mkdir", "touch", "rm",
            "cp", "mv", "diff", "sort", "uniq", "date", "true")
ALLOWED = BUILTINS + ("python", "python3", "py", "pytest")


class SandboxError(Exception):
    """The command is not allowed in the sandbox (the message explains why, in plain words)."""


def help_text() -> str:
    return ("Sandbox is on: only simple commands inside the work folder, no internet, no pipes or redirections. "
            "Allowed: " + ", ".join(ALLOWED) + ". Python: `python file.py`, `python -m pytest`, `pytest`. "
            "To create or change files, use write_file / edit_file.")


# ---------------------------------------------------------------- parsing and paths
def parse(command: str) -> list[str]:
    command = (command or "").strip()
    if not command:
        raise SandboxError("empty command")
    bad = sorted({c for c in command if c in METACHARS})
    if bad:
        shown = " ".join("newline" if c in "\n\r" else c for c in bad)
        raise SandboxError(f"not allowed in the sandbox: {shown} (one simple command at a time, "
                           "no pipes, redirections or variables). " + help_text())
    try:
        argv = shlex.split(command, posix=True)
    except ValueError as e:
        raise SandboxError(f"could not read the command: {e}")
    if not argv:
        raise SandboxError("empty command")
    name = os.path.basename(argv[0])
    if name.lower().endswith(".exe"):
        name = name[:-4]
    if name not in ALLOWED or ("/" in argv[0] or "\\" in argv[0]):
        raise SandboxError(f"'{argv[0]}' is not allowed in the sandbox. " + help_text())
    return [name] + argv[1:]


def inside(root: Path, p: Path | str) -> bool:
    rp = os.path.normcase(os.path.realpath(p))
    r = os.path.normcase(os.path.realpath(root))
    return rp == r or rp.startswith(r.rstrip(os.sep) + os.sep)


def resolve(ws: Path, arg: str, deny: list[Path] | None = None) -> Path:
    """Path argument -> real path inside the work folder, or SandboxError."""
    if not arg or arg.startswith("~"):
        raise SandboxError(f"path not allowed: {arg!r} (stay inside the work folder)")
    p = Path(arg)
    full = p if p.is_absolute() else Path(ws) / p
    real = Path(os.path.realpath(full))
    if not inside(ws, real):
        r, lex = os.path.realpath(ws), os.path.normpath(os.path.abspath(full))
        linked = lex == r or lex.startswith(r.rstrip(os.sep) + os.sep)
        why = "goes through a link that points outside" if linked else "is outside"
        raise SandboxError(f"path not allowed: {arg!r} {why} the work folder")
    for d in deny or []:
        if inside(d, real):
            raise SandboxError(f"path not allowed: {arg!r} (private app data)")
    return real


def _rel(ws: Path, p: Path) -> str:
    r = os.path.relpath(p, os.path.realpath(ws))
    return "." if r == "." else r.replace(os.sep, "/")


def _split(args: list[str], flags_with_value: tuple[str, ...] = ()) -> tuple[dict, list[str]]:
    """Very small option parser: -abc, -n 5, -n5, --name=value, '--' ends options."""
    opts: dict[str, str | bool] = {}
    rest: list[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            rest += args[i + 1:]
            break
        if a.startswith("--") and len(a) > 2:
            k, _, v = a[2:].partition("=")
            opts[k] = v or True
        elif a.startswith("-") and len(a) > 1 and not re.fullmatch(r"-\d+", a):
            body = a[1:]
            j = 0
            while j < len(body):
                f = body[j]
                if f in flags_with_value:
                    v = body[j + 1:] or (args[i + 1] if i + 1 < len(args) else "")
                    if not body[j + 1:]:
                        i += 1
                    opts[f] = v
                    break
                opts[f] = True
                j += 1
        elif re.fullmatch(r"-\d+", a):
            opts["n"] = a[1:]
        else:
            rest.append(a)
        i += 1
    return opts, rest


def _check_opts(cmd: str, opts: dict, allowed: str, long_ok: tuple[str, ...] = ()) -> None:
    for k in opts:
        if (len(k) == 1 and k not in allowed) or (len(k) > 1 and k not in long_ok):
            raise SandboxError(f"option -{k} of {cmd} is not allowed in the sandbox")


def _read_text(p: Path) -> str:
    if p.is_dir():
        raise SandboxError(f"{p.name} is a folder")
    with open(p, "rb") as f:
        data = f.read(MAX_READ + 1)
    if len(data) > MAX_READ:
        data = data[:MAX_READ]
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- built-in commands
class Runner:
    def __init__(self, ws: Path, deny: list[Path] | None = None):
        self.ws = Path(os.path.realpath(ws))
        self.deny = [Path(os.path.realpath(d)) for d in (deny or [])]

    def path(self, a: str) -> Path:
        return resolve(self.ws, a, self.deny)

    def _visible(self, p: Path) -> bool:
        return inside(self.ws, p) and not any(inside(d, p) for d in self.deny)

    def run(self, argv: list[str]) -> tuple[int, str]:
        cmd, args = argv[0], argv[1:]
        fn = getattr(self, "c_" + cmd, None)
        if fn is None:
            raise SandboxError(f"'{cmd}' is not allowed in the sandbox")
        try:
            return fn(args)
        except SandboxError:
            raise
        except FileNotFoundError as e:
            return 1, f"{cmd}: no such file or folder: {_rel(self.ws, Path(e.filename)) if e.filename else ''}"
        except (OSError, ValueError, re.error) as e:
            return 1, f"{cmd}: {e}"

    def c_pwd(self, a):
        return 0, "."

    def c_true(self, a):
        return 0, ""

    def c_date(self, a):
        return 0, time.strftime("%Y-%m-%d %H:%M:%S %Z")

    def c_echo(self, a):
        o, rest = (({"n": True}, a[1:]) if a[:1] == ["-n"] else ({}, a))
        return 0, " ".join(rest)

    def c_ls(self, a):
        o, rest = _split(a)
        _check_opts("ls", o, "alh1RF")
        out = []
        for t in rest or ["."]:
            p = self.path(t)
            if p.is_dir():
                items = sorted(os.listdir(p))
                if not o.get("a"):
                    items = [x for x in items if not x.startswith(".")]
                if len(rest) > 1:
                    out.append(f"{t}:")
                for x in items:
                    q = p / x
                    if not self._visible(q) and not os.path.islink(q):
                        continue
                    if o.get("l"):
                        st = os.lstat(q)
                        kind = "l" if q.is_symlink() else ("d" if q.is_dir() else "-")
                        out.append(f"{kind} {st.st_size:>10} {time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))} {x}")
                    else:
                        out.append(x + ("/" if o.get("F") and q.is_dir() else ""))
            else:
                if not p.exists():
                    return 2, f"ls: no such file or folder: {t}"
                out.append(t)
        return 0, "\n".join(out)

    def c_cat(self, a):
        o, rest = _split(a)
        _check_opts("cat", o, "n")
        if not rest:
            raise SandboxError("cat needs a file name")
        text = "".join(_read_text(self.path(t)) for t in rest)
        if o.get("n"):
            text = "\n".join(f"{i:6}\t{l}" for i, l in enumerate(text.split("\n"), 1))
        return 0, text

    def _headtail(self, a, tail):
        o, rest = _split(a, ("n",))
        _check_opts("tail" if tail else "head", o, "n")
        n = int(o.get("n") or 10)
        out = []
        for t in rest:
            lines = _read_text(self.path(t)).splitlines()
            if len(rest) > 1:
                out.append(f"==> {t} <==")
            out += lines[-n:] if tail and n else ([] if tail else lines[:n])
        if not rest:
            raise SandboxError("needs a file name")
        return 0, "\n".join(out)

    def c_head(self, a):
        return self._headtail(a, False)

    def c_tail(self, a):
        return self._headtail(a, True)

    def c_wc(self, a):
        o, rest = _split(a)
        _check_opts("wc", o, "lwc")
        out = []
        for t in rest:
            s = _read_text(self.path(t))
            vals = {"l": s.count("\n"), "w": len(s.split()), "c": len(s.encode())}
            keys = [k for k in "lwc" if o.get(k)] or list("lwc")
            out.append(" ".join(str(vals[k]) for k in keys) + f" {t}")
        if not rest:
            raise SandboxError("wc needs a file name")
        return 0, "\n".join(out)

    def _walk(self, root: Path, maxdepth: int | None = None):
        base = len(root.parts)
        for d, dirs, files in os.walk(root, followlinks=False):
            dp = Path(d)
            depth = len(dp.parts) - base
            if maxdepth is not None and depth >= maxdepth:
                dirs[:] = []
            dirs[:] = sorted(x for x in dirs if self._visible(dp / x))
            yield dp, dirs, sorted(files)

    def c_grep(self, a):
        o, rest = _split(a, ("e",))
        _check_opts("grep", o, "inrRlcvwEFHhe", ("include",))
        pat = o.get("e") if isinstance(o.get("e"), str) else (rest.pop(0) if rest else None)
        if not pat:
            raise SandboxError("grep needs a pattern")
        flags = re.I if o.get("i") else 0
        rx = re.compile(re.escape(pat) if o.get("F") else pat, flags)
        if o.get("w"):
            rx = re.compile(r"\b(?:" + rx.pattern + r")\b", flags)
        rec = o.get("r") or o.get("R")
        targets = rest or (["."] if rec else [])
        if not targets:
            raise SandboxError("grep needs a file name (or -r)")
        files: list[tuple[str, Path]] = []
        for t in targets:
            p = self.path(t)
            if p.is_dir():
                if not rec:
                    return 2, f"grep: {t} is a folder (use -r)"
                for d, _, fs in self._walk(p):
                    for f in fs:
                        q = d / f
                        if self._visible(q) and (not isinstance(o.get("include"), str) or fnmatch.fnmatch(f, o["include"])):
                            files.append((_rel(self.ws, q), q))
            else:
                files.append((t, p))
        show = (len(files) > 1 or rec) and not o.get("h") or o.get("H")
        out, found = [], False
        for name, q in files:
            try:
                lines = _read_text(q).splitlines()
            except (OSError, SandboxError):
                continue
            hits = [(i, l) for i, l in enumerate(lines, 1) if bool(rx.search(l)) != bool(o.get("v"))]
            found = found or bool(hits)
            if o.get("l"):
                if hits:
                    out.append(name)
            elif o.get("c"):
                out.append(f"{name}:{len(hits)}" if show else str(len(hits)))
            else:
                for i, l in hits:
                    out.append((f"{name}:" if show else "") + (f"{i}:" if o.get("n") else "") + l)
        return (0 if found else 1), "\n".join(out[:5000])

    def c_find(self, a):
        paths, i = [], 0
        while i < len(a) and not a[i].startswith("-"):
            paths.append(a[i])
            i += 1
        name = iname = kind = pathpat = None
        maxdepth = None
        expr = a[i:]
        j = 0
        while j < len(expr):
            k = expr[j]
            v = expr[j + 1] if j + 1 < len(expr) else None
            if k in ("-name", "-iname", "-type", "-maxdepth", "-path"):
                if v is None:
                    raise SandboxError(f"find {k} needs a value")
                if k == "-name":
                    name = v
                elif k == "-iname":
                    iname = v.lower()
                elif k == "-type":
                    if v not in ("f", "d"):
                        raise SandboxError("find -type: only f or d")
                    kind = v
                elif k == "-maxdepth":
                    maxdepth = int(v)
                else:
                    pathpat = v
                j += 2
            elif k == "-print":
                j += 1
            else:
                raise SandboxError(f"find {k} is not allowed in the sandbox (allowed: -name -iname -type -maxdepth -path)")
        out = []
        for t in paths or ["."]:
            root = self.path(t)
            for d, dirs, files in self._walk(root, maxdepth):
                entries = ([(d, True)] if d == root else []) + [(d / x, True) for x in dirs] + [(d / f, False) for f in files]
                for q, isdir in entries:
                    if not self._visible(q):
                        continue
                    rel = _rel(self.ws, q)
                    shown = t.rstrip("/") + rel[len(_rel(self.ws, root)):] if _rel(self.ws, root) != "." else ("./" + rel if rel != "." else ".")
                    if kind == "f" and isdir or kind == "d" and not isdir:
                        continue
                    if name and not fnmatch.fnmatchcase(q.name, name):
                        continue
                    if iname and not fnmatch.fnmatch(q.name.lower(), iname):
                        continue
                    if pathpat and not fnmatch.fnmatch(shown, pathpat):
                        continue
                    out.append(shown)
        return 0, "\n".join(out[:5000])

    def c_mkdir(self, a):
        o, rest = _split(a)
        _check_opts("mkdir", o, "p")
        for t in rest:
            self.path(t).mkdir(parents=bool(o.get("p")), exist_ok=bool(o.get("p")))
        return 0, ""

    def c_touch(self, a):
        for t in a:
            p = self.path(t)
            p.touch()
        return 0, ""

    def c_rm(self, a):
        o, rest = _split(a)
        _check_opts("rm", o, "rRfd")
        for t in rest:
            full = Path(t) if Path(t).is_absolute() else self.ws / t
            if os.path.islink(full) and not t.startswith("~"):      # remove the link itself, never its target
                parent = Path(os.path.realpath(full.parent))
                if not self._visible(parent):
                    raise SandboxError(f"path not allowed: {t!r} is outside the work folder")
                os.unlink(full)
                continue
            p = self.path(t)
            if p == self.ws:
                raise SandboxError("rm: not allowed on the whole work folder")
            if p.is_dir():
                if not (o.get("r") or o.get("R")):
                    return 1, f"rm: {t} is a folder (use -r)"
                shutil.rmtree(p)
            elif p.exists():
                p.unlink()
            elif not o.get("f"):
                return 1, f"rm: no such file: {t}"
        return 0, ""

    def _two(self, cmd, a, flags):
        o, rest = _split(a)
        _check_opts(cmd, o, flags)
        if len(rest) < 2:
            raise SandboxError(f"{cmd} needs a source and a destination")
        srcs = [self.path(t) for t in rest[:-1]]
        dst = self.path(rest[-1])
        return o, srcs, dst

    def c_cp(self, a):
        o, srcs, dst = self._two("cp", a, "rRf")
        for s in srcs:
            target = dst / s.name if dst.is_dir() else dst
            if s.is_dir():
                if not (o.get("r") or o.get("R")):
                    return 1, f"cp: {s.name} is a folder (use -r)"
                shutil.copytree(s, target, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(s, target, follow_symlinks=True)
        return 0, ""

    def c_mv(self, a):
        o, srcs, dst = self._two("mv", a, "f")
        for s in srcs:
            if s == self.ws:
                raise SandboxError("mv: not allowed on the whole work folder")
            shutil.move(str(s), str(dst / s.name if dst.is_dir() else dst))
        return 0, ""

    def c_diff(self, a):
        o, rest = _split(a)
        _check_opts("diff", o, "u")
        if len(rest) != 2:
            raise SandboxError("diff needs two files")
        x, y = (_read_text(self.path(t)).splitlines() for t in rest)
        d = list(difflib.unified_diff(x, y, rest[0], rest[1], lineterm=""))
        return (1 if d else 0), "\n".join(d)

    def c_sort(self, a):
        o, rest = _split(a)
        _check_opts("sort", o, "rnu")
        lines = [l for t in rest for l in _read_text(self.path(t)).splitlines()]
        key = (lambda s: float(re.match(r"\s*(-?\d+(\.\d+)?)", s).group(1)) if re.match(r"\s*-?\d", s) else 0.0) if o.get("n") else None
        lines.sort(key=key, reverse=bool(o.get("r")))
        if o.get("u"):
            lines = list(dict.fromkeys(lines))
        return 0, "\n".join(lines)

    def c_uniq(self, a):
        o, rest = _split(a)
        _check_opts("uniq", o, "c")
        lines = [l for t in rest for l in _read_text(self.path(t)).splitlines()]
        out: list[tuple[str, int]] = []
        for l in lines:
            if out and out[-1][0] == l:
                out[-1] = (l, out[-1][1] + 1)
            else:
                out.append((l, 1))
        return 0, "\n".join((f"{c:7} {l}" if o.get("c") else l) for l, c in out)


# ---------------------------------------------------------------- python in a child process
BOOT = r'''
import os, sys
WS = os.path.realpath(sys.argv[1]); DENY = [os.path.realpath(d) for d in sys.argv[2].split(os.pathsep) if d]
MODE, TARGET = sys.argv[3], sys.argv[4]
def _in(p, root):
    return p == root or p.startswith(root.rstrip(os.sep) + os.sep)
READ = [WS] + [os.path.realpath(p) for p in {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix} if p]
READ += ["/usr/lib", "/usr/local/lib", "/usr/share", "/lib", "/lib64", "/etc/localtime", "/etc/mime.types", "/dev/null", "/dev/urandom", "/proc/self", "/System", "/Library/Frameworks/Python.framework", "/Library/Developer/CommandLineTools", "/Applications/Xcode.app", "/opt/homebrew", "/usr/local/Cellar", "/usr/local/opt"]
if os.name == "nt":
    READ += [os.environ.get("SYSTEMROOT", r"C:\Windows")]
NET = {"socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg", "socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr", "socket.getnameinfo"}
PROC = {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn", "os.fork", "os.forkpty", "pty.spawn", "os.startfile", "os.kill", "os.killpg", "ctypes.dlopen", "ctypes.dlsym", "ctypes.cdata", "_winapi.CreateProcess", "winreg.OpenKey", "sys.remote_exec"}
WRITE1 = {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.truncate", "os.utime", "shutil.rmtree", "os.chflags", "os.lchmod", "os.setxattr", "os.removexattr"}
WRITE2 = {"os.rename", "os.link", "os.symlink", "shutil.copyfile", "shutil.move", "shutil.copytree"}
READ1 = {"os.listdir", "os.scandir", "glob.glob", "os.chdir"}
class Blocked(PermissionError):
    pass
def _real(p):
    if isinstance(p, int):
        return None
    try:
        p = os.fspath(p)
    except TypeError:
        return None
    if isinstance(p, bytes):
        p = os.fsdecode(p)
    return os.path.realpath(p)
def _w(p, what):
    r = _real(p)
    if r is None or r in ("/dev/null", "nul", "NUL") or os.path.basename(r).upper() == "NUL":
        return
    if not _in(r, WS) or any(_in(r, d) for d in DENY):
        raise Blocked("sandbox: %s outside the work folder is not allowed: %s" % (what, p))
def _r(p, what):
    r = _real(p)
    if r is None:
        return
    if any(_in(r, d) for d in DENY) or not any(_in(r, x) for x in READ):
        raise Blocked("sandbox: %s outside the work folder is not allowed: %s" % (what, p))
def hook(ev, args):
    if ev in NET:
        raise Blocked("sandbox: no network access from commands")
    if ev in PROC:
        raise Blocked("sandbox: starting other programs or native code is not allowed (%s)" % ev)
    if ev == "import" and args and str(args[0]).split(".")[0] in ("ctypes", "_ctypes", "cffi", "_cffi_backend"):
        raise Blocked("sandbox: native code (%s) is not allowed" % args[0])
    if ev == "open":
        path, mode, flags = (list(args) + [None, None, 0])[:3]
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC))
        (_w if writing else _r)(path, "writing" if writing else "reading")
    elif ev in WRITE1:
        _w(args[0], "changing files")
    elif ev in WRITE2:
        _r(args[0], "reading"); _w(args[1], "changing files")
    elif ev in READ1:
        _r(args[0] if args else ".", "reading")
os.chdir(WS)
sys.addaudithook(hook)
import runpy
sys.argv = [TARGET] + sys.argv[5:]
if MODE == "module":
    sys.path.insert(0, WS)
    runpy.run_module(TARGET, run_name="__main__", alter_sys=True)
else:
    sys.path.insert(0, os.path.dirname(os.path.realpath(TARGET)))
    runpy.run_path(TARGET, run_name="__main__")
'''


def python_exe() -> str | None:
    """The interpreter used for python commands (the app's own one, or a system Python in desktop builds)."""
    if not getattr(sys, "frozen", False) and sys.executable:
        return sys.executable
    for n in ("python3", "python", "py"):
        w = shutil.which(n)
        if w:
            return w
    return None


def child_env(ws: Path) -> dict[str, str]:
    tmp = Path(ws) / ".tmp"
    tmp.mkdir(exist_ok=True)
    env = {"PATH": os.pathsep.join(p for p in ([os.path.dirname(python_exe() or "")] + os.defpath.split(os.pathsep)) if p),
           "HOME": str(ws), "USERPROFILE": str(ws), "TMPDIR": str(tmp), "TEMP": str(tmp), "TMP": str(tmp),
           "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONNOUSERSITE": "1", "NO_COLOR": "1",
           "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9",
           "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "ALL_PROXY": "http://127.0.0.1:9"}
    if os.name == "nt":
        for k in ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT"):
            if os.environ.get(k):
                env[k] = os.environ[k]
    return env


def _limits(timeout: int):
    def apply():
        try:
            import resource
            for lim, val in ((resource.RLIMIT_CPU, min(CPU_SECONDS, timeout + 2)), (resource.RLIMIT_FSIZE, FILE_BYTES),
                             (resource.RLIMIT_CORE, 0), (getattr(resource, "RLIMIT_AS", None), MEM_BYTES)):
                if lim is None:
                    continue
                try:
                    resource.setrlimit(lim, (val, val))
                except (ValueError, OSError):
                    pass
        except ImportError:
            pass
    return apply if os.name == "posix" else None


def python_argv(runner: Runner, argv: list[str]) -> list[str]:
    """Validate a python/pytest command and build the child argv (bootstrap + mode + target + args)."""
    cmd, args = argv[0], argv[1:]
    if cmd == "pytest":
        args = ["-m", "pytest"] + args
    while args and args[0] in ("-u", "-B", "-q", "-E", "-s", "-I"):
        args = args[1:]
    if not args:
        raise SandboxError("interactive python is not available in the sandbox: give a file, e.g. python main.py")
    if args[0] == "-m":
        if len(args) < 2 or args[1] not in PY_MODULES:
            raise SandboxError("python -m: only " + ", ".join(sorted(PY_MODULES)) + " are allowed in the sandbox")
        mode, target, rest = "module", args[1], args[2:]
    elif args[0].startswith("-"):
        raise SandboxError(f"python option {args[0]} is not allowed in the sandbox (no -c)")
    else:
        p = runner.path(args[0])
        if not p.is_file():
            raise SandboxError(f"python: file not found: {args[0]}")
        mode, target, rest = "script", str(p), args[1:]
    for x in rest:  # arguments that look like paths must stay inside too
        if x.startswith(("/", "~", "\\")) or ".." in Path(x).parts or re.match(r"^[A-Za-z]:[\\/]", x):
            if not x.startswith("-"):
                runner.path(x)
        elif x.startswith("--") and "=" in x:
            v = x.split("=", 1)[1]
            if v.startswith(("/", "~")) or ".." in Path(v).parts:
                runner.path(v)
    exe = python_exe()
    if not exe:
        raise SandboxError("no Python found on this computer: install Python 3 to run Python programs")
    return [exe, "-I", "-B", "-c", BOOT, str(runner.ws), os.pathsep.join(map(str, runner.deny)), mode, target] + rest


def run_python(runner: Runner, argv: list[str], timeout: int, max_output: int) -> tuple[int, str]:
    full = python_argv(runner, argv)
    t = max(1, min(int(timeout or MAX_TIMEOUT), MAX_TIMEOUT))
    kw = {}
    if os.name == "posix":
        kw["preexec_fn"] = _limits(t)
        kw["start_new_session"] = True
    try:
        p = subprocess.Popen(full, cwd=runner.ws, env=child_env(runner.ws), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False, **kw)
    except OSError as e:
        return 127, f"could not start python: {e}"
    try:
        out, err = p.communicate(timeout=t)
    except subprocess.TimeoutExpired:
        _kill(p)
        p.communicate()
        raise SandboxError(f"stopped after {t}s (time limit of the sandbox)")
    text = out.decode("utf-8", "replace")
    if err:
        text += "\n[stderr]\n" + err.decode("utf-8", "replace")
    if p.returncode and p.returncode < 0:
        text += f"\n[stopped by the sandbox: signal {-p.returncode} (CPU, memory or file-size limit)]"
    return p.returncode, text


def _kill(p: subprocess.Popen) -> None:
    try:
        if os.name == "posix":
            import signal
            os.killpg(p.pid, signal.SIGKILL)
        else:
            p.kill()
    except (OSError, ProcessLookupError):
        pass


def run(ws: Path, command: str, timeout: int = MAX_TIMEOUT, max_output: int = 12000,
        deny: list[Path] | None = None) -> str:
    """Run one command in the sandbox. Returns 'exit=N\\n<output>' like the normal shell tool."""
    argv = parse(command)
    runner = Runner(ws, deny)
    if argv[0] in ("python", "python3", "py", "pytest"):
        code, out = run_python(runner, argv, timeout, max_output)
    else:
        code, out = runner.run(argv)
    if len(out) > max_output:
        out = out[:max_output] + f"\n... ({len(out) - max_output} chars truncated)"
    return f"exit={code}\n{out}".rstrip()
