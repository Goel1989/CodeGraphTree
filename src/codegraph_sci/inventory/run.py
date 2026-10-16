"""``cgs inventory``: language of every file, include paths, coverage report (§3.2)."""

from __future__ import annotations

import fnmatch
import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from codegraph_sci.core.profile import AnalysisProfile
from codegraph_sci.inventory.detect import (
    decode_text,
    detect_by_content,
    file_ext,
    fortran_variant,
    is_binary,
    python_variant,
)
from codegraph_sci.inventory.table import ExtensionTable, load_table
from codegraph_sci.inventory.walk import WalkProblem, walk_repo

_C_INCLUDE = re.compile(r'(?m)^[ \t]*#[ \t]*include[ \t]*"([^"\n]+)"')
_F_INCLUDE = re.compile(r"""(?im)^[ \t]*include[ \t]*['"]([^'"\n]+)['"]""")
_CPP_HEADER_HINT = re.compile(r"(?m)^\s*(class\s+\w+|namespace\s+\w+|template\s*<)|\bstd::")
MAX_READ_BYTES = 64 * 1024 * 1024


@dataclass
class InventoryEntry:
    path: str
    lang: str | None
    variant: str | None
    confidence: float
    decided_by: str
    status: str  # source, not_covered, unknown, ignored, binary
    size: int = 0
    lines: int = 0
    mtime_ns: int = 0


@dataclass
class CoverageLine:
    lang: str
    files: int
    lines: int
    adapter: str
    variants: list[str]


@dataclass
class InventoryResult:
    root: str
    entries: list[InventoryEntry]
    include_paths: list[str]
    unknown_groups: dict[str, list[str]]
    ignored_count: int
    binary_count: int
    problems: list[WalkProblem]
    coverage: dict[str, CoverageLine] = field(default_factory=dict)
    includes: dict[str, list[str]] = field(default_factory=dict)  # file -> included files (resolved)

    def entry(self, path: str) -> InventoryEntry | None:
        for e in self.entries:
            if e.path == path:
                return e
        return None

    def source_files(self) -> list[InventoryEntry]:
        return [e for e in self.entries if e.status == "source"]


def _resolve_include(includer: str, target: str, by_suffix: dict[str, list[str]], files: set[str]) -> list[str]:
    target = target.replace("\\", "/").strip()
    local = posixpath.normpath(posixpath.join(posixpath.dirname(includer), target))
    if local in files:
        return [local]
    return by_suffix.get(posixpath.basename(target), []) if "/" not in target else [
        f for f in by_suffix.get(posixpath.basename(target), []) if f == target or f.endswith("/" + target)
    ]


