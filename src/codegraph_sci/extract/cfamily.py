"""C and C++ extraction with tree-sitter: definitions, call sites, includes, partial macro expansion.

Identities (§3.5): ``c:<name>`` (``@<file>`` for ``static``), ``cpp:<ns>::<Class>::<name>(<param types>)``.
Overload choice, inheritance and cross-file lookups are left to Link: references carry hints
(enclosing namespaces and class, receiver type, argument types).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import tree_sitter

from codegraph_sci.core.facts import (
    ArgFact,
    Definition,
    Directive,
    FileFacts,
    IncludeRef,
    ParseError,
    Reference,
)
from codegraph_sci.core.ids import c_uid, cpp_uid, file_uid, normalize_cpp_params
from codegraph_sci.core.plugins import ExtractContext
from codegraph_sci.extract.preproc import line_conditions

_PARSERS: dict[str, tree_sitter.Parser] = {}
_DEFINE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)(\(([^)]*)\))?\s*(.*)$")
_CALL_IN_BODY = re.compile(r"(?<![\w.>#])([A-Za-z_]\w*)\s*\(")
_C_KEYWORDS = frozenset("""if while for switch return sizeof do else case goto typedef struct union enum
static extern const volatile inline defined alignof decltype typeid static_assert noexcept catch new delete
throw operator template typename void int char short long float double signed unsigned bool auto""".split())
_MACRO_BLOCK = re.compile(r"^[A-Z][A-Z0-9_]*$")


def parser_for(lang: str) -> tree_sitter.Parser:
    if lang not in _PARSERS:
        if lang == "c":
            import tree_sitter_c as mod
        else:
            import tree_sitter_cpp as mod  # type: ignore[no-redef]
        _PARSERS[lang] = tree_sitter.Parser(tree_sitter.Language(mod.language()))
    return _PARSERS[lang]


def _t(node: tree_sitter.Node | None) -> str:
    if node is None or node.text is None:
        return ""
    return node.text.decode("utf-8", errors="replace")


@dataclass
class Macro:
    name: str
    params: list[str] | None
    body: str


@dataclass
class _State:
    namespaces: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)  # qualified class names
    src: str = ""
    locals: dict[str, str] = field(default_factory=dict)  # local name -> declared type (normalized)
    in_function: bool = False
    anonymous_ns: bool = False


def _base_type(type_text: str) -> str:
    t = re.sub(r"\b(const|volatile|struct|class|typename|mutable|static|inline|constexpr)\b", " ", type_text)
    t = t.replace("&", " ").replace("*", " ")
    return re.sub(r"\s+", " ", t).strip()


def collect_macros(text: str) -> dict[str, Macro]:
    macros: dict[str, Macro] = {}
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        while line.endswith("\\") and i + 1 < len(lines):
            i += 1
            line = line[:-1] + " " + lines[i]
        m = _DEFINE.match(line)
        if m:
            params = [p.strip() for p in m.group(3).split(",")] if m.group(2) else None
            macros[m.group(1)] = Macro(m.group(1), [p for p in params if p] if params is not None else None,
                                       m.group(4).strip())
        i += 1
    return macros


class CFamilyExtractor:
    def __init__(self, lang: str, path: str, text: str, encoding: str, ctx: ExtractContext,
                 adapter: str, version: str) -> None:
        self.lang = lang
        self.path = path
        self.text = text
        self.encoding = encoding
        self.ctx = ctx
        self.adapter = adapter
        self.version = version
        self.lines = text.replace("\r\n", "\n").split("\n")
        self.conditions = line_conditions(text)
        self.file_uid = file_uid(path)
        self.definitions: list[Definition] = []
        self.references: list[Reference] = []
        self.includes: list[IncludeRef] = []
        self.directives: list[Directive] = []
        self.errors: list[ParseError] = []
        self.macros: dict[str, Macro] = {}
        self.namespace_names: set[str] = set()
        self.uid_counts: dict[str, int] = {}

    # ------------------------------------------------------------ helpers
    def col(self, node: tree_sitter.Node) -> int:
        row, byte_col = node.start_point
        line = self.lines[row] if row < len(self.lines) else ""
        if line.isascii():
            return byte_col + 1
        return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore")) + 1

    def cond(self, line: int) -> str | None:
        return self.conditions[line - 1] if 0 < line <= len(self.conditions) else None

    def unique(self, uid: str) -> str:
        n = self.uid_counts.get(uid, 0) + 1
        self.uid_counts[uid] = n
        return uid if n == 1 else f"{uid}#{n}"

    # ------------------------------------------------------------- driver
    def run(self) -> FileFacts:
        self.macros = collect_macros(self.text)
        tree = parser_for(self.lang).parse(self.text.encode("utf-8"))
        if tree.root_node.has_error:
            self.errors.append(ParseError("tree-sitter reported syntax errors (partial extraction)"))
        self._includes(tree.root_node)
        used_fallback = tree.root_node.has_error and self._error_ratio(tree.root_node) > 0.5
        if used_fallback:
            self.errors.append(ParseError("more than half of the file is not understood: pattern extractor used"))
            self.pattern_extract()
        else:
            self.visit(tree.root_node, _State(src=self.file_uid))
        return FileFacts(path=self.path, lang=self.lang, encoding=self.encoding, adapter=self.adapter,
                         adapter_version=self.version, definitions=self.definitions, references=self.references,
                         includes=self.includes, directives=self.directives, errors=self.errors,
                         used_fallback=used_fallback).sort()

    def _error_ratio(self, root: tree_sitter.Node) -> float:
        """Share of the code lines covered by tree-sitter ERROR nodes."""
        code = {i for i, ln in enumerate(self.lines) if ln.strip() and not ln.lstrip().startswith(("#", "//"))}
        if not code:
            return 0.0
        bad: set[int] = set()
        stack = [root]
        while stack:
            node = stack.pop()
            if node.type == "ERROR":
                bad.update(range(node.start_point[0], node.end_point[0] + 1))
                continue
            if node.has_error:
                stack.extend(node.children)
        return len(bad & code) / len(code)

    def pattern_extract(self) -> None:
        """Fallback: regular expressions on the text with comments and strings blanked."""
        def blank(m: re.Match[str]) -> str:
            return re.sub(r"[^\n]", " ", m.group(0))

        clean = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', blank, self.text,
                       flags=re.S)
        clean = re.sub(r"(?m)^[ \t]*#[^\n]*", blank, clean)
        line_starts = [0]
        for m in re.finditer("\n", clean):
            line_starts.append(m.end())

        def pos(offset: int) -> tuple[int, int]:
            lo, hi = 0, len(line_starts) - 1
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if line_starts[mid] <= offset:
                    lo = mid
                else:
                    hi = mid - 1
            return lo + 1, offset - line_starts[lo] + 1

        header = re.compile(r"(?m)^[ \t]*(?:[\w:<>,*&~]+[ \t*&]+)+([A-Za-z_~][\w:~]*)\s*\(([^;{}()]*)\)"
                            r"\s*(?:const\s*)?\{")
        for m in header.finditer(clean):
            raw = m.group(1)
            if raw in _C_KEYWORDS:
                continue
            depth, end = 0, len(clean)
            for i in range(m.end() - 1, len(clean)):
                if clean[i] == "{":
                    depth += 1
                elif clean[i] == "}":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            params = [re.sub(r"\s*\b\w+\s*$", "", p.strip()) or p.strip() for p in m.group(2).split(",")
                      if p.strip()]
            start_line, end_line = pos(m.start(1))[0], pos(end)[0]
            name = raw.split("::")[-1]
            uid = self.unique(c_uid(raw) if self.lang == "c" else cpp_uid(raw, params))
            self.definitions.append(Definition(uid, name, "routine",
                                               "c_function" if self.lang == "c" else "cpp_function", name,
                                               (start_line, end_line), attrs={"qualified": raw}))
            for cm in _CALL_IN_BODY.finditer(clean, m.end(), end):
                callee = cm.group(1)
                if callee in _C_KEYWORDS:
                    continue
                line, col = pos(cm.start(1))
                self.references.append(Reference(uid, callee, "call", line, col, condition=self.cond(line),
                                                 hint={"name": callee, "namespaces": []}))

    def _includes(self, root: tree_sitter.Node) -> None:
        stack = [root]
        seen_macro_files: set[str] = set()
        while stack:
            node = stack.pop()
            if node.type == "preproc_include":
                path_node = node.child_by_field_name("path")
                if path_node is None:
                    continue
                raw = _t(path_node)
                system = path_node.type == "system_lib_string"
                target = raw[1:-1] if len(raw) >= 2 else raw
                resolved = self.ctx.resolve_include(target, self.path) if self.ctx.resolve_include else None
                line = path_node.start_point[0] + 1
                self.directives.append(Directive("include", _t(node).strip(), line))
                if system and resolved is None:
                    continue
                self.references.append(Reference(self.file_uid, target, "include", line, self.col(path_node) + 1,
                                                 condition=self.cond(line)))
                self.includes.append(IncludeRef(target, resolved.path if resolved else None,
                                                resolved.sha256 if resolved else None, line))
                if resolved is not None:
                    self._macros_from(resolved.path, resolved.text, seen_macro_files, 0)
                continue
            if node.type in ("preproc_ifdef", "preproc_if", "preproc_elif", "preproc_else", "preproc_def",
                             "preproc_function_def"):
                kind = node.type.replace("preproc_", "")
                self.directives.append(Directive(kind, _t(node).split("\n", 1)[0].strip(),
                                                 node.start_point[0] + 1))
            stack.extend(reversed(node.children))

    def _macros_from(self, path: str, text: str, seen: set[str], depth: int) -> None:
        if path in seen or depth > 6:
            return
        seen.add(path)
        for name, macro in collect_macros(text).items():
            self.macros.setdefault(name, macro)
        if self.ctx.resolve_include is None:
            return
        for m in re.finditer(r'(?m)^\s*#\s*include\s*"([^"]+)"', text):
            inc = self.ctx.resolve_include(m.group(1), path)
            if inc is not None:
                self._macros_from(inc.path, inc.text, seen, depth + 1)

    # ------------------------------------------------------------ walking
    def visit(self, node: tree_sitter.Node, st: _State) -> None:
        t = node.type
        if t == "namespace_definition":
            name = _t(node.child_by_field_name("name"))
            body = node.child_by_field_name("body")
            inner = _State(st.namespaces + ([n for n in name.split("::") if n] if name else []), list(st.classes),
                           st.src, dict(st.locals), st.in_function, st.anonymous_ns or not name)
            if name:
                self.namespace_names.update(name.split("::"))
            if body is not None:
                for child in body.children:
                    self.visit(child, inner)
            return
        if t in ("class_specifier", "struct_specifier") and self.lang == "cpp":
            self.class_definition(node, st)
            return
        if t == "function_definition":
            self.function_definition(node, st)
            return
        if t == "call_expression":
            self.call(node, st)
        if t == "declaration" and st.in_function:
            self.local_declaration(node, st)
        for child in node.children:
            self.visit(child, st)

    def local_declaration(self, node: tree_sitter.Node, st: _State) -> None:
        type_node = node.child_by_field_name("type")
        if type_node is None:
            return
        base = _base_type(_t(type_node))
        for decl in node.children_by_field_name("declarator"):
            name = self._declared_name(decl)
            if name:
                st.locals[name] = base + ("*" if "*" in _t(decl).split("=")[0] else "")

    @staticmethod
    def _declared_name(decl: tree_sitter.Node) -> str | None:
        node: tree_sitter.Node | None = decl
        while node is not None:
            if node.type in ("identifier", "field_identifier"):
                return _t(node)
            inner = node.child_by_field_name("declarator")
            if inner is None:
                for c in node.children:
                    if c.type in ("identifier", "field_identifier"):
                        return _t(c)
                return None
            node = inner
        return None

    # -------------------------------------------------------- definitions
    def class_definition(self, node: tree_sitter.Node, st: _State) -> None:
        name_node = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        if name_node is None or body is None:
            for child in node.children:
                self.visit(child, st)
            return
        name = _t(name_node)
        prefix = st.classes[-1] if st.classes else "::".join(st.namespaces)
        qualified = f"{prefix}::{name}" if prefix else name
        uid = self.unique(cpp_uid(qualified, None))
        line_start, line_end = node.start_point[0] + 1, node.end_point[0] + 1
        subtype = "cpp_class" if node.type == "class_specifier" else "cpp_struct"
        self.definitions.append(Definition(uid, name, "type", subtype, name, (line_start, line_end),
                                           parent=st.src if st.src != self.file_uid else None,
                                           condition=self.cond(line_start), attrs={"qualified": qualified}))
        for child in node.children:
            if child.type == "base_class_clause":
                for base in child.children:
                    if base.type in ("type_identifier", "qualified_identifier", "template_type"):
                        text = _t(base)
                        line = base.start_point[0] + 1
                        self.references.append(Reference(uid, text, "inherit", line, self.col(base),
                                                         condition=self.cond(line),
                                                         hint={"namespaces": list(st.namespaces),
                                                               "class": qualified}))
        inner = _State(list(st.namespaces), st.classes + [qualified], uid, {}, False, st.anonymous_ns)
        for child in body.children:
            self.visit(child, inner)

    def function_definition(self, node: tree_sitter.Node, st: _State) -> None:
        body = node.child_by_field_name("body")
        declarator = node.child_by_field_name("declarator")
        fdecl = declarator
        while fdecl is not None and fdecl.type != "function_declarator":
            fdecl = fdecl.child_by_field_name("declarator")
        if body is None or fdecl is None:
            return  # = default, = delete, pure virtual: declarations, not definitions
        name_node = fdecl.child_by_field_name("declarator")
        raw_name = _t(name_node).replace(" ", "")
        type_node = node.child_by_field_name("type")
        params_node = fdecl.child_by_field_name("parameters")
        # A macro block such as PYBIND11_MODULE(name, m) { ... } is not a function.
        if type_node is None and _MACRO_BLOCK.match(raw_name) and params_node is not None and all(
                p.child_by_field_name("declarator") is None for p in params_node.children
                if p.type == "parameter_declaration"):
            for child in body.children:
                self.visit(child, _State(list(st.namespaces), list(st.classes), self.file_uid, {}, True,
                                         st.anonymous_ns))
            return
        is_static = any(c.type == "storage_class_specifier" and _t(c) == "static" for c in node.children)
        params, locals_ = self._params(params_node)
        line_start, line_end = node.start_point[0] + 1, node.end_point[0] + 1
        if self.lang == "c":
            name = raw_name
            uid = self.unique(c_uid(name, self.path if is_static else None))
            subtype, qualified, cls = "c_function", name, None
        else:
            parts = [p for p in raw_name.split("::") if p]
            name = parts[-1] if parts else raw_name
            qualifier = parts[:-1]
            if st.classes:
                cls = "::".join([st.classes[-1], *qualifier]) if qualifier else st.classes[-1]
            elif qualifier and not all(q in self.namespace_names for q in qualifier):
                cls = "::".join(st.namespaces + qualifier)
            else:
                cls = None
            if cls:
                qualified = f"{cls}::{name}"
                subtype = "cpp_method"
            else:
                qualified = "::".join(st.namespaces + qualifier + [name])
                subtype = "cpp_function"
            file_local = (is_static and not cls) or st.anonymous_ns
            uid = self.unique(cpp_uid(qualified, params, self.path if file_local else None))
        attrs: dict[str, Any] = {"qualified": qualified, "params": [normalize_cpp_params([p]) for p in params]}
        if self.lang == "cpp" and cls:
            attrs["class"] = cls
            if any(_t(c) == "virtual" for c in node.children):
                attrs["virtual"] = True
        if is_static:
            attrs["static"] = True
        parent = st.src if st.src != self.file_uid else None
        signature = re.sub(r"\s+", " ", self.text.encode("utf-8")[node.start_byte:body.start_byte]
                           .decode("utf-8", errors="replace")).strip()
        self.definitions.append(Definition(uid, name, "routine", subtype, name, (line_start, line_end),
                                           signature=signature, parent=parent, condition=self.cond(line_start),
                                           attrs=attrs))
        inner = _State(list(st.namespaces), st.classes + ([cls] if cls and (not st.classes or cls != st.classes[-1])
                                                          else []), uid, locals_, True, st.anonymous_ns)
        if self.lang == "cpp" and cls and not st.classes:
            inner.classes = [cls]
        for child in node.children:
            if child.type == "field_initializer_list":
                self.visit(child, inner)
        self.visit(body, inner)

    def _params(self, params_node: tree_sitter.Node | None) -> tuple[list[str], dict[str, str]]:
        params: list[str] = []
        locals_: dict[str, str] = {}
        if params_node is None:
            return params, locals_
        for p in params_node.children:
            if p.type not in ("parameter_declaration", "optional_parameter_declaration",
                              "variadic_parameter_declaration"):
                if p.type == "...":
                    params.append("...")
                continue
            text = _t(p)
            if p.type == "optional_parameter_declaration":
                default = p.child_by_field_name("default_value")
                if default is not None:
                    text = text[: default.start_byte - p.start_byte].rstrip().rstrip("=").rstrip()
            decl = p.child_by_field_name("declarator")
            name = self._declared_name(decl) if decl is not None else None
            type_text = text
            if name:
                type_text = re.sub(rf"\b{re.escape(name)}\b(?!.*\b{re.escape(name)}\b)", "", text, count=1)
                type_node = p.child_by_field_name("type")
                locals_[name] = _base_type(_t(type_node)) + ("*" if "*" in type_text else "") if type_node \
                    else _base_type(type_text)
            params.append(type_text.strip())
        return params, locals_

    # -------------------------------------------------------------- calls
    def _arg_types(self, args_node: tree_sitter.Node | None, st: _State) -> tuple[list[ArgFact], list[str | None]]:
        facts: list[ArgFact] = []
        types: list[str | None] = []
        if args_node is None:
            return facts, types
        for a in args_node.children:
            if a.type in ("(", ")", ","):
                continue
            text = _t(a)
            value: str | int | float | None = None
            typ: str | None = None
            if a.type == "number_literal":
                low = text.lower()
                if re.search(r"[.]|e[+-]?\d", low) and not low.startswith("0x"):
                    typ = "float" if low.endswith("f") else "double"
                    try:
                        value = float(low.rstrip("fl"))
                    except ValueError:
                        value = None
                else:
                    typ = "int"
                    try:
                        value = int(low.rstrip("ul"), 0)
                    except ValueError:
                        value = None
            elif a.type in ("string_literal", "raw_string_literal", "concatenated_string"):
                typ = "const char*"
                value = text[1:-1] if a.type == "string_literal" else None
            elif a.type == "char_literal":
                typ = "char"
            elif a.type in ("true", "false"):
                typ = "bool"
            elif a.type == "identifier":
                typ = st.locals.get(text)
            facts.append(ArgFact(text, value))
            types.append(typ)
        return facts, types

    def call(self, node: tree_sitter.Node, st: _State) -> None:
        fn = node.child_by_field_name("function")
        if fn is None:
            return
        args, arg_types = self._arg_types(node.child_by_field_name("arguments"), st)
        line = fn.start_point[0] + 1
        col = self.col(fn)
        base_hint: dict[str, Any] = {"namespaces": list(st.namespaces)}
        if st.classes:
            base_hint["class"] = st.classes[-1]
        if self.lang == "cpp":
            base_hint["arg_types"] = arg_types
        if fn.type == "identifier":
            name = _t(fn)
            macro = self.macros.get(name)
            if macro is not None:
                self.expand_macro(macro, line, col, st, base_hint, args, 0)
                return
            kind = "dynamic_call" if name in st.locals else "call"
            self.references.append(Reference(st.src, name, kind, line, col, args=args, condition=self.cond(line),
                                             hint={**base_hint, "name": name}))
            return
        if fn.type in ("qualified_identifier", "template_function"):
            text = _t(fn).replace(" ", "")
            name_text = re.sub(r"<.*>", "", text)
            self.references.append(Reference(st.src, name_text, "call", line, col, args=args,
                                             condition=self.cond(line),
                                             hint={**base_hint, "qualified": name_text}))
            return
        if fn.type == "field_expression" and self.lang == "cpp":
            arg = fn.child_by_field_name("argument")
            field_node = fn.child_by_field_name("field")
            method = _t(field_node)
            text = re.sub(r"\s+", "", _t(fn))
            hint = {**base_hint, "method": method}
            if arg is not None and arg.type == "this" and st.classes:
                hint["receiver_type"] = st.classes[-1]
            elif arg is not None and arg.type == "identifier" and _t(arg) in st.locals:
                hint["receiver_type"] = st.locals[_t(arg)].rstrip("*")
            self.references.append(Reference(st.src, text, "call", line, col, args=args, condition=self.cond(line),
                                             hint=hint))
            return
        text = re.sub(r"\s+", "", _t(fn))
        self.references.append(Reference(st.src, text, "dynamic_call", line, col, args=args,
                                         condition=self.cond(line), hint=base_hint))

    def expand_macro(self, macro: Macro, line: int, col: int, st: _State, base_hint: dict[str, Any],
                     args: list[ArgFact], depth: int) -> None:
        if depth > 3:
            return
        body = re.sub(r'"(?:\\.|[^"\\])*"', '""', macro.body)
        params = set(macro.params or [])
        for m in _CALL_IN_BODY.finditer(body):
            callee = m.group(1)
            if callee in params or callee in _C_KEYWORDS:
                continue
            inner = self.macros.get(callee)
            if inner is not None and inner.name != macro.name:
                self.expand_macro(inner, line, col, st, base_hint, args, depth + 1)
                continue
            self.references.append(Reference(st.src, callee, "call", line, col, args=args,
                                             condition=self.cond(line),
                                             hint={**base_hint, "name": callee, "macro": macro.name}))
