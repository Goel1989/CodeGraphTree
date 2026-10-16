"""Domain packs (§3.8): safe loading, strict schema, discovery, noise rules.

A pack is a declarative ``rules.yaml``; the core turns it into deterministic rules. Unknown keys,
wrong types, unknown format versions and Python object tags are refused with a precise message.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import yaml

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


def _schema() -> dict[str, Any]:
    text = resources.files("codegraph_sci.enrich").joinpath("schemas/pack.schema.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def load_pack_file(path: Path) -> PackRules:
    try:
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
    for item in data.get("entry_points", []) + data.get("bridges", []):
        for rx in [item.get("pattern")] + list(item.get("declaration_patterns", [])):
            if rx:
                try:
                    re.compile(rx)
                except re.error as exc:
                    raise PackError(f"{path}: invalid regular expression {rx!r}: {exc}") from exc
    return PackRules(str(data["pack"]), str(data["version"]), str(path), data)


def builtin_pack_dir(name: str) -> Path:
    return Path(str(resources.files("codegraph_sci.enrich").joinpath(name)))


def find_pack(name: str, search: list[Path]) -> Path | None:
    """``rules.yaml`` of a pack: built-in, then the given folders (``<folder>/<name>/rules.yaml``)."""
    if name in BUILTIN_PACKS:
        return builtin_pack_dir(name) / "rules.yaml"
    for folder in search:
        candidate = folder / name / "rules.yaml"
        if candidate.is_file():
            return candidate
    return None


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
