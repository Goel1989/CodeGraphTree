"""Phase 3 of the requirements plan: unified language packages.

Every language, native or keyword-based, is described by a versioned package and selected by one documented
registry (built-in < user < project < explicit). A new language is installed and analyzed without changing the
core, and an ambiguous selection is rejected with a message naming both files.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from codegraph_sci.core.facts import SourceFile
from codegraph_sci.core.plugins import ExtractContext
from codegraph_sci.extract.registry import (
    LanguagePackageError,
    builtin_packages,
    load_registry,
    package_files,
)

TINY_RULES: dict[str, Any] = {
    "case_sensitive": False,
    "comments": {"line": ["--"]},
    "strings": ['"'],
    "definitions": [{"keywords": ["task"], "name": "after_keyword", "end_keywords": ["done"], "kind": "routine"}],
    "calls": [{"keywords": ["do"], "name": "after_keyword"}],
}
MAIN = 'task main\n  do prepare\n  -- do commented\n  print "do quoted"\ndone\n'
LIB = "task prepare\n  do helper\ndone\n\ntask helper\ndone\n"


def tiny_package(folder: Path, language: str = "tiny", **extra: Any) -> Path:
    """A complete package folder: manifest, declared test case and its expected result."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "tests").mkdir(exist_ok=True)
    (folder / "tests" / "sample.tny").write_text(MAIN, encoding="utf-8")
    (folder / "tests" / "sample.expected.json").write_text(json.dumps({"definitions": ["main"]}), encoding="utf-8")
    data: dict[str, Any] = {
        "package_format": 1, "language": language, "version": "1.0", "extensions": [".tny"],
        "detection": {"filenames": ["Tinyfile"], "shebangs": ["tiny"]},
        "dialects": ["tiny1"], "backend": "keywords", "rules": TINY_RULES,
        "naming": {"case_sensitive": False, "qualification": "lexical"},
        "relationships": ["calls"], "resolution": {"confidence": "heuristic", "capabilities": ["names"]},
        "limitations": ["no scopes beyond nesting"],
        "tests": [{"source": "tests/sample.tny", "expected": "tests/sample.expected.json"}],
        "provenance": {"source": "manual", "author": "test suite"},
        **extra,
    }
    path = folder / "package.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def test_builtin_packages_describe_the_native_adapters() -> None:
    from codegraph_sci.inventory.table import load_table

    packages = {p.language: p for p in builtin_packages()}
    assert sorted(packages) == ["c", "cpp", "fortran", "python"]
    table = load_table()
    for language, package in packages.items():
        assert package.backend == f"native:{language}" and package.level == "builtin"
        assert package.provenance["source"] == "builtin" and package.limitations and package.relationships
        assert package.resolution["capabilities"] and package.naming["qualification"]
        declared = {e for e in package.extensions}
        from_table = {e for e, (lang, _v) in table.lang_by_ext.items() if lang == language}
        from_table |= {e for e, lang in table.exact.items() if lang == language}
        assert declared == from_table, language  # the package and the inventory table agree
    registry = load_registry()
    assert list(registry.packages) == ["c", "cpp", "fortran", "python"]
    assert registry.added() == [] and registry.extensions() == {}
    assert {lang: type(a).__name__ for lang, a in registry.adapters().items()} == {
        "c": "CAdapter", "cpp": "CppAdapter", "fortran": "FortranAdapter", "python": "PythonAdapter"}


def test_a_new_language_is_installed_and_analyzed_without_changing_the_core(tmp_path: Path) -> None:
    """Acceptance of phase 3: a package in the project folder, then a scan."""
    from codegraph_sci.core.project import open_project
    from codegraph_sci.query.api import GraphQuery
    from codegraph_sci.scan import ScanOptions, scan

    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "main.tny").write_text(MAIN, encoding="utf-8")
    (repo / "src" / "lib.tny").write_text(LIB, encoding="utf-8")
    project = open_project(repo, tmp_path / "proj")
    tiny_package(project.rules_dir / "languages" / "tiny")
    stats = scan(project, ScanOptions(jobs=1)).stats
    assert stats["files_source"] == 2 and stats["files_failed"] == 0
    with GraphQuery(project.db_path) as q:
        main = q.resolve("main")
        assert [n.uid for n in main] == ["kw:tiny:main@src/main.tny"]
        callees = q.callees("kw:tiny:main@src/main.tny")
        assert [item.node.uid for item in callees.items] == ["kw:tiny:prepare@src/lib.tny"]
        assert [n.uid for n in q.resolve("helper")] == ["kw:tiny:helper@src/lib.tny"]
        languages = {line.lang: line.adapter for line in q.inventory().languages}
    assert languages == {"tiny": "keywords:tiny"}


