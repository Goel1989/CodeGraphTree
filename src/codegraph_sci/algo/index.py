"""Index step (§3.3): aggregated edges, node statistics, file and directory links."""

from __future__ import annotations

import posixpath
from collections import defaultdict
from collections.abc import Iterable

from codegraph_sci.algo.graph import impact_sizes
from codegraph_sci.core.graph import (
    AggregateEdge,
    CallSiteRecord,
    DataAccessRecord,
    EdgeRecord,
    NodeRecord,
    NodeStatRecord,
)
from codegraph_sci.core.model import CALL_PATH, CONFIDENCE_RANK

SITE_EDGE_KIND = {"call": "calls", "maybe_call": "calls", "dynamic_call": "calls", "use": "uses",
                  "include": "uses", "inherit": "inherits", "bind": "binds"}


BINDING_BRIDGES = ("bridge:pybind11", "bridge:python_extension")


def site_edge_kind(site: CallSiteRecord) -> str:
    if site.origin.startswith("bridge:") and site.ref_kind in ("call", "maybe_call", "dynamic_call"):
        return "binds" if site.origin.startswith(BINDING_BRIDGES) else "bridges"
    return SITE_EDGE_KIND.get(site.ref_kind, "calls")


def aggregate_edges(sites: Iterable[CallSiteRecord], struct_edges: Iterable[EdgeRecord]) -> list[EdgeRecord]:
    """One edge per (caller, callee, kind): number of sites, weakest confidence, origins, conditions."""
    acc: dict[tuple[str, str, str], tuple[int, str, set[str], set[str]]] = {}
    for s in sites:
        targets = list(s.candidates) if s.candidates else ([s.dst] if s.dst else [])
        if not targets:
            continue
        kind = site_edge_kind(s)
        for dst in targets:
            key = (s.src, dst, kind)
            count, conf, origins, conds = acc.get(key, (0, "exact", set(), set()))
            if CONFIDENCE_RANK.get(s.confidence, 9) > CONFIDENCE_RANK.get(conf, 9):
                conf = s.confidence
            origins.add(s.origin)
            if s.condition:
                conds.add(s.condition)
            acc[key] = (count + 1, conf, origins, conds)
    edges = [EdgeRecord(src, dst, kind, n, conf, sorted(o), sorted(c))
             for (src, dst, kind), (n, conf, o, c) in acc.items()]
    edges.extend(struct_edges)
    edges.sort(key=lambda e: (e.src, e.dst, e.kind))
    return edges


def node_statistics(nodes: list[NodeRecord], edges: list[EdgeRecord], noise: dict[str, str],
                    reasons: dict[str, str] | None = None) -> list[NodeStatRecord]:
    """fan-in/fan-out (distinct callers/callees) and impact size, raw and without noise nodes."""
    index = {n.uid: i for i, n in enumerate(nodes)}
    succ: list[list[int]] = [[] for _ in nodes]
    succ_f: list[list[int]] = [[] for _ in nodes]
    callers: dict[int, set[int]] = defaultdict(set)
    callees: dict[int, set[int]] = defaultdict(set)
    callers_f: dict[int, set[int]] = defaultdict(set)
    callees_f: dict[int, set[int]] = defaultdict(set)
    for e in edges:
        if e.kind not in CALL_PATH or e.src not in index or e.dst not in index or e.src == e.dst:
            continue
        a, b = index[e.src], index[e.dst]
        succ[a].append(b)
        callers[b].add(a)
        callees[a].add(b)
        if e.src not in noise and e.dst not in noise:
            succ_f[a].append(b)
            callers_f[b].add(a)
            callees_f[a].add(b)
    for lists in (succ, succ_f):
        for i, lst in enumerate(lists):
            lists[i] = sorted(set(lst))
    impact = impact_sizes(len(nodes), succ)
    impact_f = impact_sizes(len(nodes), succ_f)
    return [NodeStatRecord(n.uid, len(callers[i]), len(callees[i]), len(callers_f[i]), len(callees_f[i]),
                           impact[i], impact_f[i], n.uid in noise, (reasons or noise).get(n.uid))
            for i, n in enumerate(nodes)]


def file_and_dir_edges(nodes: list[NodeRecord], sites: Iterable[CallSiteRecord]
                       ) -> tuple[list[AggregateEdge], list[AggregateEdge]]:
    """File-level links (one per site; ``calls`` for the call path, ``uses`` for use/include)."""
    file_of = {n.uid: n.file for n in nodes if n.file}
    fcount: dict[tuple[str, str, str], int] = defaultdict(int)
    for s in sites:
        targets = list(s.candidates) if s.candidates else ([s.dst] if s.dst else [])
        kind = site_edge_kind(s)
        kind = "uses" if kind in ("uses", "inherits") else "calls"
        for dst in targets:
            src_file = s.file
            dst_file = file_of.get(dst)
            if dst_file is None or dst_file == src_file:
                continue
            fcount[(src_file, dst_file, kind)] += 1
    file_edges = [AggregateEdge(a, b, k, c) for (a, b, k), c in sorted(fcount.items())]
    dcount: dict[tuple[str, str, str], int] = defaultdict(int)
    for e in file_edges:
        da, db = posixpath.dirname(e.src) or ".", posixpath.dirname(e.dst) or "."
        if da != db:
            dcount[(da, db, e.kind)] += e.count
    dir_edges = [AggregateEdge(a, b, k, c) for (a, b, k), c in sorted(dcount.items())]
    return file_edges, dir_edges


def data_edges(accesses: Iterable[DataAccessRecord]) -> list[EdgeRecord]:
    """One ``reads``/``writes``/... edge per (routine, data, mode), weighted by the number of accesses."""
    acc: dict[tuple[str, str, str], tuple[int, set[str]]] = {}
    for a in accesses:
        count, origins = acc.get((a.src, a.data, a.mode), (0, set()))
        origins.add(a.origin)
        acc[(a.src, a.data, a.mode)] = (count + 1, origins)
    return [EdgeRecord(src, dst, mode, n, "resolved", sorted(o), []) for (src, dst, mode), (n, o) in sorted(acc.items())]
