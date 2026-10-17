"""Cross-language bridges (§3.8, lot 8). They only act on sites left unresolved (or external) by Link.

Native bridges (generic, enabled by default), declared in ``catalog.py``:
* ``pybind11`` and ``python_extension``: Python calls into compiled modules -> bound C/C++ functions;
* ``c_cpp``: C++ <-> C calls (``extern "C"`` linkage, same name);
* ``fortran_c``: C/C++ <-> Fortran (trailing underscore, upper case, g77 double underscore, ``BIND(C, NAME=)``).

Rule bridges (packs, profile rules, AI proposals), format of a pack ``bridges[]`` entry:
* ``prefix_calls``: ``call_prefixes`` tried from the longest to the shortest, ``name_transform`` applied;
* ``declaration_patterns``: declare a routine of the other language -> ``binding`` node, never a call site;
* ``candidates``: several targets are kept as an ambiguous site (``keep_ambiguous``, default) or none is linked
  (``unique``); a target is never picked among homonyms;
* ``require_declaration``: a prefix call is linked only if a declaration pattern of the rule names its target;
* ``files`` / ``target_files``: globs limiting the caller files and the files targets may come from.

Every site resolved by a bridge records its evidence (phase 5): rule and version, mechanism, evidence kind,
binding declaration, transformed name, candidate selection and reason.
"""

from __future__ import annotations

import fnmatch
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from codegraph_sci.core.bridge_catalog import MECHANISMS, NATIVE_VERSION
from codegraph_sci.core.graph import CallSiteRecord, NodeRecord

if TYPE_CHECKING:
    from codegraph_sci.link.linker import Linker

TRANSFORMS = ("strip_prefix", "lowercase", "uppercase", "append_underscore", "strip_underscore")
_CALLS = ("call", "maybe_call")


def apply_transform(name: str, prefix: str, ops: list[str]) -> str:
    out = name
    if "strip_prefix" in ops or not ops:
        out = out[len(prefix):] if prefix and out.startswith(prefix) else out
    for op in ops:
        if op == "lowercase":
            out = out.lower()
        elif op == "uppercase":
            out = out.upper()
        elif op == "append_underscore":
            out = out + "_"
        elif op == "strip_underscore":
            out = out.rstrip("_")
    return out


def _matches(path: str | None, globs: list[str] | None) -> bool:
    return not globs or (path is not None and any(fnmatch.fnmatchcase(path, g) for g in globs))


