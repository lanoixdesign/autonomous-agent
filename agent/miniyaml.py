"""Tiny YAML-subset parser used when PyYAML is not installed.

Supports: nested mappings by indentation, `- item` lists, inline `[a, b]` lists,
quoted/unquoted scalars, true/false/null, integers/floats, `#` comments.
That is enough for permissions.yaml. Use PyYAML for anything fancier.
"""
from __future__ import annotations

from typing import Any


def _strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1] in " \t"):
            return line[:i].rstrip()
    return line.rstrip()


def _split_inline(s: str) -> list[str]:
    items, cur, quote = [], "", None
    for ch in s:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
            cur += ch
        elif ch == ",":
            items.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        items.append(cur.strip())
    return items


def scalar(s: str) -> Any:
    s = s.strip()
    if s == "" or s in ("~", "null", "Null", "NULL"):
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        return s[1:-1]
    if s.startswith("[") and s.endswith("]"):
        return [scalar(x) for x in _split_inline(s[1:-1])]
    if s.startswith("{") and s.endswith("}"):
        out = {}
        for part in _split_inline(s[1:-1]):
            k, _, v = part.partition(":")
            out[scalar(k)] = scalar(v)
        return out
    if s in ("true", "True", "yes"):
        return True
    if s in ("false", "False", "no"):
        return False
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return s


def _split_key(content: str) -> tuple[str, str] | None:
    quote = None
    for i, ch in enumerate(content):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == ":" and (i + 1 == len(content) or content[i + 1] in " \t"):
            return content[:i].strip(), content[i + 1:].strip()
    return None


def loads(text: str) -> Any:
    lines = []
    for raw in text.splitlines():
        if raw.strip() in ("---", "..."):
            continue
        line = _strip_comment(raw)
        if line.strip():
            lines.append((len(line) - len(line.lstrip(" ")), line.strip()))
    if not lines:
        return {}
    value, _ = _block(lines, 0, lines[0][0])
    return value


def _block(lines, i, indent):
    if lines[i][1].startswith("- ") or lines[i][1] == "-":
        out: list = []
        while i < len(lines) and lines[i][0] == indent and (lines[i][1].startswith("- ") or lines[i][1] == "-"):
            item = lines[i][1][1:].strip()
            i += 1
            if item == "":
                if i < len(lines) and lines[i][0] > indent:
                    val, i = _block(lines, i, lines[i][0])
                    out.append(val)
                else:
                    out.append(None)
            elif _split_key(item) and not item.startswith(("'", '"', "[")):
                # list of mappings: "- key: value" (+ following indented keys)
                sub = [(indent + 2, item)]
                while i < len(lines) and lines[i][0] > indent:
                    sub.append(lines[i])
                    i += 1
                val, _ = _block(sub, 0, indent + 2)
                out.append(val)
            else:
                out.append(scalar(item))
        return out, i
    out_map: dict = {}
    while i < len(lines) and lines[i][0] == indent:
        kv = _split_key(lines[i][1])
        if kv is None:
            raise ValueError(f"miniyaml: cannot parse line: {lines[i][1]!r}")
        key, rest = kv
        key = scalar(key)
        i += 1
        if rest == "":
            if i < len(lines) and lines[i][0] > indent:
                val, i = _block(lines, i, lines[i][0])
            elif i < len(lines) and lines[i][0] == indent and lines[i][1].startswith("- "):
                val, i = _block(lines, i, indent)
            else:
                val = None
            out_map[key] = val
        else:
            out_map[key] = scalar(rest)
    return out_map, i
