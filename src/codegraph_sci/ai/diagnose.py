"""What the analysis does not cover yet, and why (requirements plan phase 9). Deterministic: no model involved.

Six cases, each with the files concerned:

* ``unknown_language``: files whose language the inventory could not identify;
* ``missing_package``: a known language without an installed language package (``.jl``, ``.rs``…);
* ``unsupported_dialect``: a dialect (inventory variant) the language package does not declare;
* ``partial_coverage``: files read with a fallback extractor, or a keyword package without measured tests;
* ``parser_failures``: files whose extraction failed or exceeded its deadline, repeatedly for one language;
* ``unsupported_binding``: unresolved calls with a common prefix, the sign of a cross-language mechanism
  that no bridge describes.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from codegraph_sci.core.project import Project
from codegraph_sci.inventory.profile_io import load_profile
from codegraph_sci.query.api import GraphQuery

KINDS = ("unknown_language", "missing_package", "unsupported_dialect", "partial_coverage", "parser_failures",
         "unsupported_binding")
MIN_FAILURES = 2  # "repeated" parser failures
MIN_FALLBACK_SHARE = 0.10
MIN_BINDING_SITES = 3


@dataclass
class Diagnosis:
    kind: str
    target: str  # extension, language, or call pattern
    count: int
    examples: list[str] = field(default_factory=list)
    detail: str = ""


def diagnose(project: Project) -> list[Diagnosis]:
    from codegraph_sci.inventory.run import run_inventory
    from codegraph_sci.scan import language_hints, language_registry

    profile = load_profile(project.profile_path)
    registry = language_registry(project, profile)
    inventory = run_inventory(project.root, profile, hints=language_hints(registry))
    out: list[Diagnosis] = []
    for ext, paths in inventory.unknown_groups.items():
        out.append(Diagnosis("unknown_language", ext, len(paths), paths[:5], "extension not identified"))
    missing: dict[str, list[str]] = defaultdict(list)
    dialects: dict[tuple[str, str], list[str]] = defaultdict(list)
    for entry in inventory.entries:
        if entry.status == "not_covered" and entry.lang:
            missing[entry.lang].append(entry.path)
        elif entry.status == "source" and entry.lang in registry.packages and entry.variant:
            declared = set(registry.packages[entry.lang].dialects)
            for part in entry.variant.split("+"):
                if declared and part not in declared:
                    dialects[(entry.lang, part)].append(entry.path)
    for lang, paths in sorted(missing.items()):
        out.append(Diagnosis("missing_package", lang, len(paths), paths[:5],
                             "known language without an installed language package"))
    for (lang, dialect), paths in sorted(dialects.items()):
        out.append(Diagnosis("unsupported_dialect", f"{lang}:{dialect}", len(paths), paths[:5],
                             f"dialect not declared by the {lang} package"))
    for package in registry.packages.values():
        if package.backend == "keywords" and not package.tests:
            out.append(Diagnosis("partial_coverage", package.language, 0, [],
                                 "keyword package without test cases: coverage not measured"))
    if project.db_path.is_file():
        out += _from_database(project)
    return sorted(out, key=lambda d: (KINDS.index(d.kind), d.target))


def _from_database(project: Project) -> list[Diagnosis]:
    out: list[Diagnosis] = []
    with GraphQuery(project.db_path) as q:
        by_lang: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        for path, lang, status in q.con.execute("SELECT path, lang, parse_status FROM files ORDER BY path"):
            by_lang[lang or "-"][status].append(path)
        for lang, statuses in sorted(by_lang.items()):
            total = sum(len(v) for v in statuses.values())
            fallback = statuses.get("fallback", [])
            if fallback and len(fallback) / total >= MIN_FALLBACK_SHARE:
                out.append(Diagnosis("partial_coverage", lang, len(fallback), fallback[:5],
                                     f"{len(fallback)} of {total} file(s) read by the fallback extractor"))
            failed = statuses.get("failed", []) + statuses.get("timeout", [])
            if len(failed) >= MIN_FAILURES:
                out.append(Diagnosis("parser_failures", lang, len(failed), sorted(failed)[:5],
                                     f"{len(failed)} file(s) failed or exceeded their deadline"))
        for group in q.unresolved(limit=200):
            if group.pattern.endswith("_*") and group.count >= MIN_BINDING_SITES:
                examples: list[Any] = [f"{e['file']}:{e['line']}" for e in group.examples]
                out.append(Diagnosis("unsupported_binding", f"{group.lang}:{group.pattern}", group.count, examples,
                                     "unresolved calls sharing a prefix: a cross-language mechanism without bridge"))
    return out