class BridgeEngine:
    def __init__(self, linker: Linker, rules: list[dict[str, Any]], native: bool,
                 read_text: Callable[[str], str | None] | None) -> None:
        self.lk = linker
        self.rules = rules
        self.native = native
        self.read_text = read_text
        self.binding_targets: dict[str, str] = {}
        self._bind_c: dict[str, str] | None = None

    # ------------------------------------------------------------ helpers
    def lang_of(self, site: CallSiteRecord) -> str | None:
        info = self.lk.file_info.get(site.file)
        return info[0] if info else None

    @staticmethod
    def evidence(bridge: str, mechanism: str, *, version: str | None = None, binding: str | None = None,
                 name: str | None = None, policy: str = "unique", reason: str = "") -> dict[str, Any]:
        out: dict[str, Any] = {"rule": f"bridge:{bridge}", "rule_version": version or NATIVE_VERSION,
                               "mechanism": mechanism, "evidence_kind": MECHANISMS[mechanism].evidence,
                               "candidate_selection": policy,
                               "reason": reason or MECHANISMS[mechanism].description}
        if binding is not None:
            out["binding"] = binding
        if name is not None:
            out["name"] = name
        return out

    def set(self, site: CallSiteRecord, dst: str, bridge: str, evidence: dict[str, Any],
            candidates: list[str] | None = None) -> None:
        site.dst = dst
        site.resolution = "resolved" if self.lk.nodes[dst].in_scope else "out_of_scope"
        site.confidence = "resolved"
        site.origin = f"bridge:{bridge}"
        site.candidates = sorted(set(candidates or []))
        site.evidence = evidence

    def set_ambiguous(self, site: CallSiteRecord, candidates: list[str], bridge: str,
                      evidence: dict[str, Any]) -> None:
        site.dst = None
        site.resolution = "ambiguous"
        site.confidence = "ambiguous"
        site.origin = f"bridge:{bridge}"
        site.candidates = sorted(set(candidates))
        site.evidence = evidence

    @property
    def bind_c_index(self) -> dict[str, str]:
        """C name -> Fortran routine declared ``BIND(C, NAME=...)`` (built once)."""
        if self._bind_c is None:
            self._bind_c = {}
            for u, (dd, _p, lang) in sorted(self.lk.defs.items()):
                if lang == "fortran" and dd.kind == "routine" and dd.attrs.get("bind_c"):
                    self._bind_c.setdefault(str(dd.attrs["bind_c"]), u)
        return self._bind_c

    def fortran_routine(self, name: str) -> str | None:
        uid = f"f:{name.lower()}"
        d = self.lk.defs.get(uid)
        if d is not None and d[0].kind == "routine":
            return uid
        return self.bind_c_index.get(name)

    def fortran_bind_c(self, c_name: str) -> str | None:
        return self.bind_c_index.get(c_name)

    def c_function(self, name: str, from_path: str | None = None) -> str | None:
        if from_path is not None and f"c:{name}@{from_path}" in self.lk.defs:
            return f"c:{name}@{from_path}"
        if f"c:{name}" in self.lk.defs:
            return f"c:{name}"
        uids = [u for u in self.lk.cpp_funcs.get(name, []) if "@" not in u]
        return uids[0] if len(uids) == 1 else None

    # ------------------------------------------------------------- run
    def run(self) -> None:
        if self.native:
            self.python_bindings()
            self.c_cpp()
            self.fortran_c()
        for rule in self.rules:
            declared: dict[str, str] = {}
            if rule.get("declaration_patterns"):
                declared = self.declarations(rule)
            if rule.get("call_prefixes"):
                self.prefix_calls(rule, declared)

    # -------------------------------------------------- Python bindings
    def _binding_target(self, d_uid: str) -> str | None:
        d, path, lang = self.lk.defs[d_uid]
        target = str(d.attrs.get("target", ""))
        if not target:
            return None
        if d.attrs.get("bridge") == "pybind11":
            namespaces = [str(n) for n in d.attrs.get("namespaces", [])]
            uids = self.lk._cpp_funcs(target, namespaces, path)
            if not uids and "::" in target:
                qual, _, meth = target.rpartition("::")
                cls = self.lk._cpp_class(qual, namespaces)
                uids = self.lk._cpp_methods(cls, meth) if cls else []
            return sorted(uids)[0] if uids else None
        return self.c_function(target, path)

    def python_bindings(self) -> None:
        modules: dict[str, str] = {}
        members: dict[tuple[str, str], str] = {}
        for uid, (d, _path, _lang) in sorted(self.lk.defs.items()):
            if d.kind != "binding":
                continue
            if d.subtype in ("pybind11_module", "pyext_module"):
                modules.setdefault(str(d.attrs["module"]), uid)
            elif d.subtype in ("pybind11_def", "pyext_def"):
                members.setdefault((str(d.attrs["module"]), str(d.attrs["py_name"])), uid)
                target = self._binding_target(uid)
                if target:
                    self.binding_targets[uid] = target
        if not modules:
            return
        for site in self.lk.sites:
            if site.resolution != "external" or not site.dst or not site.dst.startswith("ext:python:"):
                continue
            dotted = site.dst[len("ext:python:"):]
            parts = dotted.split(".")
            for i in range(len(parts), 0, -1):
                module = ".".join(parts[:i])
                if module not in modules:
                    continue
                mod_uid = modules[module]
                bridge = str(self.lk.defs[mod_uid][0].attrs.get("bridge", "pybind11"))
                prefix = "pybind11" if bridge == "pybind11" else "pyext"
                rest = parts[i:]
                if not rest:
                    self.set(site, mod_uid, bridge, self.evidence(bridge, f"{prefix}_module", binding=mod_uid,
                                                                  name=module))
                elif len(rest) == 1 and (module, rest[0]) in members:
                    member = members[(module, rest[0])]
                    impl = self.binding_targets.get(member)
                    dst = member if site.ref_kind == "use" or impl is None else impl
                    self.set(site, dst, bridge, self.evidence(bridge, f"{prefix}_def", binding=member,
                                                              name=f"{module}.{rest[0]}"))
                break

    # ------------------------------------------------------------- C/C++
    def c_cpp(self) -> None:
        for site, ref in zip(self.lk.sites, self.lk.site_refs, strict=True):
            if site.resolution != "unresolved" or site.ref_kind not in _CALLS:
                continue
            lang = self.lang_of(site)
            name = str(ref.hint.get("name") or "")
            if not name or "::" in name:
                continue
            if lang == "cpp" and f"c:{name}" in self.lk.defs:
                self.set(site, f"c:{name}", "c_cpp", self.evidence("c_cpp", "c_linkage_same_name", name=name))
            elif lang == "c":
                uids = [u for u in self.lk.cpp_funcs.get(name, []) if "@" not in u]
                if len(uids) == 1:
                    self.set(site, uids[0], "c_cpp", self.evidence("c_cpp", "c_linkage_same_name", name=name))

    # ------------------------------------------------------------ Fortran
    def fortran_c(self) -> None:
        for site, ref in zip(self.lk.sites, self.lk.site_refs, strict=True):
            if site.resolution != "unresolved" or site.ref_kind not in _CALLS:
                continue
            lang = self.lang_of(site)
            name = site.target_text
            if lang in ("c", "cpp"):
                if "::" in name or "." in name or "->" in name:
                    continue
                target = self.fortran_bind_c(name)
                evidence = self.evidence("fortran_c", "bind_c_name", binding=target, name=name)
                if target is None and name.endswith("_"):
                    base, mechanism = name[:-1], "trailing_underscore"
                    if base.endswith("_") and "_" in base[:-1]:
                        base, mechanism = base[:-1], "g77_double_underscore"
                    target = self.fortran_routine(base)
                    evidence = self.evidence("fortran_c", mechanism, name=base.lower())
                if target is None and name.isupper() and any(c.isalpha() for c in name):
                    target = self.fortran_routine(name)
                    evidence = self.evidence("fortran_c", "uppercase_name", name=name.lower())
                if target is not None:
                    self.set(site, target, "fortran_c", evidence)
            elif lang == "fortran":
                if "%" in name:
                    continue
                bind = ref.hint.get("bind_c")
                low = name.lower()
                candidates = [(str(bind), "bind_c_name")] if bind else [
                    (low + "_", "trailing_underscore"), (low, "same_name"), (name.upper(), "uppercase_name"),
                    (low + "__", "g77_double_underscore")]
                for cand, mechanism in candidates:
                    target_c = self.c_function(cand)
                    if target_c is not None:
                        binding = f'BIND(C, NAME="{cand}") in {site.src}' if bind else None
                        self.set(site, target_c, "fortran_c",
                                 self.evidence("fortran_c", mechanism, binding=binding, name=cand))
                        break

    # -------------------------------------------------------------- rules
    def _lookup_all(self, lang: str, name: str) -> list[str]:
        """Every target of ``name`` in ``lang``: one for Fortran and C, all homonyms for C++."""
        if lang == "fortran":
            found = self.fortran_routine(name)
            return [found] if found else []
        if lang == "c":
            found = self.c_function(name)
            return [found] if found else []
        if lang == "cpp":
            return sorted(self.lk.cpp_funcs.get(name, []))
        return []

    def prefix_calls(self, rule: dict[str, Any], declared: dict[str, str] | None = None) -> None:
        src_lang, dst_lang = str(rule["from"]), str(rule["to"])
        prefixes = sorted((str(p) for p in rule["call_prefixes"]), key=lambda p: (-len(p), p))
        ops = [str(o) for o in rule.get("name_transform", ["strip_prefix"])]
        bridge = "prefix_calls" + (f"@{rule['id']}" if rule.get("id") else "")
        policy = str(rule.get("candidates", "keep_ambiguous"))
        files, target_files = rule.get("files"), rule.get("target_files")
        version = str(rule["version"]) if rule.get("version") else None
        mechanism_label = str(rule.get("mechanism", ""))
        declared_by_name = {k.lower(): v for k, v in (declared or {}).items()}
        for site in self.lk.sites:
            if site.resolution != "unresolved" or site.ref_kind not in _CALLS or self.lang_of(site) != src_lang:
                continue
            if not _matches(site.file, files):
                continue
            for prefix in prefixes:
                if not (site.target_text.startswith(prefix) and len(site.target_text) > len(prefix)):
                    continue
                name = apply_transform(site.target_text, prefix, ops)
                binding = declared_by_name.get(name.lower())
                if rule.get("require_declaration") and binding is None:
                    break  # a similar name alone is not evidence enough
                targets = [u for u in self._lookup_all(dst_lang, name)
                           if _matches(self.lk.nodes[u].file if u in self.lk.nodes else None, target_files)]
                mechanism = "declaration_macro" if binding is not None else "prefix_call"
                reason = (f"prefix {prefix!r} removed and {', '.join(ops)} applied"
                          + (f"; declared by {binding}" if binding else "")
                          + (f" ({mechanism_label})" if mechanism_label else ""))
                evidence = self.evidence(bridge, mechanism, version=version, binding=binding, name=name,
                                         policy=policy, reason=reason)
                if len(targets) == 1:
                    self.set(site, targets[0], bridge, evidence)
                elif len(targets) > 1 and policy == "keep_ambiguous":
                    self.set_ambiguous(site, targets, bridge, evidence)
                break

    def declarations(self, rule: dict[str, Any]) -> dict[str, str]:
        """Binding nodes for declaration patterns; returns transformed target name -> binding uid."""
        src_lang, dst_lang = str(rule["from"]), str(rule["to"])
        ops = [o for o in rule.get("name_transform", ["lowercase"]) if o != "strip_prefix"] or ["lowercase"]
        patterns = [re.compile(str(p)) for p in rule["declaration_patterns"]]
        macro_names = {m.group(0) for p in rule["declaration_patterns"] for m in [re.match(r"[A-Za-z_]\w*", str(p))]
                       if m}
        declared: dict[str, str] = {}
        # Declarations are never call sites.
        keep = [i for i, s in enumerate(self.lk.sites) if not (s.target_text in macro_names and
                                                                self.lang_of(s) == src_lang)]
        self.lk.sites[:] = [self.lk.sites[i] for i in keep]
        self.lk.site_refs[:] = [self.lk.site_refs[i] for i in keep]
        if self.read_text is None:
            return declared
        for path, (lang, _lines) in sorted(self.lk.file_info.items()):
            if lang != src_lang or not _matches(path, rule.get("files")):
                continue
            text = self.read_text(path)
            if not text:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if line.lstrip().startswith(("//", "#")):
                    continue
                for rx in patterns:
                    for m in rx.finditer(line):
                        name = m.groupdict().get("name") or (m.group(1) if m.groups() else None)
                        if not name:
                            continue
                        uid = f"bind:decl:{name}@{path}"
                        if uid not in self.lk.nodes:
                            self.lk.nodes[uid] = NodeRecord(uid, name, "binding", "macro_declaration", lang, path,
                                                            number, number, True, {"pattern": rx.pattern})
                        transformed = apply_transform(name, "", ops)
                        declared.setdefault(transformed, uid)
                        target = self._lookup_all(dst_lang, transformed)
                        if len(target) == 1:
                            self.binding_targets[uid] = target[0]
        return declared
