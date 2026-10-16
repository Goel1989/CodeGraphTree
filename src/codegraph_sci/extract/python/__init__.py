"""Python adapter: ``ast`` for Python 3, tree-sitter fallback for Python 2 or invalid files.

Name binding is resolved inside the file (local, enclosing, module, builtins); each reference
carries a ``bind`` hint that Link turns into a target uid across modules.
"""

from __future__ import annotations

import ast
import builtins
import sys
from typing import Any

from codegraph_sci.core.facts import ArgFact, Definition, FileFacts, ParseError, Reference, SourceFile
from codegraph_sci.core.ids import py_uid
from codegraph_sci.core.plugins import ExtractContext

ADAPTER = "python"
VERSION = "1.1"
BUILTINS = frozenset(dir(builtins))


def module_name_for(path: str) -> str:
    """``pkg/sub/mod.py`` -> ``pkg.sub.mod``; ``pkg/__init__.py`` -> ``pkg``."""
    p = path.replace("\\", "/")
    for suffix in (".pyw", ".py"):
        if p.endswith(suffix):
            p = p[: -len(suffix)]
    if p.endswith("/__init__"):
        p = p[: -len("/__init__")]
    elif p == "__init__":
        p = "__init__"
    return p.replace("/", ".")


def resolve_relative(module: str, is_package: bool, level: int, target: str | None) -> str:
    """Absolute module name of ``from <level dots><target> import ...``."""
    parts = module.split(".")
    if not is_package:
        parts = parts[:-1]
    if level > 1:
        parts = parts[: len(parts) - (level - 1)]
    base = ".".join(parts)
    if target:
        return f"{base}.{target}" if base else target
    return base


class _Scope:
    def __init__(self, kind: str, qual: str, parent: _Scope | None, node: ast.AST | None = None) -> None:
        self.kind = kind  # module, class, function
        self.qual = qual  # dotted name relative to the module ("" for the module)
        self.parent = parent
        self.names: dict[str, dict[str, Any]] = {}
        self.node = node


def _dotted(node: ast.AST) -> tuple[str, list[str]] | None:
    """``a.b.c`` -> ("a", ["b", "c"]); None if the root is not a plain name."""
    attrs: list[str] = []
    while isinstance(node, ast.Attribute):
        attrs.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return node.id, list(reversed(attrs))
    return None


def _literal(node: ast.AST) -> str | int | float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (str, int, float)) and not isinstance(
            node.value, bool):
        return node.value
    return None


