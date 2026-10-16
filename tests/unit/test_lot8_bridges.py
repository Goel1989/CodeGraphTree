from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from tests.helpers import FIXTURES, graph_diff, scan_fixture

from codegraph_sci.algo.graph import k_shortest_simple_paths
from codegraph_sci.audit.sample import precision_sample
from codegraph_sci.core.model import CALL_PATH
from codegraph_sci.core.profile import RuleRef
from codegraph_sci.core.project import open_project
from codegraph_sci.inventory.profile_io import profile_from_inventory, save_profile
from codegraph_sci.inventory.run import run_inventory
from codegraph_sci.link.bridges import apply_transform
from codegraph_sci.scan import ScanOptions, scan
from codegraph_sci.store.export import export_dict


@pytest.mark.parametrize("name,expected", [("bridge_pybind11", "expected_graph.json"),
                                           ("bridge_fortran_c", "expected_graph.json"),
                                           ("bridge_prefix_negative", "expected_graph.json"),
                                           ("mini_hybrid", "expected_graph_bridges.json")])
def test_bridge_fixtures(name: str, expected: str, tmp_path: Path) -> None:
    result = scan_fixture(name, tmp_path / "proj", expected_file=expected)
    want = json.loads((FIXTURES / name / expected).read_text(encoding="utf-8"))
    diff = graph_diff(export_dict(result.db_path), want)
    assert diff == [], "\n".join(diff)


def test_mini_hybrid_chain_and_no_unresolved(tmp_path: Path) -> None:
    result = scan_fixture("mini_hybrid", tmp_path / "proj", expected_file="expected_graph_bridges.json")
    data = export_dict(result.db_path)
    assert [s for s in data["call_sites"] if s["resolution"] == "unresolved"] == []
    uids = sorted(n["uid"] for n in data["nodes"])
    index = {u: i for i, u in enumerate(uids)}
    succ: list[list[int]] = [[] for _ in uids]
    for e in data["edges"]:
        if e["kind"] in CALL_PATH:
            succ[index[e["src"]]].append(index[e["dst"]])
    paths, _ = k_shortest_simple_paths(index["py:app.run.run_case"], index["f:kernel"], succ)
    assert [[uids[i] for i in p] for p in paths] == [
        ["py:app.run.run_case", "cpp:hybrid::solve(int)", "c:c_solve", "f:kernel"]]
    kinds = {(e["src"], e["dst"]): e["kind"] for e in data["edges"]}
    assert kinds[("py:app.run.run_case", "cpp:hybrid::solve(int)")] == "binds"
    assert kinds[("cpp:hybrid::solve(int)", "c:c_solve")] == "bridges"


def test_declaration_macro_is_never_a_call_site(tmp_path: Path) -> None:
    result = scan_fixture("bridge_prefix_negative", tmp_path / "proj")
    data = export_dict(result.db_path)
    assert not [s for s in data["call_sites"] if s["target_text"] == "FDECL"]
    bindings = [n for n in data["nodes"] if n["kind"] == "binding"]
    assert {n["subtype"] for n in bindings} == {"macro_declaration"}


def test_name_transforms() -> None:
    assert apply_transform("FCALL_SOLVE", "FCALL_", ["strip_prefix", "lowercase"]) == "solve"
    assert apply_transform("solve", "", ["uppercase", "append_underscore"]) == "SOLVE_"
    assert apply_transform("x__", "", ["strip_underscore"]) == "x"


def test_profile_rule_is_applied(tmp_path: Path) -> None:
    src = FIXTURES / "bridge_prefix_negative" / "src"
    project = open_project(src, tmp_path / "proj")
    rule_file = project.folder / "rules" / "r-0001.yaml"
    rule_file.parent.mkdir(parents=True, exist_ok=True)
    rule_file.write_text(yaml.safe_dump({"from": "cpp", "to": "fortran", "call_prefixes": ["FCALL_"],
                                         "name_transform": ["strip_prefix", "lowercase"]}), encoding="utf-8")
    profile = profile_from_inventory(run_inventory(src))
    profile.rules = [RuleRef("r-0001", "bridge", "ai", "approved", "rules/r-0001.yaml")]
    save_profile(project.profile_path, profile)
    data = export_dict(scan(project, ScanOptions()).db_path)
    site = next(s for s in data["call_sites"] if s["target_text"] == "FCALL_ASSEMBLE")
    assert site["dst"] == "f:assemble" and site["origin"] == "bridge:prefix_calls@r-0001"
    profile.rules[0].status = "rejected"
    save_profile(project.profile_path, profile)
    data = export_dict(scan(project, ScanOptions()).db_path)
    site = next(s for s in data["call_sites"] if s["target_text"] == "FCALL_ASSEMBLE")
    assert site["resolution"] == "unresolved"


def test_bridges_group_in_precision_sample(tmp_path: Path) -> None:
    result = scan_fixture("bridge_fortran_c", tmp_path / "proj")
    sheet = precision_sample(result.db_path, per_group=10)
    groups = {e["group"] for e in sheet["entries"]}
    assert "bridges" in groups
