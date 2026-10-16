from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import pytest
from tests.helpers import FIXTURES, scan_fixture

from codegraph_sci.core.graph import (
    CallSiteRecord,
    EdgeRecord,
    FileRecord,
    GraphBundle,
    NodeRecord,
    NodeStatRecord,
)
from codegraph_sci.core.project import open_project
from codegraph_sci.query.api import GraphQuery, QueryError
from codegraph_sci.query.types import Direction, Level
from codegraph_sci.scan import ScanOptions, scan
from codegraph_sci.store.writer import write_full


@pytest.fixture()
def basic(tmp_path: Path) -> GraphQuery:
    result = scan_fixture("fortran_basic", tmp_path / "proj")
    return GraphQuery(result.db_path)


def test_callers_default_question(basic: GraphQuery) -> None:
    report = basic.callers("f:solve")
    assert report.count == 1 and report.file_count == 1 and report.site_count == 1
    item = report.items[0]
    assert item.node.uid == "f:main"
    assert [(s.file, s.line, s.col) for s in item.sites] == [("main.f90", 7, 8)]


def test_callees_hide_noise(basic: GraphQuery) -> None:
    hidden = basic.callees("f:norm2v")
    assert hidden.count == 0 and hidden.hidden_noise == 1
    shown = basic.callees("f:norm2v", hide_noise=False)
    assert [i.node.uid for i in shown.items] == ["ext:intrinsic:real"]


def test_find_and_node(basic: GraphQuery) -> None:
    assert [r.uid for r in basic.find("build")][0] == "f:mesh_mod::build_mesh"
    assert basic.find("refine")[0].uid == "f:mesh_mod::refine"
    assert [r.uid for r in basic.resolve("SOLVE")] == ["f:solve"]
    node = basic.node("f:main")
    assert node.fan_out == 2 and node.kind == "routine" and node.impact_size == 0
    assert basic.node("f:mesh_mod::refine").impact_size == 2
    with pytest.raises(QueryError):
        basic.node("f:nope")


def test_children_and_file_links(basic: GraphQuery) -> None:
    page = basic.children("f:main", direction=Direction.CALLEES)
    assert [i.uid for i in page.items] == ["f:mesh_mod::build_mesh", "f:solve"]
    assert page.items[1].has_children
    page = basic.children("f:main", direction=Direction.CALLEES, limit=1, offset=1)
    assert page.total == 2 and [i.uid for i in page.items] == ["f:solve"]
    files = basic.children("file:main.f90", direction=Direction.CALLEES, level=Level.FILE)
    assert sorted(i.file for i in files.items) == ["mesh_mod.f90", "solve.f90"]
    links = basic.file_links("file:solve.f90", direction=Direction.CALLERS)
    assert [(link.file, link.count) for link in links] == [("main.f90", 1)]
    dirs = basic.children(".", direction=Direction.CALLEES, level=Level.DIRECTORY)
    assert dirs.total == 0


def test_paths_and_impact(basic: GraphQuery) -> None:
    report = basic.paths("f:main", "f:mesh_mod::refine")
    assert [[s.uid for s in p.steps] for p in report.paths] == [
        ["f:main", "f:mesh_mod::build_mesh", "f:mesh_mod::refine"]]
    assert basic.paths("f:main", "f:mesh_mod::refine", max_len=1).paths == []
    impact = basic.impact("f:mesh_mod::refine")
    assert impact.total == 2 and impact.by_depth == {1: 1, 2: 1} and not impact.truncated
    assert impact.entry_points == ["f:main"]
    bounded = basic.impact("f:mesh_mod::refine", max_depth=1)
    assert bounded.total == 1 and bounded.truncated


