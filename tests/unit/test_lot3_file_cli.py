"""File commands of ``cgs`` and the retired function-view code (file-dependency migration lot 3, decision D41).

``cgs files dependencies|dependents|impact|cycles`` answer at the file level with the same contract as the window.
The query code that only served the removed Functions 3D view is gone; the symbol-level tools (callers, callees,
path, impact, data) stay for checking and for the validation claims; ``test_lot9_query`` covers them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.helpers import scan_fixture

from codegraph_sci.query.api import GraphQuery, QueryError
from codegraph_sci.query.types import Level

CYCLE_FILES = {
    "cyc/__init__.py": "",
    "cyc/a.py": "from cyc import b\n\n\ndef fa():\n    b.fb()\n",
    "cyc/b.py": "from cyc import a\n\n\ndef fb():\n    a.fa()\n",
    "use.py": "from cyc import a\n\n\ndef go():\n    a.fa()\n",
}


@pytest.fixture()
def hybrid(tmp_path: Path) -> str:
    return str(scan_fixture("mini_hybrid", tmp_path / "proj", expected_file="expected_graph_bridges.json").db_path)


def _cgs(args: list[str], capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    try:
        code = main(args)
    finally:
        netguard.uninstall()
    return code, capsys.readouterr().out


def test_files_dependencies_and_dependents(hybrid: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _cgs(["files", "dependencies", "csrc/solver.c", "--db", hybrid], capsys)
    assert code == 0
    assert "csrc/solver.c depends on 2 file(s)" in out
    assert "fsrc/kernel.f90" in out and "bridge 1" in out and "csrc/solver_api.h" in out and "include 1" in out
    code, out = _cgs(["files", "dependents", "csrc/solver.c", "--db", hybrid], capsys)
    assert code == 0 and "1 file(s) depend on csrc/solver.c" in out and "ext/bindings.cpp" in out
    code, out = _cgs(["files", "dependencies", "csrc/solver.c", "--relationship", "include", "--json",
                      "--db", hybrid], capsys)
    data = json.loads(out)
    assert [r["path"] for r in data] == ["csrc/solver_api.h"]
    assert data[0]["relationships"] == {"include": 1} and data[0]["confirmed"] is True


def test_files_impact(hybrid: str, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = _cgs(["files", "impact", "fsrc/kernel.f90", "--db", hybrid], capsys)
    assert code == 0
    assert "Changing fsrc/kernel.f90 may affect 3 file(s): 3 confirmed, 0 possible" in out
    assert out.index("[1] csrc/solver.c") < out.index("[2] ext/bindings.cpp") < out.index("[3] app/run.py")
    code, out = _cgs(["files", "impact", "fsrc/kernel.f90", "--max-depth", "1", "--json", "--db", hybrid], capsys)
    assert json.loads(out)["confirmed"] == ["csrc/solver.c"]


def test_files_cycles(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.core.project import open_project
    from codegraph_sci.scan import ScanOptions, scan

    repo = tmp_path / "repo"
    for rel, text in CYCLE_FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    db = str(scan(open_project(repo, tmp_path / "proj"), ScanOptions(jobs=1)).db_path)
    code, out = _cgs(["files", "cycles", "--db", db], capsys)
    assert code == 0 and "1 file cycle(s)" in out and "cyc/a.py, cyc/b.py" in out
    code, out = _cgs(["files", "cycles", "--json", "--db", db], capsys)
    assert json.loads(out) == [["cyc/a.py", "cyc/b.py"]]


def test_files_unknown_file_is_an_error(hybrid: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit, match="unknown file"):
        _cgs(["files", "dependents", "nowhere.c", "--db", hybrid], capsys)


def test_function_view_code_is_retired(hybrid: str) -> None:
    for gone in ("initial_subgraph", "connected_neighbors", "call_sites"):
        assert not hasattr(GraphQuery, gone), gone
    with GraphQuery(hybrid) as q:
        for call in (lambda: q.graph3d_overview(mode="functions"), lambda: q.graph3d_group("group:f:kernel",
                     mode="functions"), lambda: q.groups(Level.ROUTINE),
                     lambda: q.graph3d_main_paths("f:kernel", mode="functions"),
                     lambda: q.paths_from_main("f:kernel", level=Level.ROUTINE)):
            with pytest.raises(QueryError, match="file"):
                call()
        assert q.graph3d_overview(mode="files").nodes  # the file views keep working
        assert q.graph3d("c:c_solve", mode="functions").nodes  # `cgs view3d` keeps its modes
