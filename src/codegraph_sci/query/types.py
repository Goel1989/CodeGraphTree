"""Result types of the query API (§3.10). Plain dataclasses: shared by the CLI and the desktop app."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Direction(Enum):
    CALLERS = "callers"
    CALLEES = "callees"


class Level(Enum):
    ROUTINE = "routine"
    FILE = "file"
    DIRECTORY = "directory"


@dataclass
class NodeSummary:
    uid: str
    display_name: str
    kind: str
    subtype: str | None
    lang: str | None
    file: str | None
    line: int | None
    fan_in: int = 0
    fan_out: int = 0
    is_noise: bool = False


@dataclass
class NodeDetail(NodeSummary):
    line_end: int | None = None
    in_scope: bool = True
    attrs: dict[str, Any] = field(default_factory=dict)
    impact_size: int = 0
    fan_in_filtered: int = 0
    fan_out_filtered: int = 0
    noise_reason: str | None = None


@dataclass
class CallSite:
    file: str
    line: int
    col: int
    target_text: str
    ref_kind: str
    condition: str | None
    origin: str
    confidence: str
    resolution: str
    src: str = ""
    dst: str | None = None


@dataclass
class LinkItem:
    node: NodeSummary
    sites: list[CallSite]


@dataclass
class CallerReport:
    target: NodeSummary
    count: int  # distinct callers
    file_count: int  # distinct files containing the calls
    site_count: int
    items: list[LinkItem]
    hidden_noise: int = 0


@dataclass
class TreeItem:
    uid: str
    label: str
    kind: str
    lang: str | None
    file: str | None
    edge_kind: str
    count: int
    confidence: str
    possible: bool
    has_children: bool
    is_noise: bool = False


@dataclass
class Page:
    items: list[Any]
    total: int
    offset: int
    limit: int
    hidden: int = 0


@dataclass
class FileLink:
    file: str
    lang: str | None
    kind: str
    count: int


@dataclass
class PathStep:
    uid: str
    edge_kind: str | None  # kind of the edge arriving at this step (None for the start)
    confidence: str | None
    possible: bool


@dataclass
class GraphPath:
    steps: list[PathStep]


@dataclass
class PathReport:
    paths: list[GraphPath]
    truncated: bool


@dataclass
class ImpactReport:
    target: str
    total: int
    by_depth: dict[int, int]
    items: list[tuple[int, NodeSummary]]
    entry_points: list[str]
    truncated: bool


@dataclass
class DataAccessView:
    routine: str
    data: str
    family: str | None
    mode: str
    key_kind: str
    file: str
    line: int
    origin: str


@dataclass
class SiteGroup:
    lang: str
    resolution: str
    pattern: str
    count: int
    files: int
    examples: list[dict[str, Any]]


@dataclass
class SourceExcerpt:
    path: str
    start: int
    end: int
    lines: list[str]
    stale: bool
    encoding: str | None
    missing: bool = False


@dataclass
class LanguageLine:
    lang: str
    files: int
    lines: int
    adapter: str | None
    statuses: dict[str, int]


@dataclass
class InventoryReport:
    languages: list[LanguageLine]
    unknown_groups: dict[str, int]
    total_files: int


@dataclass
class ScanHealth:
    files_by_status: dict[str, int]
    sites_by_resolution: dict[str, int]
    unresolved_rate: float
    ambiguous: int
    last_scan: dict[str, Any]
    failures: list[dict[str, Any]]


@dataclass
class DefaultRoots:
    main_routine: NodeSummary | None
    main_file: NodeSummary | None
    routine_candidates: list[NodeSummary] = field(default_factory=list)


@dataclass
class SubgraphEdge:
    src: str
    dst: str
    item: TreeItem


@dataclass
class SubgraphReport:
    root: TreeItem
    nodes: dict[str, TreeItem]
    edges: list[SubgraphEdge]
    truncated: bool = False
    hidden_noise: int = 0


@dataclass
class NeighborsReport:
    center: TreeItem
    callers: list[TreeItem]
    callees: list[TreeItem]
    hidden_noise: int = 0


@dataclass
class MainPathReport:
    root_uid: str
    target_uid: str
    paths: list[GraphPath]
    total_found: int
    multiple_possible: bool
    showing_shortest_only: bool
    truncated: bool = False



@dataclass
class Graph3DNode:
    id: str
    label: str
    kind: str
    lang: str | None
    file: str | None
    line: int | None
    fan_in: int
    fan_out: int
    is_root: bool = False
    is_noise: bool = False


@dataclass
class Graph3DLink:
    source: str
    target: str
    kind: str  # calls, bridges, binds, dispatches, implements, uses, defines
    count: int
    confidence: str


@dataclass
class Graph3D:
    """Bounded neighbourhood of a node for the 3D view (functions, files or both)."""

    root: str
    mode: str
    nodes: list[Graph3DNode]
    links: list[Graph3DLink]
    truncated: bool = False
    hidden_noise: int = 0
