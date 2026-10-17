"""Phase 4 of the requirements plan: the published rule format and its workflow.

Rules are created from templates, validated, tested against their own expected results and only then activated.
The guide (``docs/rules/README.md``) is executable: its tutorial is followed here, from the documentation alone.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from codegraph_sci.core.patterns import MAX_PATTERN_LENGTH, MAX_RULE_FILE_BYTES, check_pattern
from codegraph_sci.core.project import Project, open_project
from codegraph_sci.rules import (
    RuleWorkflowError,
    activate_rule,
    new_rule,
    run_rule_tests,
    validate_rule,
)

ROOT = Path(__file__).parents[2]
GUIDE = ROOT / "docs" / "rules" / "README.md"


@pytest.fixture()
def project(tmp_path: Path) -> Project:
    repo = tmp_path / "repo"
    repo.mkdir()
    return open_project(repo, tmp_path / "proj")


# ----------------------------------------------------------------- pattern limits
@pytest.mark.parametrize(("pattern", "problem"), [
    (r"(a+)+$", "nested quantifier"),
    (r"(\w*)*x", "nested quantifier"),
    (r"(?:ab|a)*{2}", "invalid"),
    (r"(a)\1", "backreference"),
    (r"(?P<x>a)(?P=x)", "backreference"),
    ("a" * (MAX_PATTERN_LENGTH + 1), "longer than"),
    (r"([a-z", "invalid"),
])
def test_unsafe_patterns_are_rejected(pattern: str, problem: str) -> None:
    message = check_pattern(pattern)
    assert message is not None and problem in message


@pytest.mark.parametrize("pattern", [
    r'nom\s*=\s*"(?P<name>\w+)",\s*op\s*=\s*(?P<op>\d+)',  # shapes used by real packs
    r"^(?P<name>[A-Z][A-Z0-9_]+)\s*=\s*MACRO\(",
    r"^&&",
    r"CALL_(\w+)\s*\(",
    r"(?:ab)+c",
])
def test_ordinary_patterns_are_accepted(pattern: str) -> None:
    assert check_pattern(pattern) is None


def test_existing_packs_respect_the_limits() -> None:
    from codegraph_sci.enrich.packs import BUILTIN_PACKS, builtin_pack_dir, load_pack_file

    for path in [builtin_pack_dir(n) / "rules.yaml" for n in BUILTIN_PACKS] + list((ROOT / "packs").glob("*/rules.yaml")):
        load_pack_file(path)  # raises on an unsafe pattern


def test_pack_with_an_unsafe_pattern_names_file_and_key(tmp_path: Path) -> None:
    from codegraph_sci.enrich.packs import PackError, load_pack_file

    path = tmp_path / "rules.yaml"
    path.write_text(yaml.safe_dump({
        "pack": "demo", "version": "1.0", "format_version": 1, "identifiers": ["demo"],
        "entry_points": [{"kind": "command", "glob": "*.py", "pattern": "(a+)+b", "target": "py:{name}"}]}),
        encoding="utf-8")
    with pytest.raises(PackError, match=r"rules\.yaml: key 'entry_points/0/pattern': .*nested quantifier"):
        load_pack_file(path)


def test_oversized_rule_files_are_rejected(project: Project) -> None:
    from codegraph_sci.extract.registry import LanguagePackageError, load_registry

    path = new_rule("language", "big", project)
    path.write_text(path.read_text(encoding="utf-8") + "#" * MAX_RULE_FILE_BYTES, encoding="utf-8")
    with pytest.raises(LanguagePackageError, match="larger than"):
        load_registry(project.rules_dir / "languages")


# ----------------------------------------------------------------- language packages
def test_language_template_is_valid_tested_and_proposed(project: Project) -> None:
    path = new_rule("language", "tiny", project, extension=".tny")
    assert path == project.rules_dir / "languages" / "tiny" / "language.yaml"
    assert (path.parent / "tests" / "basic.source").is_file()
    assert (path.parent / "tests" / "basic.expected.json").is_file()
    check = validate_rule(path)
    assert (check.kind, check.name, check.errors) == ("language", "tiny", [])
    results = run_rule_tests(path)
    assert [r.passed for r in results] == [True]
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data["status"] == "proposed" and data["extensions"] == [".tny"]
    with pytest.raises(RuleWorkflowError, match="already exists"):
        new_rule("language", "tiny", project)


def test_failing_test_reports_missing_and_unexpected_facts(project: Project) -> None:
    path = new_rule("language", "tiny", project, extension=".tny")
    expected = path.parent / "tests" / "basic.expected.json"
    data = json.loads(expected.read_text(encoding="utf-8"))
    data["definitions"][0]["line_end"] += 1
    data["references"].append({"from": "main", "target": "ghost", "kind": "call", "line": 99, "col": 1})
    expected.write_text(json.dumps(data), encoding="utf-8")
    [result] = run_rule_tests(path)
    assert not result.passed
    text = "\n".join(result.details)
    assert "missing definition" in text and "unexpected definition" in text and "ghost" in text


def test_activation_requires_passing_tests_then_approves(project: Project) -> None:
    from codegraph_sci.extract.registry import load_registry

    path = new_rule("language", "tiny", project, extension=".tny")
    assert "tiny" not in load_registry(project.rules_dir / "languages").packages  # proposed: inactive
    expected = path.parent / "tests" / "basic.expected.json"
    good = expected.read_text(encoding="utf-8")
    expected.write_text(json.dumps({"definitions": [], "references": []}), encoding="utf-8")
    with pytest.raises(RuleWorkflowError, match="tests failed"):
        activate_rule(path)
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["status"] == "proposed"
    expected.write_text(good, encoding="utf-8")
    summary = activate_rule(path)
    assert "1 test passed" in summary
    text = path.read_text(encoding="utf-8")
    assert yaml.safe_load(text)["status"] == "approved"
    assert text.startswith("#")  # comments of the template are kept
    assert "tiny" in load_registry(project.rules_dir / "languages").packages
    from codegraph_sci.inventory.profile_io import load_profile

    assert any("tiny" in h.change for h in load_profile(project.profile_path).history)


def test_activation_needs_at_least_one_test_and_a_valid_file(project: Project) -> None:
    path = new_rule("language", "tiny", project, extension=".tny")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["tests"] = []
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(RuleWorkflowError, match="at least one test"):
        activate_rule(path)
    data["version"] = "x"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    check = validate_rule(path)
    assert check.errors and "key 'version'" in check.errors[0]
    with pytest.raises(RuleWorkflowError, match="key 'version'"):
        activate_rule(path)


def test_activation_refuses_an_ambiguous_selection(project: Project) -> None:
    new_rule("language", "tiny", project, extension=".tny")
    activate_rule(project.rules_dir / "languages" / "tiny" / "language.yaml")
    other = new_rule("language", "other", project, extension=".tny")
    with pytest.raises(RuleWorkflowError, match="ambiguous extension"):
        activate_rule(other)
    assert yaml.safe_load(other.read_text(encoding="utf-8"))["status"] == "proposed"  # left unchanged


# ----------------------------------------------------------------- bridges and project packs
def _write_c_fortran_repo(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "main.c").write_text("void run(void) { CALL_SOLVE(); }\n", encoding="utf-8")
    (folder / "solve.f90").write_text("subroutine solve\nend subroutine solve\n", encoding="utf-8")


def test_bridge_template_tests_and_activation(project: Project) -> None:
    from codegraph_sci.inventory.profile_io import load_profile
    from codegraph_sci.scan import load_bridge_rules

    path = new_rule("bridge", "c_calls", project)
    assert path == project.rules_dir / "bridges" / "c_calls.yaml"
    check = validate_rule(path)
    assert (check.kind, check.errors) == ("bridge", [])
    results = run_rule_tests(path)
    assert results and all(r.passed for r in results), [r.details for r in results]
    activate_rule(path)
    profile = load_profile(project.profile_path)
    [ref] = [r for r in profile.rules if r.kind == "bridge"]
    assert (ref.id, ref.status, ref.source, ref.file) == ("c_calls", "approved", "manual", "rules/bridges/c_calls.yaml")
    rules = load_bridge_rules(project, profile)
    assert [(r["from"], r["to"], r["id"]) for r in rules] == [("c", "fortran", "c_calls")]


def test_bridge_negative_expectation_fails_when_the_edge_exists(project: Project) -> None:
    path = new_rule("bridge", "c_calls", project)
    expected = next((path.parent / "tests").glob("*.expected.json"))
    data = json.loads(expected.read_text(encoding="utf-8"))
    data["absent_edges"] = data["edges"]
    expected.write_text(json.dumps(data), encoding="utf-8")
    results = run_rule_tests(path)
    assert not all(r.passed for r in results)
    assert any("unexpected edge" in d for r in results for d in r.details)


def test_bridge_with_an_unsafe_declaration_pattern_is_invalid(project: Project) -> None:
    path = new_rule("bridge", "c_calls", project)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["rule"]["declaration_patterns"] = ["(a+)+"]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    [error] = validate_rule(path).errors
    assert "key 'rule/declaration_patterns/0'" in error and "nested quantifier" in error


def test_project_pack_template_tests_and_activation(project: Project) -> None:
    from codegraph_sci.enrich.packs import default_search_paths, find_pack
    from codegraph_sci.inventory.profile_io import load_profile

    path = new_rule("project", "acme_conventions", project)
    assert path == project.rules_dir / "projects" / "acme_conventions.yaml"
    assert validate_rule(path).errors == []
    results = run_rule_tests(path)
    assert results and all(r.passed for r in results), [r.details for r in results]
    activate_rule(path)
    assert "acme_conventions" in load_profile(project.profile_path).packs
    assert find_pack("acme_conventions", default_search_paths(project.folder)) == path


# ----------------------------------------------------------------- command line
def test_cli_rules_commands(project: Project, capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    try:
        assert main(["rules", "new", "language", "tiny", str(project.root), "--project", str(project.folder),
                     "--extension", ".tny"]) == 0
        path = project.rules_dir / "languages" / "tiny" / "language.yaml"
        assert str(path) in capsys.readouterr().out
        assert main(["rules", "validate", str(path)]) == 0
        assert main(["rules", "test", str(path)]) == 0
        assert "PASS" in capsys.readouterr().out
        assert main(["rules", "activate", str(path)]) == 0
        expected = path.parent / "tests" / "basic.expected.json"
        expected.write_text(json.dumps({"definitions": []}), encoding="utf-8")
        assert main(["rules", "test", str(path)]) == 1
        assert "FAIL" in capsys.readouterr().out
        path.write_text("language: [\n", encoding="utf-8")
        assert main(["rules", "validate", str(path)]) == 1
        assert "invalid YAML" in capsys.readouterr().out
    finally:
        netguard.uninstall()


# ----------------------------------------------------------------- the guide, followed literally
def _guide_files() -> dict[str, str]:
    """Files of the tutorial: a fenced block preceded by ``<!-- file: <relative path> -->``."""
    text = GUIDE.read_text(encoding="utf-8")
    blocks = re.findall(r"<!-- file: (\S+) -->\s*```[a-z]*\n(.*?)```", text, re.S)
    return {name: body for name, body in blocks}


def test_guide_documents_every_required_topic() -> None:
    text = GUIDE.read_text(encoding="utf-8").lower()
    for topic in ("definition matching", "name and scope capture", "call versus declaration",
                  "comments and strings", "imports and includes", "source coordinates", "limitations",
                  "resource limits", "rules/languages", "rules/bridges", "rules/projects",
                  "cgs rules new", "cgs rules validate", "cgs rules test", "cgs rules activate"):
        assert topic in text, topic


def test_a_language_package_is_created_and_tested_from_the_guide_alone(project: Project) -> None:
    """Acceptance of phase 4: write the tutorial files, validate, test, activate and analyze."""
    from codegraph_sci.query.api import GraphQuery
    from codegraph_sci.scan import ScanOptions, scan

    files = _guide_files()
    package = [name for name in files if name.endswith("language.yaml")]
    assert len(package) == 1 and any(name.endswith(".expected.json") for name in files)
    for name, body in files.items():
        target = project.rules_dir / name if name.startswith("languages/") else project.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    path = project.rules_dir / package[0]
    assert validate_rule(path).errors == []
    assert all(r.passed for r in run_rule_tests(path)), [r.details for r in run_rule_tests(path)]
    activate_rule(path)
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    stats = scan(project, ScanOptions(jobs=1)).stats
    assert stats["files_source"] >= 1 and stats["files_failed"] == 0
    with GraphQuery(project.db_path) as q:  # what the guide says the analysis finds
        [main] = [n for n in q.resolve("main") if n.lang == data["language"]]
        callees = sorted(item.node.display_name for item in q.callees(main.uid).items)
    assert callees == ["report", "start"]
