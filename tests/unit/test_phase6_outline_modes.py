"""Phase 6 of the requirements plan: FULL and OUTLINE are distinct extraction modes in every adapter.

The mode is chosen before the files are scheduled and is part of the cache identity. In OUTLINE an adapter
extracts definitions and the context needed to resolve symbols, and never extracts the calls inside bodies: the
call extraction code is not even run. Definitions are identical in both modes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from tests.helpers import FIXTURES

from codegraph_sci.core.facts import FileFacts, SourceFile, decode_facts
from codegraph_sci.core.plugins import ExtractContext, decode_bytes
from codegraph_sci.extract.registry import adapters_from_specs, builtin_packages

CALL_KINDS = {"call", "maybe_call", "dynamic_call"}
FIXTURES_BY_LANGUAGE = {
    "python": ["python_basic", "mini_hybrid", "bridge_pybind11"],
    "c": ["c_basic", "bridge_fortran_c", "mini_hybrid"],
    "cpp": ["cpp_basic", "cpp_overloads", "bridge_pybind11", "mini_hybrid"],
    "fortran": ["fortran_basic", "fortran_advanced", "mini_hybrid"],
}


def _extract(language: str, adapter: Any, root: Path, path: str, variant: str | None, outline: bool) -> FileFacts:
    from codegraph_sci.extract.context import make_include_resolver

    text, encoding = decode_bytes((root / path).read_bytes())
    ctx = ExtractContext(outline=outline, resolve_include=make_include_resolver(root, []))
    return adapter.extract(SourceFile(path, language, variant, encoding, text), ctx)


def _cases() -> list[tuple[str, str]]:
    return [(lang, name) for lang, names in FIXTURES_BY_LANGUAGE.items() for name in names]


@pytest.mark.parametrize(("language", "fixture"), _cases())
def test_outline_adapters_extract_no_call_and_the_same_definitions(language: str, fixture: str) -> None:
    from codegraph_sci.inventory.run import run_inventory

    adapter = adapters_from_specs([p.spec() for p in builtin_packages() if p.language == language])[language]
    root = FIXTURES / fixture / "src"
    files = [e for e in run_inventory(root).source_files() if e.lang == language]
    assert files, fixture
    for entry in files:
        full = _extract(language, adapter, root, entry.path, entry.variant, False)
        outline = _extract(language, adapter, root, entry.path, entry.variant, True)
        assert outline.definitions == full.definitions, entry.path
        assert outline.includes == full.includes, entry.path
        # The adapter itself skipped the calls: nothing to trim afterwards.
        assert not [r for r in outline.references if r.kind in CALL_KINDS], entry.path


def test_keyword_adapter_outline() -> None:
    from codegraph_sci.extract.registry import load_registry

    profile = FIXTURES / "keywords_language" / "profile" / "acme_script.yaml"
    adapter = load_registry(explicit=[profile]).adapters()["acme_script"]
    root = FIXTURES / "keywords_language" / "src"
    for path in ("scripts/main.acs", "scripts/helpers.acs"):
        full = _extract("acme_script", adapter, root, path, None, False)
        outline = _extract("acme_script", adapter, root, path, None, True)
        assert outline.definitions == full.definitions
        assert any(r.kind in CALL_KINDS for r in full.references)
        assert not [r for r in outline.references if r.kind in CALL_KINDS]


def test_python_and_c_family_never_run_their_call_extraction_in_outline(monkeypatch: pytest.MonkeyPatch) -> None:
    import codegraph_sci.extract.cfamily as cfamily
    import codegraph_sci.extract.python as python

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("call extraction ran in OUTLINE mode")

    monkeypatch.setattr(python._AstExtractor, "call", refuse)
    monkeypatch.setattr(cfamily.CFamilyExtractor, "call", refuse)
    adapters = adapters_from_specs([p.spec() for p in builtin_packages()])
    for language, fixture, path in (("python", "python_basic", None), ("cpp", "cpp_basic", None),
                                    ("c", "c_basic", None)):
        root = FIXTURES / fixture / "src"
        for file in sorted(root.rglob("*")):
            if file.suffix in (".py", ".cpp", ".c", ".h", ".hpp"):
                rel = path or file.relative_to(root).as_posix()
                lang = "cpp" if file.suffix in (".hpp", ".h") and language == "cpp" else language
                _extract(lang, adapters[lang], root, rel, None, True)


def test_python_fallback_outline_extracts_no_call() -> None:
    from codegraph_sci.extract.python.fallback import extract_tree_sitter

    text = "def f():\n    print 'old'\n    g()\n\ndef g():\n    pass\n"  # Python 2: the ast module fails
    full = extract_tree_sitter("a.py", text, "utf-8", "a")
    outline = extract_tree_sitter("a.py", text, "utf-8", "a", outline=True)
    assert outline.definitions == full.definitions and full.references
    assert not [r for r in outline.references if r.kind in CALL_KINDS]


# ----------------------------------------------------------------- acceptance, every native language
REPO: dict[str, str] = {
    "app/main.py": "from lib.helpers import tidy\n\n\ndef run():\n    tidy()\n",
    "lib/__init__.py": "",
    "lib/helpers.py": "def tidy():\n    clean()\n\n\ndef clean():\n    pass\n",
    "app/main.c": "void tidy_c(void);\nvoid run_c(void) { tidy_c(); }\n",
    "lib/helpers.c": "void clean_c(void) {}\nvoid tidy_c(void) { clean_c(); }\n",
    "app/main.cpp": "namespace lib { void tidy_cpp(); }\nvoid run_cpp() { lib::tidy_cpp(); }\n",
    "lib/helpers.cpp": "namespace lib {\nvoid clean_cpp() {}\nvoid tidy_cpp() { clean_cpp(); }\n}\n",
}
CALLERS = {"py:app.main.run": "py:lib.helpers.tidy", "c:run_c": "c:tidy_c", "cpp:run_cpp()": "cpp:lib::tidy_cpp()"}
INNER = {"py:lib.helpers.tidy": "py:lib.helpers.clean", "c:tidy_c": "c:clean_c",
         "cpp:lib::tidy_cpp()": "cpp:lib::clean_cpp()"}


def _facts(db: Path) -> dict[str, FileFacts]:
    con = sqlite3.connect(db)
    try:
        rows = con.execute("SELECT f.path, c.facts FROM files f JOIN facts_cache c ON c.cache_key = f.cache_key")
        return {path: decode_facts(blob) for path, blob in rows}
    finally:
        con.close()


def _scan(repo: Path, proj: Path, include: list[str]) -> dict[str, Any]:
    from codegraph_sci.core.profile import Scope
    from codegraph_sci.core.project import open_project
    from codegraph_sci.inventory.profile_io import load_profile, profile_from_inventory, save_profile
    from codegraph_sci.inventory.run import run_inventory
    from codegraph_sci.scan import ScanOptions, scan

    project = open_project(repo, proj)
    profile = load_profile(project.profile_path) if project.profile_path.is_file() else profile_from_inventory(
        run_inventory(repo))
    profile.scope = Scope(include=include, exclude=[])
    proj.mkdir(parents=True, exist_ok=True)
    save_profile(project.profile_path, profile)
    return scan(project, ScanOptions(jobs=1)).stats


def test_in_scope_callers_reach_outline_definitions_then_full_when_moved_into_scope(tmp_path: Path) -> None:
    from codegraph_sci.query.api import GraphQuery

    repo, proj = tmp_path / "repo", tmp_path / "proj"
    for rel, text in REPO.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    stats = _scan(repo, proj, ["app/"])
    assert stats["files"]["outline_parsed"] == 4 and stats["files"]["full_parsed"] == 3
    facts = _facts(proj / "project.sqlite")
    for path in ("lib/helpers.py", "lib/helpers.c", "lib/helpers.cpp"):
        assert facts[path].extraction_mode == "outline" and facts[path].references == [], path
    with GraphQuery(proj / "project.sqlite") as q:
        for caller, target in CALLERS.items():
            [item] = q.callees(caller, hide_noise=False).items
            assert item.node.uid == target, caller
            assert [s.resolution for s in item.sites] == ["out_of_scope"], caller
        for definition in INNER:
            assert q.callees(definition, hide_noise=False).items == [], definition  # internals not extracted

    moved = _scan(repo, proj, ["app/", "lib/"])  # the OUTLINE facts are never reused for FULL
    assert moved["files_extracted"] == 4 and moved["files"]["full_parsed"] == 4
    facts = _facts(proj / "project.sqlite")
    assert all(facts[p].extraction_mode == "full" for p in ("lib/helpers.py", "lib/helpers.c", "lib/helpers.cpp"))
    with GraphQuery(proj / "project.sqlite") as q:
        for definition, inner in INNER.items():
            assert [i.node.uid for i in q.callees(definition, hide_noise=False).items] == [inner], definition

    back = _scan(repo, proj, ["app/"])  # and back: OUTLINE again, from a new extraction
    assert back["files_extracted"] == 4 and back["files"]["outline_parsed"] == 4


def test_cpp_local_class_inside_a_body_is_kept_in_outline() -> None:
    adapter = adapters_from_specs([p.spec() for p in builtin_packages() if p.language == "cpp"])["cpp"]
    text = "void outer() {\n  struct Local { void m() { helper(); } };\n  Local().m();\n}\nvoid helper() {}\n"
    full = adapter.extract(SourceFile("a.cpp", "cpp", None, "utf-8", text), ExtractContext())
    outline = adapter.extract(SourceFile("a.cpp", "cpp", None, "utf-8", text), ExtractContext(outline=True))
    assert outline.definitions == full.definitions
    assert any(r.kind in CALL_KINDS for r in full.references)
    assert not [r for r in outline.references if r.kind in CALL_KINDS]
