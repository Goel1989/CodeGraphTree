"""Resource limits of configurable rules (requirements plan phase 4).

Rule files are data: they never execute code. The only computation they control is regular-expression matching
(pack entry points, bridge declarations, memory-manager prefixes), which Python cannot interrupt, so a pattern is
accepted only if it is short, compiles, and has none of the constructs that cause catastrophic backtracking:
nested quantifiers such as ``(a+)+`` and backreferences. Rule files themselves are limited in size.
"""

from __future__ import annotations

import re

MAX_PATTERN_LENGTH = 500
MAX_RULE_FILE_BYTES = 1024 * 1024
MAX_KEYWORDS = 200  # per keyword list of a keyword-language package (enforced by its schema)

_BACKREFERENCE = re.compile(r"(?<!\\)(?:\\\\)*\\[1-9]|\(\?P=")
_QUANTIFIER = re.compile(r"[*+?]|\{\d+(?:,\d*)?\}")


def _strip_classes_and_escapes(pattern: str) -> str:
    """The pattern with escapes and character classes replaced by a neutral character."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            out.append("x")
            i += 2
        elif ch == "[":
            j = i + 1
            if j < len(pattern) and pattern[j] == "^":
                j += 1
            if j < len(pattern) and pattern[j] == "]":
                j += 1
            while j < len(pattern) and pattern[j] != "]":
                j += 2 if pattern[j] == "\\" else 1
            out.append("x")
            i = j + 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _nested_quantifier(pattern: str) -> bool:
    """A quantified group whose body itself contains a quantifier, e.g. ``(a+)+`` or ``(?:\\w*)*``."""
    text = _strip_classes_and_escapes(pattern)
    stack: list[int] = []
    for i, ch in enumerate(text):
        if ch == "(":
            stack.append(i)
        elif ch == ")" and stack:
            start = stack.pop()
            body = text[start + 1:i]
            if body.startswith("?"):
                body = re.sub(r"^\?(?:P<\w+>|[:=!]|<[=!]|[aiLmsux-]+:?)", "", body)
            following = _QUANTIFIER.match(text, i + 1)
            if following is not None and following.group(0) != "?" and _QUANTIFIER.search(body):
                return True
    return False


def check_pattern(pattern: str) -> str | None:
    """Why a configurable regular expression is refused, or None if it is accepted."""
    if len(pattern) > MAX_PATTERN_LENGTH:
        return f"pattern longer than {MAX_PATTERN_LENGTH} characters"
    try:
        re.compile(pattern)
    except re.error as exc:
        return f"invalid regular expression: {exc}"
    if _BACKREFERENCE.search(pattern):
        return "backreference not allowed (unbounded matching time)"
    if _nested_quantifier(pattern):
        return "nested quantifier not allowed, such as (a+)+ (catastrophic backtracking)"
    return None


def check_rule_file_size(size: int) -> str | None:
    if size > MAX_RULE_FILE_BYTES:
        return f"rule file larger than {MAX_RULE_FILE_BYTES} bytes"
    return None
