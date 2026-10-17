"""Rule workflow (requirements plan phase 4): create, validate, test and activate rules.

Layout of a project's rules (``<project>/rules/``)::

    languages/<name>/language.yaml        language package (format 1), with tests/<case>.source + .expected.json
    bridges/<name>.yaml                   bridge rule (bridge format 1), with tests/<name>_<case>/ repositories
    projects/<name>.yaml                  project pack (pack format 1), with validation repositories

A rule is created ``proposed`` from a template; activation validates it, runs its tests (at least one, all must
pass) and only then approves it. Everything here is deterministic and never uses the AI. Guide:
``docs/rules/README.md``.
"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Any

import yaml

from codegraph_sci.core.facts import FileFacts, SourceFile
from codegraph_sci.core.plugins import ExtractContext, decode_bytes
from codegraph_sci.core.profile import AnalysisProfile, HistoryEntry, RuleRef
from codegraph_sci.core.project import PROJECT_FILE, Project, open_project
from codegraph_sci.enrich.packs import PackError, load_bridge_file, load_pack_file
from codegraph_sci.extract.registry import (
    LanguagePackage,
    LanguagePackageError,
    adapters_from_specs,
    load_package_file,
    load_registry,
    parse_package,
    user_folder,
)
from codegraph_sci.inventory.profile_io import ConfigError, load_profile, profile_from_inventory, save_profile
from codegraph_sci.inventory.run import run_inventory
from codegraph_sci.inventory.table import load_table

KINDS = ("language", "bridge", "project")
FOLDERS = {"language": "languages", "bridge": "bridges", "project": "projects"}


class RuleWorkflowError(RuntimeError):
    """A rule cannot be created or activated; the message says why."""


@dataclass
class RuleCheck:
    path: Path
    kind: str | None  # language, bridge, project (None if the file cannot be read)
    name: str | None
    errors: list[str] = field(default_factory=list)


@dataclass
class RuleTestResult:
    name: str
    passed: bool
    details: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ creation
def _template(kind: str) -> Traversable:
    return resources.files("codegraph_sci.templates").joinpath("rules", kind)


def _copy_tree(source: Traversable, target: Path, replace: dict[str, str]) -> None:
    for entry in sorted(source.iterdir(), key=lambda e: e.name):
        name = entry.name
        if entry.is_dir():
            _copy_tree(entry, target / name, replace)
            continue
        text = entry.read_text(encoding="utf-8")
        for old, new in replace.items():
            text = text.replace(old, new)
        target.mkdir(parents=True, exist_ok=True)
        (target / name).write_bytes(text.encode("utf-8"))


def new_rule(kind: str, name: str, project: Project, *, extension: str | None = None) -> Path:
    """Create a rule from its template in the project's ``rules/`` folder; returns the rule file (proposed)."""
    if kind not in KINDS:
        raise RuleWorkflowError(f"unknown rule kind {kind!r} (expected one of {', '.join(KINDS)})")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise RuleWorkflowError(f"invalid name {name!r}: lower case letters, digits and _, starting with a letter")
    ext = extension or f".{name[:8]}"
    if not re.fullmatch(r"\.[\w+-]+", ext):
        raise RuleWorkflowError(f"invalid extension {ext!r}: a dot followed by letters, digits, _, + or -")
    folder = project.rules_dir / FOLDERS[kind]
    replace = {"__NAME__": name, "__EXTENSION__": ext}
    template = _template(kind)
    if kind == "language":
        target = folder / name
        path = target / "language.yaml"
        if target.exists():
            raise RuleWorkflowError(f"{target} already exists")
        _copy_tree(template, target, replace)
        _write_expected(path)
        return path
    path = folder / f"{name}.yaml"
    tests = folder / "tests" / f"{name}_basic"
    if path.exists() or tests.exists():
        raise RuleWorkflowError(f"{path} already exists")
    folder.mkdir(parents=True, exist_ok=True)
    text = template.joinpath(f"{kind}.yaml").read_text(encoding="utf-8")
    for old, new in replace.items():
        text = text.replace(old, new)
    path.write_bytes(text.encode("utf-8"))
    _copy_tree(template.joinpath("tests", "basic"), tests, replace)
    expected = template.joinpath("tests", "basic.expected.json").read_text(encoding="utf-8")
    (folder / "tests" / f"{name}_basic.expected.json").write_bytes(expected.encode("utf-8"))
    return path


