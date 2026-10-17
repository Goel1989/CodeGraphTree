"""``cgs inventory``: language of every file, include paths, coverage report (§3.2)."""

from __future__ import annotations

import fnmatch
import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from codegraph_sci.core.graph import InventoryIssue, InventoryItem
from codegraph_sci.core.profile import AnalysisProfile
from codegraph_sci.inventory.detect import (
    decode_text,
    detect_by_content,
    file_ext,
    fortran_variant,
    is_binary,
    python_variant,
    shebang_interpreter,
)
from codegraph_sci.inventory.table import ExtensionTable, load_table
from codegraph_sci.inventory.walk import (
    REASON_UNREADABLE,
    SkippedDir,
    WalkedEntry,
    WalkedFile,
    WalkProblem,
    walk_repo,
)

_C_INCLUDE = re.compile(r'(?m)^[ \t]*#[ \t]*include[ \t]*"([^"\n]+)"')
_F_INCLUDE = re.compile(r"""(?im)^[ \t]*include[ \t]*['"]([^'"\n]+)['"]""")
_CPP_HEADER_HINT = re.compile(r"(?m)^\s*(class\s+\w+|namespace\s+\w+|template\s*<)|\bstd::")
MAX_READ_BYTES = 64 * 1024 * 1024
POLICIES = ("analysis", "complete")  # inventory policies (requirements plan phase 2)
# Detection status of a read file -> (eligibility, reason when it is not analyzed).
_ELIGIBILITY = {"source": ("eligible", None), "not_covered": ("unsupported_language", "language not covered"),
                "unknown": ("not_source", "unknown language"), "binary": ("not_source", "binary content")}
_IGNORED_REASON = {"name": "ignored file name", "extension": "ignored extension", "profile": "ignored by the profile"}


@dataclass
class LanguageHints:
    """What installed language packages (other than the built-in ones) tell the inventory (phase 3)."""

    extensions: dict[str, str] = field(default_factory=dict)  # extension -> language
    filenames: dict[str, str] = field(default_factory=dict)  # exact file name -> language
    shebangs: dict[str, str] = field(default_factory=dict)  # interpreter -> language
    adapters: dict[str, str] = field(default_factory=dict)  # language -> adapter (coverage report)


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
    skipped_dirs: list[SkippedDir] = field(default_factory=list)  # left out of the walk, with the reason
    coverage: dict[str, CoverageLine] = field(default_factory=dict)
    includes: dict[str, list[str]] = field(default_factory=dict)  # file -> included files (resolved)
    policy: str = "analysis"  # analysis: exclusions respected; complete: excluded content recorded too
    items: list[InventoryItem] = field(default_factory=list)  # every discovered entry, sorted by path
    issues: list[InventoryIssue] = field(default_factory=list)  # discovery problems, sorted

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


def _includer_form(path: str, included_by: dict[str, set[str]], entries: dict[str, InventoryEntry]) -> str | None:
    """Source form (fixed/free) shared by every Fortran file including ``path``, if unique."""
    forms = {(entries[i].variant or "").split("+")[0] for i in included_by.get(path, ())
             if entries[i].lang == "fortran"}
    return forms.pop() if len(forms) == 1 else None


def _parent(path: str) -> str | None:
    if path == ".":
        return None
    return posixpath.dirname(path) or "."


def _entry_item(e: InventoryEntry, link_target: str | None) -> InventoryItem:
    reason: str | None
    if e.status == "ignored":
        eligibility, reason = "not_source", _IGNORED_REASON.get(e.decided_by, "ignored")
    else:
        eligibility, reason = _ELIGIBILITY[e.status]
    return InventoryItem(e.path, _parent(e.path), "file", file_ext(e.path.rsplit("/", 1)[-1]), e.size, None, e.lang,
                         e.variant, e.confidence, e.decided_by or None, eligibility,
                         "pending" if eligibility == "eligible" else "not_analyzed", reason, link_target)


