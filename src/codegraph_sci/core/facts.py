"""Facts extracted from one file (§3.7): the only format the core knows, for every language."""

from __future__ import annotations

import json
import zlib
from dataclasses import asdict, dataclass, field
from typing import Any

from codegraph_sci.core.versions import FACTS_FORMAT_VERSION


@dataclass(slots=True)
class SourceFile:
    path: str
    lang: str
    variant: str | None
    encoding: str
    text: str


@dataclass(slots=True)
class LocalSymbol:
    """Declaration visible inside a routine (mostly Fortran)."""

    name: str
    role: str  # array, scalar, dummy, dummy_procedure, external, function, intrinsic, parameter
    source: str  # local, include:<path>, common:<block>, module:<name>


@dataclass(slots=True)
class Definition:
    uid: str
    display_name: str
    kind: str
    subtype: str
    name: str
    span: tuple[int, int]
    signature: str | None = None
    doc: str | None = None
    local_symbols: list[LocalSymbol] = field(default_factory=list)
    parent: str | None = None  # uid of the enclosing definition (module, class...)
    condition: str | None = None  # preprocessor guard of the definition
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ArgFact:
    text: str
    value: str | int | float | None = None  # literal value when known


@dataclass(slots=True)
class Reference:
    """A call or usage site, not yet resolved."""

    src: str
    target_text: str
    kind: str  # call, maybe_call, use, include, inherit, bind, dynamic_call
    line: int
    col: int
    args: list[ArgFact] = field(default_factory=list)
    condition: str | None = None
    candidates: list[str] = field(default_factory=list)  # uids proposed by the adapter (overloads)
    confidence: str | None = None  # forced confidence (e.g. heuristic for dynamic calls)
    hint: dict[str, Any] = field(default_factory=dict)  # adapter hints for Link (scope, receiver...)


@dataclass(slots=True)
class IncludeRef:
    text: str
    resolved_path: str | None
    sha256: str | None
    line: int = 0


@dataclass(slots=True)
class DataAccess:
    src: str
    data_key: str
    mode: str  # reads, writes, creates, destroys, uses
    key_kind: str  # literal, symbolic, family
    line: int
    family_key: str | None = None
    subtype: str = "common_block"
    origin: str | None = None


@dataclass(slots=True)
class Directive:
    kind: str  # if, ifdef, ifndef, elif, else, endif, define, include
    text: str
    line: int


@dataclass(slots=True)
class ParseError:
    message: str
    line: int = 0


@dataclass(slots=True)
class FileFacts:
    path: str
    lang: str
    encoding: str
    adapter: str
    adapter_version: str
    definitions: list[Definition] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    data_accesses: list[DataAccess] = field(default_factory=list)
    directives: list[Directive] = field(default_factory=list)
    includes: list[IncludeRef] = field(default_factory=list)
    errors: list[ParseError] = field(default_factory=list)
    used_fallback: bool = False
    variant: str | None = None

    def sort(self) -> FileFacts:
        """Sort every collection (line, column, then name): required for determinism."""
        self.definitions.sort(key=lambda d: (d.span[0], d.span[1], d.uid))
        for d in self.definitions:
            d.local_symbols.sort(key=lambda s: (s.name, s.role, s.source))
        self.references.sort(key=lambda r: (r.line, r.col, r.target_text, r.kind, r.src))
        for r in self.references:
            r.candidates.sort()
        self.data_accesses.sort(key=lambda a: (a.line, a.src, a.data_key, a.mode))
        self.directives.sort(key=lambda d: (d.line, d.kind, d.text))
        self.includes.sort(key=lambda i: (i.line, i.text))
        self.errors.sort(key=lambda e: (e.line, e.message))
        return self

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["format_version"] = FACTS_FORMAT_VERSION
        return data

    @staticmethod
    def from_dict(data: dict[str, Any]) -> FileFacts:
        if data.get("format_version") != FACTS_FORMAT_VERSION:
            raise ValueError(f"unsupported facts format {data.get('format_version')!r}")
        return FileFacts(
            path=data["path"], lang=data["lang"], encoding=data["encoding"], adapter=data["adapter"],
            adapter_version=data["adapter_version"],
            definitions=[
                Definition(
                    uid=d["uid"], display_name=d["display_name"], kind=d["kind"], subtype=d["subtype"],
                    name=d["name"], span=(d["span"][0], d["span"][1]), signature=d["signature"],
                    doc=d["doc"], local_symbols=[LocalSymbol(**s) for s in d["local_symbols"]],
                    parent=d["parent"], condition=d["condition"], attrs=d["attrs"],
                )
                for d in data["definitions"]
            ],
            references=[
                Reference(
                    src=r["src"], target_text=r["target_text"], kind=r["kind"], line=r["line"],
                    col=r["col"], args=[ArgFact(**a) for a in r["args"]], condition=r["condition"],
                    candidates=r["candidates"], confidence=r["confidence"], hint=r["hint"],
                )
                for r in data["references"]
            ],
            data_accesses=[DataAccess(**a) for a in data["data_accesses"]],
            directives=[Directive(**d) for d in data["directives"]],
            includes=[IncludeRef(**i) for i in data["includes"]],
            errors=[ParseError(**e) for e in data["errors"]],
            used_fallback=data["used_fallback"],
            variant=data.get("variant"),
        )


def canonical_json(data: Any) -> str:
    """Canonical JSON: sorted keys, no extra whitespace, UTF-8 friendly."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def encode_facts(facts: FileFacts) -> bytes:
    """Compressed canonical JSON (zlib). Never pickle."""
    return zlib.compress(canonical_json(facts.to_dict()).encode("utf-8"), 6)


def decode_facts(blob: bytes) -> FileFacts:
    return FileFacts.from_dict(json.loads(zlib.decompress(blob).decode("utf-8")))
