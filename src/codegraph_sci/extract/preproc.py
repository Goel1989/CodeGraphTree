"""C preprocessor conditions shared by the Fortran, C and C++ adapters (all branches are kept)."""

from __future__ import annotations

import re

_WS = re.compile(r"\s+")
_DIRECTIVE = re.compile(r"^\s*#\s*(\w+)\s*(.*)$")


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


class CondStack:
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


def line_conditions(text: str) -> list[str | None]:
    """Condition of every line (index = line - 1); directive lines get the condition after them."""
    stack = CondStack()
    out: list[str | None] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw.lstrip().startswith("#"):
            m = _DIRECTIVE.match(raw)
            if m:
                stack.directive(m.group(1).lower(), m.group(2))
        out.append(stack.current())
    return out