def _walked_item(w: WalkedEntry, by_extension: dict[str, tuple[str, str]]) -> InventoryItem:
    item = InventoryItem(w.rel, _parent(w.rel), w.kind, "", w.size, w.files, eligibility=w.eligibility,
                         reason=w.reason, link_target=w.link_target)
    if w.kind == "directory":
        item.status = "walked" if w.walked else "not_walked"
    elif w.kind == "file":
        item.extension = file_ext(w.rel.rsplit("/", 1)[-1])
        if w.eligibility == "excluded":  # never read: the extension alone tells the language
            known = by_extension.get(item.extension) or by_extension.get(item.extension.lower())
            if known is not None:
                item.lang, item.evidence = known[0], f"extension:{known[1]}"
                item.confidence = 1.0
    return item


def _count_files(items: dict[str, InventoryItem]) -> None:
    """Files below each walked directory, including the counted content of folders that were not walked."""
    counts: dict[str, int] = defaultdict(int)
    for item in items.values():
        if item.kind == "file":
            n = 1
        elif item.kind == "directory" and item.status == "not_walked":
            n = item.files or 0
        else:
            continue
        parent = item.parent
        while parent is not None:
            counts[parent] += n
            parent = _parent(parent)
    for item in items.values():
        if item.kind == "directory" and item.status == "walked":
            item.files = counts.get(item.path, 0)


