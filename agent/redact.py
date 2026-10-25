"""Secret redaction. Every string that reaches a log or the audit file goes through here."""
from __future__ import annotations

import os
import re
from typing import Any

SECRET_NAME_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)", re.I)
SECRET_VALUE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),          # OpenAI / OpenRouter style
    re.compile(r"gsk_[A-Za-z0-9]{16,}"),             # Groq
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),       # GitHub tokens
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9\-]{10,}"),    # Slack
    re.compile(r"AKIA[0-9A-Z]{16}"),                 # AWS access key id
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
]
MASK = "***REDACTED***"


def secret_env_values(env: dict[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    vals = [v for k, v in env.items() if SECRET_NAME_RE.search(k) and v and len(v) >= 8]
    return sorted(set(vals), key=len, reverse=True)


def is_secret_name(name: str) -> bool:
    return bool(SECRET_NAME_RE.search(name))


def redact(text: Any, extra: list[str] | None = None) -> Any:
    """Redact secrets in a string, or recursively in dicts/lists."""
    if isinstance(text, dict):
        return {k: (MASK if is_secret_name(str(k)) and v else redact(v, extra)) for k, v in text.items()}
    if isinstance(text, (list, tuple)):
        return [redact(v, extra) for v in text]
    if not isinstance(text, str):
        return text
    out = text
    for val in secret_env_values() + list(extra or []):
        if val:
            out = out.replace(val, MASK)
    for pat in SECRET_VALUE_PATTERNS:
        if pat.groups:
            out = pat.sub(lambda m: m.group(1) + MASK, out)
        else:
            out = pat.sub(MASK, out)
    return out


def scrubbed_env() -> dict[str, str]:
    """Environment for child processes: secret-looking variables removed."""
    return {k: v for k, v in os.environ.items() if not is_secret_name(k)}