def test_user_level_package_covers_a_language_known_but_not_covered(tmp_path: Path) -> None:
    from codegraph_sci.inventory.run import LanguageHints, run_inventory

    user = tmp_path / "user"
    tiny_package(user / "julia", language="julia", extensions=[".jl"])
    registry = load_registry(user=user)
    assert registry.packages["julia"].level == "user"
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.jl").write_text(MAIN, encoding="utf-8")
    (repo / "Tinyfile").write_text(LIB, encoding="utf-8")
    (repo / "run").write_text("#!/usr/bin/env tiny\n" + LIB, encoding="utf-8")
    hints = LanguageHints(registry.extensions(), registry.filenames(), registry.shebangs(), registry.adapter_names())
    result = run_inventory(repo, hints=hints)
    found = {e.path: (e.lang, e.status, e.decided_by) for e in result.entries}
    assert found["a.jl"] == ("julia", "source", "extension:.jl")  # the package wins over "not covered"
    assert found["Tinyfile"] == ("julia", "source", "package:filename")
    assert found["run"] == ("julia", "source", "package:shebang:tiny")
    assert result.coverage["julia"].adapter == "keywords:julia"
    without = {e.path: e.status for e in run_inventory(repo).entries}
    assert without["a.jl"] == "not_covered"


def test_legacy_keyword_profile_is_read_as_a_keyword_package(tmp_path: Path) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "keywords_language" / "profile" / "acme_script.yaml"
    registry = load_registry(explicit=[fixture])
    package = registry.packages["acme_script"]
    assert (package.backend, package.level, package.legacy) == ("keywords", "explicit", True)
    assert registry.extensions() == {".acs": "acme_script"}
    from codegraph_sci.extract.keywords import KeywordAdapter, load_keyword_profile

    # Same adapter version as before the registry: existing caches stay valid.
    assert registry.adapters()["acme_script"].version == KeywordAdapter(load_keyword_profile(fixture)).version


def test_precedence_and_explicit_override(tmp_path: Path) -> None:
    user, project = tmp_path / "user", tmp_path / "project"
    tiny_package(user / "tiny")
    tiny_package(project / "tiny", overrides=True, version="2.0")
    registry = load_registry(project, user=user)
    assert (registry.packages["tiny"].level, registry.packages["tiny"].version) == ("project", "2.0")
    assert [(i.package.level, i.reason.split(" ")[0]) for i in registry.inactive] == [("user", "replaced")]
    # Replacing a built-in language needs the same explicit declaration.
    tiny_package(project / "py", language="python", extensions=[".py"], overrides=True, detection={})
    registry = load_registry(project, user=user)
    assert registry.packages["python"].backend == "keywords"
    assert registry.adapter_names()["python"] == "keywords:python"


@pytest.mark.parametrize("case", ["same_level", "no_override", "builtin_no_override", "extension", "builtin_extension",
                                  "reserved", "unknown_backend"])
def test_ambiguous_or_invalid_selection_is_rejected(tmp_path: Path, case: str) -> None:
    user, project = tmp_path / "user", tmp_path / "project"
    if case == "same_level":
        tiny_package(project / "one")
        tiny_package(project / "two")
        message = "ambiguous language package selection for 'tiny'"
    elif case == "no_override":
        tiny_package(user / "tiny")
        tiny_package(project / "tiny")
        message = "declare 'overrides: true'"
    elif case == "builtin_no_override":
        tiny_package(project / "py", language="python", extensions=[".py"])
        message = "already provided by the builtin package"
    elif case == "extension":
        tiny_package(project / "tiny")
        tiny_package(project / "other", language="other")
        message = "ambiguous extension '.tny'"
    elif case == "builtin_extension":
        tiny_package(project / "tiny", extensions=[".F90"])
        message = "ambiguous extension '.F90'"
    elif case == "reserved":
        tiny_package(project / "tiny", extensions=[".h"])
        message = "decided by content"
    else:
        path = tiny_package(project / "tiny")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        del data["rules"]
        data["backend"] = "native:tinyparser"
        path.write_text(yaml.safe_dump(data), encoding="utf-8")
        message = "native backend 'tinyparser' is not installed"
    with pytest.raises(LanguagePackageError, match=message.replace("(", r"\(").replace(".", r"\.")):
        load_registry(project, user=user, reserved_extensions=[".h"])


