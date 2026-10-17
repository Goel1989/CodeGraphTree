"""Plugin contracts (§3.7): language adapters receive a file and its context, and return facts."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from codegraph_sci.core.facts import FileFacts, SourceFile


@dataclass
class IncludedFile:
    path: str  # repository-relative path
    text: str
    sha256: str


@dataclass
class ExtractContext:
    """Everything an adapter may know besides the file itself."""

    include_paths: list[str] = field(default_factory=list)
    defines: dict[str, str] = field(default_factory=dict)
    known_arrays: set[str] = field(default_factory=set)
    timeout_s: float = 60.0
    keep_all_branches: bool = True
    # OUTLINE extraction (file outside the analysis scope): adapters may skip everything but definitions and
    # includes; the result is reduced to them anyway. Part of the cache key through the extraction mode.
    outline: bool = False
    # Resolves an include: (text as written, including file) -> included file, or None.
    resolve_include: Callable[[str, str], IncludedFile | None] | None = None
    # Python: repository-relative path -> dotted module name.
    module_name: Callable[[str], str] | None = None

    def params(self) -> dict[str, object]:
        """Extraction parameters that belong in the facts cache key."""
        return {"include_paths": sorted(self.include_paths), "defines": dict(sorted(self.defines.items())),
                "known_arrays": sorted(self.known_arrays), "keep_all_branches": self.keep_all_branches}


class LanguageAdapter(Protocol):
    name: str  # "fortran", "python", "c", "cpp", "keywords:<language>"
    version: str
    languages: list[str]

    def extract(self, file: SourceFile, ctx: ExtractContext) -> FileFacts: ...


def decode_bytes(data: bytes) -> tuple[str, str]:
    """UTF-8 first (BOM removed), else Latin-1, which never fails. Returns (text, encoding)."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("latin-1"), "latin-1"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