def test_dispatch_steps_are_possible(tmp_path: Path) -> None:
    b = GraphBundle()
    b.files = [FileRecord("a.f90", "fortran")]
    b.nodes = [NodeRecord(u, u, "routine", None, "fortran", "a.f90", 1, 1) for u in ("f:a", "f:b", "f:c")]
    b.edges = [EdgeRecord("f:a", "f:b", "dispatches", 1, "heuristic", ["pack"], []),
               EdgeRecord("f:b", "f:c", "calls", 1, "exact", ["native:fortran"], [])]
    b.call_sites = [CallSiteRecord("f:b", "a.f90", 1, 1, "call", "c", "f:c", "resolved", "exact", "native:fortran")]
    b.node_stats = [NodeStatRecord(u) for u in ("f:a", "f:b", "f:c")]
    write_full(tmp_path / "d.sqlite", b)
    with GraphQuery(tmp_path / "d.sqlite") as q:
        steps = q.paths("f:a", "f:c").paths[0].steps
    assert [(s.uid, s.edge_kind, s.possible) for s in steps] == [
        ("f:a", None, False), ("f:b", "dispatches", True), ("f:c", "calls", False)]


def test_source_staleness(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "fortran_basic" / "src", repo)
    result = scan_fixture("fortran_basic", tmp_path / "proj", repo)
    with GraphQuery(result.db_path) as q:
        excerpt = q.source("file:solve.f90", 6, 7)
        assert excerpt.lines == ["  x = norm2v(n)", "  call report(x)"] and not excerpt.stale
        target = repo / "solve.f90"
        target.write_text(target.read_text(encoding="utf-8").replace("call report", "call report2"),
                          encoding="utf-8")
        assert q.source("file:solve.f90", 6, 7).stale
        st = os.stat(target)
        os.utime(target, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        assert q.source("file:solve.f90", 1, 2).stale


def test_unresolved_and_health(tmp_path: Path) -> None:
    result = scan_fixture("fortran_ambiguity", tmp_path / "proj")
    with GraphQuery(result.db_path) as q:
        groups = q.unresolved()
        assert sorted(g.pattern for g in groups) == ["apply", "ext_*", "fn"]
        assert len(q.unresolved(include_ambiguous=True)) == 4
        health = q.scan_health()
        assert health.sites_by_resolution["unresolved"] == 3 and health.ambiguous == 1
        assert q.inventory().languages[0].lang == "fortran"


def test_cli_queries(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    result = scan_fixture("mini_hybrid", tmp_path / "proj", expected_file="expected_graph_bridges.json")
    db = str(result.db_path)
    try:
        assert main(["callers", "kernel", "--db", db]) == 0
        assert main(["path", "run_case", "kernel", "--db", db]) == 0
        assert main(["impact", "kernel", "--db", db, "--json"]) == 0
        assert main(["callees", "solve", "--db", db]) == 0  # routine preferred over its binding
        with pytest.raises(SystemExit):
            main(["callers", "nothing_like_this", "--db", db])
    finally:
        netguard.uninstall()
    out = capsys.readouterr().out
    assert "is called by 1 routine(s) in 1 file(s)" in out
    assert "--bridges, resolved--> f:kernel" in out


@pytest.mark.slow
def test_query_times_on_synthetic(tmp_path: Path) -> None:
    sys.path.insert(0, str(Path(__file__).parents[1] / "synthetic"))
    from generate import generate

    repo = tmp_path / "syn"
    generate(repo, routines=15000, files=3000, seed=42)
    db = scan(open_project(repo, tmp_path / "proj"), ScanOptions()).db_path
    with GraphQuery(db) as q:
        hub = "f:r_00000"
        start = time.perf_counter()
        report = q.callers(hub)
        t_callers = time.perf_counter() - start
        start = time.perf_counter()
        q.children(hub, direction=Direction.CALLERS)
        t_children = time.perf_counter() - start
        start = time.perf_counter()
        q.find("r_0123")
        t_find = time.perf_counter() - start
        start = time.perf_counter()
        q.impact(hub, max_depth=3)
        t_impact = time.perf_counter() - start
    print(f"\ncallers of a hub ({report.count} callers): {t_callers * 1000:.0f} ms; children: "
          f"{t_children * 1000:.0f} ms; find: {t_find * 1000:.0f} ms; impact depth 3: {t_impact * 1000:.0f} ms")
    assert t_callers < 0.1 and t_children < 0.2