def _write_expected(path: Path) -> None:
    """Expected results of the template's test case, written from the extraction of its own source: the user
    starts from a passing test and edits both sides."""
    package = parse_package(yaml.safe_load(path.read_text(encoding="utf-8")), str(path), "project")
    for test in package.tests:
        facts = _extract(package, path.parent / test["source"], test["source"])
        (path.parent / test["expected"]).write_bytes(
            (json.dumps(facts_view(facts), indent=1, ensure_ascii=False) + "\n").encode("utf-8"))


# ------------------------------------------------------------------ validation
def _load_yaml(path: Path) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RuleWorkflowError(f"{path}: invalid YAML (only plain data is accepted): {exc}") from exc
    except OSError as exc:
        raise RuleWorkflowError(f"{path}: unreadable: {exc}") from exc


def rule_kind(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    if "package_format" in data or "definitions" in data:
        return "language"
    if "bridge_format" in data:
        return "bridge"
    if "pack" in data:
        return "project"
    return None


def validate_rule(path: Path) -> RuleCheck:
    """Syntax, schema, pattern limits and declared test files of a rule file."""
    path = Path(path)
    try:
        data = _load_yaml(path)
    except RuleWorkflowError as exc:
        return RuleCheck(path, None, None, [str(exc)])
    kind = rule_kind(data)
    if kind is None:
        return RuleCheck(path, None, None, [f"{path}: not a language package, bridge rule or project pack"])
    name = str(data.get("language") or data.get("name") or data.get("pack") or "") or None
    try:
        if kind == "language":
            load_package_file(path, "project")
        elif kind == "bridge":
            bridge = load_bridge_file(path)
            _check_repo_tests(path, bridge.tests)
        else:
            load_pack_file(path)
            if name != path.stem and path.name != "rules.yaml":
                raise RuleWorkflowError(f"{path}: key 'pack': {name!r} must match the file name {path.stem!r}")
            _check_repo_tests(path, list(data.get("validation", [])))
    except (LanguagePackageError, PackError, RuleWorkflowError, ConfigError) as exc:
        return RuleCheck(path, kind, name, [str(exc)])
    return RuleCheck(path, kind, name, [])


def _check_repo_tests(path: Path, tests: list[dict[str, str]]) -> None:
    for i, test in enumerate(tests):
        if not (path.parent / test["repo"]).is_dir():
            raise RuleWorkflowError(f"{path}: key 'tests/{i}/repo': folder {test['repo']!r} not found")
        if not (path.parent / test["expected"]).is_file():
            raise RuleWorkflowError(f"{path}: key 'tests/{i}/expected': file {test['expected']!r} not found")


# ------------------------------------------------------------------ tests
def facts_view(facts: FileFacts) -> dict[str, Any]:
    """What a language test compares: definitions and references with their source coordinates."""
    names = {d.uid: d.display_name for d in facts.definitions}
    definitions = sorted(({"name": d.display_name, "kind": d.kind, "line_start": d.span[0], "line_end": d.span[1],
                           "parent": names.get(d.parent) if d.parent else None} for d in facts.definitions),
                         key=lambda d: (d["line_start"], d["name"]))
    references = sorted(({"from": names.get(r.src), "target": r.target_text, "kind": r.kind, "line": r.line,
                          "col": r.col} for r in facts.references),
                        key=lambda r: (r["line"], r["col"], r["target"], r["kind"]))
    return {"definitions": definitions, "references": references}


def _extract(package: LanguagePackage, source: Path, rel: str) -> FileFacts:
    adapter = adapters_from_specs([package.spec()])[package.language]
    text, encoding = decode_bytes(source.read_bytes())
    return adapter.extract(SourceFile(rel, package.language, None, encoding, text), ExtractContext())


def _compare(label: str, expected: list[dict[str, Any]], actual: list[dict[str, Any]]) -> list[str]:
    def key(item: dict[str, Any]) -> str:
        return json.dumps(item, sort_keys=True, ensure_ascii=False)

    want, got = {key(i) for i in expected}, {key(i) for i in actual}
    return ([f"missing {label}: {k}" for k in sorted(want - got)]
            + [f"unexpected {label}: {k}" for k in sorted(got - want)])


def _language_tests(path: Path) -> list[RuleTestResult]:
    package = load_package_file(path, "project")
    out = []
    for test in package.tests:
        facts = _extract(package, path.parent / test["source"], test["source"])
        expected = json.loads((path.parent / test["expected"]).read_text(encoding="utf-8"))
        actual = facts_view(facts)
        details: list[str] = []
        for section, label in (("definitions", "definition"), ("references", "reference")):
            if section in expected:  # a section left out of the expected file is not compared
                details += _compare(label, list(expected[section]), actual[section])
        details += [f"extraction error line {e.line}: {e.message}" for e in facts.errors
                    if not expected.get("allow_errors")]
        out.append(RuleTestResult(test["source"], not details, details))
    return out


def _repo_edges(repo: Path, *, bridge: dict[str, Any] | None = None, pack: Path | None = None) -> set[tuple[str, ...]]:
    """Edges (source uid, target uid, kind) of a small repository scanned with one rule only."""
    from codegraph_sci.scan import ScanOptions, scan
    from codegraph_sci.store.db import open_db

    with tempfile.TemporaryDirectory(prefix="cgs-rule-test-", ignore_cleanup_errors=True) as tmp:
        project = open_project(repo, Path(tmp) / "project")
        options = ScanOptions(jobs=1, bridge_rules=[bridge] if bridge else [])
        if pack is not None:
            name = str(yaml.safe_load(pack.read_text(encoding="utf-8"))["pack"])
            target = project.folder / "packs" / name
            target.mkdir(parents=True)
            shutil.copyfile(pack, target / "rules.yaml")
            options.packs = [name]
        scan(project, options)
        con = open_db(project.db_path)
        try:
            return {tuple(row) for row in con.execute(
                "SELECT s.uid, d.uid, e.kind FROM edges e JOIN nodes s ON s.id = e.src JOIN nodes d ON d.id = e.dst")}
        finally:
            con.close()


def _repo_tests(path: Path, tests: list[dict[str, str]], **rule: Any) -> list[RuleTestResult]:
    out = []
    for test in tests:
        edges = _repo_edges(path.parent / test["repo"], **rule)
        expected = json.loads((path.parent / test["expected"]).read_text(encoding="utf-8"))
        details = [f"missing edge: {e['src']} -> {e['dst']} ({e['kind']})" for e in expected.get("edges", [])
                   if (e["src"], e["dst"], e["kind"]) not in edges]
        details += [f"unexpected edge: {e['src']} -> {e['dst']} ({e['kind']})" for e in expected.get("absent_edges", [])
                    if (e["src"], e["dst"], e["kind"]) in edges]
        out.append(RuleTestResult(test["repo"], not details, details))
    return out


def run_rule_tests(path: Path) -> list[RuleTestResult]:
    """Run the test cases declared by a valid rule file (raises ``RuleWorkflowError`` if it is invalid)."""
    path = Path(path)
    check = validate_rule(path)
    if check.errors:
        raise RuleWorkflowError(check.errors[0])
    if check.kind == "language":
        return _language_tests(path)
    if check.kind == "bridge":
        bridge = load_bridge_file(path)
        return _repo_tests(path, bridge.tests, bridge={**bridge.rule, "id": bridge.name})
    data = _load_yaml(path)
    return _repo_tests(path, list(data.get("validation", [])), pack=path)


# ------------------------------------------------------------------ activation
def find_project(path: Path) -> Project | None:
    """Project whose folder contains ``path`` (it holds ``project.json``), if any."""
    for parent in Path(path).resolve().parents:
        if (parent / PROJECT_FILE).is_file():
            return open_project(folder=parent)
    return None


def _profile(project: Project) -> AnalysisProfile:
    """The project's analysis profile, created from an inventory (as a first scan would) if it does not exist."""
    if project.profile_path.is_file():
        return load_profile(project.profile_path)
    profile = profile_from_inventory(run_inventory(project.root))
    project.folder.mkdir(parents=True, exist_ok=True)
    save_profile(project.profile_path, profile)
    return profile


def _set_status(text: str, status: str) -> str:
    """Set the top-level ``status`` key, keeping comments and layout."""
    line = re.compile(r"(?m)^status:[ \t]*[\"']?\w+[\"']?")
    if line.search(text):
        return line.sub(f"status: {status}", text, count=1)
    version = re.compile(r"(?m)^(version:.*)$")
    if version.search(text):
        return version.sub(lambda m: f"{m.group(1)}\nstatus: {status}", text, count=1)
    return f"status: {status}\n{text}"


def activate_rule(path: Path) -> str:
    """Validate, test (at least one test, all passing), then approve a rule. Returns a summary."""
    path = Path(path).resolve()
    check = validate_rule(path)
    if check.errors:
        raise RuleWorkflowError(check.errors[0])
    results = run_rule_tests(path)
    if not results:
        raise RuleWorkflowError(f"{path}: at least one test case is required before activation")
    failed = [r.name for r in results if not r.passed]
    if failed:
        raise RuleWorkflowError(f"{path}: tests failed: {', '.join(failed)} (run: cgs rules test {path})")
    project = find_project(path)
    tests = f"{len(results)} test{'s' if len(results) != 1 else ''} passed"
    if check.kind == "language":
        return _activate_language(path, str(check.name), project, tests)
    if project is None:
        raise RuleWorkflowError(f"{path}: bridge rules and project packs belong to a project's rules/ folder")
    folder = project.rules_dir / FOLDERS[str(check.kind)]
    if path.parent != folder.resolve():
        raise RuleWorkflowError(f"{path}: place the file in {folder}")
    profile = _profile(project)
    name = str(check.name)
    if check.kind == "bridge":
        source = str((load_bridge_file(path).provenance or {}).get("source", "manual"))
        profile.rules = [r for r in profile.rules if r.id != name]
        profile.rules.append(RuleRef(name, "bridge", source if source in ("ai", "manual") else "manual", "approved",
                                     f"rules/{FOLDERS['bridge']}/{path.name}"))
    elif name not in profile.packs:
        profile.packs.append(name)
    profile.profile_version += 1
    profile.history.append(HistoryEntry(profile.profile_version, f"{check.kind} {name} activated ({tests})", "user"))
    save_profile(project.profile_path, profile)
    return f"{check.kind} {name} activated ({tests})"


def _activate_language(path: Path, language: str, project: Project | None, tests: str) -> str:
    user = user_folder().resolve()
    in_project = project is not None and path.is_relative_to((project.rules_dir / "languages").resolve())
    if not in_project and not path.is_relative_to(user):
        raise RuleWorkflowError(f"{path}: place the package in <project>/rules/languages/ or {user}")
    original = path.read_text(encoding="utf-8")
    path.write_bytes(_set_status(original, "approved").encode("utf-8"))
    profile = _profile(project) if project is not None else None
    try:
        statuses = {lang: e.status for lang, e in (profile.languages.items() if profile else [])}
        statuses[language] = "approved"
        load_registry(project.rules_dir / "languages" if project is not None else None, profile_status=statuses,
                      reserved_extensions=load_table().ambiguous)
    except LanguagePackageError as exc:
        path.write_bytes(original.encode("utf-8"))
        raise RuleWorkflowError(str(exc)) from exc
    if project is not None and profile is not None:
        if language in profile.languages:
            profile.languages[language].status = "approved"
        profile.profile_version += 1
        profile.history.append(HistoryEntry(profile.profile_version, f"language {language} activated ({tests})",
                                            "user"))
        save_profile(project.profile_path, profile)
    return f"language {language} activated ({tests})"
