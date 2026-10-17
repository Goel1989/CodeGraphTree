"""Language packages (requirements plan phase 3): one contract for every language, whatever its backend.

A language package declares its language, version, extensions and detection hints, dialects, backend, naming and
scope rules, relationship types, resolution capabilities, limitations, test cases and provenance
(``language_package.schema.json``). Two backends:

* ``keywords``: declarative keyword rules (§3.9), for simple languages, legacy formats and project DSLs;
* ``native:<name>``: a parser-backed adapter. The four built-in ones are listed in ``BUILTIN_BACKENDS``; others
  are installed separately and declare themselves in the entry point group ``codegraph_sci.language_backends``
  (a callable returning a ``LanguageAdapter``). Configuration files never execute code.

Packages are found at three levels, in increasing precedence: ``builtin`` (shipped in ``extract/languages/``),
``user`` (``<data dir>/languages/``) and ``project`` (``<project>/rules/languages/``); packages given explicitly
to a scan come last. Each level holds ``<name>.yaml`` files or ``<name>/package.yaml`` folders. A keyword profile
in the earlier format (§3.9) is read as a keyword package. Only approved packages are active. Selection is never
ambiguous: two active packages of one level for the same language, a package that replaces a lower-level one
without ``overrides: true``, or two languages claiming the same extension are errors that name both files.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib import resources
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from codegraph_sci.core.paths import data_dir
from codegraph_sci.core.patterns import check_rule_file_size
from codegraph_sci.core.plugins import LanguageAdapter

PACKAGE_FORMAT = 1
LEVELS = ("builtin", "user", "project", "explicit")
BACKEND_GROUP = "codegraph_sci.language_backends"
BUILTIN_BACKENDS = ("c", "cpp", "fortran", "python")
PACKAGE_FILES = ("language.yaml", "package.yaml")  # in a package folder (language.yaml: rule layout of phase 4)

# A package as handed to extraction workers: (language, backend, keyword rules or None).
PackageSpec = tuple[str, str, dict[str, Any] | None]


class LanguagePackageError(ValueError):
    """Invalid package or ambiguous selection: the message names the file(s), the key and the faulty value."""


@dataclass
class LanguagePackage:
    language: str
    version: str
    backend: str  # "keywords" or "native:<name>"
    level: str  # builtin, user, project, explicit
    path: str  # file it was read from
    status: str = "approved"
    overrides: bool = False
    description: str = ""
    extensions: list[str] = field(default_factory=list)
    filenames: list[str] = field(default_factory=list)
    shebangs: list[str] = field(default_factory=list)
    dialects: list[str] = field(default_factory=list)
    naming: dict[str, Any] = field(default_factory=dict)
    relationships: list[str] = field(default_factory=list)
    resolution: dict[str, Any] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    tests: list[dict[str, str]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] | None = None  # keyword backend: the keyword profile (§3.9 format)
    legacy: bool = False  # read from a keyword profile of the earlier format

    def spec(self) -> PackageSpec:
        return self.language, self.backend, self.rules

    def summary(self) -> dict[str, Any]:
        return {"language": self.language, "version": self.version, "backend": self.backend, "level": self.level,
                "path": self.path, "status": self.status, "extensions": list(self.extensions),
                "filenames": list(self.filenames), "shebangs": list(self.shebangs), "dialects": list(self.dialects),
                "overrides": self.overrides, "legacy": self.legacy, "relationships": list(self.relationships),
                "resolution": dict(self.resolution), "limitations": list(self.limitations),
                "tests": [dict(t) for t in self.tests], "provenance": dict(self.provenance)}


@dataclass
class InactivePackage:
    package: LanguagePackage
    reason: str


@dataclass
class LanguageRegistry:
    packages: dict[str, LanguagePackage]  # selected package of each language
    inactive: list[InactivePackage] = field(default_factory=list)

    def specs(self) -> list[PackageSpec]:
        return [self.packages[lang].spec() for lang in sorted(self.packages)]

    def adapters(self) -> dict[str, LanguageAdapter]:
        return adapters_from_specs(self.specs())

    def _hints(self, attribute: str) -> dict[str, str]:
        return {value: p.language for p in self.added() for value in getattr(p, attribute)}

    def added(self) -> list[LanguagePackage]:
        """Selected packages that are not built-in: the inventory learns their extensions and hints."""
        return [self.packages[lang] for lang in sorted(self.packages) if self.packages[lang].level != "builtin"]

    def extensions(self) -> dict[str, str]:
        return self._hints("extensions")

    def filenames(self) -> dict[str, str]:
        return self._hints("filenames")

    def shebangs(self) -> dict[str, str]:
        return self._hints("shebangs")

    def adapter_names(self) -> dict[str, str]:
        """Language -> adapter name as written in the analysis profile (``native:<name>``, ``keywords:<lang>``)."""
        return {lang: (p.backend if p.backend.startswith("native:") else f"keywords:{lang}")
                for lang, p in sorted(self.packages.items())}


def _schema(name: str, package: str = "codegraph_sci.extract") -> dict[str, Any]:
    data: dict[str, Any] = json.loads(resources.files(package).joinpath(name).read_text(encoding="utf-8"))
    return data


def _validate(data: Any, schema: dict[str, Any], origin: str) -> None:
    if not isinstance(data, dict):
        raise LanguagePackageError(f"{origin}: key '(root)': expected a mapping")
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(data),
                    key=lambda e: list(map(str, e.absolute_path)))
    if errors:
        err = errors[0]
        key = "/".join(str(p) for p in err.absolute_path) or "(root)"
        raise LanguagePackageError(f"{origin}: key '{key}': {err.message} (value: {err.instance!r})")


def _keyword_profile(rules: dict[str, Any], data: dict[str, Any], origin: str) -> dict[str, Any]:
    """The keyword rules of a package as a §3.9 keyword profile, validated by the keyword-profile schema."""
    profile = {"language": data["language"], "version": data["version"], "format_version": 1,
               "extensions": list(data["extensions"]), **rules}
    _validate(profile, _schema("language.schema.json", "codegraph_sci.extract.keywords"), f"{origin} (rules)")
    return profile


def parse_package(data: Any, origin: str, level: str) -> LanguagePackage:
    """A package from loaded YAML data (package format 1, or a §3.9 keyword profile)."""
    if isinstance(data, dict) and "package_format" not in data and "definitions" in data:
        _validate(data, _schema("language.schema.json", "codegraph_sci.extract.keywords"), origin)
        source = str(data.get("source", "manual"))
        return LanguagePackage(str(data["language"]), str(data["version"]), "keywords", level, origin,
                               status=str(data.get("status", "approved")), extensions=list(data["extensions"]),
                               naming={"case_sensitive": bool(data.get("case_sensitive", False)),
                                       "qualification": "lexical"},
                               relationships=["calls", "maybe_calls", "includes"],
                               resolution={"confidence": "heuristic", "capabilities": ["names"]},
                               limitations=["Keyword extraction is heuristic: no scopes beyond nesting, no types, "
                                            "no overloads."],
                               provenance={"source": source}, rules=dict(data), legacy=True)
    _validate(data, _schema("language_package.schema.json"), origin)
    detection = data.get("detection") or {}
    rules = data.get("rules")
    return LanguagePackage(
        str(data["language"]), str(data["version"]), str(data["backend"]), level, origin,
        status=str(data.get("status", "approved")), overrides=bool(data.get("overrides", False)),
        description=str(data.get("description", "")), extensions=list(data["extensions"]),
        filenames=list(detection.get("filenames", [])), shebangs=list(detection.get("shebangs", [])),
        dialects=list(data.get("dialects", [])), naming=dict(data.get("naming") or {}),
        relationships=list(data.get("relationships", [])), resolution=dict(data.get("resolution") or {}),
        limitations=list(data.get("limitations", [])), tests=[dict(t) for t in data.get("tests", [])],
        provenance=dict(data["provenance"]),
        rules=_keyword_profile(dict(rules), data, origin) if rules is not None else None)


def load_package_file(path: Path, level: str) -> LanguagePackage:
    try:
        size_problem = check_rule_file_size(path.stat().st_size)
        if size_problem is not None:
            raise LanguagePackageError(f"{path}: {size_problem}")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise LanguagePackageError(f"{path}: invalid YAML (only plain data is accepted): {exc}") from exc
    except OSError as exc:
        raise LanguagePackageError(f"{path}: unreadable: {exc}") from exc
    package = parse_package(data, str(path), level)
    if package.level != "builtin":
        for test in package.tests:  # declared test cases must exist next to the package
            for key in ("source", "expected"):
                if not (path.parent / test[key]).exists():
                    raise LanguagePackageError(f"{path}: key 'tests': {key} file {test[key]!r} not found")
    return package


def package_files(folder: Path) -> list[Path]:
    """``<name>.yaml`` files and ``<name>/language.yaml`` (or ``package.yaml``) folders, sorted by name."""
    if not folder.is_dir():
        return []
    found = [p for p in folder.glob("*.yaml") if p.is_file()]
    for sub in folder.iterdir():
        manifests = [sub / name for name in PACKAGE_FILES if (sub / name).is_file()]
        if len(manifests) > 1:
            raise LanguagePackageError(f"{sub}: both {' and '.join(PACKAGE_FILES)}: keep one package manifest")
        found += manifests
    return sorted(found, key=lambda p: p.as_posix())


def builtin_packages() -> list[LanguagePackage]:
    folder = resources.files("codegraph_sci.extract").joinpath("languages")
    out = []
    for name in sorted(e.name for e in folder.iterdir() if e.name.endswith(".yaml")):
        data = yaml.safe_load(folder.joinpath(name).read_text(encoding="utf-8"))
        out.append(parse_package(data, f"builtin:{name}", "builtin"))
    return out


def user_folder() -> Path:
    return data_dir() / "languages"


def load_registry(project_folder: Path | None = None, *, explicit: Iterable[Path] = (),
                  profile_status: dict[str, str | None] | None = None,
                  reserved_extensions: Iterable[str] = (), user: Path | None = None) -> LanguageRegistry:
    """Select one package per language.

    ``project_folder``: the project's ``rules/languages`` folder. ``profile_status``: language -> status recorded
    in the analysis profile; a project package whose language is ``proposed`` or ``rejected`` there stays
    inactive (AI proposals need approval). ``reserved_extensions``: extensions the inventory decides by content
    (such as ``.h``), which no package may claim.
    """
    candidates = list(builtin_packages())
    candidates += [load_package_file(p, "user") for p in package_files(user if user is not None else user_folder())]
    if project_folder is not None:
        candidates += [load_package_file(p, "project") for p in package_files(project_folder)]
    candidates += [load_package_file(Path(p), "explicit") for p in explicit]
    gate = profile_status or {}
    selected: dict[str, LanguagePackage] = {}
    inactive: list[InactivePackage] = []
    for level in LEVELS:
        active: dict[str, LanguagePackage] = {}
        for package in (c for c in candidates if c.level == level):
            if package.status != "approved":
                inactive.append(InactivePackage(package, f"status {package.status}"))
                continue
            if level == "project" and gate.get(package.language) in ("proposed", "rejected"):
                inactive.append(InactivePackage(package, f"{gate[package.language]} in the analysis profile"))
                continue
            other = active.get(package.language)
            if other is not None:
                raise LanguagePackageError(f"ambiguous language package selection for '{package.language}': "
                                           f"{other.path} and {package.path} (both {level})")
            active[package.language] = package
        for language, package in sorted(active.items()):
            previous = selected.get(language)
            if previous is not None:
                if not package.overrides:
                    raise LanguagePackageError(
                        f"{package.path}: language '{language}' is already provided by the {previous.level} package "
                        f"{previous.path}; declare 'overrides: true' to replace it")
                inactive.append(InactivePackage(previous, f"replaced by {package.path}"))
            selected[language] = package
    _check_extensions(selected, set(reserved_extensions))
    for package in selected.values():
        if package.backend.startswith("native:"):
            _native_factory(package.backend.split(":", 1)[1], package.path)  # unknown backends fail now
    inactive.sort(key=lambda i: (i.package.language, LEVELS.index(i.package.level), i.package.path))
    return LanguageRegistry(dict(sorted(selected.items())), inactive)


def _check_extensions(selected: dict[str, LanguagePackage], reserved: set[str]) -> None:
    """One language per extension. Built-in extensions are case-sensitive (``.C`` is C++); added packages are
    matched without case by the inventory, so they are compared in lower case."""
    owners: dict[str, LanguagePackage] = {}
    reserved_lower = {r.lower() for r in reserved}
    for language in sorted(selected, key=lambda lang: (selected[lang].level != "builtin", lang)):
        package = selected[language]
        for ext in package.extensions:
            key = ext if package.level == "builtin" else ext.lower()
            if package.level != "builtin" and key in reserved_lower:
                raise LanguagePackageError(f"{package.path}: key 'extensions': {ext!r} is decided by content and "
                                           f"repository context; it cannot be claimed by a package")
            claims = [key] if package.level == "builtin" else [key, *(o for o in owners if o.lower() == key)]
            for claim in claims:
                owner = owners.get(claim)
                if owner is not None and owner.language != language:
                    raise LanguagePackageError(f"ambiguous extension {ext!r}: claimed by '{owner.language}' "
                                               f"({owner.path}) and '{language}' ({package.path})")
            owners.setdefault(key, package)
    for attribute, label in (("filenames", "file name"), ("shebangs", "shebang interpreter")):
        hint_owners: dict[str, LanguagePackage] = {}
        for language in sorted(selected):
            package = selected[language]
            if package.level == "builtin":
                continue  # built-in detection hints live in the inventory table
            for value in getattr(package, attribute):
                owner = hint_owners.setdefault(value, package)
                if owner.language != language:
                    raise LanguagePackageError(f"ambiguous {label} {value!r}: claimed by '{owner.language}' "
                                               f"({owner.path}) and '{language}' ({package.path})")


def _native_factory(name: str, origin: str) -> Any:
    if name in BUILTIN_BACKENDS:
        return name
    found = sorted((ep for ep in entry_points(group=BACKEND_GROUP) if ep.name == name), key=lambda ep: ep.value)
    if not found:
        raise LanguagePackageError(f"{origin}: key 'backend': native backend {name!r} is not installed "
                                   f"(entry point group {BACKEND_GROUP})")
    if len(found) > 1:
        raise LanguagePackageError(f"{origin}: key 'backend': native backend {name!r} is installed more than once")
    return found[0]


def native_adapter(name: str) -> LanguageAdapter:
    """A parser-backed adapter: built-in, or installed through the ``codegraph_sci.language_backends`` group."""
    if name == "fortran":
        from codegraph_sci.extract.fortran import FortranAdapter

        return FortranAdapter()
    if name == "python":
        from codegraph_sci.extract.python import PythonAdapter

        return PythonAdapter()
    if name == "c":
        from codegraph_sci.extract.c import CAdapter

        return CAdapter()
    if name == "cpp":
        from codegraph_sci.extract.cpp import CppAdapter

        return CppAdapter()
    adapter: LanguageAdapter = _native_factory(name, f"backend native:{name}").load()()
    return adapter


def adapters_from_specs(specs: Iterable[PackageSpec]) -> dict[str, LanguageAdapter]:
    """Adapters by language (also run in extraction workers, from the specs chosen by the scan)."""
    from codegraph_sci.extract.keywords import KeywordAdapter, KeywordProfile

    adapters: dict[str, LanguageAdapter] = {}
    for language, backend, rules in specs:
        if backend == "keywords":
            adapters[language] = KeywordAdapter(KeywordProfile(language, dict(rules or {})))
        else:
            adapters[language] = native_adapter(backend.split(":", 1)[1])
    return adapters
