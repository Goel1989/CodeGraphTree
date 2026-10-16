"""Reading and writing ``analysis_profile.yaml``: safe loading and strict schema (§3.2, §3.8)."""

from __future__ import annotations

import copy
import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from codegraph_sci.core.profile import AnalysisProfile, HistoryEntry, LanguageEntry
from codegraph_sci.inventory.run import InventoryResult

PROFILE_FILE = "analysis_profile.yaml"
DEFAULT_PACKS = ("generic_noise", "generic_fortran")


class ConfigError(ValueError):
    """A configuration file (profile, pack, rule) is invalid. The message names file, key and value."""


def _schema() -> dict[str, Any]:
    text = resources.files("codegraph_sci.inventory").joinpath("profile.schema.json").read_text(encoding="utf-8")
    data: dict[str, Any] = json.loads(text)
    return data


def safe_load_yaml(path: Path) -> Any:
    """``yaml.safe_load`` only: python object tags are refused."""
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML: {exc}") from exc


def validate(data: Any, schema: dict[str, Any], origin: str) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(map(str, e.absolute_path)))
    if errors:
        err = errors[0]
        key = "/".join(str(p) for p in err.absolute_path) or "(root)"
        raise ConfigError(f"{origin}: key '{key}': {err.message} (value: {err.instance!r})")


def load_profile(path: Path) -> AnalysisProfile:
    data = safe_load_yaml(path)
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: key '(root)': expected a mapping")
    validate(data, _schema(), str(path))
    return AnalysisProfile.from_dict(data)


def profile_text(profile: AnalysisProfile) -> str:
    header = "# CodeGraph-Sci analysis profile. The analysis reads only this file.\n"
    return header + yaml.safe_dump(profile.to_dict(), sort_keys=False, allow_unicode=True, width=110)


def profile_sha256(profile: AnalysisProfile) -> str:
    return hashlib.sha256(profile_text(profile).encode("utf-8")).hexdigest()


def save_profile(path: Path, profile: AnalysisProfile) -> None:
    validate(profile.to_dict(), _schema(), str(path))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(profile_text(profile), encoding="utf-8", newline="\n")
    tmp.replace(path)


def profile_from_inventory(result: InventoryResult, previous: AnalysisProfile | None = None,
                           by: str = "cgs inventory") -> AnalysisProfile:
    """New profile = previous user decisions + what the inventory found.

    The version increases only when the content changes: two inventories of the same repository
    give the same profile.
    """
    prof = copy.deepcopy(previous) if previous else AnalysisProfile()
    languages: dict[str, LanguageEntry] = {}
    for lang, cov in result.coverage.items():
        old = prof.languages.get(lang)
        languages[lang] = LanguageEntry(files=cov.files, lines=cov.lines, adapter=cov.adapter,
                                        variants=list(cov.variants),
                                        source=old.source if old else None, status=old.status if old else None)
    changed = (languages != prof.languages or result.include_paths != prof.include_paths)
    prof.languages = languages
    prof.include_paths = list(result.include_paths)
    if previous is None:
        prof.packs = list(DEFAULT_PACKS)
        prof.history = [HistoryEntry(prof.profile_version, "profile created by the inventory", by)]
    elif changed:
        prof.profile_version += 1
        prof.history.append(HistoryEntry(prof.profile_version, "inventory updated", by))
    return prof