def test_invalid_packages_name_the_file_and_key(tmp_path: Path) -> None:
    project = tmp_path / "project"
    path = tiny_package(project / "tiny")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["version"] = "one"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(LanguagePackageError, match=r"package\.yaml: key 'version'"):
        load_registry(project)
    data["version"] = "1.0"
    data["tests"] = [{"source": "tests/missing.tny", "expected": "tests/sample.expected.json"}]
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(LanguagePackageError, match=r"key 'tests': source file 'tests/missing\.tny' not found"):
        load_registry(project)
    data["tests"] = []
    data["rules"] = {"definitions": "nope"}
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(LanguagePackageError, match=r"\(rules\): key 'definitions'"):
        load_registry(project)
    path.write_text("!!python/object/apply:os.system ['echo unsafe']\n", encoding="utf-8")
    with pytest.raises(LanguagePackageError, match="invalid YAML"):
        load_registry(project)


def test_unapproved_packages_stay_inactive(tmp_path: Path) -> None:
    project = tmp_path / "project"
    tiny_package(project / "tiny", status="proposed")
    tiny_package(project / "other", language="other", extensions=[".oth"])
    registry = load_registry(project, profile_status={"other": "rejected"})
    assert "tiny" not in registry.packages and "other" not in registry.packages
    assert sorted((i.package.language, i.reason) for i in registry.inactive) == [
        ("other", "rejected in the analysis profile"), ("tiny", "status proposed")]
    assert package_files(project) == [project / "other" / "package.yaml", project / "tiny" / "package.yaml"]


def test_installed_native_backend_through_the_entry_point_group(tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    import codegraph_sci.extract.registry as registry_module
    from codegraph_sci.core.facts import Definition, FileFacts

    class ToyAdapter:
        name, version, languages = "toy", "0.1", ["toy"]

        def extract(self, file: SourceFile, ctx: ExtractContext) -> FileFacts:
            return FileFacts(path=file.path, lang=file.lang, encoding=file.encoding, adapter=self.name,
                             adapter_version=self.version,
                             definitions=[Definition("toy:x", "x", "routine", "toy", "x", (1, 1))])

    class EntryPoint:
        name, value = "toyparser", "toy_package:factory"

        def load(self) -> Any:
            return ToyAdapter

    monkeypatch.setattr(registry_module, "entry_points",
                        lambda group: [EntryPoint()] if group == registry_module.BACKEND_GROUP else [])
    project = tmp_path / "project"
    path = tiny_package(project / "toy", language="toy", extensions=[".toy"])
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    del data["rules"]
    data["backend"] = "native:toyparser"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    registry = load_registry(project)
    adapter = registry.adapters()["toy"]
    facts = adapter.extract(SourceFile("a.toy", "toy", None, "utf-8", "x"), ExtractContext())
    assert [d.uid for d in facts.definitions] == ["toy:x"]
    assert registry.adapter_names()["toy"] == "native:toyparser"


def test_cli_languages_lists_packages_with_their_level(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard
    from codegraph_sci.core.project import open_project

    repo = tmp_path / "repo"
    repo.mkdir()
    project = open_project(repo, tmp_path / "proj")
    tiny_package(project.rules_dir / "languages" / "tiny")
    tiny_package(project.rules_dir / "languages" / "draft", language="draft", extensions=[".drf"], status="proposed")
    try:
        assert main(["languages", str(repo), "--project", str(project.folder), "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert [(p["language"], p["level"], p["backend"]) for p in data["packages"]] == [
            ("c", "builtin", "native:c"), ("cpp", "builtin", "native:cpp"), ("fortran", "builtin", "native:fortran"),
            ("python", "builtin", "native:python"), ("tiny", "project", "keywords")]
        assert [(p["language"], p["reason"]) for p in data["inactive"]] == [("draft", "status proposed")]
        assert main(["languages", str(repo), "--project", str(project.folder)]) == 0
        text = capsys.readouterr().out
        assert "tiny" in text and "project" in text and "draft" in text
        tiny_package(project.rules_dir / "languages" / "tiny2")
        assert main(["languages", str(repo), "--project", str(project.folder)]) == 2
        assert "ambiguous language package selection" in capsys.readouterr().err
    finally:
        netguard.uninstall()