def run_inventory(root: Path | str, profile: AnalysisProfile | None = None,
                  table: ExtensionTable | None = None,
                  keyword_extensions: dict[str, str] | None = None) -> InventoryResult:
    """Detect the language of every file. ``keyword_extensions`` maps extensions of languages
    described by a keyword profile (§3.9) to their language name."""
    root = Path(root).resolve()
    table = table or load_table()
    profile = profile or AnalysisProfile()
    problems: list[WalkProblem] = []
    overrides = profile.file_overrides
    ignored_exts = {g.ext.lower(): g.reason for g in profile.ignored}
    keyword_langs = {lang: e.adapter for lang, e in profile.languages.items() if e.adapter.startswith("keywords:")}
    keyword_exts = {k.lower(): v for k, v in (keyword_extensions or {}).items()}

    entries: dict[str, InventoryEntry] = {}
    texts: dict[str, str] = {}
    pending: dict[str, list[str]] = {}  # ambiguous path -> candidates

    for wf in walk_repo(root, table.excluded_dirs, profile.exclude_dirs, problems):
        rel, name = wf.rel, wf.rel.rsplit("/", 1)[-1]
        ext = file_ext(name)
        lext = ext.lower()
        base = InventoryEntry(rel, None, None, 1.0, "", "unknown", wf.size, 0, wf.mtime_ns)
        if name in table.ignored_names or lext in ignored_exts:
            base.status, base.decided_by = "ignored", ("profile" if lext in ignored_exts else "name")
            entries[rel] = base
            continue
        if lext in table.ignored_exts and not any(fnmatch.fnmatchcase(rel, o.glob) for o in overrides):
            base.status, base.decided_by = "ignored", "extension"
            entries[rel] = base
            continue
        try:
            with wf.abs.open("rb") as handle:
                data = handle.read() if wf.size <= MAX_READ_BYTES else handle.read(MAX_READ_BYTES)
        except OSError as exc:
            problems.append(WalkProblem(rel, f"unreadable: {exc}"))
            continue
        if is_binary(data[:8192]):
            base.status, base.decided_by = "binary", "content:nul_bytes"
            entries[rel] = base
            continue
        text = decode_text(data)
        base.lines = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
        entry = base
        forced = next((o for o in overrides if fnmatch.fnmatchcase(rel, o.glob)), None)
        if forced is not None:
            entry.lang, entry.decided_by, entry.status = forced.language, f"override:{forced.glob}", "source"
            entry.variant = forced.variant
            if forced.language == "fortran" and not entry.variant:
                base_form = table.lang_by_ext.get(lext, ("", None))[1]
                entry.variant = fortran_variant(base_form, ext, text)
        elif ext in table.exact:
            entry.lang, entry.decided_by, entry.status = table.exact[ext], f"extension:{ext}", "source"
        elif lext in table.lang_by_ext:
            lang, variant = table.lang_by_ext[lext]
            entry.lang, entry.decided_by, entry.status = lang, f"extension:{lext}", "source"
            if lang == "fortran":
                entry.variant = fortran_variant(variant, ext, text)
            elif lang == "python":
                entry.variant = python_variant(text)
        elif lext in table.ambiguous:
            pending[rel] = table.ambiguous[lext]
        elif lext in table.not_covered:
            entry.lang, entry.decided_by, entry.status = table.not_covered[lext], f"extension:{lext}", "not_covered"
        elif lext in keyword_exts:
            entry.lang, entry.decided_by, entry.status = keyword_exts[lext], f"extension:{lext}", "source"
        elif not ext:
            det_lang, conf, rule = detect_by_content(table, text)
            if det_lang:
                entry.lang, entry.confidence, entry.decided_by = det_lang, conf, rule
                entry.status = "source" if det_lang in table.adapters else "not_covered"
                if det_lang == "python":
                    entry.variant = python_variant(text)
                elif det_lang == "fortran":
                    entry.variant = fortran_variant(None, ext, text)
            else:
                entry.decided_by = rule
        else:
            entry.decided_by = "extension:unknown"
        entries[rel] = entry
        if entry.lang in ("c", "cpp", "fortran") or rel in pending:
            texts[rel] = text

    # Repository context: who includes whom.
    files = set(entries)
    by_suffix: dict[str, list[str]] = defaultdict(list)
    for path in sorted(files):
        by_suffix[posixpath.basename(path)].append(path)
    includes: dict[str, list[str]] = {}
    included_by: dict[str, set[str]] = defaultdict(set)
    for path, text in sorted(texts.items()):
        targets = _C_INCLUDE.findall(text)
        if entries[path].lang == "fortran" or path in pending:
            targets += _F_INCLUDE.findall(text)
        resolved = sorted({r for t in targets for r in _resolve_include(path, t, by_suffix, files)} - {path})
        if resolved:
            includes[path] = resolved
            for r in resolved:
                included_by[r].add(path)

    # Decide ambiguous files; iterate so that a header included by a C++ header becomes C++.
    for _ in range(10):
        changed = False
        for path, candidates in sorted(pending.items()):
            entry = entries[path]
            includer_langs = {entries[i].lang for i in included_by.get(path, ())}
            text = texts.get(path, "")
            new: tuple[str | None, str, str | None, float]
            if "cpp" in candidates:
                if "cpp" in includer_langs:
                    new = ("cpp", "context:included_by_cpp", None, 1.0)
                elif _CPP_HEADER_HINT.search(text):
                    new = ("cpp", "content:cpp_keywords", None, 0.9)
                elif "c" in includer_langs:
                    new = ("c", "context:included_by_c", None, 1.0)
                else:
                    new = ("c", "default:c", None, 0.7)
            else:  # fortran or other
                if "fortran" in includer_langs:
                    forms = {(entries[i].variant or "").split("+")[0] for i in included_by[path]
                             if entries[i].lang == "fortran"}
                    form = forms.pop() if len(forms) == 1 else None
                    new = ("fortran", "context:included_by_fortran",
                           fortran_variant(form, "", text).split("+")[0], 1.0)
                else:
                    det_lang, conf, rule = detect_by_content(table, text, ["fortran"])
                    if det_lang == "fortran":
                        new = ("fortran", rule, fortran_variant(None, "", text).split("+")[0], conf)
                    else:
                        new = (None, "context:unknown", None, 1.0)
            if (entry.lang, entry.decided_by) != (new[0], new[1]):
                entry.lang, entry.decided_by, entry.variant, entry.confidence = new
                entry.status = "source" if new[0] else "unknown"
                changed = True
        if not changed:
            break

    ordered = [entries[p] for p in sorted(entries)]
    unknown: dict[str, list[str]] = defaultdict(list)
    for e in ordered:
        if e.status == "unknown":
            unknown[file_ext(e.path.rsplit("/", 1)[-1]).lower() or "(none)"].append(e.path)
    include_dirs = sorted({posixpath.dirname(p) or "." for targets in includes.values() for p in targets})

    coverage: dict[str, CoverageLine] = {}
    for e in ordered:
        if e.status in ("source", "not_covered") and e.lang:
            line = coverage.setdefault(e.lang, CoverageLine(
                e.lang, 0, 0, table.adapters.get(e.lang) or keyword_langs.get(e.lang) or "none", []))
            line.files += 1
            line.lines += e.lines
            for part in (e.variant or "").split("+"):
                if part and part not in line.variants:
                    line.variants.append(part)
    for line in coverage.values():
        line.variants.sort()

    problems.sort(key=lambda p: (p.path, p.message))
    return InventoryResult(
        root=str(root), entries=ordered, include_paths=include_dirs,
        unknown_groups={k: v for k, v in sorted(unknown.items())},
        ignored_count=sum(1 for e in ordered if e.status == "ignored"),
        binary_count=sum(1 for e in ordered if e.status == "binary"),
        problems=problems, coverage=dict(sorted(coverage.items())), includes=includes,
    )
