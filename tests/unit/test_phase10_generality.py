"""Phase 10 of the requirements plan: generality, with Code_Aster optional.

An independent validation matrix of miniature fixtures runs without any shipped domain pack; packs are never
activated by name or detection; the Code_Aster pack is validated like any project pack; the installed wheel works
outside the checkout.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from tests.helpers import FIXTURES, graph_diff, scan_fixture

from codegraph_sci.store.export import export_dict

ROOT = Path(__file__).parents[2]
# Corpus -> (fixture, expected file, what it validates). Code_Aster: tests/corpus (optional, outside regular CI).
MATRIX = {
    "python library without main": ("python_library", "expected_graph.json"),
    "C project": ("c_basic", "expected_graph.json"),
    "C++ project": ("cpp_overloads", "expected_graph.json"),
    "Fortran project": ("fortran_arrays_includes", "expected_graph.json"),
    "independent mixed-language project": ("mini_hybrid", "expected_graph_bridges.json"),
    "custom language (keyword DSL)": ("keywords_language", "expected_graph.json"),
}


@pytest.fixture()
def no_shipped_packs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The installation without its ``packs/`` folder (Code_Aster not installed)."""
    import codegraph_sci.core.paths as paths

    empty = tmp_path / "installation"
    empty.mkdir()
    monkeypatch.setattr(paths, "install_dir", lambda: empty)
    monkeypatch.delenv("CGS_PACKS_PATH", raising=False)
    return empty


@pytest.mark.parametrize("corpus", sorted(MATRIX))
def test_validation_matrix_without_shipped_packs(corpus: str, no_shipped_packs: Path, tmp_path: Path) -> None:
    fixture, expected_file = MATRIX[corpus]
    import json

    expected = json.loads((FIXTURES / fixture / expected_file).read_text(encoding="utf-8"))
    result = scan_fixture(fixture, tmp_path / "proj", expected_file=expected_file)
    assert graph_diff(export_dict(result.db_path), expected) == [], corpus


def test_core_works_without_code_aster(no_shipped_packs: Path, tmp_path: Path) -> None:
    from codegraph_sci.enrich.packs import BUILTIN_PACKS, default_search_paths, find_pack, load_packs
    from codegraph_sci.inventory.profile_io import DEFAULT_PACKS

    assert find_pack("code_aster", default_search_paths(tmp_path)) is None
    assert set(DEFAULT_PACKS) <= set(BUILTIN_PACKS)  # only generic packs are enabled by default
    assert [p.name for p in load_packs(list(DEFAULT_PACKS), default_search_paths(tmp_path))] == list(DEFAULT_PACKS)


def test_packs_are_never_activated_by_name_or_detection(tmp_path: Path) -> None:
    """A repository that matches the Code_Aster detection rules is analyzed without that pack unless configured."""
    from codegraph_sci.core.project import open_project
    from codegraph_sci.scan import ScanOptions, scan

    repo = tmp_path / "repo"
    for folder in ("bibfor", "bibcxx", "code_aster"):
        (repo / folder).mkdir(parents=True)
    (repo / "bibfor" / "a.f90").write_text("subroutine a\n  call jemarq()\nend subroutine a\n", encoding="utf-8")
    db = scan(open_project(repo, tmp_path / "proj"), ScanOptions(jobs=1)).db_path
    packs = {p["name"] for p in export_dict(db)["plugins"] if p["type"] == "pack"}
    assert "code_aster" not in packs


def test_core_names_no_shipped_pack() -> None:
    """Adding a code base needs configuration or extensions, never a project-name exception in the core."""
    names = {p.parent.name for p in (ROOT / "packs").glob("*/rules.yaml")}
    offenders = []
    for path in (ROOT / "src" / "codegraph_sci").rglob("*"):
        if path.is_file() and path.suffix in (".py", ".yaml", ".json", ".sql", ".js", ".html"):
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            offenders += [f"{path.relative_to(ROOT)}: {n}" for n in names if n.lower() in text]
    assert offenders == []


@pytest.mark.skipif(not (ROOT / "packs" / "code_aster" / "rules.yaml").is_file(), reason="Code_Aster pack absent")
def test_code_aster_pack_is_validated_like_any_project_pack() -> None:
    from codegraph_sci.rules import run_rule_tests, validate_rule

    path = ROOT / "packs" / "code_aster" / "rules.yaml"
    check = validate_rule(path)
    assert (check.kind, check.name, check.errors) == ("project", "code_aster", [])
    results = run_rule_tests(path)
    assert results and all(r.passed for r in results), [r.details for r in results]


def test_installed_wheel_works_outside_the_checkout() -> None:
    out = subprocess.run([sys.executable, str(ROOT / "tools" / "check_wheel.py")], capture_output=True, text=True,
                         timeout=600)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "check_wheel: OK" in out.stdout
