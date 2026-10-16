"""Loading of the extension table (``extensions.yaml``)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

NATIVE_LANGUAGES = ("c", "cpp", "fortran", "python")


@dataclass
class ExtensionTable:
    lang_by_ext: dict[str, tuple[str, str | None]]  # lowercase ext -> (language, variant)
    exact: dict[str, str]
    ambiguous: dict[str, list[str]]
    not_covered: dict[str, str]
    ignored_exts: set[str]
    ignored_names: set[str]
    excluded_dirs: set[str]
    adapters: dict[str, str]  # language -> adapter (native:<lang>)
    signatures: dict[str, list[tuple[re.Pattern[str], int]]]
    signature_lines: int
    shebang: dict[str, str]
    modes: dict[str, str]
    extra: dict[str, Any] = field(default_factory=dict)


def load_table(path: Path | None = None) -> ExtensionTable:
    if path is None:
        text = resources.files("codegraph_sci.inventory").joinpath("extensions.yaml").read_text(encoding="utf-8")
    else:
        text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data.get("format_version") != 1:
        raise ValueError(f"extension table: unsupported format_version {data.get('format_version')!r}")
    lang_by_ext: dict[str, tuple[str, str | None]] = {}
    adapters: dict[str, str] = {}
    for lang, spec in data["languages"].items():
        adapters[lang] = spec["adapter"]
        for ext, variant in spec["extensions"].items():
            lang_by_ext[ext.lower()] = (lang, variant)
    sigs = data["signatures"]
    signatures = {
        lang: [(re.compile(rx), int(weight)) for rx, weight in rules]
        for lang, rules in sigs.items() if lang != "max_lines"
    }
    return ExtensionTable(
        lang_by_ext=lang_by_ext,
        exact=dict(data.get("exact_extensions", {})),
        ambiguous={k: list(v) for k, v in data.get("ambiguous", {}).items()},
        not_covered=dict(data.get("not_covered", {})),
        ignored_exts={e.lower() for e in data.get("ignored_extensions", [])},
        ignored_names=set(data.get("ignored_names", [])),
        excluded_dirs=set(data.get("excluded_dirs", [])),
        adapters=adapters,
        signatures=signatures,
        signature_lines=int(sigs.get("max_lines", 200)),
        shebang=dict(data.get("shebang", {})),
        modes=dict(data.get("modes", {})),
    )
