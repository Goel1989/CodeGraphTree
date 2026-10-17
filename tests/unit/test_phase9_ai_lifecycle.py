"""Phase 9 of the requirements plan: one lifecycle for every AI proposal, separate from the active analysis.

``draft -> validated -> approved`` (or ``rejected``): generating, validating or rejecting never changes the
analysis; only an explicit approval of a validated proposal activates it; automatic approval needs a separate,
recorded policy; language packages are validated against expected results written independently; the diagnosis
says why something is not covered; documents that cannot be read are reported.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from tests.helpers import FIXTURES

from codegraph_sci.ai.complete import Completion, read_document
from codegraph_sci.ai.proposals import (
    ProposalError,
    approve,
    auto_approval_enabled,
    list_proposals,
    load,
    reject,
    set_auto_approval,
)
from codegraph_sci.ai.worker import AIClient
from codegraph_sci.core.project import Project, open_project
from codegraph_sci.inventory.profile_io import load_profile
from codegraph_sci.scan import ScanOptions, scan
from codegraph_sci.store.export import export_json

AI = Path(__file__).parents[1] / "ai"
GOOD = f"fake:{AI / 'responses.json'}"


def _project(name: str, tmp_path: Path) -> Project:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / name / "src", repo)
    project = open_project(repo, tmp_path / "proj")
    scan(project, ScanOptions(jobs=1))
    return project


def _state(project: Project) -> tuple[str, str]:
    """What the analysis uses: the profile and the canonical graph."""
    return project.profile_path.read_text(encoding="utf-8"), export_json(project.db_path)


def test_override_generation_and_rejection_leave_the_analysis_unchanged(tmp_path: Path) -> None:
    project = _project("unknown_extension", tmp_path)
    before = _state(project)
    [prop] = Completion(project, AIClient(GOOD, in_process=True)).run()
    assert (prop.kind, prop.status, prop.id) == ("override", "validated", "p-0001")
    assert load_profile(project.profile_path).file_overrides == []  # the bug of the base: written directly
    scan(project, ScanOptions(jobs=1))
    assert _state(project) == before
    stored = load(project, "p-0001")
    assert [h["status"] for h in stored.history] == ["draft", "validated"]
    assert stored.provenance["model"] == GOOD and stored.validation["passed"]
    reject(project, "p-0001", "not this time")
    scan(project, ScanOptions(jobs=1))
    assert _state(project) == before
    with pytest.raises(ProposalError, match="only a validated proposal"):
        approve(project, "p-0001")


def test_explicit_approval_activates_then_scans_need_no_ai(tmp_path: Path) -> None:
    project = _project("unknown_extension", tmp_path)
    [prop] = Completion(project, AIClient(GOOD, in_process=True)).run()
    approved = approve(project, str(prop.id))
    assert approved.status == "approved" and approved.history[-1]["by"] == "user"
    assert [(o.glob, o.language) for o in load_profile(project.profile_path).file_overrides] == [("*.ftx", "fortran")]
    with pytest.raises(ProposalError, match="approved"):
        approve(project, str(prop.id))
    code = ("import sys; from pathlib import Path; from codegraph_sci.core.project import open_project;"
            "from codegraph_sci.scan import ScanOptions, scan; "
            f"r = scan(open_project(folder=Path(r'{project.folder}')), ScanOptions(jobs=1));"
            "print(any(m.startswith('codegraph_sci.ai') for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"
    assert '"dst": "f:solver_a"' in export_json(project.db_path)


def test_automatic_approval_needs_a_recorded_policy(tmp_path: Path) -> None:
    project = _project("unknown_extension", tmp_path)
    assert not auto_approval_enabled(project)
    with pytest.raises(ProposalError, match="automatic approval is not enabled"):
        Completion(project, AIClient(GOOD, in_process=True), auto=True).run()
    assert list_proposals(project) == []
    set_auto_approval(project, True)
    [prop] = Completion(project, AIClient(GOOD, in_process=True), auto=True).run()
    assert prop.status == "approved" and load(project, str(prop.id)).history[-1]["by"] == "auto-policy"
    set_auto_approval(project, False)
    policy = (project.folder / "ai_policy.yaml").read_text(encoding="utf-8")
    assert "auto_approve: false" in policy and policy.count("by: user") == 2


def _keyword_project(tmp_path: Path) -> Project:
    repo = tmp_path / "repo"
    shutil.copytree(FIXTURES / "keywords_language" / "src", repo)
    (repo / "manual.md").unlink()
    project = open_project(repo, tmp_path / "proj")
    scan(project, ScanOptions(jobs=1))
    return project


def _expected(folder: Path, defs: dict[str, list[tuple[str, int, int]]]) -> Path:
    folder.mkdir(parents=True)
    for name, items in defs.items():
        shutil.copyfile(FIXTURES / "keywords_language" / "src" / "scripts" / f"{name}.acs", folder / f"{name}.acs")
        (folder / f"{name}.expected.json").write_text(json.dumps({"definitions": [
            {"name": n, "kind": "routine", "line_start": a, "line_end": b, "parent": None} for n, a, b in items]}),
            encoding="utf-8")
    return folder


def test_language_proposal_needs_independent_expected_results(tmp_path: Path) -> None:
    project = _keyword_project(tmp_path)
    before = _state(project)
    proposals = Completion(project, AIClient(GOOD, in_process=True),
                           document=FIXTURES / "keywords_language" / "src" / "manual.md").run()
    prop = next(p for p in proposals if p.kind == "keywords")
    assert prop.status == "validated" and prop.independent["status"] == "none"
    assert "coverage" not in prop.content  # no recall claimed without independent results
    assert "recall not measured" in prop.reason
    with pytest.raises(ProposalError, match="expected results written independently"):
        approve(project, str(prop.id))
    assert not (project.rules_dir / "languages" / "acme_script").exists()
    assert _state(project) == before
    stored = load(project, str(prop.id))
    document = stored.provenance["document"]
    assert document["status"] == "read" and len(document["sha256"]) == 64
    assert stored.provenance["passages"] and any("proc" in line for line in stored.provenance["passages"])
    assert isinstance(stored.provenance["assumptions"], list) and stored.provenance["examples"]


def test_language_proposal_failing_independent_results_is_rejected(tmp_path: Path) -> None:
    project = _keyword_project(tmp_path)
    wrong = _expected(tmp_path / "expected", {"helpers": [("prepare", 3, 5), ("missing_one", 20, 21)]})
    proposals = Completion(project, AIClient(GOOD, in_process=True), expected=wrong).run()
    prop = next(p for p in proposals if p.kind == "keywords")
    assert prop.status == "rejected" and "independent expected results not met" in prop.reason
    assert prop.independent["definitions_recall"] == 0.5


def test_language_proposal_approved_against_independent_results(tmp_path: Path) -> None:
    project = _keyword_project(tmp_path)
    good = _expected(tmp_path / "expected", {"helpers": [("prepare", 3, 5), ("compute", 7, 9), ("square", 11, 13),
                                                         ("report", 15, 16)]})
    proposals = Completion(project, AIClient(GOOD, in_process=True), expected=good).run()
    prop = next(p for p in proposals if p.kind == "keywords")
    assert prop.status == "validated" and prop.content["coverage"]["definitions_recall"] == 1.0
    approved = approve(project, str(prop.id))
    package = project.rules_dir / "languages" / "acme_script" / "language.yaml"
    assert approved.activation["package"] == "rules/languages/acme_script/language.yaml" and package.is_file()
    assert "status: approved" in package.read_text(encoding="utf-8")
    assert (package.parent / "tests" / "helpers.expected.json").is_file()
    scan(project, ScanOptions(jobs=1))
    assert '"uid": "kw:acme_script:main@scripts/main.acs"' in export_json(project.db_path)


def test_documents_that_cannot_be_read_are_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert read_document(None).status == "none"
    missing = read_document(tmp_path / "nope.md")
    assert (missing.status, missing.error) == ("missing", "file not found")
    pdf = tmp_path / "manual.pdf"
    pdf.write_bytes(b"%PDF-1.4 damaged")
    damaged = read_document(pdf)
    assert damaged.status in ("pdf_unsupported", "unreadable") and damaged.error and damaged.sha256
    empty = tmp_path / "empty.md"
    empty.write_text("   \n", encoding="utf-8")
    assert read_document(empty).status == "unreadable"

    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    project = _project("unknown_extension", tmp_path / "cli")
    try:
        assert main(["complete", str(project.root), "--project", str(project.folder), "--model", GOOD,
                     "--in-process", "--document", str(pdf)]) == 0
    finally:
        netguard.uninstall()
    err = capsys.readouterr()
    assert "warning: document" in err.err and "Nothing is active yet" in err.out
    assert load(project, "p-0001").provenance["document"]["status"] in ("pdf_unsupported", "unreadable")


def _fail_c_files(path: str, lang: str, variant: str | None, mode: str = "full") -> tuple[str, bytes | None,
                                                                                            str | None]:
    from codegraph_sci.scan import _extract_job

    if lang == "c":
        return path, None, "parser crashed (test)"
    return _extract_job(path, lang, variant, mode)


def test_diagnosis_distinguishes_the_six_cases(tmp_path: Path) -> None:
    import yaml

    from codegraph_sci.ai.diagnose import diagnose

    repo = tmp_path / "repo"
    files = {
        "a.xyz": "something unknown\n",
        "b.jl": "function f()\nend\n",
        "old.py": "print 'python 2'\n",
        "old2.py": "print 'still python 2'\nexec 'x'\n",
        "one.c": "void one(void) {}\n",
        "two.c": "void two(void) {}\n",
        "glue.cpp": "void glue() { EXT_A(); EXT_B(); EXT_C(); }\n",
    }
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    project = open_project(repo, tmp_path / "proj")
    # A user package for Python that declares only the python3 dialect.
    folder = project.rules_dir / "languages" / "python3_only"
    folder.mkdir(parents=True)
    (folder / "language.yaml").write_text(yaml.safe_dump({
        "package_format": 1, "language": "python", "version": "1.0", "extensions": [".py"], "dialects": ["python3"],
        "backend": "native:python", "overrides": True, "provenance": {"source": "manual"}}), encoding="utf-8")
    scan(project, ScanOptions(jobs=1, extract_job=_fail_c_files))
    found: dict[str, Any] = {(d.kind, d.target): d for d in diagnose(project)}
    assert ("unknown_language", ".xyz") in found
    assert ("missing_package", "julia") in found
    assert ("unsupported_dialect", "python:python2") in found
    assert ("partial_coverage", "python") in found  # Python 2 files read by the fallback extractor
    assert found[("parser_failures", "c")].count == 2
    assert ("unsupported_binding", "cpp:EXT_*") in found

    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    try:
        assert main(["ai-diagnose", str(repo), "--project", str(project.folder)]) == 0
        assert main(["ai-policy", str(repo), "--project", str(project.folder), "--auto-approve", "on"]) == 0
        assert auto_approval_enabled(project)
    finally:
        netguard.uninstall()


def test_rule_change_proposals_follow_the_same_lifecycle(tmp_path: Path) -> None:
    from codegraph_sci.ai.proposals import record
    from codegraph_sci.rules import new_rule

    project = _project("unknown_extension", tmp_path)
    path = new_rule("bridge", "c_calls", project)
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["rule"]["call_prefixes"] = ["CALL_", "FCALL_"]
    good = record(project, "rule_change", "bridges/c_calls.yaml", {"file": "bridges/c_calls.yaml", "data": data},
                  passed=True, reason="ok", checks={}, provenance={"model": "test"})
    data_bad = {**data, "rule": {**data["rule"], "candidates": "first"}}
    bad = record(project, "rule_change", "bridges/c_calls.yaml", {"file": "bridges/c_calls.yaml", "data": data_bad},
                 passed=True, reason="ok", checks={}, provenance={"model": "test"})
    text = path.read_text(encoding="utf-8")
    with pytest.raises(ProposalError, match="candidates"):
        approve(project, bad.id)
    assert path.read_text(encoding="utf-8") == text  # an invalid change is not kept
    approve(project, good.id)
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["rule"]["call_prefixes"] == ["CALL_", "FCALL_"]
