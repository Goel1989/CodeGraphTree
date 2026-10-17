"""In-memory graph records written to the project database (one record type per table, §3.6).

Records reference each other by uid and by repository-relative path, never by database id:
the store assigns integer ids deterministically when writing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class FileRecord:
    path: str
    lang: str | None
    variant: str | None = None
    sha256: str | None = None
    size: int = 0
    encoding: str | None = None
    parse_status: str = "ok"  # ok, fallback, failed, skipped, not_analyzed
    adapter: str | None = None
    adapter_version: str | None = None
    error: str | None = None
    mtime_ns: int = 0
    cache_key: str | None = None


@dataclass(slots=True)
class InventoryRecord:
    path: str
    lang: str | None
    variant: str | None
    confidence: float
    decided_by: str


@dataclass(slots=True)
class InventoryItem:
    """One discovered entry of the repository and what became of it (phase 2: every entry is accounted for).

    ``eligibility``: eligible, excluded, not_source, unsupported_language, unreadable, not_applicable (walked
    directories). ``status``: for a file, the analysis status (pending before a scan, then the file's
    ``parse_status``, or not_analyzed); for a directory, walked or not_walked. ``reason`` says why an entry was not
    analyzed (or not walked).
    """

    path: str  # relative, "/" separators; "." for the root
    parent: str | None  # None for the root
    kind: str  # file, directory, symlink (not followed), special
    extension: str = ""
    size: int | None = None
    files: int | None = None  # directories: files below, including those of folders not walked
    lang: str | None = None
    variant: str | None = None
    confidence: float | None = None
    evidence: str | None = None  # how the language was decided (extension:.f90, shebang:python3, ...)
    eligibility: str = "not_applicable"
    status: str = "not_analyzed"
    reason: str | None = None
    link_target: str | None = None  # target of a symbolic link, as written in the link


@dataclass(slots=True)
class InventoryIssue:
    """A discovery problem: unreadable entry, symbolic link loop, broken or external link."""

    path: str
    kind: str  # unreadable, loop, broken_link, external_link
    message: str


@dataclass(slots=True)
class NodeRecord:
    uid: str
    display_name: str
    kind: str
    subtype: str | None = None
    lang: str | None = None
    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    in_scope: bool = True
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CallSiteRecord:
    src: str
    file: str
    line: int
    col: int
    ref_kind: str
    target_text: str
    dst: str | None
    resolution: str
    confidence: str
    origin: str
    condition: str | None = None
    candidates: list[str] = field(default_factory=list)
    # How the target was found when a rule beyond the language's own lookup decided it (bridges): rule, rule
    # version, mechanism, evidence kind, binding declaration, transformed name, candidate selection, reason.
    evidence: dict[str, Any] = field(default_factory=dict)

    def sort_key(self) -> tuple[str, int, int, str, str, str]:
        return (self.file, self.line, self.col, self.src, self.target_text, self.ref_kind)


@dataclass(slots=True)
class DataAccessRecord:
    src: str
    data: str
    family: str | None
    mode: str
    key_kind: str
    file: str
    line: int
    origin: str


@dataclass(slots=True)
class EdgeRecord:
    src: str
    dst: str
    kind: str
    site_count: int
    min_confidence: str
    origins: list[str]
    conditions: list[str]


@dataclass(slots=True)
class NodeStatRecord:
    uid: str
    fan_in: int = 0
    fan_out: int = 0
    fan_in_filtered: int = 0
    fan_out_filtered: int = 0
    impact_size: int = 0
    impact_size_filtered: int = 0
    is_noise: bool = False
    noise_reason: str | None = None


@dataclass(slots=True)
class AggregateEdge:
    """File-level or directory-level link (``file_edges`` / ``dir_edges``)."""

    src: str
    dst: str
    kind: str
    count: int


@dataclass(slots=True)
class PluginRecord:
    name: str
    type: str
    version: str


@dataclass(slots=True)
class ScanRunRecord:
    started_at: str
    finished_at: str
    root: str
    git_rev: str | None
    profile_version: int
    profile_sha256: str
    plugins: list[dict[str, str]]
    stats: dict[str, Any]


@dataclass
class GraphBundle:
    """Everything a scan writes. Collections are sorted by :meth:`sort` before writing."""

    files: list[FileRecord] = field(default_factory=list)
    inventory: list[InventoryRecord] = field(default_factory=list)
    inventory_items: list[InventoryItem] = field(default_factory=list)
    inventory_issues: list[InventoryIssue] = field(default_factory=list)
    nodes: list[NodeRecord] = field(default_factory=list)
    call_sites: list[CallSiteRecord] = field(default_factory=list)
    data_accesses: list[DataAccessRecord] = field(default_factory=list)
    edges: list[EdgeRecord] = field(default_factory=list)
    node_stats: list[NodeStatRecord] = field(default_factory=list)
    file_edges: list[AggregateEdge] = field(default_factory=list)
    dir_edges: list[AggregateEdge] = field(default_factory=list)
    plugins: list[PluginRecord] = field(default_factory=list)
    scan_run: ScanRunRecord | None = None
    facts_cache: dict[str, bytes] = field(default_factory=dict)

    def sort(self) -> GraphBundle:
        self.files.sort(key=lambda f: f.path)
        self.inventory.sort(key=lambda i: i.path)
        self.inventory_items.sort(key=lambda i: i.path)
        self.inventory_issues.sort(key=lambda i: (i.path, i.kind, i.message))
        self.nodes.sort(key=lambda n: n.uid)
        for site in self.call_sites:
            site.candidates.sort()
        self.call_sites.sort(key=CallSiteRecord.sort_key)
        self.data_accesses.sort(key=lambda a: (a.file, a.line, a.src, a.data, a.mode))
        for edge in self.edges:
            edge.origins.sort()
            edge.conditions.sort()
        self.edges.sort(key=lambda e: (e.src, e.dst, e.kind))
        self.node_stats.sort(key=lambda s: s.uid)
        self.file_edges.sort(key=lambda e: (e.src, e.dst, e.kind))
        self.dir_edges.sort(key=lambda e: (e.src, e.dst, e.kind))
        self.plugins.sort(key=lambda p: (p.type, p.name))
        return self
