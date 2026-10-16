"""Minimal ``.gitignore`` matcher (patterns, negation, directory-only, anchoring, ``**``)."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class _Rule:
    base: str  # directory of the .gitignore, relative to the root ("" for the root)
    regex: re.Pattern[str]
    negate: bool
    dir_only: bool


def _translate(pattern: str) -> str:
    """Translate a gitignore glob (without leading slash) into a regex on a relative path."""
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*":
            if pattern[i:i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pattern[i:i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            j = pattern.find("]", i + 1)
            if j == -1:
                out.append(re.escape(c))
            else:
                body = pattern[i + 1:j].replace("\\", "\\\\")
                if body.startswith("!"):
                    body = "^" + body[1:]
                out.append(f"[{body}]")
                i = j
        elif c == "\\" and i + 1 < len(pattern):
            i += 1
            out.append(re.escape(pattern[i]))
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


class GitIgnore:
    """Accumulates rules of every ``.gitignore`` met during the walk."""

    def __init__(self) -> None:
        self._rules: list[_Rule] = []

    def add_file(self, base: str, text: str) -> None:
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line or line.startswith("#"):
                continue
            negate = line.startswith("!")
            if negate:
                line = line[1:]
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            if not line:
                continue
            anchored = "/" in line
            line = line.lstrip("/")
            body = _translate(line)
            regex = f"^{body}(?:/.*)?$" if anchored else f"^(?:.*/)?{body}(?:/.*)?$"
            self._rules.append(_Rule(base, re.compile(regex), negate, dir_only))

    def ignored(self, rel_path: str, is_dir: bool) -> bool:
        """``rel_path`` is relative to the repository root, with ``/``."""
        result = False
        for rule in self._rules:
            if rule.base:
                if not rel_path.startswith(rule.base + "/"):
                    continue
                path = rel_path[len(rule.base) + 1:]
            else:
                path = rel_path
            if rule.dir_only and not is_dir:
                # A directory-only pattern still matches files below that directory.
                parent = path.rsplit("/", 1)[0] if "/" in path else ""
                if not parent or not rule.regex.match(parent):
                    continue
            if rule.regex.match(path):
                result = not rule.negate
        return result
