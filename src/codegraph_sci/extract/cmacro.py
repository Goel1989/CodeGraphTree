"""C preprocessor macro expansion (object-like and function-like macros, ``#`` and ``##``, ``__VA_ARGS__``).

Used by the C and C++ adapters to see through macros that hide calls or declare functions,
e.g. ``CALL_X()`` -> ``F_FUNC(X, x)()`` -> ``x_()``. Pure text processing: never executes anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_IDENT_RX = re.compile(r"[A-Za-z_]\w*")
CALL_RX = re.compile(r"(?<![\w.>#])([A-Za-z_]\w*)\s*\(")
C_KEYWORDS = frozenset("""if while for switch return sizeof do else case goto typedef struct union enum
static extern const volatile inline defined alignof decltype typeid static_assert noexcept catch new delete
throw operator template typename void int char short long float double signed unsigned bool auto""".split())


@dataclass
class Macro:
    name: str
    params: list[str] | None
    body: str


def macro_args(text: str, start: int) -> tuple[list[str], int] | None:
    """Arguments of an invocation whose ``(`` is at ``start``: (arguments, index after the ``)``)."""
    depth, i, cur = 0, start, start + 1
    args: list[str] = []
    quote: str | None = None
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                args.append(text[cur:i].strip())
                return (args if any(args) else []), i + 1
        elif ch == "," and depth == 1:
            args.append(text[cur:i].strip())
            cur = i + 1
        i += 1
    return None


def _substitute(macro: Macro, args: list[str]) -> str:
    params = list(macro.params or [])
    values: dict[str, str] = {}
    for idx, prm in enumerate(params):
        if prm == "..." or prm.endswith("..."):
            values["__VA_ARGS__"] = ", ".join(args[idx:])
            break
        values[prm] = args[idx] if idx < len(args) else ""
    body = macro.body
    if values:
        names = "|".join(sorted(map(re.escape, values), key=len, reverse=True))
        body = re.sub(r"(?<![\w#])#\s*(" + names + r")\b", lambda m: '"' + values[m.group(1)] + '"', body)
        body = re.sub(r"\b(" + names + r")\b", lambda m: values[m.group(1)], body)
    return re.sub(r"\s*##\s*", "", body)


def expand_text(text: str, macros: dict[str, Macro], disabled: frozenset[str] = frozenset(), depth: int = 0) -> str:
    """Expand every macro of ``text`` (a macro is not expanded inside its own expansion)."""
    if depth > 12 or not macros:
        return text
    out: list[str] = []
    i = 0
    changed = False
    for m in _IDENT_RX.finditer(text):
        if m.start() < i:
            continue
        name = m.group(0)
        macro = macros.get(name)
        if macro is None or name in disabled:
            continue
        if macro.params is None:
            replacement, end = macro.body, m.end()
        else:
            k = m.end()
            while k < len(text) and text[k] in " \t":
                k += 1
            if k >= len(text) or text[k] != "(":
                continue
            parsed = macro_args(text, k)
            if parsed is None:
                continue
            args, end = parsed
            replacement = _substitute(macro, args)
        out.append(text[i:m.start()])
        out.append(expand_text(replacement, macros, disabled | {name}, depth + 1))
        i = end
        changed = True
    if not changed:
        return text
    out.append(text[i:])
    return "".join(out)


def callees_of(expanded: str, macros: dict[str, Macro]) -> list[str]:
    """Functions called in an expanded text (method calls on objects, keywords and macros excluded)."""
    text = re.sub(r'"(?:\\.|[^"\\])*"', '""', expanded)
    out = []
    for m in CALL_RX.finditer(text):
        callee = m.group(1)
        before = text[:m.start(1)].rstrip()
        if callee in C_KEYWORDS or callee in macros or before.endswith((".", "->", "::")):
            continue
        out.append(callee)
    return out


def declared_name(declarator: str, macros: dict[str, Macro]) -> str | None:
    """Real name of a function declared through a macro (``DEFS(X, x, ...)`` -> ``x_``)."""
    expanded = re.sub(r"\b__stdcall\b", " ", expand_text(declarator, macros))
    m = re.search(r"([A-Za-z_]\w*)\s*\(", expanded)
    if m and m.group(1) not in C_KEYWORDS:
        return m.group(1)
    return None
