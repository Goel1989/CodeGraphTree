"""Vocabulary of the data model (§3.5): node kinds, edge kinds, resolutions, confidences."""

from __future__ import annotations

NODE_KINDS = frozenset({
    "file", "module", "type", "routine", "interface", "binding", "data", "entry_point",
    "dispatch_target", "test_case", "external",
})

EDGE_KINDS = frozenset({
    "contains", "calls", "uses", "inherits", "binds", "bridges", "implements", "dispatches",
    "reads", "writes", "creates", "destroys", "exercises",
})

CALL_PATH = frozenset({"calls", "bridges", "binds", "implements", "dispatches"})
FILE_DEPENDENCY = frozenset({"uses", "contains"})

RESOLUTIONS = ("resolved", "ambiguous", "external", "out_of_scope", "unresolved")

# Ordered from strongest to weakest; an edge keeps the weakest confidence of its sites.
CONFIDENCES = ("exact", "resolved", "heuristic", "ambiguous")
CONFIDENCE_RANK = {name: rank for rank, name in enumerate(CONFIDENCES)}

DATA_KEY_KINDS = ("literal", "symbolic", "family")
DATA_MODES = ("reads", "writes", "creates", "destroys", "uses")

# Reference kinds produced by adapters (Reference.kind).
REF_KINDS = frozenset({"call", "maybe_call", "use", "include", "inherit", "bind", "dynamic_call"})


def weakest_confidence(values: list[str]) -> str:
    """Return the weakest confidence among ``values`` (``exact`` if empty)."""
    if not values:
        return "exact"
    return max(values, key=lambda v: CONFIDENCE_RANK.get(v, len(CONFIDENCES)))
