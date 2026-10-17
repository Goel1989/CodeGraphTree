"""Phase 5 of the requirements plan: declared bridge mechanisms and persisted evidence.

Every cross-language link records the bridge, its version, the mechanism that matched, the binding declaration
when there is one, and how the candidate was selected. Ambiguous targets keep their candidates instead of one
being picked by name.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from tests.helpers import scan_fixture

from codegraph_sci.core.bridge_catalog import MECHANISMS, NATIVE_BRIDGES
from codegraph_sci.store.export import export_dict


def _sites(db: Path) -> dict[str, dict[str, Any]]:
    return {s["target_text"]: s for s in export_dict(db)["call_sites"]}


def test_catalog_declares_every_native_bridge() -> None:
    assert [b.id for b in NATIVE_BRIDGES] == ["pybind11", "python_extension", "c_cpp", "fortran_c"]
    for bridge in NATIVE_BRIDGES:
        assert bridge.version and bridge.source_languages and bridge.target_languages
        assert bridge.matching and bridge.transform and bridge.constraints
        assert bridge.candidates in ("unique", "keep_ambiguous")
        assert all(m in MECHANISMS for m in bridge.mechanisms)
    assert {m.evidence for m in MECHANISMS.values()} == {"binding_declaration", "naming_convention", "rule"}


def test_fortran_c_links_expose_their_mechanism(tmp_path: Path) -> None:
    result = scan_fixture("bridge_fortran_c", tmp_path / "proj")
    sites = _sites(result.db_path)
    expected = {
        "fort_exported": ("bind_c_name", "binding_declaration", "f:exported"),
        "compute_": ("trailing_underscore", "naming_convention", None),
        "COMPUTE2": ("uppercase_name", "naming_convention", None),
        "legacy_double__": ("g77_double_underscore", "naming_convention", None),
        "c_callback": ("trailing_underscore", "naming_convention", None),
        "c_named": ("bind_c_name", "binding_declaration", 'BIND(C, NAME="c_named_impl") in f:compute'),
    }
    for target, (mechanism, kind, binding) in expected.items():
        evidence = sites[target]["evidence"]
        assert evidence["rule"] == "bridge:fortran_c" and evidence["rule_version"] == "1.0", target
        assert (evidence["mechanism"], evidence["evidence_kind"], evidence.get("binding")) == (
            mechanism, kind, binding), target
        assert evidence["candidate_selection"] == "unique" and evidence["reason"], target


def test_python_binding_links_name_their_declaration(tmp_path: Path) -> None:
    result = scan_fixture("bridge_pybind11", tmp_path / "proj")
    bridged = [s for s in export_dict(result.db_path)["call_sites"] if s["origin"] == "bridge:pybind11"]
    assert bridged
    for site in bridged:
        evidence = site["evidence"]
        assert evidence["mechanism"] in ("pybind11_def", "pybind11_module")
        assert evidence["evidence_kind"] == "binding_declaration"
        assert str(evidence["binding"]).startswith("bind:pybind11:")


def test_query_exposes_extraction_and_resolution_evidence(tmp_path: Path) -> None:
    from codegraph_sci.query.api import GraphQuery

    result = scan_fixture("bridge_fortran_c", tmp_path / "proj")
    with GraphQuery(result.db_path) as q:
        [item] = [i for i in q.callees("c:c_named_impl").items]
        [site] = item.sites
        assert site.evidence["extraction"].startswith("native:c@")
        assert site.evidence["resolution_rule"] == "bridge:fortran_c"
        assert site.evidence["mechanism"] == "bind_c_name" and site.evidence["binding"] == "f:exported"
        native = [s for i in q.callees("f:compute").items for s in i.sites]
        assert all(s.evidence["extraction"].startswith("native:fortran@") for s in native)


def test_native_resolutions_get_a_derived_reason(tmp_path: Path) -> None:
    from codegraph_sci.query.api import GraphQuery

    result = scan_fixture("fortran_basic", tmp_path / "proj")
    with GraphQuery(result.db_path) as q:
        sites = [s for name in ("main",) for n in q.resolve(name) for i in q.callees(n.uid).items for s in i.sites]
    assert sites
    for site in sites:
        assert site.evidence["resolution_rule"] == "native:fortran"
        assert site.evidence["reason"] and site.evidence["candidate_selection"]


def _write(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _scan(root: Path, folder: Path, rules: list[dict[str, Any]], native: bool = True) -> Path:
    from codegraph_sci.core.project import open_project
    from codegraph_sci.scan import ScanOptions, scan

    return scan(open_project(root, folder), ScanOptions(jobs=1, bridge_rules=rules, native_bridges=native)).db_path


OVERLOADS = {
    "main.c": "void run(void) { CPP_SOLVE(); }\n",
    "solve.cpp": "void solve(int n) {}\nvoid solve(double x) {}\n",
}


def test_rule_keeps_ambiguous_candidates_instead_of_picking_one(tmp_path: Path) -> None:
    root = _write(tmp_path / "repo", OVERLOADS)
    rule = {"from": "c", "to": "cpp", "call_prefixes": ["CPP_"], "name_transform": ["strip_prefix", "lowercase"],
            "id": "r1", "version": "1.2"}
    site = _sites(_scan(root, tmp_path / "a", [rule]))["CPP_SOLVE"]
    assert (site["resolution"], site["dst"]) == ("ambiguous", None)
    assert site["candidates"] == ["cpp:solve(double)", "cpp:solve(int)"]
    assert site["evidence"]["candidate_selection"] == "keep_ambiguous"
    assert site["evidence"]["rule"] == "bridge:prefix_calls@r1" and site["evidence"]["rule_version"] == "1.2"
    unique = _sites(_scan(root, tmp_path / "b", [{**rule, "candidates": "unique"}]))["CPP_SOLVE"]
    assert (unique["resolution"], unique["dst"], unique["candidates"]) == ("unresolved", None, [])


def test_rule_requiring_a_declaration_links_only_declared_names(tmp_path: Path) -> None:
    root = _write(tmp_path / "repo", {
        "main.c": "DECLARE_F(solve)\nvoid run(void) { CALL_SOLVE(); CALL_OTHER(); }\n",
        "f.f90": "subroutine solve\nend subroutine solve\nsubroutine other\nend subroutine other\n",
    })
    rule = {"from": "c", "to": "fortran", "call_prefixes": ["CALL_"], "name_transform": ["strip_prefix", "lowercase"],
            "declaration_patterns": [r"DECLARE_F\((?P<name>\w+)"], "require_declaration": True}
    sites = _sites(_scan(root, tmp_path / "proj", [rule]))
    assert sites["CALL_SOLVE"]["dst"] == "f:solve"
    assert sites["CALL_SOLVE"]["evidence"]["binding"] == "bind:decl:solve@main.c"
    assert sites["CALL_SOLVE"]["evidence"]["evidence_kind"] == "binding_declaration"
    assert sites["CALL_OTHER"]["resolution"] == "unresolved"  # a similar name alone is not enough
    loose = _sites(_scan(root, tmp_path / "loose", [{k: v for k, v in rule.items() if k != "require_declaration"}]))
    assert loose["CALL_OTHER"]["dst"] == "f:other"
    assert loose["CALL_OTHER"]["evidence"]["mechanism"] == "prefix_call"


def test_rule_file_and_target_constraints(tmp_path: Path) -> None:
    root = _write(tmp_path / "repo", {
        "legacy/a.c": "void a(void) { CALL_SOLVE(); }\n",
        "modern/b.c": "void b(void) { CALL_SOLVE(); }\n",
        "f/solve.f90": "subroutine solve\nend subroutine solve\n",
    })
    rule = {"from": "c", "to": "fortran", "call_prefixes": ["CALL_"], "name_transform": ["strip_prefix", "lowercase"],
            "files": ["legacy/*"]}
    by_file = {s["file"]: s for s in export_dict(_scan(root, tmp_path / "a", [rule]))["call_sites"]}
    assert by_file["legacy/a.c"]["dst"] == "f:solve" and by_file["modern/b.c"]["dst"] is None
    blocked = {**rule, "files": ["*"], "target_files": ["lib/*"]}
    by_file = {s["file"]: s for s in export_dict(_scan(root, tmp_path / "b", [blocked]))["call_sites"]}
    assert by_file["legacy/a.c"]["dst"] is None


def test_bridge_rules_are_recorded_with_their_version(tmp_path: Path) -> None:
    from codegraph_sci.query.api import GraphQuery

    root = _write(tmp_path / "repo", OVERLOADS)
    rule = {"from": "c", "to": "cpp", "call_prefixes": ["CPP_"], "id": "r1", "version": "1.2"}
    db = _scan(root, tmp_path / "proj", [rule])
    plugins = {(p["name"], p["type"], p["version"]) for p in export_dict(db)["plugins"]}
    assert {("r1", "bridge_rule", "1.2"), ("fortran_c", "bridge", "1.0"), ("pybind11", "bridge", "1.0")} <= plugins
    with GraphQuery(db) as q:
        assert {b["id"] for b in q.bridges()} >= {"fortran_c", "c_cpp", "pybind11", "python_extension"}


@pytest.mark.parametrize(("key", "value", "message"), [
    ("candidates", "first", "candidates"),
    ("require_declaration", True, "declaration_patterns"),
    ("mechanism", "", "mechanism"),
])
def test_new_bridge_keys_are_validated(tmp_path: Path, key: str, value: Any, message: str) -> None:
    import yaml

    from codegraph_sci.enrich.packs import PackError, load_bridge_file

    path = tmp_path / "b.yaml"
    path.write_text(yaml.safe_dump({"bridge_format": 1, "name": "b", "version": "1.0", "tests": [],
                                    "rule": {"from": "c", "to": "fortran", "call_prefixes": ["X_"], key: value}}),
                    encoding="utf-8")
    with pytest.raises(PackError, match=message):
        load_bridge_file(path)


def test_evidence_is_deterministic(tmp_path: Path) -> None:
    first = scan_fixture("bridge_fortran_c", tmp_path / "one")
    second = scan_fixture("bridge_fortran_c", tmp_path / "two")
    a, b = export_dict(first.db_path), export_dict(second.db_path)
    assert json.dumps(a["call_sites"], sort_keys=True) == json.dumps(b["call_sites"], sort_keys=True)


def test_cli_callees_shows_the_mechanism(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    result = scan_fixture("bridge_fortran_c", tmp_path / "proj")
    try:
        assert main(["callees", "c:c_named_impl", "--db", str(result.db_path)]) == 0
        assert "via bind_c_name (f:exported)" in capsys.readouterr().out
        assert main(["callees", "c:c_named_impl", "--db", str(result.db_path), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["items"][0]["sites"][0]["evidence"]["mechanism"] == "bind_c_name"
    finally:
        netguard.uninstall()
