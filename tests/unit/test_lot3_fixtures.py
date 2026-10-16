from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import jsonschema
import pytest

from codegraph_sci.inventory.run import run_inventory

TESTS = Path(__file__).parents[1]
FIXTURES = TESTS / "fixtures"
SCHEMAS = FIXTURES / "schemas"
sys.path.insert(0, str(TESTS / "synthetic"))

from generate import generate  # noqa: E402

GRAPH_FIXTURES = sorted(p.parent.name for p in FIXTURES.glob("*/expected_graph.json"))
INVENTORY_FIXTURES = sorted(p.parent.name for p in FIXTURES.glob("*/expected_inventory.json")
                            if p.parent.name != "inventory_mixed")


def _schema(name: str) -> dict[str, object]:
    data: dict[str, object] = json.loads((SCHEMAS / f"{name}.schema.json").read_text(encoding="utf-8"))
    return data


def test_catalogue_is_complete() -> None:
    expected = {"fortran_basic", "fortran_fixed_form", "fortran_preproc", "fortran_ambiguity",
                "fortran_arrays_includes", "fortran_advanced", "fortran_data", "fortran_traps",
                "python_basic", "c_basic", "cpp_basic", "cpp_overloads", "mini_hybrid", "partial_scope",
                "robustness"}
    assert expected <= set(GRAPH_FIXTURES)
    assert expected <= set(INVENTORY_FIXTURES)


@pytest.mark.parametrize("name", GRAPH_FIXTURES)
def test_expected_graph_schema(name: str) -> None:
    data = json.loads((FIXTURES / name / "expected_graph.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, _schema("expected_graph"))
    uids = {n["uid"] for n in data["nodes"]}
    for site in data["call_sites"]:
        assert (FIXTURES / name / "src" / site["file"]).is_file(), site
        if site["dst"] and not site["dst"].startswith("file:"):
            assert site["dst"] in uids, site
        if site["resolution"] in ("unresolved", "ambiguous"):
            assert site["dst"] is None, site
    for edge in data["edges"] if not data.get("partial") else []:
        for end in (edge["src"], edge["dst"]):
            assert end in uids or end.startswith("file:"), edge


@pytest.mark.parametrize("name", INVENTORY_FIXTURES)
def test_expected_inventory(name: str) -> None:
    from codegraph_sci.core.profile import AnalysisProfile

    expected = json.loads((FIXTURES / name / "expected_inventory.json").read_text(encoding="utf-8"))
    jsonschema.validate(expected, _schema("expected_inventory"))
    result = run_inventory(FIXTURES / name / "src", AnalysisProfile())
    got = {e.path: {"lang": e.lang, "variant": e.variant, "status": e.status} for e in result.entries}
    assert got == expected["files"]
    assert result.include_paths == expected.get("include_paths", [])


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def test_generator_is_deterministic(tmp_path: Path) -> None:
    e1 = generate(tmp_path / "a", routines=400, files=40, seed=7)
    e2 = generate(tmp_path / "b", routines=400, files=40, seed=7)
    assert _tree_hash(tmp_path / "a") == _tree_hash(tmp_path / "b")
    assert e1 == e2
    e3 = generate(tmp_path / "c", routines=400, files=40, seed=8)
    assert e3 != e1
    result = run_inventory(tmp_path / "a")
    assert {e.path: e.lang for e in result.entries} == e1["files"]