def run_inventory(root: Path | str, profile: AnalysisProfile | None = None,
                  table: ExtensionTable | None = None,
                  keyword_extensions: dict[str, str] | None = None,
                  hints: LanguageHints | None = None) -> InventoryResult:
    """Detect the language of every file. ``keyword_extensions`` maps extensions of languages
    described by a keyword profile (§3.9) to their language name; ``hints`` come from installed language
    packages: their extensions take precedence over "known but not covered", their file names over ignored names.

    Every discovered entry is also recorded in ``items`` with its analysis eligibility and the reason why it is not
    analyzed; the profile's ``inventory_policy: complete`` records the content of excluded folders as well."""
    root = Path(root).resolve()
    table = table or load_table()
    profile = profile or AnalysisProfile()
    problems: list[WalkProblem] = []
    skipped: list[SkippedDir] = []
    walked: list[WalkedEntry] = []
    unreadable: list[WalkedFile] = []
    links: dict[str, str] = {}
    overrides = profile.file_overrides
    ignored_exts = {g.ext.lower(): g.reason for g in profile.ignored}
    keyword_langs = {lang: e.adapter for lang, e in profile.languages.items() if e.adapter.startswith("keywords:")}
    hints = hints or LanguageHints()
    keyword_exts = {k.lower(): v for k, v in {**(keyword_extensions or {}), **hints.extensions}.items()}

    entries: dict[str, InventoryEntry] = {}
    texts: dict[str, str] = {}
    pending: dict[str, list[str]] = {}  # ambiguous path -> candidates

    for wf in walk_repo(root, table.excluded_dirs, profile.exclude_dirs, problems,
                        all_subfolders=profile.all_subfolders, skipped=skipped, entries=walked,
                        complete=profile.inventory_policy == "complete"):
        rel, name = wf.rel, wf.rel.rsplit("/", 1)[-1]
        if wf.link_target is not None:
            links[rel] = wf.link_target
        ext = file_ext(name)
        lext = ext.lower()
        base = InventoryEntry(rel, None, None, 1.0, "", "unknown", wf.size, 0, wf.mtime_ns)
        if (name in table.ignored_names and name not in hints.filenames) or lext in ignored_exts:
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
            unreadable.append(wf)
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
        elif name in hints.filenames:
            entry.lang, entry.decided_by, entry.status = hints.filenames[name], "package:filename", "source"
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
        elif lext in keyword_exts:
            entry.lang, entry.decided_by, entry.status = keyword_exts[lext], f"extension:{lext}", "source"
        elif lext in table.not_covered:
            entry.lang, entry.decided_by, entry.status = table.not_covered[lext], f"extension:{lext}", "not_covered"
        elif not ext and (interpreter := shebang_interpreter(text)) in hints.shebangs:
            entry.lang, entry.decided_by, entry.status = (hints.shebangs[str(interpreter)],
                                                          f"package:shebang:{interpreter}", "source")
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
    include_dir_set: set[str] = set()
    included_by: dict[str, set[str]] = defaultdict(set)
    for path, text in sorted(texts.items()):
        targets = _C_INCLUDE.findall(text)
        if entries[path].lang == "fortran" or path in pending:
            targets += _F_INCLUDE.findall(text)
        resolved_set: set[str] = set()
        for t in targets:
            target = t.replace("\\", "/").strip()
            for r in _resolve_include(path, target, by_suffix, files):
                if r == path:
                    continue
                resolved_set.add(r)
                # Include path = directory such that <dir>/<target as written> is the file.
                if r.endswith("/" + target) and posixpath.dirname(path) != posixpath.dirname(r):
                    include_dir_set.add(r[: -len(target) - 1] or ".")
                elif r == target:
                    include_dir_set.add(".")
                elif posixpath.dirname(path) != posixpath.dirname(r) or "/" not in target:
                    include_dir_set.add(posixpath.dirname(r) or ".")
        resolved = sorted(resolved_set)
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
            fortran_form = _includer_form(path, included_by, entries)
            if "cpp" in candidates and "fortran" in candidates and includer_langs == {"fortran"}:
                new = ("fortran", "context:included_by_fortran",
                       fortran_variant(fortran_form, "", text).split("+")[0], 1.0)
            elif "cpp" in candidates:
                if "cpp" in includer_langs:
                    new = ("cpp", "context:included_by_cpp", None, 1.0)
                elif _CPP_HEADER_HINT.search(text):
                    new = ("cpp", "content:cpp_keywords", None, 0.9)
                elif "c" in includer_langs:
                    new = ("c", "context:included_by_c", None, 1.0)
                else:
                    det, conf, rule = detect_by_content(table, text, candidates)
                    if det == "fortran" and not included_by.get(path):
                        new = ("fortran", rule, fortran_variant(None, "", text).split("+")[0], conf)
                    elif det == "cpp":
                        new = ("cpp", rule, None, conf)
                    else:
                        new = ("c", "default:c", None, 0.7)
            else:  # fortran or other
                if "fortran" in includer_langs:
                    new = ("fortran", "context:included_by_fortran",
                           fortran_variant(fortran_form, "", text).split("+")[0], 1.0)
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
    include_dirs = sorted(include_dir_set)

    coverage: dict[str, CoverageLine] = {}
    for e in ordered:
        if e.status in ("source", "not_covered") and e.lang:
            line = coverage.setdefault(e.lang, CoverageLine(
                e.lang, 0, 0, hints.adapters.get(e.lang) or table.adapters.get(e.lang) or keyword_langs.get(e.lang)
                or "none", []))
            line.files += 1
            line.lines += e.lines
            for part in (e.variant or "").split("+"):
                if part and part not in line.variants:
                    line.variants.append(part)
    for line in coverage.values():
        line.variants.sort()

    # Every discovered entry, with the reason why it is not analyzed.
    # Same precedence as the detection above; an ambiguous extension (decided from content) gives no language.
    by_extension: dict[str, tuple[str, str]] = {}
    for mapping in (table.not_covered, keyword_exts, {e: lv[0] for e, lv in table.lang_by_ext.items()}):
        by_extension.update({ext.lower(): (lang, ext.lower()) for ext, lang in mapping.items()})
    for ext in table.ambiguous:
        by_extension.pop(ext.lower(), None)
    by_extension.update({ext: (lang, ext) for ext, lang in table.exact.items()})
    items = {w.rel: _walked_item(w, by_extension) for w in walked}
    for e in ordered:
        items[e.path] = _entry_item(e, links.get(e.path))
    for wf in unreadable:
        items[wf.rel] = InventoryItem(wf.rel, _parent(wf.rel), "file", file_ext(wf.rel.rsplit("/", 1)[-1]), wf.size,
                                      eligibility="unreadable", reason=REASON_UNREADABLE, link_target=wf.link_target)
    _count_files(items)

    problems.sort(key=lambda p: (p.path, p.message))
    return InventoryResult(
        root=str(root), entries=ordered, include_paths=include_dirs,
        unknown_groups={k: v for k, v in sorted(unknown.items())},
        ignored_count=sum(1 for e in ordered if e.status == "ignored"),
        binary_count=sum(1 for e in ordered if e.status == "binary"),
        problems=problems, skipped_dirs=skipped, coverage=dict(sorted(coverage.items())), includes=includes,
        policy=profile.inventory_policy, items=[items[k] for k in sorted(items)],
        issues=sorted((InventoryIssue(pb.path, pb.kind, pb.message) for pb in problems),
                      key=lambda i: (i.path, i.kind, i.message)),
    )
