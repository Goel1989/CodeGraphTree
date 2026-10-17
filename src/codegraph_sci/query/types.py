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
    # Phase 5: extraction (adapter@version), resolution_rule, candidate_selection, reason, and for bridges the
    # rule version, mechanism, evidence kind, binding declaration and transformed name.
    evidence: dict[str, Any] = field(default_factory=dict)


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
    # Sites not counted above: callees, sites of the routine left unresolved or ambiguous; callers, ambiguous
    # sites for which this routine is one of the candidates.
    unresolved_sites: int = 0
    ambiguous_sites: int = 0


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
class InventoryAccounting:
    """Every entry discovered by the last analysis, counted (requirements plan phase 2)."""

    policy: str  # analysis or complete
    total: int
    by_kind: dict[str, int]
    by_eligibility: dict[str, int]
    by_status: dict[str, int]
    by_reason: dict[str, int]
    issues: int


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
    size: int = 0  # members of a group, isolated or "more" bucket
    note: str = ""  # extra tooltip text (folders and languages of a group, category of a non-code file)
    group: str = ""  # folder of the node's file ("." at the root), for grouping (D34)
    in_scope: bool = True  # False: defined outside the analysis scope (OUTLINE)


@dataclass
class Graph3DLink:
    source: str
    target: str
    kind: str  # calls, bridges, binds, dispatches, implements, uses, defines
    count: int
    confidence: str
    cross_dir: bool = False  # the two ends are in different folders
    status: str = "resolved"  # resolved, ambiguous, external, out_of_scope (D34)


@dataclass
class Graph3D:
    """Bounded neighbourhood of a node for the 3D view (functions, files or both)."""

    root: str
    mode: str
    nodes: list[Graph3DNode]
    links: list[Graph3DLink]
    truncated: bool = False
    hidden_noise: int = 0
    level: str = "entity"  # entity, file or directory (D34)
    # Renderer-neutral layout description: the positions are computed by the renderer (force-directed, seeded by
    # the node order), and the evidence of a link is GraphQuery.link_evidence(source, target) -> dependency rows.
    layout: dict[str, Any] = field(default_factory=lambda: {"version": 1, "algorithm": "force-directed",
                                                             "dimensions": 3})


@dataclass
class GroupSummary:
    """A connected group of routines or files: linked to each other, linked to nothing outside."""

    id: str  # "group:<representative uid>"
    representative: str  # most connected member (then smallest uid)
    label: str
    size: int
    members: list[str]
    langs: dict[str, int]
    top_dirs: list[tuple[str, int]]  # first-level folders, largest first


@dataclass
class GroupsReport:
    level: str  # "functions" or "files"
    groups: list[GroupSummary]  # two members or more, largest first
    isolated: list[str]  # members linked to nothing (sorted)
    hidden_noise: int = 0  # utility routines left out of the grouping


@dataclass
class NonCodeFile:
    path: str
    category: str  # docs, data, configuration, images, archives, binary, unknown type, code (not analyzed), other


@dataclass
class NonCodeReport:
    counts: dict[str, int]
    files: list[NonCodeFile]  # at most NON_CODE_LIMIT, sorted by category then path
    truncated: bool = False


REFERENCE_CATEGORIES = ("external_known", "out_of_scope", "ambiguous", "dynamic", "parser_limitation", "unknown")


@dataclass
class ReferenceCategories:
    """Every reference site that is not resolved to a routine of the analysis scope, in exactly one category."""

    counts: dict[str, int]  # category -> sites (REFERENCE_CATEGORIES, all present)
    by_kind: dict[str, dict[str, int]]  # category -> ref_kind -> sites
    examples: dict[str, list[str]]  # category -> up to 5 "file:line target" (sorted)
    call_sites_total: int  # every call-like site (call, maybe_call, dynamic_call), resolved or not
    references_total: int  # every reference site (calls, uses, includes, inheritance)


# ---------------------------------------------------------------- dependency tables (requirements plan phase 7)
RELATIONSHIPS = ("call", "dynamic_call", "import", "include", "inherit", "bridge", "binding", "binding_declaration")
DEPENDENCY_LEVELS = ("entity", "file", "directory")
DEPENDENCY_SORTS = ("path", "line", "caller", "target", "relationship", "status", "language", "rule")


@dataclass(frozen=True)
class DependencyFilter:
    """Filters of the dependency table; ``None`` or empty means "any". Texts match case-insensitively."""

    text: str | None = None  # in caller, target text, resolved target or caller file
    relationships: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()  # resolutions: resolved, ambiguous, external, out_of_scope, unresolved
    language: str | None = None  # language of the caller's file
    path: str | None = None  # caller files starting with this path
    caller: str | None = None  # exact caller uid
    target: str | None = None  # exact target uid
    rule: str | None = None  # resolution rule (origin) starting with this text
    # Exact keys of an aggregated row (to list its occurrences).
    caller_file: str | None = None
    target_file: str | None = None
    caller_dir: str | None = None
    target_dir: str | None = None


@dataclass
class DependencyRow:
    site_id: int | None  # None for a binding declaration (no call site)
    caller: str
    caller_name: str
    caller_file: str
    caller_lang: str | None
    target_text: str
    target: str | None
    target_name: str | None
    candidates: list[str]
    target_file: str | None
    target_lang: str | None
    relationship: str
    line: int
    col: int
    resolution: str
    confidence: str
    rule: str
    condition: str | None


@dataclass
class DependencyGroup:
    """An aggregated row: one (source, target, relationship) at the entity, file or directory level."""

    level: str
    source: str
    target: str | None  # None: the occurrences have no resolved target
    relationship: str
    count: int
    statuses: dict[str, int]
    occurrences: DependencyFilter  # filter listing the individual rows


@dataclass
class DependencyPage:
    total: int
    offset: int
    rows: list[Any]  # DependencyRow or DependencyGroup


@dataclass
class DependencyEvidence:
    row: DependencyRow
    evidence: dict[str, Any]
    excerpt: SourceExcerpt
