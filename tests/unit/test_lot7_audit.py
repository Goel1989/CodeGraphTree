from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from tests.helpers import FIXTURES, scan_fixture

from codegraph_sci.audit.baseline import compare_baseline
from codegraph_sci.audit.common import wilson_interval
from codegraph_sci.audit.corpus import check_expectations
from codegraph_sci.audit.diff import double_extraction
from codegraph_sci.audit.invariants import invariants, site_pattern, unresolved_groups
from codegraph_sci.audit.report import audit_report, inventory_coherence
from codegraph_sci.audit.sample import (
    load_sheet,
    merge_into_reference,
    precision_sample,
    recall_sample,
    replay_reference,
    review,
    save_sheet,
    sheet_metrics,
)


def test_wilson_bound_sizes_the_samples() -> None:
    low, high = wilson_interval(148, 150)
    assert low > 0.95 > 0.0 and high <= 1.0  # §2.1: 150 links, at most 2 errors -> lower bound > 95 %
    assert wilson_interval(0, 0) == (0.0, 1.0)


@pytest.fixture()
def hybrid_db(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    for name in ("fortran_basic", "fortran_fixed_form", "python_basic", "c_basic", "cpp_basic"):
        shutil.copytree(FIXTURES / name / "src", repo / name)
    result = scan_fixture("fortran_basic", tmp_path / "proj", repo)
    return result.db_path, repo


def test_baseline_recall_on_fixtures(hybrid_db: tuple[Path, Path]) -> None:
    db, _ = hybrid_db
    data = compare_baseline(db)
    assert data["definitions_recall"] == 1.0, data["missing_definitions"]
    assert data["fortran_calls_recall"] == 1.0, data["missing_calls"]
    assert data["definitions_reference"] > 20


def test_double_extraction_runs(hybrid_db: tuple[Path, Path]) -> None:
    db, _ = hybrid_db
    data = double_extraction(db)
    assert set(data) == {"c", "cpp", "fortran", "python"}
    assert data["fortran"]["def_only_primary"] == 0 and data["fortran"]["call_only_secondary"] == 0


def test_invariants_and_groups(hybrid_db: tuple[Path, Path]) -> None:
    db, _ = hybrid_db
    inv = invariants(db)
    assert inv["files_by_status"]["fallback"] == 1  # the Python 2 file
    assert 0 <= inv["unresolved_rate"] < 0.2
    groups = unresolved_groups(db, include_ambiguous=True)
    assert all(g["count"] >= 1 for g in groups)
    assert site_pattern("FCALL_FOO") == "FCALL_*" and site_pattern("obj.method") == "obj.*"
    assert inventory_coherence(db)["issues"] == []


def test_samples_review_report_and_replay(hybrid_db: tuple[Path, Path], tmp_path: Path) -> None:
    db, repo = hybrid_db
    sheet = precision_sample(db, per_group=5, seed=1, revision="test")
    assert sheet == precision_sample(db, per_group=5, seed=1, revision="test")  # deterministic
    path = tmp_path / "precision.yaml"
    save_sheet(path, sheet)
    answers = iter(["y"] * 100)
    assert review(path, ask=lambda _p: next(answers), show=lambda _s: None) == 0
    reviewed = load_sheet(path)
    metrics = sheet_metrics(reviewed)
    assert set(metrics) == {"c", "cpp", "fortran", "python"}
    assert all(m["rate"] == 1.0 for m in metrics.values())
    rsheet = recall_sample(db, per_lang=5, seed=1)
    rpath = tmp_path / "recall.yaml"
    save_sheet(rpath, rsheet)
    answers = iter(["y"] * 100)
    review(rpath, ask=lambda _p: next(answers), show=lambda _s: None)
    report = audit_report(db, path, rpath)
    names = {m["metric"] for m in report["metrics"]}
    assert "precision[fortran]" in names and "recall_call_sites[python]" in names
    ref = tmp_path / "corpus" / "reference_sample.yaml"
    assert merge_into_reference(reviewed, ref) == len(reviewed["entries"])
    assert merge_into_reference(load_sheet(rpath), ref) > 0
    assert replay_reference(ref, db) == []
    # A regression: a verified call disappears from the code -> the replay reports it.
    entry = next(e for e in reviewed["entries"] if e["file"].endswith("solve.f90"))
    target = repo / entry["file"]
    lines = target.read_text(encoding="utf-8").split("\n")
    lines[entry["line"] - 1] = "  continue"
    target.write_text("\n".join(lines), encoding="utf-8")
    scan_fixture("fortran_basic", db.parent, repo)
    assert any("disappeared" in p for p in replay_reference(ref, db))


def test_corpus_expectations(hybrid_db: tuple[Path, Path]) -> None:
    db, _ = hybrid_db
    expectations = yaml.safe_load("""
inventory:
  languages: {fortran: {min_files: 4}, python: {min_files: 1}}
  max_unknown_rate: 0.5
expect:
  - node: "f:solve"
  - node: "f:does_not_exist"
  - callers_count: {node: "f:report", min: 1, max: 1}
  - edge: {src: "f:solve", dst: "f:report", kind: calls}
  - no_call_to: ["f:k"]
  - hidden: "f:report"
""")
    results = check_expectations(db, expectations)
    status = {r["item"]: r["ok"] for r in results}
    assert status["node: f:solve"] is True and status["node: f:does_not_exist"] is False
    assert status["callers_count: {'node': 'f:report', 'min': 1, 'max': 1}"] is True
    assert status["hidden: f:report"] is None


def test_cli_audit_report(hybrid_db: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    db, _ = hybrid_db
    try:
        main(["audit", "report", "--db", str(db)])
        assert main(["audit", "baseline", "--db", str(db), "--json"]) == 0
    finally:
        netguard.uninstall()
    out = capsys.readouterr().out
    assert "definitions_recall" in out and "V1 criteria" in out
