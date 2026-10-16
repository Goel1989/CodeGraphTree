"""Noise (§3.8 ``noise``): routines hidden by default (packs), proposed ones, automatically detected hubs.

Hidden nodes stay in the database; the views count them in a "+N" badge and show them on demand.
"""

from __future__ import annotations

from collections import defaultdict

from codegraph_sci.core.graph import EdgeRecord, NodeRecord
from codegraph_sci.core.model import CALL_PATH
from codegraph_sci.enrich.packs import PackRules, matches


def noise_map(nodes: list[NodeRecord], edges: list[EdgeRecord], packs: list[PackRules]) -> dict[str, str]:
    """uid -> reason, for every node hidden by default. ``optional:`` reasons are proposals (not hidden)."""
    out: dict[str, str] = {}
    for n in nodes:
        if n.kind == "external" and (n.subtype == "intrinsic" or n.uid.startswith("ext:python:builtins.")):
            out[n.uid] = n.subtype or "external"
    callers: dict[str, set[str]] = defaultdict(set)
    callees: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e.kind in CALL_PATH and e.src != e.dst:
            callers[e.dst].add(e.src)
            callees[e.src].add(e.dst)
    routines = [n for n in nodes if n.kind == "routine"]
    for pack in packs:
        hide = pack.noise_patterns("hide")
        optional = pack.noise_patterns("optional")
        for n in routines:
            if hide and matches(n.display_name, hide):
                out[n.uid] = f"pack:{pack.name}"
            elif optional and matches(n.display_name, optional) and n.uid not in out:
                out[n.uid] = f"optional:{pack.name}"
        hubs = pack.hubs
        if hubs:
            min_in, max_out = int(hubs["min_fan_in"]), int(hubs.get("max_fan_out", 10**9))
            for n in routines:
                fan_in, fan_out = len(callers[n.uid]), len(callees[n.uid])
                if fan_in >= min_in and fan_out <= max_out and n.uid not in out:
                    out[n.uid] = f"hub:{pack.name} (fan-in {fan_in})"
    return out


def hidden(reasons: dict[str, str]) -> dict[str, str]:
    """Only the reasons that hide a node by default."""
    return {k: v for k, v in reasons.items() if not v.startswith("optional:")}
