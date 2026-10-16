"""Independent pattern extractor for Fortran: line-based, deliberately simple.

Used (1) as a fallback when the statement parser cannot understand a file, and (2) as the
second extractor of the double extraction (audit). It shares no code with the parser on
purpose: it only finds program units and CALL statements.
"""

from __future__ import annotations

import re

from codegraph_sci.core.facts import Definition, FileFacts, ParseError, Reference
from codegraph_sci.core.ids import file_uid, fortran_module_uid, variant_uid

ADAPTER = "fortran-patterns"
VERSION = "1.0"

_HEADER = re.compile(r"^\s*(?:(?:recursive|pure|elemental|impure|module|integer|real|logical|complex|character"
                     r"|double\s+precision|type\s*\(\s*\w+\s*\))[\s*()\w=,]*?\s+)?(subroutine|function|program)"
                     r"\s+([a-z_]\w*)", re.I)
_MODULE = re.compile(r"^\s*module\s+(?!procedure\b)([a-z_]\w*)\s*$", re.I)
_END = re.compile(r"^\s*end\s*(subroutine|function|program|module|interface)?\s*(\w*)\s*$", re.I)
_INTERFACE = re.compile(r"^\s*(abstract\s+)?interface\b", re.I)
_CALL = re.compile(r"\bcall\s+([a-z_]\w*(?:\s*%\s*[a-z_]\w*)*)", re.I)
_CONTAINS = re.compile(r"^\s*contains\s*$", re.I)
_STRING = re.compile(r"'[^']*'|\"[^\"]*\"")


def _code_part(line: str, fixed: bool) -> str | None:
    """Code of a physical line with comments and strings blanked (same length), or None."""
    if line.lstrip().startswith("#"):
        return None
    if fixed:
        if not line.strip() or line[:1] in "cC*!dD":
            return None
        line = line[:72]
        line = " " * 6 + line[6:] if len(line) > 6 else line
    line = _STRING.sub(lambda m: " " * len(m.group(0)), line)
    bang = line.find("!")
    if bang >= 0:
        line = line[:bang]
    return line if line.strip() else None


def extract_patterns(path: str, text: str, encoding: str, variant: str | None) -> FileFacts:
    fixed = (variant or "").startswith("fixed")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    definitions: list[Definition] = []
    references: list[Reference] = []
    errors: list[ParseError] = []
    stack: list[tuple[str, str, str, int]] = []  # (kind, name, uid, start line)
    counts: dict[str, int] = {}
    in_interface = 0
    module: str | None = None
    module_contains = False

    def unique(uid: str) -> str:
        counts[uid] = counts.get(uid, 0) + 1
        return variant_uid(uid, counts[uid])

    def close(end_line: int) -> None:
        kind, name, uid, start = stack.pop()
        if kind == "module":
            definitions.append(Definition(uid, name, "module", "f_module", name.lower(), (start, end_line)))
        else:
            subtype = {"subroutine": "f_subroutine", "function": "f_function", "program": "f_program"}[kind]
            definitions.append(Definition(uid, name, "routine", subtype, name.lower(), (start, end_line)))

    for number, raw in enumerate(lines, start=1):
        code = _code_part(raw, fixed)
        if code is None:
            continue
        if _INTERFACE.match(code):
            in_interface += 1
            continue
        end = _END.match(code)
        if end:
            word = (end.group(1) or "").lower()
            if word == "interface":
                in_interface = max(0, in_interface - 1)
            elif in_interface:
                continue
            elif stack:
                if stack[-1][0] == "module":
                    module, module_contains = None, False
                close(number)
            continue
        if in_interface:
            continue
        if _CONTAINS.match(code) and stack and stack[-1][0] == "module":
            module_contains = True
            continue
        mm = _MODULE.match(code)
        if mm:
            module, module_contains = mm.group(1).lower(), False
            stack.append(("module", mm.group(1), unique(fortran_module_uid(mm.group(1))), number))
            continue
        hm = _HEADER.match(code)
        if hm and "=" not in code[:hm.start(1)]:
            name = hm.group(2)
            if stack and stack[-1][0] in ("subroutine", "function", "program") and not module_contains:
                close(number - 1)
            base = f"f:{module}::{name.lower()}" if module and module_contains else f"f:{name.lower()}"
            stack.append((hm.group(1).lower(), name, unique(base), number))
            continue
        for cm in _CALL.finditer(code):
            if not stack or stack[-1][0] == "module":
                continue
            target = re.sub(r"\s+", "", cm.group(1))
            references.append(Reference(src=stack[-1][2], target_text=target, kind="call", line=number,
                                        col=cm.start(1) + 1))
    if stack:
        errors.append(ParseError("unterminated program unit at end of file", len(lines)))
        while stack:
            close(len(lines))
    return FileFacts(path=path, lang="fortran", encoding=encoding, adapter=ADAPTER, adapter_version=VERSION,
                     definitions=definitions, references=references, errors=errors, used_fallback=True,
                     variant=variant).sort()


def file_node_uid(path: str) -> str:
    return file_uid(path)
