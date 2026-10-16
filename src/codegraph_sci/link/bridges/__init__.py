"""Cross-language bridges (§3.8, lot 8). They only act on sites left unresolved (or external) by Link.

Native bridges (generic, enabled by default):
* ``pybind11`` and ``python_extension``: Python calls into compiled modules -> bound C/C++ functions;
* ``c_cpp``: C++ <-> C calls (``extern "C"`` linkage, same name);
* ``fortran_c``: C/C++ <-> Fortran (trailing underscore, upper case, g77 double underscore, ``BIND(C, NAME=)``).

Rule bridges (packs, profile rules, AI proposals), format of a pack ``bridges[]`` entry:
* ``prefix_calls``: ``call_prefixes`` tried from the longest to the shortest, ``name_transform`` applied;
* ``declaration_patterns``: declare a routine of the other language -> ``binding`` node, never a call site.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

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

    def set(self, site: CallSiteRecord, dst: str, bridge: str, candidates: list[str] | None = None) -> None:
        site.dst = dst
        site.resolution = "resolved" if self.lk.nodes[dst].in_scope else "out_of_scope"
        site.confidence = "resolved"
        site.origin = f"bridge:{bridge}"
        site.candidates = sorted(set(candidates or []))

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
            if rule.get("call_prefixes"):
                self.prefix_calls(rule)
            if rule.get("declaration_patterns"):
                self.declarations(rule)

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
                rest = parts[i:]
                if not rest:
                    self.set(site, mod_uid, bridge)
                elif len(rest) == 1 and (module, rest[0]) in members:
                    member = members[(module, rest[0])]
                    impl = self.binding_targets.get(member)
                    dst = member if site.ref_kind == "use" or impl is None else impl
                    self.set(site, dst, bridge)
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
                self.set(site, f"c:{name}", "c_cpp")
            elif lang == "c":
                uids = [u for u in self.lk.cpp_funcs.get(name, []) if "@" not in u]
                if len(uids) == 1:
                    self.set(site, uids[0], "c_cpp")

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
                if target is None and name.endswith("_"):
                    base = name[:-1]
                    if base.endswith("_") and "_" in base[:-1]:
                        base = base[:-1]
                    target = self.fortran_routine(base)
                if target is None and name.isupper() and any(c.isalpha() for c in name):
                    target = self.fortran_routine(name)
                if target is not None:
                    self.set(site, target, "fortran_c")
            elif lang == "fortran":
                if "%" in name:
                    continue
                bind = ref.hint.get("bind_c")
                candidates = [str(bind)] if bind else [name.lower() + "_", name.lower(), name.upper(),
                                                       name.lower() + "__"]
                for cand in candidates:
                    target_c = self.c_function(cand)
                    if target_c is not None:
                        self.set(site, target_c, "fortran_c")
                        break

    # -------------------------------------------------------------- rules
    def _lookup(self, lang: str, name: str) -> str | None:
        if lang == "fortran":
            return self.fortran_routine(name)
        if lang in ("c", "cpp"):
            return self.c_function(name) if lang == "c" else (
                sorted(self.lk.cpp_funcs.get(name, []))[0] if self.lk.cpp_funcs.get(name) else None)
        return None

    def prefix_calls(self, rule: dict[str, Any]) -> None:
        src_lang, dst_lang = str(rule["from"]), str(rule["to"])
        prefixes = sorted((str(p) for p in rule["call_prefixes"]), key=lambda p: (-len(p), p))
        ops = [str(o) for o in rule.get("name_transform", ["strip_prefix"])]
        origin = "prefix_calls" + (f"@{rule['id']}" if rule.get("id") else "")
        for site in self.lk.sites:
            if site.resolution != "unresolved" or site.ref_kind not in _CALLS or self.lang_of(site) != src_lang:
                continue
            for prefix in prefixes:
                if site.target_text.startswith(prefix) and len(site.target_text) > len(prefix):
                    target = self._lookup(dst_lang, apply_transform(site.target_text, prefix, ops))
                    if target is not None:
                        self.set(site, target, origin)
                    break

    def declarations(self, rule: dict[str, Any]) -> None:
        src_lang, dst_lang = str(rule["from"]), str(rule["to"])
        ops = [o for o in rule.get("name_transform", ["lowercase"]) if o != "strip_prefix"] or ["lowercase"]
        patterns = [re.compile(str(p)) for p in rule["declaration_patterns"]]
        macro_names = {m.group(0) for p in rule["declaration_patterns"] for m in [re.match(r"[A-Za-z_]\w*", str(p))]
                       if m}
        # Declarations are never call sites.
        keep = [i for i, s in enumerate(self.lk.sites) if not (s.target_text in macro_names and
                                                                self.lang_of(s) == src_lang)]
        self.lk.sites[:] = [self.lk.sites[i] for i in keep]
        self.lk.site_refs[:] = [self.lk.site_refs[i] for i in keep]
        if self.read_text is None:
            return
        for path, (lang, _lines) in sorted(self.lk.file_info.items()):
            if lang != src_lang:
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
                        target = self._lookup(dst_lang, apply_transform(name, "", ops))
                        if target is not None:
                            self.binding_targets[uid] = target
