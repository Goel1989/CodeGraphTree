"""Link: global symbol tables and resolution of every reference into a call site (§3.3, §3.5).

Input: the facts of the files analysed in detail, plus the definitions of the files outside the
scope (light index). Output: nodes, call sites (one per reference, never merged), structural
edges (contains, implements). Everything is processed in a sorted order: same input, same output.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from codegraph_sci.core.facts import Definition, FileFacts, Reference
from codegraph_sci.core.graph import CallSiteRecord, DataAccessRecord, EdgeRecord, NodeRecord
from codegraph_sci.core.ids import file_uid, variant_uid
from codegraph_sci.core.model import CONFIDENCE_RANK
from codegraph_sci.link.bridges import BridgeEngine
from codegraph_sci.link.externals import external_for

INTRINSIC_MODULES = frozenset({"iso_c_binding", "iso_fortran_env", "ieee_arithmetic", "ieee_exceptions",
                               "ieee_features", "omp_lib", "omp_lib_kinds", "openacc", "mpi", "mpi_f08"})
_DROP = "__drop__"
_NODE_ATTRS_SKIP = {"var_types", "uses", "commons", "args"}


@dataclass
class Resolution:
    dst: str | None
    resolution: str  # resolved, ambiguous, external, out_of_scope, unresolved
    confidence: str
    candidates: list[str] = field(default_factory=list)


@dataclass
class LinkResult:
    nodes: list[NodeRecord]
    call_sites: list[CallSiteRecord]
    struct_edges: list[EdgeRecord]
    stats: dict[str, int]
    data_accesses: list[DataAccessRecord] = field(default_factory=list)


def _base(uid: str) -> str:
    return uid.split("#", 1)[0]


class Linker:
    def __init__(self, facts: list[FileFacts], outline: list[FileFacts], file_info: dict[str, tuple[str | None, int]],
                 origin_prefix: dict[str, str] | None = None, *, bridge_rules: list[dict[str, Any]] | None = None,
                 native_bridges: bool = True, read_text: Callable[[str], str | None] | None = None) -> None:
        self.facts = sorted(facts, key=lambda f: f.path)
        self.outline = sorted(outline, key=lambda f: f.path)
        self.file_info = dict(file_info)  # path -> (lang, line count)
        self.origin_prefix = origin_prefix or {}
        self.nodes: dict[str, NodeRecord] = {}
        self.defs: dict[str, tuple[Definition, str, str]] = {}  # uid -> (definition, path, lang)
        self.renames: dict[tuple[str, str], str] = {}
        self.sites: list[CallSiteRecord] = []
        self.site_refs: list[Reference] = []
        self.bridge_rules = bridge_rules or []
        self.native_bridges = native_bridges
        self.read_text = read_text
        self.binding_targets: dict[str, str] = {}
        self.data_records: list[DataAccessRecord] = []
        self.struct_edges: list[EdgeRecord] = []
        self.variants: dict[str, list[str]] = defaultdict(list)
        self.parent: dict[str, str] = {}
        # Fortran
        self.f_module_vars: dict[str, set[str]] = defaultdict(set)
        # Python
        self.py_bases: dict[str, list[str]] = defaultdict(list)
        self.py_methods_by_name: dict[str, list[str]] = defaultdict(list)
        # C
        self.c_by_name: dict[str, list[str]] = defaultdict(list)
        # C++
        self.cpp_funcs: dict[str, list[str]] = defaultdict(list)  # qualified name -> uids
        self.cpp_classes: dict[str, str] = {}  # qualified -> uid
        self.cpp_methods: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        self.cpp_methods_by_name: dict[str, list[str]] = defaultdict(list)
        self.cpp_bases: dict[str, list[str]] = defaultdict(list)  # class qualified -> base qualifieds
        self.cpp_derived: dict[str, list[str]] = defaultdict(list)

    # ================================================================ nodes
    def run(self) -> LinkResult:
        for path, (lang, lines) in sorted(self.file_info.items()):
            self._file_node(path, lang, lines)
        for facts, in_scope in [(f, True) for f in self.facts] + [(f, False) for f in self.outline]:
            for d in facts.definitions:
                self._add_definition(d, facts, in_scope)
        self._build_indexes()
        for facts in self.facts:
            for ref in facts.references:
                if ref.kind == "inherit":
                    self._site(facts, ref, self._resolve(facts, ref))
        self._build_hierarchies()
        for facts in self.facts:
            for ref in facts.references:
                if ref.kind != "inherit":
                    res = self._resolve(facts, ref)
                    if res.dst != _DROP:
                        self._site(facts, ref, res)
        engine = BridgeEngine(self, self.bridge_rules, self.native_bridges, self.read_text)
        engine.run()
        self.binding_targets = engine.binding_targets
        self._structure()
        self._data_accesses()
        self._prune_externals()
        stats = {"nodes": len(self.nodes), "call_sites": len(self.sites)}
        for res_name in ("resolved", "ambiguous", "external", "out_of_scope", "unresolved"):
            stats[res_name] = sum(1 for s in self.sites if s.resolution == res_name)
        return LinkResult(sorted(self.nodes.values(), key=lambda n: n.uid), self.sites, self.struct_edges, stats,
                          self.data_records)

    def _file_node(self, path: str, lang: str | None, lines: int) -> None:
        uid = file_uid(path)
        if uid not in self.nodes:
            self.nodes[uid] = NodeRecord(uid, path.rsplit("/", 1)[-1], "file", None, lang, path, 1, max(lines, 1))

    def _add_definition(self, d: Definition, facts: FileFacts, in_scope: bool) -> None:
        uid = d.uid
        if uid in self.nodes:
            k = 2
            while variant_uid(_base(uid), k) in self.nodes:
                k += 1
            new = variant_uid(_base(uid), k)
            self.renames[(facts.path, uid)] = new
            uid = new
        attrs: dict[str, Any] = {k: v for k, v in d.attrs.items() if k not in _NODE_ATTRS_SKIP}
        if d.signature:
            attrs["signature"] = d.signature
        if d.doc:
            attrs["doc"] = d.doc
        if d.condition:
            attrs["condition"] = d.condition
        self.nodes[uid] = NodeRecord(uid, d.display_name, d.kind, d.subtype, facts.lang, facts.path, d.span[0],
                                     d.span[1], in_scope, attrs)
        self.defs[uid] = (d, facts.path, facts.lang)
        if d.parent:
            self.parent[uid] = self.renames.get((facts.path, d.parent), d.parent)
        self.variants[_base(uid)].append(uid)

    def _src(self, facts: FileFacts, uid: str) -> str:
        return self.renames.get((facts.path, uid), uid)

    def _ext(self, uid: str, subtype: str, display: str | None = None) -> str:
        if uid not in self.nodes:
            name = display or uid.split(":", 2)[-1]
            self.nodes[uid] = NodeRecord(uid, name, "external", subtype, None, None, None, None, True, {})
        return uid

    # ============================================================== indexes
    def _build_indexes(self) -> None:
        for uid, (d, _path, lang) in sorted(self.defs.items()):
            if lang == "fortran":
                if d.kind == "module":
                    for s in d.local_symbols:
                        if s.role not in ("external", "function", "intrinsic", "dummy_procedure"):
                            self.f_module_vars[uid].add(s.name)
            elif lang == "python":
                if d.subtype == "py_method":
                    self.py_methods_by_name[d.name].append(uid)
            elif lang == "c":
                self.c_by_name[d.name].append(uid)
            elif lang == "cpp":
                qualified = str(d.attrs.get("qualified", d.name))
                if d.kind == "type":
                    self.cpp_classes.setdefault(qualified, uid)
                elif d.kind == "routine":
                    cls = d.attrs.get("class")
                    if cls:
                        self.cpp_methods[str(cls)][d.name].append(uid)
                        self.cpp_methods_by_name[d.name].append(uid)
                    self.cpp_funcs[qualified].append(uid)

    def _build_hierarchies(self) -> None:
        for site in self.sites:
            if site.ref_kind != "inherit" or site.dst is None:
                continue
            src_lang = self.nodes[site.src].lang if site.src in self.nodes else None
            if src_lang == "python":
                self.py_bases[site.src].append(site.dst)
            elif src_lang == "cpp":
                child = self.defs[site.src][0].attrs.get("qualified") if site.src in self.defs else None
                parent = self.defs[site.dst][0].attrs.get("qualified") if site.dst in self.defs else None
                if child and parent:
                    self.cpp_bases[str(child)].append(str(parent))
                    self.cpp_derived[str(parent)].append(str(child))

    # ============================================================ resolution
    def _site(self, facts: FileFacts, ref: Reference, res: Resolution) -> None:
        dst = res.dst
        resolution = res.resolution
        if dst is not None and dst in self.nodes and not self.nodes[dst].in_scope and resolution == "resolved":
            resolution = "out_of_scope"
        origin = self.origin_prefix.get(facts.lang, f"native:{facts.lang}")
        self.site_refs.append(ref)
        self.sites.append(CallSiteRecord(
            src=self._src(facts, ref.src), file=facts.path, line=ref.line, col=ref.col, ref_kind=ref.kind,
            target_text=ref.target_text, dst=dst, resolution=resolution, confidence=res.confidence, origin=origin,
            condition=ref.condition, candidates=sorted(set(res.candidates))))

    def _resolve(self, facts: FileFacts, ref: Reference) -> Resolution:
        if ref.kind == "include":
            return self._resolve_include(facts, ref)
        lang = facts.lang
        if lang == "fortran":
            return self._resolve_fortran(facts, ref)
        if lang == "python":
            return self._resolve_python(facts, ref)
        if lang == "c":
            return self._resolve_c(facts, ref)
        if lang == "cpp":
            return self._resolve_cpp(facts, ref)
        return self._resolve_generic(facts, ref)

    def _resolve_include(self, facts: FileFacts, ref: Reference) -> Resolution:
        resolved = next((i.resolved_path for i in facts.includes
                         if i.line == ref.line and i.text == ref.target_text and i.resolved_path), None)
        if resolved is None:
            return Resolution(None, "unresolved", "heuristic")
        uid = file_uid(resolved)
        if uid not in self.nodes:
            self._file_node(resolved, self.file_info.get(resolved, (None, 1))[0], self.file_info.get(resolved,
                                                                                                    (None, 1))[1])
        return Resolution(uid, "resolved", "exact")

    def _with_variants(self, uid: str, confidence: str) -> Resolution:
        variants = sorted(self.variants.get(_base(uid), [uid]), key=lambda u: (len(u), u))
        if len(variants) > 1:
            return Resolution(variants[0], "resolved", "resolved", variants)
        return Resolution(uid, "resolved", confidence)

    def _resolve_generic(self, facts: FileFacts, ref: Reference) -> Resolution:
        """Keyword-profile languages: a call resolves to a definition of the same language and name."""
        name = str(ref.hint.get("key", ref.target_text))
        if ref.kind == "use":
            for path, (lang, _n) in sorted(self.file_info.items()):
                stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                if lang == facts.lang and (stem == ref.target_text or stem.lower() == name):
                    return Resolution(file_uid(path), "resolved", "heuristic")
            return Resolution(None, "unresolved", "heuristic")
        uid = f"kw:{facts.lang}:{name}"
        if uid in self.nodes:
            return self._with_variants(uid, "heuristic")
        if ref.kind == "maybe_call" and ref.hint.get("only_known_names", True):
            return Resolution(_DROP, "unresolved", "heuristic")
        return Resolution(None, "unresolved", "heuristic")


    # -------------------------------------------------------------- Fortran
    def _f_chain(self, uid: str) -> list[str]:
        chain: list[str] = []
        u: str | None = uid
        while u is not None and u in self.defs and len(chain) < 20:
            chain.append(u)
            u = self.parent.get(u)
        return chain

    def _f_modules(self, chain: list[str]) -> list[str]:
        out: list[str] = []
        queue: list[str] = []
        for u in chain:
            for m in self.defs[u][0].attrs.get("uses", []) if u in self.defs else []:
                queue.append(str(m))
        seen: set[str] = set()
        while queue:
            m = queue.pop(0)
            if m in seen:
                continue
            seen.add(m)
            out.append(m)
            mod_uid = f"fmod:{m}"
            if mod_uid in self.defs:
                queue.extend(str(x) for x in self.defs[mod_uid][0].attrs.get("uses", []))
        return out

    def _f_lookup(self, name: str, chain: list[str], modules: list[str]) -> str | None:
        for u in chain:
            d = self.defs[u][0]
            if d.kind == "module":
                cand = f"f:{d.name}::{name}"
            elif d.kind in ("routine",):
                cand = f"{_base(u)}::{name}"
            else:
                continue
            if cand in self.nodes and cand in self.defs:
                return cand
        for m in modules:
            cand = f"f:{m}::{name}"
            if cand in self.defs:
                return cand
        cand = f"f:{name}"
        if cand in self.defs and self.defs[cand][0].kind != "module":
            return cand
        return None

    def _resolve_fortran(self, facts: FileFacts, ref: Reference) -> Resolution:
        src = self._src(facts, ref.src)
        if ref.kind == "use":
            name = ref.target_text.lower()
            if f"fmod:{name}" in self.defs:
                return Resolution(f"fmod:{name}", "resolved", "exact")
            if name in INTRINSIC_MODULES:
                return Resolution(self._ext(f"ext:fortran:{name}", "fortran_module", name), "external", "exact")
            return Resolution(None, "unresolved", "heuristic")
        if ref.kind == "dynamic_call":
            return Resolution(None, "unresolved", "heuristic")
        chain = self._f_chain(src)
        modules = self._f_modules(chain)
        hint = ref.hint
        if "binding" in hint:
            base_type = hint.get("base_type")
            type_uid = self._f_lookup(str(base_type), chain, modules) if base_type else None
            if type_uid is not None and self.defs[type_uid][0].kind == "type":
                bindings = self.defs[type_uid][0].attrs.get("bindings", {})
                impl = bindings.get(str(hint["binding"])) if isinstance(bindings, dict) else None
                if impl:
                    type_chain = self._f_chain(self.parent.get(type_uid, type_uid))
                    target = self._f_lookup(str(impl), type_chain, self._f_modules(type_chain))
                    if target is not None:
                        return self._with_variants(target, "resolved")
                if hint.get("component_ok"):
                    return Resolution(_DROP, "unresolved", "heuristic")
            return Resolution(None, "unresolved", "heuristic")
        name = ref.target_text.lower()
        target = self._f_lookup(name, chain, modules)
        if target is not None:
            d = self.defs[target][0]
            if d.kind == "interface":
                return self._f_generic(target)
            if d.kind == "routine":
                return self._with_variants(target, "exact" if ref.kind == "call" else "resolved")
            if ref.kind == "maybe_call":
                return Resolution(_DROP, "unresolved", "heuristic")
        if hint.get("intrinsic"):
            return Resolution(self._ext(f"ext:intrinsic:{name}", "intrinsic", name), "external", "exact")
        ext = external_for("fortran", name)
        if ext:
            return Resolution(self._ext(ext, ext.split(":")[1], name), "external", "exact")
        if ref.kind == "maybe_call":
            for m in modules + [self.defs[u][0].name for u in chain if self.defs[u][0].kind == "module"]:
                if name in self.f_module_vars.get(f"fmod:{m}", set()):
                    return Resolution(_DROP, "unresolved", "heuristic")
            return Resolution(None, "ambiguous", "ambiguous")
        return Resolution(None, "unresolved", "heuristic")

    def _f_generic(self, iface_uid: str) -> Resolution:
        d = self.defs[iface_uid][0]
        specifics = d.attrs.get("specifics", [])
        scope_chain = self._f_chain(self.parent.get(iface_uid, iface_uid))
        modules = self._f_modules(scope_chain)
        uids: list[str] = []
        for s in specifics if isinstance(specifics, list) else []:
            u = self._f_lookup(str(s), scope_chain, modules)
            if u is not None and self.defs[u][0].kind == "routine":
                uids.extend(self.variants.get(_base(u), [u]))
        uids = sorted(set(uids))
        if len(uids) == 1:
            return Resolution(uids[0], "resolved", "resolved")
        if uids:
            return Resolution(None, "ambiguous", "ambiguous", uids)
        return Resolution(None, "unresolved", "heuristic")

    # --------------------------------------------------------------- Python
    def _py_method(self, class_uid: str, name: str, seen: set[str] | None = None) -> str | None:
        seen = seen or set()
        if class_uid in seen:
            return None
        seen.add(class_uid)
        cand = f"{class_uid}.{name}"
        if cand in self.defs:
            return cand
        for base in self.py_bases.get(class_uid, []):
            found = self._py_method(base, name, seen)
            if found:
                return found
        return None

    def _py_find(self, dotted: str, depth: int = 0) -> tuple[str | None, str]:
        """Resolve an absolute dotted name. Status: repo, repo_missing or external.

        Follows what a module re-exports: its own imports (``from x import y``), its star imports
        (``from x import *``) and callable module-level instances (``tr = Translation()`` -> ``__call__``).
        """
        if f"py:{dotted}" in self.defs:
            return f"py:{dotted}", "repo"
        parts = dotted.split(".")
        for i in range(len(parts) - 1, 0, -1):
            prefix = "py:" + ".".join(parts[:i])
            if prefix in self.defs:
                rest = parts[i:]
                d = self.defs[prefix][0]
                if d.kind == "type" and len(rest) == 1:
                    m = self._py_method(prefix, rest[0])
                    if m:
                        return m, "repo"
                if d.kind == "module" and depth < 8:
                    found = self._py_reexport(d, rest, depth)
                    if found is not None:
                        return found
                return None, "repo_missing"
        return None, "external"

    def _py_reexport(self, module: Definition, rest: list[str], depth: int) -> tuple[str | None, str] | None:
        imports = module.attrs.get("imports", {})
        if isinstance(imports, dict) and rest[0] in imports:
            uid, status = self._py_find(".".join([str(imports[rest[0]]), *rest[1:]]), depth + 1)
            if uid is not None or status == "external":
                return uid, status
        instances = module.attrs.get("instances", {})
        if isinstance(instances, dict) and rest[0] in instances and len(rest) == 1:
            cls, _status = self._py_bind_uid(dict(instances[rest[0]]))
            if cls is not None and cls in self.defs and self.defs[cls][0].kind == "type":
                call = self._py_method(cls, "__call__")
                if call:
                    return call, "repo"
        for star in module.attrs.get("star_imports", []) or []:
            uid, _status = self._py_find(".".join([str(star), *rest]), depth + 1)
            if uid is not None:
                return uid, "repo"
        return None

    def _py_bind_uid(self, bind: dict[str, Any]) -> tuple[str | None, str]:
        kind = bind.get("kind")
        attrs = [str(a) for a in bind.get("attrs", [])]
        if kind == "local_def":
            return self._py_find(".".join([str(bind["qual"]), *attrs]))
        if kind == "import":
            return self._py_find(".".join([str(bind["target"]), *attrs]))
        return None, "unknown"

    def _resolve_python(self, facts: FileFacts, ref: Reference) -> Resolution:
        hint = ref.hint
        if ref.kind == "use":
            dotted = str(hint.get("module", ""))
            if hint.get("name"):
                dotted = f"{dotted}.{hint['name']}" if dotted else str(hint["name"])
            uid, status = self._py_find(dotted)
            if uid is None and status == "repo_missing" and f"py:{hint.get('module')}" in self.defs:
                return Resolution(None, "unresolved", "heuristic")
            return self._py_result(uid, status, dotted, "exact")
        bind: dict[str, Any] = dict(hint.get("bind", {}))
        attrs = [str(a) for a in hint.get("attrs", [])]
        kind = bind.get("kind")
        if kind in ("local_def", "import"):
            base = str(bind["qual"] if kind == "local_def" else bind["target"])
            dotted = ".".join([base, *attrs])
            uid, status = self._py_find(dotted)
            return self._py_result(uid, status, dotted, "exact")
        if kind == "builtin":
            dotted = ".".join(["builtins", ref.target_text.split(".")[0], *attrs])
            return Resolution(self._ext(f"ext:python:{dotted}", "python", dotted), "external", "exact")
        if kind == "self" and attrs:
            cls = f"py:{bind['class']}"
            m = self._py_method(cls, attrs[0]) if len(attrs) == 1 else None
            return Resolution(m, "resolved", "resolved") if m else Resolution(None, "unresolved", "heuristic")
        if kind == "instance" and attrs:
            cls_uid, _status = self._py_bind_uid(dict(bind.get("class", {})))
            if cls_uid and self.defs.get(cls_uid, (None,))[0] is not None and self.defs[cls_uid][0].kind == "type":
                m = self._py_method(cls_uid, attrs[0]) if len(attrs) == 1 else None
                if m:
                    return Resolution(m, "resolved", "resolved")
            return self._py_method_by_name(attrs[-1])
        if kind == "getattr":
            base_uid, _status = self._py_bind_uid(dict(bind.get("base", {})))
            if base_uid:
                dotted = base_uid[3:] + "." + str(bind.get("attr")) + "".join(f".{a}" for a in attrs)
                uid, status = self._py_find(dotted)
                if uid:
                    return Resolution(uid, "resolved", "heuristic")
            return Resolution(None, "unresolved", "heuristic")
        if kind in ("variable", "expression", "instance") and attrs:
            return self._py_method_by_name(attrs[-1])
        if kind == "unknown":
            # Not bound in the file: maybe provided by a star import of the module.
            module = next((d for d in facts.definitions if d.subtype == "py_module"), None)
            if module is not None and module.attrs.get("star_imports"):
                found = self._py_reexport(module, [ref.target_text.split(".")[0], *attrs], 0)
                if found is not None and found[0] is not None:
                    return Resolution(found[0], "resolved", "resolved")
                if found is not None and found[1] == "external":
                    dotted = ".".join([ref.target_text.split(".")[0], *attrs])
                    return Resolution(self._ext(f"ext:python:{dotted}", "python", dotted), "external", "exact")
        return Resolution(None, "unresolved", "heuristic")

    def _py_method_by_name(self, name: str) -> Resolution:
        cands = sorted(self.py_methods_by_name.get(name, []))
        if len(cands) == 1:
            return Resolution(cands[0], "resolved", "heuristic")
        if cands:
            return Resolution(None, "ambiguous", "ambiguous", cands)
        return Resolution(None, "external", "exact")

    def _py_result(self, uid: str | None, status: str, dotted: str, confidence: str) -> Resolution:
        if uid is not None:
            return self._with_variants(uid, confidence)
        if status == "external":
            return Resolution(self._ext(f"ext:python:{dotted}", "python", dotted), "external", "exact")
        return Resolution(None, "unresolved", "heuristic")

    # ---------------------------------------------------------------- C
    def _resolve_c(self, facts: FileFacts, ref: Reference) -> Resolution:
        if ref.kind == "dynamic_call":
            return Resolution(None, "unresolved", "heuristic")
        name = ref.target_text
        confidence = "resolved" if ref.hint.get("macro") else "exact"
        local = f"c:{name}@{facts.path}"
        if local in self.defs:
            return self._with_variants(local, confidence)
        if f"c:{name}" in self.defs:
            return self._with_variants(f"c:{name}", confidence)
        ext = external_for("c", name)
        if ext:
            return Resolution(self._ext(ext, ext.split(":")[1], name), "external", "exact")
        return Resolution(None, "unresolved", "heuristic")

    # -------------------------------------------------------------- C++
    def _cpp_class(self, name: str, namespaces: list[str]) -> str | None:
        smart = re.match(r"^(?:std::|boost::)?(?:shared_ptr|unique_ptr|weak_ptr)\s*<\s*(.+?)\s*>$", name.strip())
        if smart:
            name = smart.group(1)
        name = re.sub(r"<.*>", "", name).strip()
        candidates = [name] + ([name[:-3]] if name.endswith("Ptr") and len(name) > 3 else [])
        for cand in candidates:  # ``XxxPtr`` is the usual typedef of a smart pointer to ``Xxx``
            for i in range(len(namespaces), -1, -1):
                q = "::".join([*namespaces[:i], cand])
                if q in self.cpp_classes:
                    return q
        return None

    def _cpp_method_by_name(self, method: str) -> Resolution | None:
        cands = sorted(self.cpp_methods_by_name.get(method, []))
        if len(cands) == 1:
            return Resolution(cands[0], "resolved", "heuristic")
        if cands:
            return Resolution(None, "ambiguous", "ambiguous", cands)
        return None

    def _cpp_methods(self, cls: str, name: str, seen: set[str] | None = None) -> list[str]:
        seen = seen or set()
        if cls in seen:
            return []
        seen.add(cls)
        found = list(self.cpp_methods.get(cls, {}).get(name, []))
        if found:
            return found
        for base in self.cpp_bases.get(cls, []):
            found = self._cpp_methods(base, name, seen)
            if found:
                return found
        return []

    def _cpp_derived_methods(self, cls: str, name: str) -> list[str]:
        out: list[str] = []
        queue = list(self.cpp_derived.get(cls, []))
        seen: set[str] = set()
        while queue:
            c = queue.pop(0)
            if c in seen:
                continue
            seen.add(c)
            out.extend(self.cpp_methods.get(c, {}).get(name, []))
            queue.extend(self.cpp_derived.get(c, []))
        return out

    def _cpp_funcs(self, qualified: str, namespaces: list[str], path: str) -> list[str]:
        for i in range(len(namespaces), -1, -1):
            q = "::".join([*namespaces[:i], qualified])
            uids = [u for u in self.cpp_funcs.get(q, []) if "@" not in u or u.endswith("@" + path)]
            if uids:
                return uids
        return []

    @staticmethod
    def _norm_type(t: str | None) -> str | None:
        if t is None:
            return None
        t = re.sub(r"\b(const|volatile)\b", "", t).replace("&", "")
        return re.sub(r"\s+", "", t)

    def _select_overload(self, uids: list[str], arg_types: list[str | None], single_conf: str) -> Resolution:
        uids = sorted(set(uids))
        if len(uids) == 1:
            return Resolution(uids[0], "resolved", single_conf)
        n = len(arg_types)

        def params(u: str) -> list[str]:
            p = self.defs[u][0].attrs.get("params", []) if u in self.defs else []
            return [str(x) for x in p] if isinstance(p, list) else []

        arity = [u for u in uids if len(params(u)) == n or "..." in params(u)]
        if len(arity) == 1:
            return Resolution(arity[0], "resolved", "resolved")
        pool = arity or uids
        if arg_types and all(t is not None for t in arg_types):
            wanted = [self._norm_type(t) for t in arg_types]
            exact = [u for u in pool if [self._norm_type(p) for p in params(u)] == wanted]
            if len(exact) == 1:
                return Resolution(exact[0], "resolved", "resolved")
        return Resolution(None, "ambiguous", "ambiguous", pool)

    def _resolve_cpp(self, facts: FileFacts, ref: Reference) -> Resolution:
        hint = ref.hint
        namespaces = [str(n) for n in hint.get("namespaces", [])]
        if ref.kind == "inherit":
            cls = self._cpp_class(ref.target_text, namespaces)
            if cls:
                return Resolution(self.cpp_classes[cls], "resolved", "exact")
            return Resolution(None, "unresolved", "heuristic")
        if ref.kind == "dynamic_call":
            return Resolution(None, "unresolved", "heuristic")
        arg_types = list(hint.get("arg_types", []))
        macro = bool(hint.get("macro"))
        if "method" in hint:
            method = str(hint["method"])
            recv = hint.get("receiver_type")
            if recv:
                cls = self._cpp_class(str(recv), namespaces)
                if cls:
                    uids = self._cpp_methods(cls, method) or self._cpp_derived_methods(cls, method)
                    if uids:
                        return self._select_overload(uids, arg_types, "resolved")
                    return Resolution(None, "unresolved", "heuristic")
            cands = sorted(self.cpp_methods_by_name.get(method, []))
            if len(cands) == 1:
                return Resolution(cands[0], "resolved", "heuristic")
            if cands:
                return Resolution(None, "ambiguous", "ambiguous", cands)
            return Resolution(None, "external", "exact")
        name = str(hint.get("qualified") or hint.get("name") or ref.target_text)
        cls_ctx = hint.get("class")
        if cls_ctx and "::" not in name:
            uids = self._cpp_methods(str(cls_ctx), name) or self._cpp_derived_methods(str(cls_ctx), name)
            if uids:
                return self._select_overload(uids, arg_types, "resolved")
        uids = self._cpp_funcs(name, namespaces, facts.path)
        if uids:
            return self._select_overload(uids, arg_types, "resolved" if macro else "exact")
        if "::" in name:
            qual, _, meth = name.rpartition("::")
            cls = self._cpp_class(qual, namespaces)
            if cls:
                uids = self._cpp_methods(cls, meth)
                if uids:
                    return self._select_overload(uids, arg_types, "resolved")
        ext = external_for("cpp", name)
        if ext:
            return Resolution(self._ext(ext, ext.split(":")[1], name), "external", "exact")
        if cls_ctx and "::" not in name:  # method inherited through a base the analysis could not follow
            by_name = self._cpp_method_by_name(name)
            if by_name is not None:
                return by_name
        return Resolution(None, "unresolved", "heuristic")

    # ------------------------------------------------------------ structure
    def _structure(self) -> None:
        edges: list[EdgeRecord] = []
        for uid, node in sorted(self.nodes.items()):
            if node.kind in ("file", "external"):
                continue
            parent = self.parent.get(uid)
            src = parent if parent and parent in self.nodes else (file_uid(node.file) if node.file else None)
            if src is not None and src != uid:
                edges.append(EdgeRecord(src, uid, "contains", 0, "exact", ["structure"], []))
            d = self.defs.get(uid, (None,))[0]
            if d is not None and d.kind == "interface" and node.lang == "fortran":
                res = self._f_generic(uid)
                for target in res.candidates or ([res.dst] if res.dst else []):
                    edges.append(EdgeRecord(uid, target, "implements", 0, "exact", [f"native:{node.lang}"], []))
        for uid, target in sorted(self.binding_targets.items()):
            if uid in self.nodes and target in self.nodes:
                edges.append(EdgeRecord(uid, target, "binds", 0, "resolved", ["bridge"], []))
        self.struct_edges = edges

    def _data_accesses(self) -> None:
        """Fortran shared data: COMMON blocks, and module variables found through the USE of each routine."""
        for facts in self.facts:
            for a in facts.data_accesses:
                src = self._src(facts, a.src)
                if src not in self.defs:
                    continue
                if a.data_key.startswith("common:"):
                    uid = f"data:{a.data_key}"
                    subtype = "common_block"
                    display = "/" + a.data_key.split(":", 1)[1] + "/"
                elif a.data_key.startswith("var:"):
                    name = a.data_key[4:]
                    chain = self._f_chain(src)
                    modules = [self.defs[u][0].name for u in chain if self.defs[u][0].kind == "module"]
                    modules += self._f_modules(chain)
                    owner = next((m for m in modules if name in self.f_module_vars.get(f"fmod:{m}", set())), None)
                    if owner is None:
                        continue
                    uid = f"data:module:{owner}::{name}"
                    subtype = "module_variable"
                    display = f"{owner}::{name}"
                else:
                    continue
                if uid not in self.nodes:
                    self.nodes[uid] = NodeRecord(uid, display, "data", subtype, facts.lang, None, None, None, True, {})
                self.data_records.append(DataAccessRecord(src, uid, None, a.mode, a.key_kind, facts.path, a.line,
                                                          a.origin or f"native:{facts.lang}"))

    def _prune_externals(self) -> None:
        """External nodes no longer referenced (e.g. replaced by a bridge) are removed."""
        used = {s.dst for s in self.sites if s.dst} | {c for s in self.sites for c in s.candidates}
        used |= {e.dst for e in self.struct_edges} | {e.src for e in self.struct_edges}
        for uid in [u for u, n in self.nodes.items() if n.kind == "external" and u not in used]:
            del self.nodes[uid]


def weakest(values: list[str]) -> str:
    return max(values, key=lambda v: CONFIDENCE_RANK.get(v, 99)) if values else "exact"
