from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from tests.helpers import scan_fixture

from codegraph_sci.query.api import GraphQuery, QueryError


@pytest.fixture()
def hybrid(tmp_path: Path) -> Path:
    result = scan_fixture("mini_hybrid", tmp_path / "proj", expected_file="expected_graph_bridges.json")
    return Path(result.db_path)


def test_graph3d_functions_both_directions(hybrid: Path) -> None:
    with GraphQuery(hybrid) as q:
        g = q.graph3d("c:c_solve", mode="functions", depth=1)
    ids = {n.id for n in g.nodes}
    assert ids == {"c:c_solve", "cpp:hybrid::solve(int)", "f:kernel"}
    links = {(link.source, link.target, link.kind) for link in g.links}
    assert ("cpp:hybrid::solve(int)", "c:c_solve", "bridges") in links
    assert ("c:c_solve", "f:kernel", "bridges") in links
    root = next(n for n in g.nodes if n.is_root)
    assert root.id == "c:c_solve" and root.lang == "c"


def test_graph3d_depth_and_cap(hybrid: Path) -> None:
    with GraphQuery(hybrid) as q:
        deep = q.graph3d("c:c_solve", mode="functions", depth=3)
        capped = q.graph3d("c:c_solve", mode="functions", depth=3, max_nodes=2)
    assert "py:app.run.run_case" in {n.id for n in deep.nodes}
    assert len(capped.nodes) == 2 and capped.truncated
    assert all(link.source in {n.id for n in capped.nodes} and link.target in {n.id for n in capped.nodes}
               for link in capped.links)


def test_graph3d_files_and_both(hybrid: Path) -> None:
    with GraphQuery(hybrid) as q:
        files = q.graph3d("c:c_solve", mode="files", depth=2)
        both = q.graph3d("c:c_solve", mode="both", depth=1)
    assert {n.id for n in files.nodes} >= {"file:csrc/solver.c", "file:fsrc/kernel.f90"}
    assert all(n.kind in ("file",) for n in files.nodes)
    kinds = {link.kind for link in both.links}
    assert "defines" in kinds  # file -> routine it defines
    assert ("file:csrc/solver.c", "c:c_solve", "defines") in {(lk.source, lk.target, lk.kind) for lk in both.links}
    with pytest.raises(QueryError):
        q2 = GraphQuery(hybrid)
        try:
            q2.graph3d("f:nope")
        finally:
            q2.close()


def test_graph3d_deterministic(hybrid: Path) -> None:
    with GraphQuery(hybrid) as q:
        a = q.graph3d("cpp:hybrid::solve(int)", mode="both", depth=2)
        b = q.graph3d("cpp:hybrid::solve(int)", mode="both", depth=2)
    assert a == b


def test_html_is_offline_and_embeds_data(hybrid: Path) -> None:
    from codegraph_sci.ui.view3d.html import build_html

    with GraphQuery(hybrid) as q:
        g = q.graph3d("c:c_solve", mode="both", depth=1)
    page = build_html(g, title="c_solve")
    assert "Content-Security-Policy" in page and "connect-src 'none'" in page
    assert "ForceGraph3D" in page and "c:c_solve" in page
    # No external resource: every script is inline, no http(s) URL is loaded.
    assert not re.search(r"<script[^>]+src=", page)
    assert not re.search(r"""(src|href)\s*=\s*["']https?://""", page)
    data = json.loads(re.search(r'<script id="graph-data" type="application/json">(.*?)</script>', page,
                                re.S).group(1))  # type: ignore[union-attr]
    assert {n["id"] for n in data["nodes"]} == {n.id for n in g.nodes}


def test_api_expand_and_select(hybrid: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.ui.view3d.app import View3DApi

    api = View3DApi(hybrid, mode="functions", hide_noise=True)
    data = api.expand("c:c_solve")
    assert {n["id"] for n in data["nodes"]} == {"c:c_solve", "cpp:hybrid::solve(int)", "f:kernel"}
    api.select("f:kernel")
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == {"event": "select", "uid": "f:kernel"}


def test_cli_view3d_export(hybrid: Path, tmp_path: Path) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    out = tmp_path / "graph.html"
    try:
        assert main(["view3d", "c_solve", "--db", str(hybrid), "--mode", "both", "--export", str(out)]) == 0
    finally:
        netguard.uninstall()
    assert "ForceGraph3D" in out.read_text(encoding="utf-8")


def test_graph3d_main_paths(hybrid: Path) -> None:
    with GraphQuery(hybrid) as q:
        graph, report = q.graph3d_main_paths("f:kernel", mode="functions")
        files, _ = q.graph3d_main_paths("f:kernel", mode="files")
        both, _ = q.graph3d_main_paths("f:kernel", mode="both")
    assert report.paths and report.paths[0].steps[-1].uid == "f:kernel"
    ids = {n.id for n in graph.nodes}
    assert {"py:app.run.run_case", "c:c_solve", "f:kernel"} <= ids
    assert graph.root == report.root_uid and any(n.is_root for n in graph.nodes)
    assert ("c:c_solve", "f:kernel") in {(lk.source, lk.target) for lk in graph.links}
    assert all(n.kind == "file" for n in files.nodes) and "file:fsrc/kernel.f90" in {n.id for n in files.nodes}
    assert "defines" in {lk.kind for lk in both.links}


def test_html_qt_host_starts_empty(hybrid: Path) -> None:
    from codegraph_sci.ui.view3d.html import build_html, empty_graph

    page = build_html(empty_graph("functions"), title="functions", host="qt")
    assert 'window.CGS_HOST = "qt"' in page and "connect-src 'none'" in page
    assert 'window.CGS_HOST = "pywebview"' in build_html(empty_graph("files"), title="files")  # default host
