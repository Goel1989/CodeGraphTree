"""Phase 7 of the requirements plan: searchable, filterable dependency tables.

Every relationship (call, import, include, inheritance, bridge, binding) is a row with its caller, target or
candidates, files and languages, type, position, status, rule and condition. Filtering, sorting and paging are done
by SQLite; entity, file and directory views aggregate the rows and keep their occurrences reachable; a filtered table
is exported and every row leads to its source evidence.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

import pytest
from tests.helpers import scan_fixture

from codegraph_sci.query.api import GraphQuery, QueryError
from codegraph_sci.query.types import DependencyFilter


@pytest.fixture(scope="module")
def hybrid(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return scan_fixture("mini_hybrid", tmp_path_factory.mktemp("deps") / "proj",
                        expected_file="expected_graph_bridges.json").db_path


def test_every_relationship_is_a_row_with_its_meaning(hybrid: Path) -> None:
    with GraphQuery(hybrid) as q:
        page = q.dependencies(limit=100)
        assert page.total == len(page.rows) == 9
        kinds = sorted(r.relationship for r in page.rows)
        assert kinds == ["binding", "binding", "binding_declaration", "bridge", "bridge", "call", "call", "include",
                         "include"]
        declaration = next(r for r in page.rows if r.relationship == "binding_declaration")  # m.def in pybind11
        assert (declaration.caller, declaration.target) == ("bind:pybind11:hybrid_ext.solve", "cpp:hybrid::solve(int)")
        include = next(r for r in page.rows if r.relationship == "include" and r.caller_file == "csrc/solver.c")
        assert (include.target_text, include.target_file, include.caller_lang) == (
            "solver_api.h", "csrc/solver_api.h", "c")
        bridge = next(r for r in page.rows if r.rule == "bridge:fortran_c")
        assert bridge.target_lang == "fortran" and bridge.caller_lang == "c" and bridge.resolution == "resolved"
        assert bridge.target == "f:kernel" and bridge.line > 0 and bridge.col > 0


def test_filters_sorting_and_paging_are_consistent(hybrid: Path) -> None:
    with GraphQuery(hybrid) as q:
        everything = q.dependencies(limit=100).rows
        by_path = [(r.caller_file, r.line, r.col) for r in everything]
        assert by_path == sorted(by_path)  # default order: path, line, column
        assert [r.site_id for r in q.dependencies(limit=3, offset=0).rows] + \
            [r.site_id for r in q.dependencies(limit=3, offset=3).rows] + \
            [r.site_id for r in q.dependencies(limit=3, offset=6).rows] == [r.site_id for r in everything]
        only = q.dependencies(DependencyFilter(relationships=("bridge", "binding")), limit=100)
        assert only.total == 4 and {r.relationship for r in only.rows} == {"bridge", "binding"}
        c_rows = q.dependencies(DependencyFilter(language="c"), limit=100).rows
        assert c_rows and all(r.caller_lang == "c" for r in c_rows)
        text = q.dependencies(DependencyFilter(text="kernel"), limit=100).rows
        assert text and all("kernel" in (r.caller + r.target_text + (r.target or "") + (r.caller_file or "")).lower()
                            for r in text)
        under = q.dependencies(DependencyFilter(path="csrc/"), limit=100).rows
        assert under and all(r.caller_file.startswith("csrc/") for r in under)
        resolved = q.dependencies(DependencyFilter(statuses=("resolved",)), limit=100)
        assert resolved.total == sum(1 for r in everything if r.resolution == "resolved")
        for key in ("caller", "target", "relationship", "status", "language", "line"):
            rows = q.dependencies(sort=key, limit=100).rows
            assert len(rows) == 9, key
        desc = q.dependencies(sort="relationship", descending=True, limit=100).rows
        assert [r.relationship for r in desc] == sorted((r.relationship for r in desc), reverse=True)
        with pytest.raises(QueryError):
            q.dependencies(sort="drop table")


def test_aggregated_views_keep_their_occurrences(hybrid: Path) -> None:
    with GraphQuery(hybrid) as q:
        total = q.dependencies(limit=1000).total
        for level in ("entity", "file", "directory"):
            groups = q.dependency_groups(level, limit=1000)
            assert sum(g.count for g in groups.rows) == total, level
            for g in groups.rows:
                occurrences = q.dependencies(g.occurrences, limit=1000)
                assert occurrences.total == g.count, (level, g)
                assert all(r.relationship == g.relationship for r in occurrences.rows)
                assert sum(g.statuses.values()) == g.count
        files = q.dependency_groups("file", DependencyFilter(relationships=("include",)), limit=100).rows
        assert {(g.source, g.target) for g in files} == {("csrc/solver.c", "csrc/solver_api.h"),
                                                         ("ext/bindings.cpp", "csrc/solver_api.h")}
        dirs = q.dependency_groups("directory", limit=100).rows
        assert ("app", "ext", "binding") in {(g.source, g.target, g.relationship) for g in dirs}


def test_rows_lead_to_their_source_evidence(hybrid: Path) -> None:
    with GraphQuery(hybrid) as q:
        for row in q.dependencies(limit=100).rows:
            evidence = q.dependency_evidence(row)
            assert evidence.excerpt.path == row.caller_file
            line = evidence.excerpt.lines[row.line - evidence.excerpt.start]
            assert row.target_text.split(".")[-1].split("::")[-1] in line, (row, line)
            assert evidence.evidence["resolution_rule"] == row.rule
            assert evidence.evidence["extraction"]


def test_binding_declarations_are_rows(tmp_path: Path) -> None:
    db = scan_fixture("bridge_prefix_negative", tmp_path / "proj").db_path
    with GraphQuery(db) as q:
        rows = q.dependencies(DependencyFilter(relationships=("binding_declaration",)), limit=100).rows
        assert {(r.caller, r.target) for r in rows} == {("bind:decl:assemble@cpp/calls.cpp", "f:assemble"),
                                                       ("bind:decl:solve@cpp/calls.cpp", "f:solve")}
        for row in rows:
            assert row.site_id is None and row.line > 0
            assert q.dependency_evidence(row).excerpt.path == "cpp/calls.cpp"


def test_ambiguous_rows_list_their_candidates(tmp_path: Path) -> None:
    db = scan_fixture("cpp_overloads", tmp_path / "proj").db_path
    with GraphQuery(db) as q:
        rows = q.dependencies(DependencyFilter(statuses=("ambiguous",)), limit=100).rows
        assert all(r.target is None and len(r.candidates) >= 2 for r in rows)


def test_cli_exports_a_filtered_table(hybrid: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    out = tmp_path / "deps.csv"
    try:
        assert main(["deps", "--db", str(hybrid), "--relationship", "include", "--relationship", "bridge",
                     "--format", "csv", "-o", str(out)]) == 0
        rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8"))))
        assert len(rows) == 4 and {r["relationship"] for r in rows} == {"include", "bridge"}
        assert {"caller", "caller_file", "caller_lang", "target_text", "target", "candidates", "target_file",
                "target_lang", "relationship", "line", "col", "resolution", "confidence", "rule",
                "condition"} <= set(rows[0])
        assert main(["deps", "--db", str(hybrid), "--level", "file", "--format", "json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert data["level"] == "file" and sum(g["count"] for g in data["rows"]) == 9
        assert main(["deps", "--db", str(hybrid), "--text", "kernel"]) == 0
        assert "kernel" in capsys.readouterr().out
    finally:
        netguard.uninstall()
