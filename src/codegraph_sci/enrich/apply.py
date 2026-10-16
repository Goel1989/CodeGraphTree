"""Declarative pack rules applied after Link (§3.8): memory manager accesses, dispatch, catalogs,
entry points, tests. Everything is deterministic and derived from facts and repository files.
"""

from __future__ import annotations

import fnmatch
import json
import posixpath
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import yaml

from codegraph_sci.core.facts import ArgFact, FileFacts, Reference
from codegraph_sci.core.graph import DataAccessRecord, EdgeRecord, NodeRecord
from codegraph_sci.enrich.packs import PackRules


def _typed(values: dict[str, Any]) -> dict[str, Any]:
    """Template values: digit strings become integers so that ``{op:04d}`` works."""
    return {k: int(v) if isinstance(v, str) and v.isdigit() else v for k, v in values.items()}


_SUFFIX = re.compile(r"""['"](\.[^'".]+)['"]\s*$""")


@dataclass
class Enrichment:
    nodes: list[NodeRecord] = field(default_factory=list)
    edges: list[EdgeRecord] = field(default_factory=list)
    data: list[DataAccessRecord] = field(default_factory=list)
    unmatched: dict[str, str] = field(default_factory=dict)
    noise: dict[str, str] = field(default_factory=dict)


class PackEngine:
    def __init__(self, packs: list[PackRules], facts: list[FileFacts], nodes: dict[str, NodeRecord],
                 repo_files: list[str], read_text: Callable[[str], str | None],
                 outline: list[FileFacts] | None = None) -> None:
        self.packs = packs
        self.facts = sorted(facts, key=lambda f: f.path)
        self.outline = sorted(outline or [], key=lambda f: f.path)
        self.nodes = nodes
        self.repo_files = sorted(repo_files)
        self.read_text = read_text
        self.out = Enrichment()
        self._new: dict[str, NodeRecord] = {}

    def node(self, uid: str, display: str, kind: str, subtype: str, file: str | None = None,
             line: tuple[int, int] | None = None, lang: str | None = None) -> str:
        if uid not in self.nodes and uid not in self._new:
            self._new[uid] = NodeRecord(uid, display, kind, subtype, lang, file, line[0] if line else None,
                                        line[1] if line else None, True, {})
        return uid

    def exists(self, uid: str) -> bool:
        return uid in self.nodes or uid in self._new

    def run(self) -> Enrichment:
        for pack in self.packs:
            origin = f"pack:{pack.name}"
            for rule in pack.data.get("memory_access", []):
                self.memory_access(rule, origin)
            for rule in pack.data.get("dispatch", []):
                self.dispatch(rule, origin)
            for rule in pack.data.get("catalogs", []):
                self.catalog(rule, origin)
            for rule in pack.data.get("entry_points", []):
                self.entry_points(rule, origin)
            for rule in pack.data.get("tests", []):
                self.tests(rule, origin)
        self.out.nodes = sorted(self._new.values(), key=lambda n: n.uid)
        return self.out

    # ------------------------------------------------------- memory access
    @staticmethod
    def _arg(ref: Reference, index: int) -> tuple[str | None, str | None]:
        """(literal string value, expression text) of argument ``index`` (1-based)."""
        if index < 1 or index > len(ref.args):
            return None, None
        arg: ArgFact = ref.args[index - 1]
        if isinstance(arg.value, str):
            return arg.value, arg.text
        exprs = ref.hint.get("arg_exprs", {})
        expr = exprs.get(str(index - 1)) if isinstance(exprs, dict) else None
        return None, str(expr) if expr else arg.text

    def memory_access(self, rule: dict[str, Any], origin: str) -> None:
        routine = str(rule["routine"]).lower()
        strategies = list(rule["object_key"])
        local_rx = re.compile(str(rule["local_prefix_pattern"])) if rule.get("local_prefix_pattern") else None
        for facts in self.facts:
            for ref in facts.references:
                if ref.kind not in ("call", "maybe_call") or ref.target_text.lower() != routine:
                    continue
                value, expr = self._arg(ref, int(rule["name_arg"]))
                if value is None and expr is None:
                    continue
                if rule.get("effect"):
                    mode = str(rule["effect"])
                else:
                    mvalue, _mexpr = self._arg(ref, int(rule.get("mode_arg", 0)))
                    mode = str((rule.get("modes") or {}).get(mvalue, "uses")) if mvalue is not None else "uses"
                suffix = None
                if value is not None and "." in value:
                    suffix = "." + value.rsplit(".", 1)[1]
                elif expr:
                    m = _SUFFIX.search(expr)
                    suffix = m.group(1) if m else None
                family = None
                if "family" in strategies and suffix:
                    family = self.node(f"data:mem:*{suffix}", f"*{suffix}", "data", "memory_family")
                    self.out.noise[family] = "family"
                data_uid, key_kind = None, None
                for strategy in strategies:
                    if strategy == "local_prefix" and value is not None and local_rx and local_rx.match(value):
                        data_uid, key_kind = f"data:mem:{ref.src}:{value}", "literal"
                    elif strategy == "literal" and value is not None and not (
                            local_rx and "local_prefix" in strategies and local_rx.match(value)):
                        data_uid, key_kind = f"data:mem:{value}", "literal"
                    elif strategy == "symbolic" and value is None and expr:
                        data_uid, key_kind = f"data:mem:{ref.src}:{expr}", "symbolic"
                    elif strategy == "family" and family is not None:
                        data_uid, key_kind = family, "family"
                    if data_uid is not None:
                        break
                if data_uid is None or key_kind is None:
                    continue
                if data_uid != family:
                    display = data_uid.split(":", 2)[-1]
                    self.node(data_uid, display, "data", "memory_object")
                self.out.data.append(DataAccessRecord(ref.src, data_uid, family if data_uid != family else None,
                                                      mode, key_kind, facts.path, ref.line, origin))
                self.out.edges.append(EdgeRecord(ref.src, data_uid, mode, 1, "resolved", [origin], []))
                if family is not None and data_uid != family:
                    self.out.edges.append(EdgeRecord(ref.src, family, mode, 1, "heuristic", [origin], []))

    # ------------------------------------------------------------ dispatch
    def dispatch(self, rule: dict[str, Any], origin: str) -> None:
        routine = str(rule["routine"]).lower()
        selector = str(rule["select_on"]).lower()
        pattern = str(rule["target_pattern"])
        for facts in self.facts + self.outline:  # dispatchers may sit outside the detailed scope
            for d in facts.definitions:
                if d.name != routine or d.kind != "routine":
                    continue
                cases = (d.attrs.get("select_cases") or {}).get(selector, [])
                for raw in cases:
                    try:
                        value: Any = int(str(raw))
                    except ValueError:
                        value = str(raw).strip("'\"")
                    try:
                        target_name = pattern.format(case=value)
                    except (ValueError, KeyError):
                        continue
                    prefix = d.uid.split(":", 1)[0]
                    target = f"{prefix}:{target_name.lower() if prefix == 'f' else target_name}"
                    if self.exists(target):
                        self.out.edges.append(EdgeRecord(d.uid, target, "dispatches", 1, "heuristic", [origin], []))
                    else:
                        self.out.unmatched[f"{d.uid} case {raw}"] = target

    # ------------------------------------------------------------ catalogs
    def _files(self, glob: str) -> list[str]:
        return [p for p in self.repo_files if fnmatch.fnmatchcase(p, glob)]

    def catalog(self, rule: dict[str, Any], origin: str) -> None:
        for path in self._files(str(rule["glob"])):
            text = self.read_text(path)
            if text is None:
                continue
            items: list[tuple[dict[str, Any], int]] = []
            if rule["format"] == "yaml":
                try:
                    root = yaml.compose(text, Loader=yaml.SafeLoader)
                    data = yaml.safe_load(text)
                except yaml.YAMLError:
                    continue
                values = data if isinstance(data, list) else list((data or {}).values())
                nodes = root.value if root is not None and isinstance(root.value, list) else []
                for i, item in enumerate(values):
                    line = nodes[i].start_mark.line + 1 if i < len(nodes) else 1
                    if isinstance(item, dict):
                        items.append((item, line))
            elif rule["format"] == "json":
                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    continue
                values = data if isinstance(data, list) else list(data.values())
                items = [(item, 1) for item in values if isinstance(item, dict)]
            for item, line in items:
                try:
                    entry = str(rule["entry"]).format(**_typed(item))
                    target = str(rule["target"]).format(**_typed(item))
                except (KeyError, IndexError, ValueError):
                    continue
                uid = self.node(f"catalog:{entry}", entry, "dispatch_target", "catalog_entry", path, (line, line))
                if self.exists(target):
                    self.out.edges.append(EdgeRecord(uid, target, "dispatches", 1, "resolved", [origin], []))
                else:
                    self.out.unmatched[uid] = target

    # -------------------------------------------------------- entry points
    def entry_points(self, rule: dict[str, Any], origin: str) -> None:
        flags = re.MULTILINE | (re.DOTALL if rule.get("multiline") else 0)
        rx = re.compile(str(rule["pattern"]), flags)
        for path in self._files(str(rule["glob"])):
            text = self.read_text(path)
            if text is None:
                continue
            stem = posixpath.splitext(posixpath.basename(path))[0]
            for m in rx.finditer(text):
                groups = {k: v for k, v in m.groupdict().items() if v is not None}
                name = groups.get("name") or groups.get("target")
                if not name:
                    continue
                line = text.count("\n", 0, m.start()) + 1
                uid = self.node(f"entry:{name}", name, "entry_point", str(rule["kind"]), path, (line, line))
                target = None
                for template in (rule.get("target"), rule.get("fallback_target")):
                    if not template:
                        continue
                    try:
                        cand = str(template).format(**_typed(groups), file_stem=stem)
                    except (KeyError, IndexError, ValueError):
                        continue
                    if cand.startswith("f:"):
                        cand = cand.lower()
                    if self.exists(cand):
                        target = cand
                        break
                if target is not None:
                    self.out.edges.append(EdgeRecord(uid, target, "calls", 1, "resolved", [origin], []))
                else:
                    self.out.unmatched[uid] = str(rule.get("target"))

    # --------------------------------------------------------------- tests
    def tests(self, rule: dict[str, Any], origin: str) -> None:
        entries = sorted(u for u in list(self.nodes) + list(self._new) if u.startswith("entry:"))
        for path in self._files(str(rule["glob"])):
            text = self.read_text(path) or ""
            nlines = max(1, text.count("\n") + (0 if text.endswith("\n") else 1))
            uid = self.node(f"test:{path}", posixpath.basename(path), "test_case", str(rule["kind"]), path,
                            (1, nlines))
            if rule.get("uses_entry_points"):
                for entry in entries:
                    if re.search(rf"(?<![\w]){re.escape(entry[6:])}(?![\w])", text):
                        self.out.edges.append(EdgeRecord(uid, entry, "exercises", 1, "heuristic", [origin], []))
