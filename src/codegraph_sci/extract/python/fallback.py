"""Python fallback extractor (tree-sitter): Python 2 files and files ``ast`` cannot read.

Only module-level names are bound (definitions, imports, builtins): enough for the call graph of
legacy scripts. Every site keeps its exact position.
"""

from __future__ import annotations

from typing import Any

import tree_sitter
import tree_sitter_python

from codegraph_sci.core.facts import Definition, FileFacts, Reference
from codegraph_sci.core.ids import py_uid

_PARSER: tree_sitter.Parser | None = None


def _parser() -> tree_sitter.Parser:
    global _PARSER
    if _PARSER is None:
        _PARSER = tree_sitter.Parser(tree_sitter.Language(tree_sitter_python.language()))
    return _PARSER


def _text(node: tree_sitter.Node) -> str:
    return node.text.decode("utf-8", errors="replace") if node.text is not None else ""


def extract_tree_sitter(path: str, text: str, encoding: str, module: str) -> FileFacts:
    from codegraph_sci.extract.python import BUILTINS, resolve_relative

    data = text.encode("utf-8")
    tree = _parser().parse(data)
    lines = text.splitlines()
    is_package = path.endswith("__init__.py")

    def col(node: tree_sitter.Node) -> int:
        row, byte_col = node.start_point
        line = lines[row] if row < len(lines) else ""
        return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore")) + 1

    module_uid = py_uid(module)
    definitions = [Definition(module_uid, module, "module", "py_module", module, (1, max(1, len(lines))))]
    references: list[Reference] = []
    names: dict[str, dict[str, Any]] = {}

    for child in tree.root_node.children:
        node = child.child_by_field_name("definition") if child.type == "decorated_definition" else child
        if node is None:
            continue
        if node.type in ("function_definition", "class_definition"):
            name = node.child_by_field_name("name")
            if name is not None:
                names[_text(name)] = {"kind": "local_def", "qual": f"{module}.{_text(name)}"}
        elif node.type == "import_statement":
            for n in node.children_by_field_name("name"):
                target = _text(n.child_by_field_name("name") or n) if n.type == "aliased_import" else _text(n)
                alias = n.child_by_field_name("alias") if n.type == "aliased_import" else None
                names[_text(alias) if alias else target.split(".")[0]] = {
                    "kind": "import", "target": target if alias else target.split(".")[0]}
        elif node.type == "import_from_statement":
            mod = node.child_by_field_name("module_name")
            mod_text = _text(mod) if mod is not None else ""
            level = len(mod_text) - len(mod_text.lstrip("."))
            base = resolve_relative(module, is_package, level, mod_text.lstrip(".") or None) if level else mod_text
            for n in node.children_by_field_name("name"):
                target = _text(n.child_by_field_name("name") or n) if n.type == "aliased_import" else _text(n)
                alias = n.child_by_field_name("alias") if n.type == "aliased_import" else None
                names[_text(alias) if alias else target] = {"kind": "import", "target": f"{base}.{target}"}

    def bind(name: str) -> dict[str, Any]:
        if name in names:
            return dict(names[name])
        return {"kind": "builtin"} if name in BUILTINS else {"kind": "unknown"}

    def visit(node: tree_sitter.Node, qual: str, scope_kind: str) -> None:
        src = py_uid(module, qual) if qual else module_uid
        for child in node.children:
            target = child.child_by_field_name("definition") if child.type == "decorated_definition" else child
            if target is not None and target.type in ("function_definition", "class_definition"):
                name_node = target.child_by_field_name("name")
                if name_node is None:
                    continue
                name = _text(name_node)
                q = f"{qual}.{name}" if qual else name
                is_class = target.type == "class_definition"
                kind = "type" if is_class else "routine"
                subtype = "py_class" if is_class else ("py_method" if scope_kind == "class" else "py_function")
                definitions.append(Definition(py_uid(module, q), name, kind, subtype, name,
                                              (target.start_point[0] + 1, target.end_point[0] + 1),
                                              parent=src))
                body = target.child_by_field_name("body")
                if body is not None:
                    visit(body, q, "class" if is_class else "function")
                continue
            if child.type == "call":
                fn = child.child_by_field_name("function")
                if fn is not None and fn.type in ("identifier", "attribute"):
                    parts = _text(fn).replace(" ", "").split(".")
                    references.append(Reference(src, ".".join(parts), "call", fn.start_point[0] + 1, col(fn),
                                                hint={"bind": bind(parts[0]), "attrs": parts[1:]}))
            visit(child, qual, scope_kind)

    visit(tree.root_node, "", "module")
    return FileFacts(path=path, lang="python", encoding=encoding, adapter="python", adapter_version="1.0",
                     definitions=definitions, references=references, used_fallback=True)
