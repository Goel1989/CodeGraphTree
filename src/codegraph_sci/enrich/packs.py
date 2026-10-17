"""Domain packs (§3.8): safe loading, strict schema, discovery, noise rules.

A pack is a declarative ``rules.yaml``; the core turns it into deterministic rules. Unknown keys,
wrong types, unknown format versions and Python object tags are refused with a precise message.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from codegraph_sci.core.patterns import check_pattern, check_rule_file_size

BUILTIN_PACKS = ("generic_noise", "generic_fortran")


class PackError(ValueError):
    """Invalid pack: the message names the file, the key and the faulty value."""


@dataclass
class PackRules:
    name: str
    version: str
    path: str
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def identifiers(self) -> list[str]:
        return [str(x) for x in self.data.get("identifiers", [])]

    @property
    def known_arrays(self) -> set[str]:
        return {str(x).lower() for x in (self.data.get("extraction") or {}).get("known_arrays", [])}

    @property
    def bridges(self) -> list[dict[str, Any]]:
        return [dict(b) for b in self.data.get("bridges", [])]

    def noise_patterns(self, key: str) -> list[str]:
        return [str(x) for x in (self.data.get("noise") or {}).get(key, [])]

    @property
    def hubs(self) -> dict[str, int] | None:
        spec = (self.data.get("noise") or {}).get("auto_detect_hubs")
        return dict(spec) if spec else None


def _schema(name: str = "pack.schema.json") -> dict[str, Any]:
    text = resources.files("codegraph_sci.enrich").joinpath(f"schemas/{name}").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def _first_error(data: Any, schema: dict[str, Any], prefix: str = "") -> str | None:
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(data),
                    key=lambda e: list(map(str, e.absolute_path)))
    if not errors:
        return None
    err = errors[0]
    key = prefix + "/".join(str(p) for p in err.absolute_path) or "(root)"
    return f"key '{key}': {err.message} (value: {err.instance!r})"


@dataclass
class BridgeFile:
    """A bridge rule file ``rules/bridges/<name>.yaml`` (bridge format 1)."""

    name: str
    version: str
    path: str
    rule: dict[str, Any]
    tests: list[dict[str, str]] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)


def load_bridge_file(path: Path) -> BridgeFile:
    """Load and validate a bridge rule file: wrapper schema, the rule against the pack bridge schema, patterns."""
    try:
        size_problem = check_rule_file_size(path.stat().st_size)
        if size_problem is not None:
            raise PackError(f"{path}: {size_problem}")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PackError(f"{path}: invalid YAML (only plain data is accepted): {exc}") from exc
    except OSError as exc:
        raise PackError(f"{path}: unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise PackError(f"{path}: key '(root)': expected a mapping")
    problem = _first_error(data, _schema("bridge_rule.schema.json"))
    if problem is None:
        pack = _schema()
        problem = _first_error(data["rule"], {"$defs": pack["$defs"], "$ref": "#/$defs/bridge"}, "rule/")
    if problem is None:
        problems = pattern_errors({"bridges": [data["rule"]]})
        problem = problems[0].replace("key 'bridges/0/", "key 'rule/") if problems else None
    if problem is not None:
        raise PackError(f"{path}: {problem}")
    return BridgeFile(str(data["name"]), str(data["version"]), str(path), dict(data["rule"]),
                      [dict(x) for x in data["tests"]], dict(data.get("provenance") or {}))


def pattern_errors(data: dict[str, Any], prefix: str = "") -> list[str]:
    """Configurable regular expressions of pack rules that break the resource limits (``core.patterns``)."""
    found: list[tuple[str, str]] = []
    for i, item in enumerate(data.get("entry_points", [])):
        found.append((f"entry_points/{i}/pattern", str(item.get("pattern", ""))))
    for i, item in enumerate(data.get("memory_access", [])):
        if item.get("local_prefix_pattern"):
            found.append((f"memory_access/{i}/local_prefix_pattern", str(item["local_prefix_pattern"])))
    for i, item in enumerate(data.get("bridges", [])):
        for j, rx in enumerate(item.get("declaration_patterns", [])):
            found.append((f"bridges/{i}/declaration_patterns/{j}", str(rx)))
    out = []
    for key, rx in found:
        problem = check_pattern(rx)
        if problem is not None:
            out.append(f"key '{prefix}{key}': {problem} (value: {rx!r})")
    return out


def load_pack_file(path: Path) -> PackRules:
    try:
        size_problem = check_rule_file_size(path.stat().st_size)
        if size_problem is not None:
            raise PackError(f"{path}: {size_problem}")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PackError(f"{path}: invalid YAML (only plain data is accepted): {exc}") from exc
    except OSError as exc:
        raise PackError(f"{path}: unreadable: {exc}") from exc
    if not isinstance(data, dict):
        raise PackError(f"{path}: key '(root)': expected a mapping")
    validator = jsonschema.Draft202012Validator(_schema())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))
    if errors:
        err = errors[0]
        key = "/".join(str(p) for p in err.absolute_path) or "(root)"
        raise PackError(f"{path}: key '{key}': {err.message} (value: {err.instance!r})")
    problems = pattern_errors(data)
    if problems:
        raise PackError(f"{path}: {problems[0]}")
    return PackRules(str(data["pack"]), str(data["version"]), str(path), data)


def builtin_pack_dir(name: str) -> Path:
    return Path(str(resources.files("codegraph_sci.enrich").joinpath(name)))


def find_pack(name: str, search: list[Path]) -> Path | None:
    """Rules of a pack: built-in, then the given folders (``<folder>/<name>/rules.yaml``, or ``<folder>/<name>.yaml``
    as written by ``cgs rules new project``)."""
    if name in BUILTIN_PACKS:
        return builtin_pack_dir(name) / "rules.yaml"
    for folder in search:
        for candidate in (folder / name / "rules.yaml", folder / f"{name}.yaml"):
            if candidate.is_file():
                return candidate
    return None


def default_search_paths(project_folder: Path) -> list[Path]:
    """Where packs are looked for: the project, ``CGS_PACKS_PATH``, then the ``packs/`` folder of the installation
    (the portable folder, or the repository root in development), where the domain packs shipped with the product
    live. Domain packs are data, kept outside the core package (rule 7).
    """
    import os

    from codegraph_sci.core.paths import install_dir

    paths = [project_folder / "packs", project_folder / "rules" / "projects"]
    paths += [Path(p) for p in os.environ.get("CGS_PACKS_PATH", "").split(os.pathsep) if p]
    paths.append(install_dir() / "packs")
    return paths


def load_packs(names: list[str], search: list[Path]) -> list[PackRules]:
    packs = []
    for name in names:
        path = find_pack(name, search)
        if path is None:
            raise PackError(f"pack '{name}' not found (searched: built-in, {', '.join(map(str, search))})")
        packs.append(load_pack_file(path))
    return packs


def detect(pack: PackRules, root: Path) -> float:
    spec = pack.data.get("detect") or {}
    any_path = [p for p in spec.get("any_path", [])]
    all_path = [p for p in spec.get("all_path", [])]
    if not any_path and not all_path:
        return 0.0
    ok_any = not any_path or any((root / p).exists() for p in any_path)
    ok_all = all((root / p).exists() for p in all_path)
    return 1.0 if ok_any and ok_all else 0.0


def matches(name: str, patterns: list[str]) -> bool:
    low = name.lower()
    return any(fnmatch.fnmatchcase(low, p.lower()) for p in patterns)
