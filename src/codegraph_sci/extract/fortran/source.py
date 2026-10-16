"""Fortran source preparation: preprocessor branches, fixed/free form, logical statements.

A logical statement keeps, for every character, its position (line, column) in the file, so
that every site points to the exact place where its target is written. String contents are
masked (``_``) in ``masked`` while ``orig`` keeps them (literal arguments).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_DIRECTIVE = re.compile(r"^\s*#\s*(\w+)\s*(.*)$")
_INCLUDE_TARGET = re.compile(r'^\s*#\s*include\s*(["<])([^">]+)[">]')
_WS = re.compile(r"\s+")


@dataclass
class PPDirective:
    kind: str
    text: str
    line: int


@dataclass
class PPInclude:
    target: str
    line: int
    col: int
    system: bool
    condition: str | None


@dataclass
class Statement:
    orig: str
    masked: str
    pos: list[tuple[int, int]]  # per character: (line, col), 1-based
    condition: str | None
    label: str | None = None

    @property
    def line(self) -> int:
        return self.pos[0][0] if self.pos else 0

    @property
    def last_line(self) -> int:
        return self.pos[-1][0] if self.pos else 0

    def at(self, index: int) -> tuple[int, int]:
        if not self.pos:
            return (0, 0)
        return self.pos[min(max(index, 0), len(self.pos) - 1)]


@dataclass
class PreparedSource:
    statements: list[Statement]
    directives: list[PPDirective] = field(default_factory=list)
    includes: list[PPInclude] = field(default_factory=list)
    line_conditions: list[str | None] = field(default_factory=list)  # index = line - 1
    errors: list[tuple[int, str]] = field(default_factory=list)


def _norm_expr(expr: str) -> str:
    expr = expr.split("//", 1)[0]
    expr = re.sub(r"/\*.*?\*/", "", expr)
    return _WS.sub(" ", expr).strip()


def _atomic(cond: str) -> bool:
    return re.fullmatch(r"!?[\w()]+", cond) is not None


def negate(cond: str) -> str:
    if cond.startswith("!") and _atomic(cond[1:]) and cond.count("(") <= 1:
        return cond[1:]
    return f"!{cond}" if _atomic(cond) else f"!({cond})"


def _join(parts: list[str]) -> str | None:
    kept = [p if ("&&" not in p and "||" not in p) or len(parts) == 1 else f"({p})" for p in parts if p]
    return " && ".join(kept) if kept else None


class _CondStack:
    """Conditions of nested #if blocks; all branches are kept (keep_all_branches)."""

    def __init__(self) -> None:
        # Each frame: (conditions of previous branches, condition of current branch)
        self.frames: list[tuple[list[str], str]] = []

    def current(self) -> str | None:
        return _join([frame[1] for frame in self.frames])

    def directive(self, kind: str, arg: str) -> None:
        if kind == "ifdef":
            self.frames.append(([], f"defined({arg.split()[0] if arg.split() else ''})"))
        elif kind == "ifndef":
            self.frames.append(([], f"!defined({arg.split()[0] if arg.split() else ''})"))
        elif kind == "if":
            self.frames.append(([], _norm_expr(arg)))
        elif kind == "elif" and self.frames:
            previous, cur = self.frames[-1]
            previous = previous + [cur]
            parts = [negate(p) for p in previous] + [_norm_expr(arg)]
            self.frames[-1] = (previous, " && ".join(parts))
        elif kind == "else" and self.frames:
            previous, cur = self.frames[-1]
            previous = previous + [cur]
            if len(previous) == 1:
                cond = negate(previous[0])
            else:
                cond = " && ".join(negate(p) for p in previous)
            self.frames[-1] = (previous, cond)
        elif kind == "endif" and self.frames:
            self.frames.pop()


def _is_fixed_comment(line: str) -> bool:
    if not line.strip():
        return True
    first = line[0]
    if first in "cC*!dD":
        return True
    stripped = line.lstrip(" ")
    return stripped.startswith("!") and (len(line) - len(stripped)) != 5


