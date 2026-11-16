"""v0.9.4: make HTTPS work in the desktop builds.

The macOS apps embed a Python whose OpenSSL looks for its certificate list in
/Library/Frameworks/Python.framework/.../etc/openssl/cert.pem — a file that only exists on Macs where the
python.org installer AND its "Install Certificates" step were run. Everywhere else every HTTPS call failed
with CERTIFICATE_VERIFY_FAILED, which the app took for a rate limit ("all keys paused, retrying in 30 s").

``ensure_ca()`` runs at start-up: when the system has no usable certificate list it points SSL_CERT_FILE
to the bundled ``certifi`` list (shipped with the builds), else, on macOS, to the system roots exported
with ``security``. Nothing changes when the system list is fine or SSL_CERT_FILE is already set.
"""
from __future__ import annotations

import os
import ssl
import subprocess
import sys
from pathlib import Path

STATE = {"source": "unknown", "file": None}


def _usable_file(p: str | None) -> bool:
    try:
        return bool(p) and os.path.isfile(p) and os.path.getsize(p) > 1000
    except OSError:
        return False


def _usable_dir(p: str | None) -> bool:
    try:
        return bool(p) and os.path.isdir(p) and any(os.scandir(p))
    except OSError:
        return False


def system_ok() -> bool:
    if sys.platform == "win32":
        return True                     # Python reads the Windows certificate store itself
    v = ssl.get_default_verify_paths()
    return _usable_file(v.cafile) or _usable_dir(v.capath)


def _certifi() -> str | None:
    try:
        import certifi                  # bundled in the desktop builds (packaging/autonomous-agent.spec)
        p = certifi.where()
        return p if _usable_file(p) else None
    except Exception:                   # noqa: BLE001 - not installed: other fallbacks
        return None


def _macos_roots(cache_dir: Path) -> str | None:
    if sys.platform != "darwin":
        return None
    out = cache_dir / "macos-roots.pem"
    try:
        pem = subprocess.run(["/usr/bin/security", "find-certificate", "-a", "-p",
                              "/System/Library/Keychains/SystemRootCertificates.keychain"],
                             capture_output=True, timeout=20).stdout
        if pem.count(b"BEGIN CERTIFICATE") < 10:
            return None
        cache_dir.mkdir(parents=True, exist_ok=True)
        out.write_bytes(pem)
        return str(out)
    except (OSError, subprocess.SubprocessError):
        return None


def ensure_ca(cache_dir: str | os.PathLike | None = None) -> dict:
    """Make sure HTTPS can verify certificates. Returns {"source": ..., "file": ...} (also in STATE)."""
    env = os.environ.get("SSL_CERT_FILE")
    if _usable_file(env):
        STATE.update(source="env", file=env)
    elif system_ok():
        STATE.update(source="system", file=None)
    else:
        f = _certifi()
        src = "bundled"
        if not f:
            f = _macos_roots(Path(cache_dir or Path.home() / ".cache" / "autonomous-agent"))
            src = "macos-keychain"
        if f:
            os.environ["SSL_CERT_FILE"] = f
            STATE.update(source=src, file=f)
        else:
            STATE.update(source="missing", file=None)
    return dict(STATE)


def is_cert_error(e: BaseException) -> bool:
    r = getattr(e, "reason", e)
    return isinstance(r, ssl.SSLCertVerificationError) or "CERTIFICATE_VERIFY_FAILED" in str(e)
