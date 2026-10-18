"""File dependencies as the primary product (file_dependency_migration_instructions_EN.md, lot 1).

``A -> B`` means file A depends on file B. Every occurrence keeps its evidence; aggregates are keyed by (source
file, target file, relationship, resolution); a site counts once per candidate file; intra-file occurrences stay in
the table but not in the graph; graphs, tables, folder aggregation, impact and exports use one contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.helpers import scan_fixture

from codegraph_sci.query.api import GraphQuery
from codegraph_sci.query.types import DependencyFilter
from codegraph_sci.store.export import export_dict

FILES = {
    "app/main.py": ("from lib import util\nfrom cyc import a\n\nutil.helper()\n\n\ndef run():\n    util.helper()\n"
                    "    missing_function()\n\n\ndef measure(obj):\n    return obj.area()\n"),
    "lib/__init__.py": "",
    "lib/util.py": "def helper():\n    return 1\n",
    "lib/shapes.py": ("class Shape:\n    def area(self):\n        return 0\n\n\nclass Square(Shape):\n"
                      "    def area(self):\n        return 1\n"),
    "lib/other.py": "class Other:\n    def area(self):\n        return 2\n",
    "cyc/__init__.py": "",
    "cyc/a.py": "from cyc import b\n\n\ndef fa():\n    b.fb()\n",
    "cyc/b.py": "from cyc import a\n\n\ndef fb():\n    a.fa()\n",
    "lone/alone.py": "def alone():\n    pass\n",
    "csrc/main.c": '#include "api.h"\n\nvoid start(void) { solve(1); }\n',
    "csrc/api.h": '#include "types.h"\nvoid solve(int n);\n',
    "csrc/types.h": "typedef int num;\n",
    "csrc/solve.c": '#include "api.h"\n\nvoid solve(int n) {}\n',
    "fsrc/state.f90": "module state\n  integer :: counter\nend module state\n",
    "fsrc/bump.f90": "subroutine bump\n  use state\n  counter = counter + 1\nend subroutine bump\n",
}


@pytest.fixture(scope="module")
def db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from codegraph_sci.core.project import open_project
    from codegraph_sci.scan import ScanOptions, scan

    root = tmp_path_factory.mktemp("filedeps")
    repo = root / "repo"
    for rel, text in FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    return scan(open_project(repo, root / "proj"), ScanOptions(jobs=1)).db_path


def _edges(db: Path) -> set[tuple[str, str, str, str]]:
    with GraphQuery(db) as q:
        return {(e.source, e.target, e.relationship, e.resolution) for e in q.file_dependencies()}


def test_relationships_keep_their_meaning(db: Path) -> None:
    edges = _edges(db)
    assert ("app/main.py", "lib/util.py", "call", "resolved") in edges  # top-level script call and in a function
    assert ("app/main.py", "lib/util.py", "import", "resolved") in edges
    assert ("csrc/main.c", "csrc/api.h", "include", "resolved") in edges
    assert ("csrc/api.h", "csrc/types.h", "include", "resolved") in edges  # nested include
    assert ("csrc/main.c", "csrc/solve.c", "call", "resolved") in edges
    assert ("fsrc/bump.f90", "fsrc/state.f90", "import", "resolved") in edges  # USE of a module
    assert ("fsrc/bump.f90", "fsrc/state.f90", "data_read", "resolved") in edges  # shared data
    assert ("fsrc/bump.f90", "fsrc/state.f90", "data_write", "resolved") in edges
    assert not {e for e in edges if e[2] in ("calls", "uses")}  # never collapsed into broad kinds


def test_top_level_and_function_calls_count_alike(db: Path) -> None:
    with GraphQuery(db) as q:
        [edge] = [e for e in q.file_dependencies() if (e.source, e.target, e.relationship) ==
                  ("app/main.py", "lib/util.py", "call")]
        assert edge.count == 2  # util.helper() at module level and inside run()
        rows = q.dependencies(edge.occurrences, limit=100).rows
        assert sorted(r.line for r in rows) == [4, 8]
        assert {r.caller for r in rows} == {"py:app.main", "py:app.main.run"}


def test_possible_dependencies_count_once_per_candidate_file(db: Path) -> None:
    with GraphQuery(db) as q:
        possible = {(e.target, e.count) for e in q.file_dependencies()
                    if e.source == "app/main.py" and e.resolution == "ambiguous"}
        # obj.area(): two candidate methods in lib/shapes.py (counted once) and one in lib/other.py
        assert possible == {("lib/shapes.py", 1), ("lib/other.py", 1)}
        [shapes] = [e for e in q.file_dependencies() if e.target == "lib/shapes.py" and e.resolution == "ambiguous"]
        rows = q.dependencies(shapes.occurrences, limit=100).rows
        assert len(rows) == 1 and rows[0].target_text == "obj.area" and len(rows[0].candidates) == 3


def test_unresolved_and_intra_file_stay_in_the_table_not_in_the_graph(db: Path) -> None:
    with GraphQuery(db) as q:
        graph = q.file_dependencies()
        assert all(e.source != e.target for e in graph)  # no self-edge in the graph
        assert all(e.target is not None for e in graph)
        groups = q.dependency_groups("file", limit=1000).rows
        assert ("lib/shapes.py", "lib/shapes.py", "inherit") in {(g.source, g.target, g.relationship) for g in groups}
        unresolved = [g for g in groups if g.source == "app/main.py" and g.target is None]
        assert unresolved and "unresolved" in {s for g in unresolved for s in g.statuses}


def test_table_graph_and_export_agree(db: Path) -> None:
    with GraphQuery(db) as q:
        graph = {(e.source, e.target, e.relationship, e.resolution): e.count for e in q.file_dependencies()}
        table: dict[tuple[Any, ...], int] = {}
        for g in q.dependency_groups("file", limit=10000).rows:
            if g.target is None or g.target == g.source:
                continue
            for status, n in g.statuses.items():
                table[(g.source, g.target, g.relationship, status)] = n
    assert table == graph
    exported = {(e["src"], e["dst"], e["relationship"], e["resolution"]): e["count"]
                for e in export_dict(db)["file_dependencies"]}
    assert exported == graph


def test_isolated_files_cycles_and_impact(db: Path) -> None:
    with GraphQuery(db) as q:
        assert "lone/alone.py" in {f["path"] for f in q.files()}  # kept in the inventory
        assert not [e for e in q.file_dependencies() if "lone/alone.py" in (e.source, e.target)]
        assert ["cyc/a.py", "cyc/b.py"] in q.file_cycles()
        impact = q.file_impact("lib/util.py")
        assert impact.confirmed == ["app/main.py"] and impact.possible == []
        shapes = q.file_impact("lib/shapes.py")
        assert shapes.confirmed == [] and shapes.possible == ["app/main.py"]  # possible, never confirmed
        deps = q.file_relations("app/main.py", incoming=False)
        assert {d.path for d in deps} >= {"lib/util.py", "cyc/a.py", "lib/shapes.py"}
        dependents = q.file_relations("lib/util.py", incoming=True)
        assert [(d.path, sorted(d.relationships)) for d in dependents] == [("app/main.py", ["call", "import"])]


def test_folder_aggregation_uses_the_same_contract(db: Path) -> None:
    with GraphQuery(db) as q:
        folders = {(e.source, e.target, e.relationship, e.resolution): e.count for e in q.folder_dependencies()}
        files = q.file_dependencies()
    expected: dict[tuple[str, str, str, str], int] = {}
    for e in files:
        a, b = e.source.rsplit("/", 1)[0], e.target.rsplit("/", 1)[0]
        if a != b:
            key = (a, b, e.relationship, e.resolution)
            expected[key] = expected.get(key, 0) + e.count
    assert folders == expected


def test_bindings_and_bridges_between_files(tmp_path: Path) -> None:
    db = scan_fixture("mini_hybrid", tmp_path / "proj", expected_file="expected_graph_bridges.json").db_path
    edges = _edges(db)
    assert ("app/run.py", "ext/bindings.cpp", "binding", "resolved") in edges
    assert ("csrc/solver.c", "fsrc/kernel.f90", "bridge", "resolved") in edges
    assert ("ext/bindings.cpp", "csrc/solver.c", "bridge", "resolved") in edges


def test_cold_cached_and_parallel_scans_are_equivalent(tmp_path: Path) -> None:
    from codegraph_sci.core.project import open_project
    from codegraph_sci.scan import ScanOptions, scan

    repo = tmp_path / "repo"
    for rel, text in FILES.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    project = open_project(repo, tmp_path / "proj")
    cold = export_dict(scan(project, ScanOptions(jobs=1)).db_path)["file_dependencies"]
    cached = export_dict(scan(project, ScanOptions(jobs=1)).db_path)["file_dependencies"]
    parallel = export_dict(scan(project, ScanOptions(jobs=3, full=True)).db_path)["file_dependencies"]
    assert cold == cached == parallel and cold


def test_occurrence_filter_by_candidate_file(db: Path) -> None:
    with GraphQuery(db) as q:
        rows = q.dependencies(DependencyFilter(caller_file="app/main.py", target_file="lib/other.py"), limit=100).rows
    assert [r.target_text for r in rows] == ["obj.area"]  # a candidate in that file is a possible dependency