class _Builder:
    def __init__(self) -> None:
        self.statements: list[Statement] = []
        self.orig: list[str] = []
        self.masked: list[str] = []
        self.pos: list[tuple[int, int]] = []
        self.condition: str | None = None
        self.label: str | None = None
        self.quote: str | None = None  # open string delimiter across continuation lines

    def start(self, condition: str | None, label: str | None) -> None:
        self.flush()
        self.condition, self.label = condition, label

    def flush(self) -> None:
        if any(not c.isspace() for c in self.orig):
            # Strip trailing and leading whitespace while keeping positions aligned.
            lo, hi = 0, len(self.orig)
            while lo < hi and self.orig[lo].isspace():
                lo += 1
            while hi > lo and self.orig[hi - 1].isspace():
                hi -= 1
            self.statements.append(Statement("".join(self.orig[lo:hi]), "".join(self.masked[lo:hi]),
                                             self.pos[lo:hi], self.condition, self.label))
        self.orig, self.masked, self.pos = [], [], []
        self.label = None

    def add_text(self, text: str, line: int, col0: int, *, free_form: bool) -> bool:
        """Append ``text`` (starting at 0-based column ``col0``). Returns True if continued (``&``)."""
        i, n = 0, len(text)
        last_code = -1  # index in self.orig of the last non-space char outside strings
        while i < n:
            ch = text[i]
            if self.quote:
                if ch == self.quote:
                    if i + 1 < n and text[i + 1] == self.quote:
                        self._push(ch, "_", line, col0 + i)
                        self._push(ch, "_", line, col0 + i + 1)
                        i += 2
                        continue
                    self._push(ch, ch, line, col0 + i)
                    self.quote = None
                    last_code = len(self.orig) - 1
                elif free_form and ch == "&" and not text[i + 1:].strip():
                    return True  # string continued on the next line
                else:
                    self._push(ch, "_", line, col0 + i)
                i += 1
                continue
            if ch in "'\"":
                self.quote = ch
                self._push(ch, ch, line, col0 + i)
                last_code = len(self.orig) - 1
            elif ch == "!":
                break
            elif ch == ";":
                self.statements_split(line)
                last_code = -1
            else:
                self._push(ch, ch, line, col0 + i)
                if not ch.isspace():
                    last_code = len(self.orig) - 1
            i += 1
        if free_form and last_code >= 0 and self.orig[last_code] == "&":
            del self.orig[last_code:]
            del self.masked[last_code:]
            del self.pos[last_code:]
            return True
        return False

    def statements_split(self, line: int) -> None:
        cond = self.condition
        self.flush()
        self.condition = cond

    def _push(self, o: str, m: str, line: int, col0: int) -> None:
        self.orig.append(o)
        self.masked.append(m)
        self.pos.append((line, col0 + 1))


def prepare(text: str, fixed_form: bool) -> PreparedSource:
    """Split ``text`` into logical statements, keeping every preprocessor branch."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    conds = _CondStack()
    result = PreparedSource(statements=[])
    builder = _Builder()
    continuing = False
    for index, raw in enumerate(lines, start=1):
        m = _DIRECTIVE.match(raw) if raw.lstrip().startswith("#") else None
        if m:
            kind, arg = m.group(1).lower(), m.group(2)
            result.directives.append(PPDirective(kind, raw.strip(), index))
            if kind == "include":
                inc = _INCLUDE_TARGET.match(raw)
                if inc:
                    col = inc.start(2) + 1
                    result.includes.append(PPInclude(inc.group(2), index, col, inc.group(1) == "<",
                                                     conds.current()))
            conds.directive(kind, arg)
            result.line_conditions.append(conds.current())
            continue
        cond = conds.current()
        result.line_conditions.append(cond)
        if fixed_form:
            if _is_fixed_comment(raw):
                continue
            body = raw.expandtabs(1) if "\t" in raw[:6] and not raw.startswith("\t") else raw
            if body.startswith("\t"):
                # Tab format: a digit right after the tab marks a continuation line.
                rest = body[1:]
                if rest[:1].isdigit() and rest[:1] != "0":
                    builder.add_text(rest[1:72], index, 2, free_form=False)
                else:
                    builder.start(cond, None)
                    builder.add_text(rest[:71], index, 1, free_form=False)
                continue
            marker = body[5:6]
            if len(body) > 5 and marker not in (" ", "0", ""):
                builder.add_text(body[6:72], index, 6, free_form=False)
            else:
                label = body[:5].strip() or None
                builder.start(cond, label)
                builder.quote = None
                builder.add_text(body[6:72], index, 6, free_form=False)
        else:
            stripped = raw.lstrip()
            if not continuing:
                if not stripped or stripped.startswith("!"):
                    continue
                builder.start(cond, None)
                builder.quote = None
                offset = len(raw) - len(stripped)
                lab = re.match(r"(\d{1,5})\s+", stripped)
                if lab:
                    builder.label = lab.group(1)
                    offset += lab.end()
                continuing = builder.add_text(raw[offset:], index, offset, free_form=True)
            else:
                if not stripped or (stripped.startswith("!") and builder.quote is None):
                    continue
                offset = len(raw) - len(stripped)
                if stripped.startswith("&"):
                    offset += 1
                continuing = builder.add_text(raw[offset:], index, offset, free_form=True)
    builder.flush()
    result.statements = builder.statements
    if conds.frames:
        result.errors.append((len(lines), "unterminated #if block"))
    return result
