"""Statement-level Fortran analysis: program units, local symbols, call sites (§3.7).

Works on the logical statements produced by :mod:`source`, so fixed form, free form,
continuations, comments, strings and preprocessor branches are already handled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from codegraph_sci.core.facts import (
    ArgFact,
    DataAccess,
    Definition,
    Directive,
    FileFacts,
    IncludeRef,
    LocalSymbol,
    ParseError,
    Reference,
)
from codegraph_sci.core.ids import file_uid, fortran_module_uid, variant_uid
from codegraph_sci.core.plugins import ExtractContext
from codegraph_sci.extract.fortran.intrinsics import INTRINSICS
from codegraph_sci.extract.fortran.source import PreparedSource, Statement, prepare

ADAPTER = "fortran"
VERSION = "1.5"


class HardParseError(Exception):
    """The file structure is not understood: the caller switches to the pattern extractor."""


_TYPESPEC = (r"(?:(?:integer|real|logical|complex|character|double\s*precision|double\s*complex|byte)"
             r"\s*(?:\*\s*(?:\d+|\(\s*\*\s*\))|\((?:[^()]|\([^()]*\))*\))?\s*"
             r"|(?:type|class)\s*\(\s*\w+\s*\)\s*)")
_PREFIX = r"(?:(?:recursive|pure|elemental|impure|non_recursive|module)\s+)"
_PROC_HDR = re.compile(rf"^(?:{_PREFIX}|{_TYPESPEC})*(subroutine|function)\s+([a-z_]\w*)\s*(.*)$")
_PROGRAM = re.compile(r"^program\s+([a-z_]\w*)\s*$")
_MODULE = re.compile(r"^module\s+(?!procedure\b)([a-z_]\w*)\s*$")
_SUBMODULE = re.compile(r"^submodule\s*\([^)]*\)\s*([a-z_]\w*)\s*$")
_BLOCKDATA = re.compile(r"^block\s*data\b\s*([a-z_]\w*)?\s*$")
_INTERFACE = re.compile(r"^(abstract\s+)?interface\b\s*(.*)$")
_TYPEDEF = re.compile(r"^type\b(?!\s*\()(?!\s+is\b)\s*(?:,[^:]*)?(?:::)?\s*([a-z_]\w*)\s*(?:\(.*\))?\s*$")
_END = re.compile(r"^end\s*(subroutine|function|program|module|submodule|interface|type|procedure|block\s*data)?"
                  r"(?:\s+([a-z_]\w*|operator\s*\(.*\)|assignment\s*\(.*\)))?\s*$")
_CONTAINS = re.compile(r"^contains\s*$")
_USE = re.compile(r"^use\b\s*(?:,\s*(?:intrinsic|non_intrinsic)\s*)?(?:::)?\s*([a-z_]\w*)\s*(.*)$")
_INCLUDE = re.compile(r"^include\s*(['\"])")
_MODPROC = re.compile(r"^(?:module\s+)?procedure\b\s*(?:::)?\s*(.*)$")
_DECL = re.compile(r"^(integer|real|logical|complex|character|double\s*precision|double\s*complex|byte"
                   r"|type\s*\(|class\s*\(|procedure\s*\()")
_SIMPLE_DECL = re.compile(r"^(dimension|common|external|intrinsic|parameter|allocatable|pointer|target|intent"
                          r"|optional|save|data|equivalence|implicit|namelist|value|volatile|bind|private"
                          r"|public|protected|asynchronous|contiguous|import|format|entry|sequence)\b")
_SKIP_EXEC = re.compile(r"^(read|open|close|inquire|rewind|backspace|endfile|flush|wait|allocate|deallocate"
                        r"|nullify|format|go\s*to|return|stop|error\s*stop|continue|cycle|exit|pause|assign"
                        r"|sync|lock|unlock|fail\s*image|case|else|elsewhere|end|block|critical"
                        r"|select\s*type|type\s+is|class\s+is|class\s+default)\b")
_IDENT = re.compile(r"[a-z_]\w*")
_RESULT = re.compile(r"\bresult\s*\(\s*([a-z_]\w*)\s*\)")
_BIND = re.compile(r"\bbind\s*\(\s*c\b(?:\s*,\s*name\s*=\s*['\"]([^'\"]*)['\"])?")

ROLE_RANK = {"scalar": 0, "dummy": 1, "parameter": 2, "array": 3, "intrinsic": 4, "function": 5,
             "external": 5, "procedure_pointer": 6, "dummy_procedure": 7}
PROCEDURE_ROLES = {"dummy_procedure", "procedure_pointer"}


@dataclass
class Scope:
    kind: str  # program, module, routine, interface, ifacebody, type, blockdata
    name: str
    uid: str | None
    line: int
    condition: str | None
    parent: Scope | None
    display: str = ""
    subtype: str = ""
    signature: str = ""
    args: list[str] = field(default_factory=list)
    result: str | None = None
    symbols: dict[str, LocalSymbol] = field(default_factory=dict)
    char_vars: set[str] = field(default_factory=set)
    var_types: dict[str, str] = field(default_factory=dict)
    uses: list[str] = field(default_factory=list)
    contains: bool = False
    abstract: bool = False
    specifics: list[str] = field(default_factory=list)
    bindings: dict[str, str] = field(default_factory=dict)
    attrs: dict[str, object] = field(default_factory=dict)

    def owner(self) -> Scope | None:
        """Innermost enclosing scope that can own local symbols (routine, program, module)."""
        s: Scope | None = self
        while s is not None and s.kind not in ("routine", "program", "module", "blockdata"):
            s = s.parent
        return s


def _match_paren(text: str, i: int) -> int:
    """Index of the ``)`` matching the ``(`` at ``i`` (masked text), or -1."""
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return j
    return -1


def _split_top(text: str, lo: int, hi: int, sep: str = ",") -> list[tuple[int, int]]:
    parts, depth, start = [], 0, lo
    for j in range(lo, hi):
        c = text[j]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == sep and depth == 0:
            parts.append((start, j))
            start = j + 1
    parts.append((start, hi))
    return parts


def _top_level_assign(text: str, lo: int) -> int:
    """Index of a top-level ``=`` (or ``=>``) assignment operator, or -1."""
    depth = 0
    for j in range(lo, len(text)):
        c = text[j]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif c == "=" and depth == 0:
            prev = text[j - 1] if j > 0 else ""
            nxt = text[j + 1] if j + 1 < len(text) else ""
            if nxt == "=" or prev in "=<>/":
                continue
            return j
    return -1


def _literal(text: str) -> str | int | float | None:
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        return t[1:-1].replace(t[0] * 2, t[0])
    if re.fullmatch(r"[+-]?\d+", t):
        return int(t)
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+)([ed][+-]?\d+)?(_\w+)?", t, re.I):
        try:
            return float(re.sub(r"_\w+$", "", t).lower().replace("d", "e"))
        except ValueError:
            return None
    return None


_DEFINE_RX = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)(\(([^)]*)\))?[ \t]*(.*)$")
_PP_INCLUDE_RX = re.compile(r'(?m)^\s*#\s*include\s*["<]([^">]+)[">]')
_MACRO_FILE_CACHE: dict[str, tuple[dict[str, str], dict[str, tuple[list[str], str]], list[str]]] = {}


def _mask_strings(text: str) -> str:
    out, quote = [], None
    for ch in text:
        if quote:
            out.append(ch if ch == quote else "_")
            if ch == quote:
                quote = None
        else:
            out.append(ch)
            if ch in "'\"":
                quote = ch
    return "".join(out)


class MacroTable:
    """C preprocessor macros visible in a Fortran file (its own ``#define`` and those of included headers).

    Each statement is expanded like ``cpp`` would do; the expanded text keeps the position of the
    macro invocation, so sites found in an expansion point at the macro in the source.
    """

    def __init__(self) -> None:
        self.objects: dict[str, str] = {}
        self.functions: dict[str, tuple[list[str], str]] = {}
        self.rx: re.Pattern[str] | None = None

    @staticmethod
    def _parse(text: str) -> tuple[dict[str, str], dict[str, tuple[list[str], str]], list[str]]:
        objects: dict[str, str] = {}
        functions: dict[str, tuple[list[str], str]] = {}
        lines = text.replace("\r\n", "\n").split("\n")
        i = 0
        while i < len(lines):
            line = lines[i]
            while line.rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                line = line.rstrip()[:-1] + " " + lines[i]
            m = _DEFINE_RX.match(line)
            if m:
                body = m.group(4).split("//")[0].strip()
                if m.group(2) is not None:
                    params = [p.strip() for p in m.group(3).split(",") if p.strip()]
                    functions[m.group(1)] = (params, body)
                else:
                    objects[m.group(1)] = body
            i += 1
        return objects, functions, _PP_INCLUDE_RX.findall(text)

    def harvest(self, text: str, path: str, ctx: ExtractContext, seen: set[str], depth: int = 0,
                cache_key: str | None = None) -> None:
        if path in seen or depth > 8:
            return
        seen.add(path)
        key = f"{path}:{cache_key}" if cache_key else None
        parsed = _MACRO_FILE_CACHE.get(key) if key else None
        if parsed is None:
            parsed = self._parse(text)
            if key:
                if len(_MACRO_FILE_CACHE) > 20000:
                    _MACRO_FILE_CACHE.clear()
                _MACRO_FILE_CACHE[key] = parsed
        objects, functions, nested = parsed
        for name, body in objects.items():
            self.objects.setdefault(name, body)
        for name, spec in functions.items():
            self.functions.setdefault(name, spec)
        if ctx.resolve_include is None:
            return
        for target in nested:
            inc = ctx.resolve_include(target, path)
            if inc is not None:
                self.harvest(inc.text, inc.path, ctx, seen, depth + 1, inc.sha256)

    def compile(self) -> None:
        names = [n for n in list(self.objects) + list(self.functions) if not n.endswith("_H_") and n != "__FILE__"]
        self.rx = re.compile(r"(?<![\w%])(" + "|".join(sorted(map(re.escape, names), key=len, reverse=True)) +
                             r")(?!\w)") if names else None

    def expand(self, st: Statement, depth: int = 0) -> Statement:
        if self.rx is None or depth > 5 or not self.rx.search(st.orig):
            return st
        orig, masked, pos = st.orig, st.masked, st.pos
        out_o: list[str] = []
        out_m: list[str] = []
        out_p: list[tuple[int, int]] = []
        i = 0
        changed = False
        for m in self.rx.finditer(orig):
            start = m.start()
            if start < i or masked[start] != orig[start]:  # inside a string
                continue
            name = m.group(1)
            if name in self.functions:
                k = m.end()
                while k < len(orig) and orig[k] == " ":
                    k += 1
                if k >= len(orig) or orig[k] != "(":
                    continue
                close = _match_paren(masked, k)
                if close < 0:
                    continue
                params, body = self.functions[name]
                args = [orig[a:b].strip() for a, b in _split_top(masked, k + 1, close)] if close > k + 1 else []
                text = body
                for p, a in zip(params, args, strict=False):
                    text = re.sub(rf"(?<![\w#])#{re.escape(p)}\b", f"'{a}'", text)
                    text = re.sub(rf"\b{re.escape(p)}\b", a, text)
                end = close + 1
            else:
                text = self.objects[name]
                end = m.end()
            out_o.append(orig[i:start])
            out_m.append(masked[i:start])
            out_p.extend(pos[i:start])
            text = text.replace("##", "")
            out_o.append(text)
            out_m.append(_mask_strings(text))
            out_p.extend([pos[start]] * len(text))
            i = end
            changed = True
        if not changed:
            return st
        out_o.append(orig[i:])
        out_m.append(masked[i:])
        out_p.extend(pos[i:])
        new = Statement("".join(out_o), "".join(out_m), out_p, st.condition, st.label)
        if len(new.orig) != len(new.masked) or len(new.orig) != len(new.pos):
            return st
        return self.expand(new, depth + 1)


def _bind_name(st: Statement, offset: int, bind: re.Match[str], default: str) -> str:
    """C name of ``BIND(C, NAME="...")``, read in the original text (strings are masked)."""
    if bind.group(1) is None:
        return default
    return st.orig[offset + bind.start(1):offset + bind.end(1)]


class FortranParser:
    def __init__(self, path: str, text: str, fixed_form: bool, ctx: ExtractContext) -> None:
        self.path = path
        self.text = text
        self.fixed = fixed_form
        self.ctx = ctx
        self.known_arrays = {a.lower() for a in ctx.known_arrays}
        self.file_uid = file_uid(path)
        self.stack: list[Scope] = []
        self.definitions: list[Definition] = []
        self.references: list[Reference] = []
        self.includes: list[IncludeRef] = []
        self.data_accesses: list[DataAccess] = []
        self._data_seen: set[tuple[str, str, str, int]] = set()
        self.errors: list[ParseError] = []
        self.uid_counts: dict[str, int] = {}
        self.last_line = 0
        self.include_depth = 0
        self.seen_includes: set[str] = set()
        self.macros = MacroTable()
        self.selects: list[tuple[Scope, str]] = []

    # ----------------------------------------------------------------- driver
    def run(self) -> tuple[list[Definition], list[Reference], list[IncludeRef], list[Directive], list[ParseError]]:
        prepared = prepare(self.text, self.fixed)
        self.macros = MacroTable()
        self.macros.harvest(self.text, self.path, self.ctx, set())
        for inc in prepared.includes:
            resolved = self.ctx.resolve_include(inc.target, self.path) if self.ctx.resolve_include else None
            if resolved is not None:
                self.macros.harvest(resolved.text, resolved.path, self.ctx, set(), cache_key=resolved.sha256)
        self.macros.compile()
        for line, msg in prepared.errors:
            self.errors.append(ParseError(msg, line))
        self._process(prepared, include_source=None)
        if self.stack:
            names = ", ".join(f"{s.kind} {s.name}" for s in self.stack)
            raise HardParseError(f"unterminated program unit(s) at end of file: {names}")
        directives = [Directive(d.kind, d.text, d.line) for d in prepared.directives]
        return self.definitions, self.references, self.includes, directives, self.errors

    def _process(self, prepared: PreparedSource, include_source: str | None) -> None:
        events: list[tuple[int, int, object]] = [(st.line, 1, st) for st in prepared.statements]
        events += [(inc.line, 0, inc) for inc in prepared.includes]
        events.sort(key=lambda e: (e[0], e[1]))
        for _line, kind, item in events:
            if kind == 0:
                if include_source is None:
                    self._pp_include(item)
                continue
            assert isinstance(item, Statement)
            self.statement(item, include_source)
            if include_source is None:
                self.last_line = item.last_line

    @property
    def scope(self) -> Scope | None:
        return self.stack[-1] if self.stack else None

    # -------------------------------------------------------------- statements
    def statement(self, st: Statement, include_source: str | None) -> None:
        st = self.macros.expand(st)
        low = st.masked.lower()
        scope = self.scope
        if scope is not None and scope.kind == "ifacebody":
            # An interface body may itself contain interfaces (dummy procedures): count nesting.
            depth = int(str(scope.attrs.get("depth", 0)))
            m = _END.match(low)
            if m and not (m.group(1) is None and m.group(2)):
                if m.group(1) in (None, "subroutine", "function"):
                    if depth == 0:
                        self.stack.pop()
                    else:
                        scope.attrs["depth"] = depth - 1
                elif m.group(1) == "interface" and depth > 0:
                    scope.attrs["depth"] = depth - 1
            elif _INTERFACE.match(low) or (_PROC_HDR.match(low) and _top_level_assign(low, 0) < 0):
                scope.attrs["depth"] = depth + 1
            return
        if scope is not None and scope.kind == "interface":
            self._in_interface(st, low, scope)
            return
        if scope is not None and scope.kind == "type":
            self._in_type(st, low, scope)
            return
        if self._header(st, low):
            return
        m = _END.match(low)
        if m and not (m.group(1) is None and m.group(2)):
            self._end(st, m.group(1))
            return
        if _CONTAINS.match(low):
            if scope is not None:
                scope.contains = True
            return
        owner = scope.owner() if scope is not None else None
        m = _USE.match(low)
        if m:
            self._use(st, m, owner)
            return
        m = _INCLUDE.match(low)
        if m:
            self._fortran_include(st, m, owner)
            return
        if owner is None:
            return
        source = f"include:{include_source}" if include_source else "local"
        if _DECL.match(low) and not _PROC_HDR.match(low):
            self._declaration(st, low, owner, source)
            return
        m = _SIMPLE_DECL.match(low)
        if m and _top_level_assign(low, 0) < 0 or (m and m.group(1) in ("data", "format", "parameter")):
            assert m is not None
            self._simple_declaration(st, low, m.group(1), owner, source)
            return
        if include_source is None and owner.kind in ("routine", "program"):
            self._executable(st, low, 0, owner)

    # ----------------------------------------------------------------- headers
    def _header(self, st: Statement, low: str) -> bool:
        scope = self.scope
        m = _PROC_HDR.match(low)
        if m and not (_DECL.match(low) and "function" not in low and "subroutine" not in low):
            kind_word, name = m.group(1), m.group(2)
            if low.count("(") != low.count(")"):
                raise HardParseError(f"line {st.line}: unbalanced parentheses in {kind_word} statement")
            rest = m.group(3)
            args: list[str] = []
            am = re.match(r"\(([^()]*)\)", rest.strip())
            if am:
                args = [a.strip() for a in am.group(1).split(",") if a.strip() and a.strip() != "*"]
            if scope is not None and scope.kind == "routine" and not scope.contains:
                if scope.name == name:
                    self.errors.append(ParseError(f"alternative header of {name} ignored", st.line))
                    return True
                self.errors.append(ParseError(f"{scope.name} closed implicitly before {name}", st.line))
                self._close(scope, self.last_line)
                self.stack.pop()
                scope = self.scope
            result = _RESULT.search(rest)
            bind = _BIND.search(rest)
            display = self._orig_word(st, low, m.start(2), name)
            sub = Scope("routine", name, None, st.line, st.condition, scope, display=display,
                        subtype="f_subroutine" if kind_word == "subroutine" else "f_function",
                        signature=re.sub(r"\s+", " ", st.orig.strip()), args=args,
                        result=result.group(1) if result else (name if kind_word == "function" else None))
            sub.attrs["recursive"] = bool(re.match(rf"^(?:{_PREFIX}|{_TYPESPEC})*?recursive\b", low)) or (
                "recursive" in low[:m.start(1)])
            if bind:
                sub.attrs["bind_c"] = _bind_name(st, m.start(3), bind, name)
            for a in args:
                sub.symbols[a] = LocalSymbol(a, "dummy", "local")
            sub.uid = self._child_uid(scope, name)
            self.stack.append(sub)
            return True
        m = _PROGRAM.match(low)
        if m:
            name = m.group(1)
            sc = Scope("program", name, None, st.line, st.condition, scope,
                       display=self._orig_word(st, low, m.start(1), name), subtype="f_program")
            sc.uid = self._unique(f"f:{name}")
            self.stack.append(sc)
            return True
        m = _MODULE.match(low) or _SUBMODULE.match(low)
        if m:
            name = m.group(1)
            sc = Scope("module", name, None, st.line, st.condition, scope,
                       display=self._orig_word(st, low, m.start(1), name),
                       subtype="f_submodule" if low.startswith("submodule") else "f_module")
            sc.uid = self._unique(fortran_module_uid(name))
            self.stack.append(sc)
            return True
        m = _BLOCKDATA.match(low)
        if m:
            name = m.group(1) or "_blockdata"
            self.stack.append(Scope("blockdata", name, None, st.line, st.condition, scope))
            return True
        m = _INTERFACE.match(low)
        if m:
            generic = m.group(2).strip()
            sc = Scope("interface", generic, None, st.line, st.condition, scope, abstract=bool(m.group(1)))
            if generic and re.fullmatch(r"[a-z_]\w*", generic):
                sc.display = self._orig_word(st, low, m.start(2), generic)
                sc.uid = self._child_uid(scope, generic)
            self.stack.append(sc)
            return True
        m = _TYPEDEF.match(low)
        if m and _top_level_assign(low, 0) < 0:
            name = m.group(1)
            sc = Scope("type", name, None, st.line, st.condition, scope,
                       display=self._orig_word(st, low, m.start(1), name), subtype="f_derived_type")
            sc.uid = self._child_uid(scope, name)
            self.stack.append(sc)
            return True
        return False

    def _orig_word(self, st: Statement, low: str, start: int, name: str) -> str:
        return st.orig[start:start + len(name)]

    def _child_uid(self, parent: Scope | None, name: str) -> str:
        if parent is None:
            base = f"f:{name}"
        elif parent.kind == "module":
            base = f"f:{parent.name}::{name}"
        elif parent.uid:
            base = f"{parent.uid.split('#')[0]}::{name}"
        else:
            base = f"f:{name}"
        return self._unique(base)

    def _unique(self, uid: str) -> str:
        n = self.uid_counts.get(uid, 0) + 1
        self.uid_counts[uid] = n
        return variant_uid(uid, n)

    # -------------------------------------------------------------------- ends
    def _end(self, st: Statement, word: str | None) -> None:
        scope = self.scope
        if scope is None:
            self.errors.append(ParseError("END without an open program unit", st.line))
            return
        expected = {"subroutine": "routine", "function": "routine", "program": "program", "module": "module",
                    "submodule": "module", "interface": "interface", "type": "type", "procedure": "routine"}
        if word is not None:
            kind = "blockdata" if word.startswith("block") else expected[word]
            if kind != scope.kind:
                self.errors.append(ParseError(f"END {word.upper()} does not close {scope.kind} {scope.name}",
                                              st.line))
                return
        self._close(scope, st.last_line)
        self.stack.pop()

    def _close(self, scope: Scope, end_line: int) -> None:
        if scope.uid is None or scope.kind in ("blockdata",):
            return
        if scope.kind == "routine":
            kind, subtype = "routine", scope.subtype
        elif scope.kind == "program":
            kind, subtype = "routine", "f_program"
        elif scope.kind == "module":
            kind, subtype = "module", scope.subtype
        elif scope.kind == "type":
            kind, subtype = "type", "f_derived_type"
        elif scope.kind == "interface":
            kind, subtype = "interface", "f_generic_interface"
        else:
            return
        attrs: dict[str, object] = {k: v for k, v in scope.attrs.items() if k != "str_assign"}
        if scope.uses:
            attrs["uses"] = sorted(set(scope.uses))
        if scope.var_types:
            attrs["var_types"] = dict(sorted(scope.var_types.items()))
        if scope.specifics:
            attrs["specifics"] = sorted(set(scope.specifics))
        if scope.bindings:
            attrs["bindings"] = dict(sorted(scope.bindings.items()))
        if scope.args:
            attrs["args"] = list(scope.args)
        if scope.result and scope.subtype == "f_function":
            attrs["result"] = scope.result
        if scope.kind in ("routine", "program") and scope.contains:
            attrs["has_internal"] = True
        attrs = {k: v for k, v in attrs.items() if v not in (False, None)}
        parent = scope.parent.uid if scope.parent is not None else None
        symbols = sorted(scope.symbols.values(), key=lambda s: s.name)
        if scope.kind in ("type", "interface"):
            symbols = []
        self.definitions.append(Definition(
            uid=scope.uid, display_name=scope.display or scope.name, kind=kind, subtype=subtype,
            name=scope.name, span=(scope.line, end_line), signature=scope.signature or None, doc=None,
            local_symbols=symbols, parent=parent, condition=scope.condition, attrs=attrs))

    # ------------------------------------------------------- interfaces, types
    def _in_interface(self, st: Statement, low: str, scope: Scope) -> None:
        m = _END.match(low)
        if m and m.group(1) == "interface":
            self._close(scope, st.last_line)
            self.stack.pop()
            return
        m = _MODPROC.match(low)
        if m and (low.startswith("module") or not low.startswith("procedure(")):
            for part in m.group(1).split(","):
                name = part.strip()
                if re.fullmatch(r"[a-z_]\w*", name):
                    scope.specifics.append(name)
            return
        hm = _PROC_HDR.match(low)
        if hm:
            name = hm.group(2)
            if scope.uid:  # generic interface with explicit bodies: bodies are its specifics
                scope.specifics.append(name)
            elif not scope.abstract:
                owner = scope.owner()
                if owner is not None:
                    self._set_role(owner, name, "external", "local")
                    bind = _BIND.search(hm.group(3))
                    if bind:
                        names = owner.attrs.setdefault("bind_names", {})
                        assert isinstance(names, dict)
                        names[name] = _bind_name(st, hm.start(3), bind, name)
            self.stack.append(Scope("ifacebody", name, None, st.line, st.condition, scope))

    def _in_type(self, st: Statement, low: str, scope: Scope) -> None:
        m = _END.match(low)
        if m and m.group(1) == "type":
            self._close(scope, st.last_line)
            self.stack.pop()
            return
        if _CONTAINS.match(low):
            scope.contains = True
            return
        if scope.contains:
            pm = re.match(r"^procedure\b\s*(?:\(\s*\w+\s*\))?\s*(?:,[^:]*)?(?:::)?\s*(.*)$", low)
            if pm:
                for part in pm.group(1).split(","):
                    bm = re.match(r"\s*([a-z_]\w*)\s*(?:=>\s*([a-z_]\w*))?\s*$", part)
                    if bm:
                        scope.bindings[bm.group(1)] = bm.group(2) or bm.group(1)

    # ----------------------------------------------------------- use, include
    def _use(self, st: Statement, m: re.Match[str], owner: Scope | None) -> None:
        name = m.group(1)
        if owner is not None:
            owner.uses.append(name)
        src = owner.uid if owner is not None and owner.uid else self.file_uid
        line, col = st.at(m.start(1))
        self.references.append(Reference(src=src, target_text=st.orig[m.start(1):m.end(1)], kind="use",
                                         line=line, col=col, condition=st.condition))

    def _fortran_include(self, st: Statement, m: re.Match[str], owner: Scope | None) -> None:
        q = m.group(1)
        start = m.end()
        end = st.orig.find(q, start)
        target = st.orig[start:end if end >= 0 else len(st.orig)]
        line, col = st.at(start)
        self._include(target, line, col, st.condition, owner)

    def _pp_include(self, inc: object) -> None:
        from codegraph_sci.extract.fortran.source import PPInclude

        assert isinstance(inc, PPInclude)
        if inc.system:
            resolved = self.ctx.resolve_include(inc.target, self.path) if self.ctx.resolve_include else None
            if resolved is None:
                return
        scope = self.scope
        owner = scope.owner() if scope is not None else None
        self._include(inc.target, inc.line, inc.col, inc.condition, owner)

    def _include(self, target: str, line: int, col: int, condition: str | None, owner: Scope | None) -> None:
        self.references.append(Reference(src=self.file_uid, target_text=target, kind="include", line=line, col=col,
                                         condition=condition))
        resolved = self.ctx.resolve_include(target, self.path) if self.ctx.resolve_include else None
        self.includes.append(IncludeRef(target, resolved.path if resolved else None,
                                        resolved.sha256 if resolved else None, line))
        if resolved is None or owner is None or self.include_depth >= 8 or resolved.path in self.seen_includes:
            return
        self.seen_includes.add(resolved.path)
        self.include_depth += 1
        try:
            prepared = prepare(resolved.text, self.fixed)
            for st in prepared.statements:
                self.statement(st, resolved.path)
        finally:
            self.include_depth -= 1
            self.seen_includes.discard(resolved.path)

    # ------------------------------------------------------------ declarations
    def _set_role(self, owner: Scope, name: str, role: str, source: str) -> None:
        current = owner.symbols.get(name)
        if current is None:
            owner.symbols[name] = LocalSymbol(name, role, source)
            return
        new_role = current.role
        if role == "external" and current.role in ("dummy", "dummy_procedure"):
            new_role = "dummy_procedure"
        elif role in ("scalar",) and current.role != "scalar":
            new_role = current.role
        elif ROLE_RANK.get(role, 0) > ROLE_RANK.get(current.role, 0):
            new_role = role
            if role == "procedure_pointer" and current.role == "dummy":
                new_role = "dummy_procedure"
        src = current.source if current.source != "local" else source
        owner.symbols[name] = LocalSymbol(name, new_role, src)

    def _entities(self, low: str, lo: int) -> list[tuple[str, bool, int, int]]:
        """Parse an entity list: (name, has_dims, start, end)."""
        out = []
        for a, b in _split_top(low, lo, len(low)):
            seg = low[a:b]
            em = re.match(r"\s*([a-z_]\w*)\s*(\()?", seg)
            if em:
                out.append((em.group(1), em.group(2) is not None, a + em.start(1), b))
        return out

    def _declaration(self, st: Statement, low: str, owner: Scope, source: str) -> None:
        m = _DECL.match(low)
        assert m is not None
        i = m.end()
        type_name = None
        if low[m.start():i].endswith("("):
            close = _match_paren(low, i - 1)
            type_name = low[i:close].strip() if close > 0 else None
            i = close + 1 if close > 0 else i
        else:
            ws = re.match(r"\s*(\*\s*(\d+|\(\s*\*\s*\)))?\s*", low[i:])
            i += ws.end() if ws else 0
            if i < len(low) and low[i] == "(":
                close = _match_paren(low, i)
                i = close + 1 if close > 0 else i
        head = low[m.start():m.end()].replace(" ", "")
        is_char = head.startswith("character")
        is_proc = head.startswith("procedure")
        attrs_text, list_start = "", i
        dc = low.find("::", i)
        if dc >= 0:
            attrs_text, list_start = low[i:dc], dc + 2
        elif low[i:].lstrip().startswith(","):
            return
        attrs = attrs_text.replace(" ", "")
        external = "external" in attrs
        pointer = "pointer" in attrs
        has_dim_attr = "dimension" in attrs
        is_param = "parameter" in attrs
        is_intrinsic = "intrinsic" in attrs
        for name, dims, _a, _b in self._entities(low, list_start):
            if is_proc:
                role = "procedure_pointer" if pointer else ("dummy_procedure" if name in owner.args else "external")
            elif external:
                role = "external"
            elif is_intrinsic:
                role = "intrinsic"
            elif dims or has_dim_attr:
                role = "array"
            elif is_param:
                role = "parameter"
            else:
                role = "scalar"
            if role == "scalar" and is_char:
                owner.char_vars.add(name)
            if type_name and re.fullmatch(r"[a-z_]\w*", type_name) and not is_proc:
                owner.var_types[name] = type_name
            self._set_role(owner, name, role, source)

    def _simple_declaration(self, st: Statement, low: str, word: str, owner: Scope, source: str) -> None:
        rest_start = len(word)
        if word == "common":
            for bm in re.finditer(r"/\s*([a-z_]\w*)?\s*/", low):
                block = bm.group(1) or "_blank"
                nxt = low.find("/", bm.end())
                seg_end = nxt if nxt >= 0 else len(low)
                for name, dims, _a, _b in self._entities(low[:seg_end], bm.end()):
                    existing = owner.symbols.get(name)
                    role = "array" if dims else (existing.role if existing else "scalar")
                    owner.symbols[name] = LocalSymbol(name, role if role != "dummy" else "scalar",
                                                      f"common:{block}")
                owner.attrs.setdefault("commons", [])
                commons = owner.attrs["commons"]
                assert isinstance(commons, list)
                if block not in commons:
                    commons.append(block)
            return
        if word in ("dimension", "allocatable", "pointer", "target"):
            start = low.find("::")
            start = start + 2 if start >= 0 else rest_start
            for name, dims, _a, _b in self._entities(low, start):
                if word == "pointer" and not dims:
                    continue
                if dims or word in ("dimension",):
                    self._set_role(owner, name, "array", source)
            return
        if word in ("external", "intrinsic"):
            start = low.find("::")
            start = start + 2 if start >= 0 else rest_start
            for name, _d, _a, _b in self._entities(low, start):
                self._set_role(owner, name, word, source)
            return
        if word == "parameter":
            p = low.find("(")
            if p >= 0:
                close = _match_paren(low, p)
                for a, b in _split_top(low, p + 1, close if close > 0 else len(low)):
                    pm = re.match(r"\s*([a-z_]\w*)\s*=", low[a:b])
                    if pm:
                        self._set_role(owner, pm.group(1), "parameter", source)

    # -------------------------------------------------------------- executable
    def _executable(self, st: Statement, low: str, lo: int, owner: Scope) -> None:
        s = low[lo:]
        stripped = s.lstrip()
        lo += len(s) - len(stripped)
        s = stripped
        if not s:
            return
        if re.match(r"end\s*select", s):
            if self.selects:
                self.selects.pop()
            return
        m = re.match(r"case\s*\(", s)
        if m and self.selects:
            sel_owner, selector = self.selects[-1]
            p = lo + m.end() - 1
            close = _match_paren(low, p)
            cases = sel_owner.attrs.setdefault("select_cases", {})
            assert isinstance(cases, dict)
            for a, b in _split_top(low, p + 1, close if close > 0 else len(low)):
                value = st.orig[a:b].strip()
                bounds = re.fullmatch(r"(-?\d+)\s*:\s*(-?\d+)", value)
                values = [str(v) for v in range(int(bounds.group(1)), int(bounds.group(2)) + 1)] if bounds and (
                    int(bounds.group(2)) - int(bounds.group(1)) < 1000) else [value]
                cases.setdefault(selector, []).extend(values)
            return
        m = re.match(r"call\s*(?=[a-z_])", s)
        if m and _top_level_assign(low, lo) < 0:
            self._call_statement(st, low, lo + m.end(), owner)
            return
        m = re.match(r"(?:else\s*)?if\s*\(", s)
        if m:
            p = lo + m.end() - 1
            close = _match_paren(low, p)
            if close < 0:
                return
            self._scan(st, low, p + 1, close, owner)
            rest = low[close + 1:].strip()
            if rest and rest != "then" and not rest.startswith("then"):
                self._executable(st, low, close + 1, owner)
            return
        m = re.match(r"(where|forall|select\s*case|do\s+while|do\s+concurrent|while)\s*\(", s)
        if m:
            p = lo + m.end() - 1
            close = _match_paren(low, p)
            if close < 0:
                return
            self._scan(st, low, p + 1, close, owner)
            if m.group(1).startswith("select"):
                self.selects.append((owner, re.sub(r"\s+", "", low[p + 1:close])))
            if m.group(1) in ("where", "forall") and low[close + 1:].strip():
                self._executable(st, low, close + 1, owner)
            return
        if re.match(r"do\b", s):
            eq = low.find("=", lo)
            if eq >= 0:
                self._scan(st, low, eq + 1, len(low), owner)
            return
        if re.match(r"associate\s*\(", s):
            p = low.find("(", lo)
            close = _match_paren(low, p)
            self._scan(st, low, p + 1, close if close > 0 else len(low), owner)
            return
        eq = _top_level_assign(low, lo)
        if eq >= 0 and re.match(r"[a-z_]\w*\s*(\(|%|=|\[)", s):
            rhs = eq + 2 if low[eq + 1:eq + 2] == ">" else eq + 1
            lhs = _IDENT.match(low, lo)
            if lhs is not None:
                self._data(owner, lhs.group(0), "writes", st.at(lo)[0])
                rhs_text = st.orig[rhs:].strip()
                if low[lhs.end():rhs].strip() in ("", "=") and ("'" in rhs_text or '"' in rhs_text):
                    assigns = owner.attrs.setdefault("str_assign", {})
                    assert isinstance(assigns, dict)
                    assigns[lhs.group(0)] = rhs_text  # simple propagation of character expressions
            self._scan(st, low, lhs.end() if lhs is not None and low[lhs.end():lhs.end() + 1] == "(" else rhs,
                       len(low), owner, skip_until=rhs)
            return
        m = re.match(r"(write|print)\b\s*", s)
        if m:
            i = lo + m.end()
            if m.group(1) == "write" and i < len(low) and low[i] == "(":
                close = _match_paren(low, i)
                i = close + 1 if close > 0 else len(low)
            else:
                parts = _split_top(low, i, len(low))
                i = parts[1][0] if len(parts) > 1 else len(low)
            self._scan(st, low, i, len(low), owner)
            return
        m = re.match(r"(stop|error\s*stop|return)\b", s)
        if m or _SKIP_EXEC.match(s):
            return

    def _call_statement(self, st: Statement, low: str, i: int, owner: Scope) -> None:
        nm = _IDENT.match(low, i)
        if nm is None:
            return
        name_start, j = nm.start(), nm.end()
        chain = [nm.group(0)]
        n = len(low)
        while True:
            k = j
            while k < n and low[k] == " ":
                k += 1
            if k < n and low[k] == "(":
                close = _match_paren(low, k)
                after = close + 1
                while after < n and low[after] == " ":
                    after += 1
                if close > 0 and after < n and low[after] == "%":
                    j = after
                    continue
                break
            if k < n and low[k] == "%":
                nm2 = _IDENT.match(low, k + 1 + (len(low[k + 1:]) - len(low[k + 1:].lstrip())))
                if nm2 is None:
                    break
                chain.append(nm2.group(0))
                j = nm2.end()
                continue
            break
        target = re.sub(r"\s+", "", st.orig[name_start:j])
        line, col = st.at(name_start)
        args: list[ArgFact] = []
        k = j
        while k < n and low[k] == " ":
            k += 1
        if k < n and low[k] == "(":
            close = _match_paren(low, k)
            end = close if close > 0 else n
            if end > k + 1 and low[k + 1:end].strip():
                for a, b in _split_top(low, k + 1, end):
                    text = st.orig[a:b].strip()
                    args.append(ArgFact(text, _literal(text)))
            self._scan(st, low, k + 1, end, owner)
        assigns = owner.attrs.get("str_assign")
        if isinstance(assigns, dict) and args:
            exprs = {str(i): assigns[a.text.lower()] for i, a in enumerate(args) if a.text.lower() in assigns}
            if exprs:
                arg_exprs = exprs
            else:
                arg_exprs = {}
        else:
            arg_exprs = {}
        name = chain[0]
        hint: dict[str, object] = {}
        kind = "call"
        if len(chain) > 1:
            hint = {"binding": chain[-1], "base": name}
            base_type = owner.var_types.get(name)
            if base_type:
                hint["base_type"] = base_type
        else:
            sym = self._lookup(owner, name)
            if sym is not None and sym.role in PROCEDURE_ROLES:
                kind = "dynamic_call"
            s: Scope | None = owner
            while s is not None:
                names = s.attrs.get("bind_names")
                if isinstance(names, dict) and name in names:
                    hint = {"bind_c": names[name]}
                    break
                s = s.parent
            if kind == "call" and not hint and name in INTRINSICS and (sym is None or sym.role == "intrinsic"):
                # CALL system_clock(...), CALL c_f_pointer(...): intrinsic subroutines (a routine of the
                # repository with the same name still wins at link time).
                hint = {"intrinsic": True}
        self.references.append(Reference(src=owner.uid or self.file_uid, target_text=target, kind=kind, line=line,
                                         col=col, args=args, condition=self._cond(st, line),
                                         hint={**hint, "arg_exprs": arg_exprs} if arg_exprs else hint))

    def _cond(self, st: Statement, line: int) -> str | None:
        return st.condition

    def _data(self, owner: Scope, name: str, mode: str, line: int) -> None:
        """Access to shared data: a COMMON member, or a name not declared locally (maybe a module variable)."""
        if owner.uid is None or owner.kind not in ("routine", "program"):
            return
        sym = self._lookup(owner, name)
        if sym is not None:
            if not sym.source.startswith("common:") or sym.role in PROCEDURE_ROLES:
                return
            key, subtype = sym.source, "common_block"
        else:
            if name in INTRINSICS or name == owner.result or name in owner.args:
                return
            key, subtype = f"var:{name}", "module_variable"
        marker = (owner.uid, key, mode, line)
        if marker in self._data_seen:
            return
        self._data_seen.add(marker)
        self.data_accesses.append(DataAccess(owner.uid, key, mode, "literal", line, subtype=subtype,
                                             origin="native:fortran"))

    def _scan(self, st: Statement, low: str, lo: int, hi: int, owner: Scope, skip_until: int = -1) -> None:
        """Find ``name(`` function references in an expression (rules of §3.7)."""
        i = lo
        while i < hi:
            c = low[i]
            if not (c.isalpha() or c == "_"):
                i += 1
                continue
            j = i
            while j < hi and (low[j].isalnum() or low[j] == "_"):
                j += 1
            prev = low[i - 1] if i > 0 else " "
            if prev.isalnum() or prev == "_":
                i = j
                continue
            if prev == "." and j < len(low) and low[j] == ".":
                i = j + 1
                continue
            name = low[i:j]
            k = j
            while k < hi and low[k] == " ":
                k += 1
            if prev == "%":
                i = j
                continue
            if k < hi and low[k] == "%":
                # x%binding( ... ) : type-bound procedure reference when the type of x is known
                nm2 = _IDENT.match(low, k + 1)
                if nm2 is not None:
                    k2 = nm2.end()
                    while k2 < hi and low[k2] == " ":
                        k2 += 1
                    base_type = owner.var_types.get(name)
                    if k2 < hi and low[k2] == "(" and base_type:
                        line, col = st.at(i)
                        target = re.sub(r"\s+", "", st.orig[i:nm2.end()])
                        self.references.append(Reference(
                            src=owner.uid or self.file_uid, target_text=target, kind="call", line=line, col=col,
                            condition=st.condition,
                            hint={"binding": nm2.group(0), "base": name, "base_type": base_type,
                                  "component_ok": True}))
                    i = nm2.end()
                    continue
            if k >= hi or low[k] != "(":
                if i >= skip_until:
                    self._data(owner, name, "reads", st.at(i)[0])
                i = j
                continue
            if i < skip_until:  # subscripts of the assigned variable: read, not called
                i = j
                continue
            ref_kind = self._classify(name, owner)
            if ref_kind is None:
                self._data(owner, name, "reads", st.at(i)[0])
            if ref_kind is not None:
                line, col = st.at(i)
                hint = {"intrinsic": True} if ref_kind == "maybe_call" and name in INTRINSICS else {}
                close = _match_paren(low, k)
                args: list[ArgFact] = []
                if close > 0 and low[k + 1:close].strip():
                    for a, b in _split_top(low, k + 1, close):
                        text = st.orig[a:b].strip()
                        args.append(ArgFact(text, _literal(text)))
                self.references.append(Reference(
                    src=owner.uid or self.file_uid, target_text=st.orig[i:j], kind=ref_kind, line=line, col=col,
                    args=args, condition=st.condition, hint=hint))
            i = j

    @staticmethod
    def _lookup(owner: Scope, name: str) -> LocalSymbol | None:
        """Local declaration, else host association (host routine, program, module)."""
        s: Scope | None = owner
        while s is not None:
            sym = s.symbols.get(name)
            if sym is not None:
                return sym
            s = s.parent
            while s is not None and s.kind not in ("routine", "program", "module"):
                s = s.parent
        return None

    def _classify(self, name: str, owner: Scope) -> str | None:
        """Rules of §3.7 for ``name(...)`` in an expression. None = data access (not a site)."""
        sym = self._lookup(owner, name)
        if sym is not None:
            if sym.role in ("array", "parameter", "dummy"):
                return None
            if sym.role == "scalar":
                if name in owner.char_vars:
                    return None
                return "call"
            if sym.role in ("external", "function"):
                return "call"
            if sym.role == "intrinsic":
                return "maybe_call"
            if sym.role in PROCEDURE_ROLES:
                return "dynamic_call"
        if name in self.known_arrays:
            return None
        if owner.result and name == owner.result and owner.subtype == "f_function" and not owner.attrs.get(
                "recursive"):
            return None
        return "maybe_call"


def extract_fortran(path: str, text: str, encoding: str, variant: str | None, ctx: ExtractContext) -> FileFacts:
    fixed = (variant or "").startswith("fixed")
    parser = FortranParser(path, text, fixed, ctx)
    definitions, references, includes, directives, errors = parser.run()
    return FileFacts(path=path, lang="fortran", encoding=encoding, adapter=ADAPTER, adapter_version=VERSION,
                     definitions=definitions, references=references, includes=includes, directives=directives,
                     errors=errors, variant=variant, data_accesses=parser.data_accesses).sort()