class _AstExtractor:
    def __init__(self, path: str, text: str, module: str) -> None:
        self.path = path
        self.text = text
        self.module = module
        self.is_package = path.replace("\\", "/").endswith("__init__.py")
        self.lines = text.splitlines()
        self.definitions: list[Definition] = []
        self.references: list[Reference] = []
        self.module_uid = py_uid(module)

    def col(self, lineno: int, col_offset: int) -> int:
        """ast offsets are in UTF-8 bytes; sites use characters."""
        if 0 < lineno <= len(self.lines):
            line = self.lines[lineno - 1]
            if not line.isascii():
                return len(line.encode("utf-8")[:col_offset].decode("utf-8", errors="ignore")) + 1
        return col_offset + 1

    def uid(self, scope: _Scope) -> str:
        return py_uid(self.module, scope.qual) if scope.qual else self.module_uid

    # ------------------------------------------------------------ binding
    def collect(self, scope: _Scope, body: list[ast.stmt]) -> None:
        """Names bound directly in a scope (not in nested functions or classes)."""
        def bind(name: str, info: dict[str, Any]) -> None:
            if name not in scope.names or scope.names[name]["kind"] == "variable":
                scope.names[name] = info

        for stmt in body:
            for node in self._walk_local(stmt):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    qual = f"{scope.qual}.{node.name}" if scope.qual else node.name
                    scope.names[node.name] = {"kind": "local_def", "qual": f"{self.module}.{qual}"}
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.asname:
                            bind(alias.asname, {"kind": "import", "target": alias.name})
                        else:
                            root = alias.name.split(".")[0]
                            bind(root, {"kind": "import", "target": root})
                elif isinstance(node, ast.ImportFrom):
                    base = resolve_relative(self.module, self.is_package, node.level, node.module) if node.level \
                        else (node.module or "")
                    for alias in node.names:
                        if alias.name == "*":
                            continue
                        bind(alias.asname or alias.name, {"kind": "import", "target": f"{base}.{alias.name}"})
                elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    value = node.value
                    for t in targets:
                        for name_node in ast.walk(t):
                            if isinstance(name_node, ast.Name):
                                info = self._value_info(scope, value) if isinstance(t, ast.Name) else None
                                scope.names[name_node.id] = info or {"kind": "variable"}
                elif isinstance(node, (ast.For, ast.AsyncFor, ast.With, ast.AsyncWith, ast.NamedExpr)):
                    targets_any: list[ast.AST] = []
                    if isinstance(node, (ast.For, ast.AsyncFor)):
                        targets_any = [node.target]
                    elif isinstance(node, ast.NamedExpr):
                        targets_any = [node.target]
                    else:
                        targets_any = [i.optional_vars for i in node.items if i.optional_vars is not None]
                    for tt in targets_any:
                        for name_node in ast.walk(tt):
                            if isinstance(name_node, ast.Name):
                                bind(name_node.id, {"kind": "variable"})

    def _walk_local(self, stmt: ast.stmt) -> list[ast.AST]:
        out: list[ast.AST] = []
        stack: list[ast.AST] = [stmt]
        while stack:
            node = stack.pop()
            out.append(node)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                continue
            stack.extend(ast.iter_child_nodes(node))
        return out

    def _value_info(self, scope: _Scope, value: ast.AST | None) -> dict[str, Any] | None:
        if isinstance(value, ast.Call):
            if isinstance(value.func, ast.Name) and value.func.id == "getattr" and len(value.args) >= 2:
                attr = _literal(value.args[1])
                base = _dotted(value.args[0])
                if isinstance(attr, str) and base is not None:
                    return {"kind": "getattr", "base": {"name": base[0], "attrs": base[1]}, "attr": attr}
            d = _dotted(value.func)
            if d is not None:
                return {"kind": "instance", "class": {"name": d[0], "attrs": d[1]}}
        return None

    def lookup(self, scope: _Scope, name: str, depth: int = 0) -> dict[str, Any]:
        if depth > 8:  # ``x = x(...)``: the name refers to itself, stop
            return {"kind": "variable"}
        s: _Scope | None = scope
        first = True
        while s is not None:
            if s.kind == "class" and not first:
                s = s.parent
                continue
            if name in s.names:
                info = dict(s.names[name])
                if info["kind"] == "instance":
                    cls = info["class"]
                    info = {"kind": "instance", "class": self.lookup(s, cls["name"], depth + 1) | {"attrs": cls["attrs"]}}
                elif info["kind"] == "getattr":
                    base = info["base"]
                    info = {"kind": "getattr", "base": self.lookup(s, base["name"], depth + 1) | {"attrs": base["attrs"]},
                            "attr": info["attr"]}
                return info
            first = False
            s = s.parent
        if name in BUILTINS:
            return {"kind": "builtin"}
        return {"kind": "unknown"}

    # ------------------------------------------------------------- visiting
    def run(self, tree: ast.Module) -> None:
        nlines = len(self.lines) if self.lines else 1
        doc = ast.get_docstring(tree)
        self.definitions.append(Definition(self.module_uid, self.module, "module", "py_module", self.module,
                                           (1, max(1, nlines)), doc=doc.splitlines()[0] if doc else None))
        scope = _Scope("module", "", None, tree)
        self.collect(scope, tree.body)
        # What other modules can see of this one: re-exported imports, star imports, callable instances.
        attrs = self.definitions[0].attrs
        imports = {n: str(i["target"]) for n, i in scope.names.items() if i["kind"] == "import"}
        stars = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and any(a.name == "*" for a in node.names):
                stars.append(resolve_relative(self.module, self.is_package, node.level, node.module)
                             if node.level else (node.module or ""))
        instances = {n: self.lookup(scope, n)["class"] for n, i in scope.names.items() if i["kind"] == "instance"}
        if imports:
            attrs["imports"] = dict(sorted(imports.items()))
        if stars:
            attrs["star_imports"] = stars
        if instances:
            attrs["instances"] = {k: v for k, v in sorted(instances.items()) if isinstance(v, dict)}
        self.visit_body(scope, tree.body)

    def visit_body(self, scope: _Scope, body: list[ast.stmt]) -> None:
        for stmt in body:
            self.visit(scope, stmt)

    def visit(self, scope: _Scope, node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            self.definition(scope, node)
            return
        if isinstance(node, ast.Import):
            for alias in node.names:
                self.use(scope, node, alias, alias.name, {"module": alias.name, "name": None})
            return
        if isinstance(node, ast.ImportFrom):
            base = resolve_relative(self.module, self.is_package, node.level, node.module) if node.level \
                else (node.module or "")
            for alias in node.names:
                if alias.name != "*":
                    self.use(scope, node, alias, alias.name, {"module": base, "name": alias.name})
            return
        if isinstance(node, ast.Call):
            self.call(scope, node)
        if isinstance(node, ast.Lambda):
            self.visit(scope, node.body)
            return
        for child in ast.iter_child_nodes(node):
            self.visit(scope, child)

    def use(self, scope: _Scope, node: ast.stmt, alias: ast.alias, text: str, hint: dict[str, Any]) -> None:
        line = getattr(alias, "lineno", node.lineno)
        col = self.col(line, getattr(alias, "col_offset", node.col_offset))
        self.references.append(Reference(self.uid(scope), text, "use", line, col, hint=hint))

    def definition(self, scope: _Scope, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        for deco in node.decorator_list:
            if isinstance(deco, ast.Call):
                self.visit(scope, deco)
            else:
                self.ref_from_expr(scope, deco, deco, "call", [])
        qual = f"{scope.qual}.{node.name}" if scope.qual else node.name
        uid = py_uid(self.module, qual)
        end = getattr(node, "end_lineno", None) or node.lineno
        doc = ast.get_docstring(node)
        if isinstance(node, ast.ClassDef):
            self.definitions.append(Definition(uid, node.name, "type", "py_class", node.name, (node.lineno, end),
                                               doc=doc.splitlines()[0] if doc else None, parent=self.uid(scope)))
            for base in node.bases:
                self.ref_from_expr(scope, base, base, "inherit", [], src=uid)
            for kw in node.keywords:
                self.visit(scope, kw.value)
            inner = _Scope("class", qual, scope, node)
            self.collect(inner, node.body)
            self.visit_body(inner, node.body)
            return
        subtype = "py_method" if scope.kind == "class" else "py_function"
        args = node.args
        params = [a.arg for a in args.posonlyargs + args.args + args.kwonlyargs]
        if args.vararg:
            params.append(args.vararg.arg)
        if args.kwarg:
            params.append(args.kwarg.arg)
        signature = f"def {node.name}({', '.join(params)})"
        self.definitions.append(Definition(uid, node.name, "routine", subtype, node.name, (node.lineno, end),
                                           signature=signature, doc=doc.splitlines()[0] if doc else None,
                                           parent=self.uid(scope)))
        for default in args.defaults + [d for d in args.kw_defaults if d is not None]:
            self.visit(scope, default)
        inner = _Scope("function", qual, scope, node)
        for i, p in enumerate(params):
            if i == 0 and subtype == "py_method" and p in ("self", "cls"):
                inner.names[p] = {"kind": "self", "class": f"{self.module}.{scope.qual}"}
            else:
                inner.names[p] = {"kind": "variable"}
        self.collect(inner, node.body)
        self.visit_body(inner, node.body)

    def call(self, scope: _Scope, node: ast.Call) -> None:
        args = [ArgFact(ast.get_source_segment(self.text, a) or "", _literal(a)) for a in node.args]
        self.ref_from_expr(scope, node.func, node.func, "call", args)

    def ref_from_expr(self, scope: _Scope, expr: ast.AST, pos: ast.AST, kind: str, args: list[ArgFact],
                      src: str | None = None) -> None:
        line = getattr(pos, "lineno", 1)
        col = self.col(line, getattr(pos, "col_offset", 0))
        src = src or self.uid(scope)
        d = _dotted(expr)
        if d is None:
            if isinstance(expr, ast.Attribute):
                text = ast.get_source_segment(self.text, expr) or expr.attr
                self.references.append(Reference(src, text, kind, line, col, args=args,
                                                 hint={"bind": {"kind": "expression"}, "attrs": [expr.attr]}))
            return
        root, attrs = d
        bind = self.lookup(scope, root)
        text = ".".join([root, *attrs])
        ref_kind = kind
        if kind == "call" and not attrs and bind["kind"] in ("variable", "getattr"):
            ref_kind = "dynamic_call"
        self.references.append(Reference(src, text, ref_kind, line, col, args=args,
                                         hint={"bind": bind, "attrs": attrs}))


def _extract_ast(path: str, text: str, encoding: str, module: str, tree: ast.Module) -> FileFacts:
    ex = _AstExtractor(path, text, module)
    ex.run(tree)
    return FileFacts(path=path, lang="python", encoding=encoding, adapter=ADAPTER, adapter_version=VERSION,
                     definitions=ex.definitions, references=ex.references).sort()


class PythonAdapter:
    name = ADAPTER
    version = VERSION
    languages = ["python"]

    def extract(self, file: SourceFile, ctx: ExtractContext) -> FileFacts:
        module = ctx.module_name(file.path) if ctx.module_name else module_name_for(file.path)
        try:
            tree = ast.parse(file.text, filename=file.path, type_comments=False)
        except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
            from codegraph_sci.extract.python.fallback import extract_tree_sitter

            facts = extract_tree_sitter(file.path, file.text, file.encoding, module)
            facts.errors.insert(0, ParseError(f"ast: {type(exc).__name__}: {exc}",
                                              getattr(exc, "lineno", 0) or 0))
            facts.used_fallback = True
            facts.variant = file.variant
            return facts.sort()
        limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(limit, 20_000))  # deeply nested expressions (long sums, big literals)
        try:
            facts = _extract_ast(file.path, file.text, file.encoding, module, tree)
        finally:
            sys.setrecursionlimit(limit)
        facts.variant = file.variant
        return facts


__all__ = ["PythonAdapter", "module_name_for", "resolve_relative"]
