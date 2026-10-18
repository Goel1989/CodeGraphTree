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

# File dependency contract (D39): "A -> B" means file A depends on file B (not an execution order). One relationship
# type per occurrence, never collapsed: the dependency table (query layer, same mapping in SQL) and the file and
# folder links of the index use these values.
FILE_RELATIONSHIPS = ("call", "dynamic_call", "import", "include", "inherit", "bridge", "binding",
                      "binding_declaration", "data_read", "data_write")
BINDING_ORIGINS = ("bridge:pybind11", "bridge:python_extension")
_REF_RELATIONSHIP = {"call": "call", "maybe_call": "call", "dynamic_call": "dynamic_call", "use": "import",
                     "include": "include", "inherit": "inherit", "bind": "binding"}
DATA_RELATIONSHIP = {"reads": "data_read", "writes": "data_write", "creates": "data_write", "destroys": "data_write"}
# Resolutions whose target is confirmed; "ambiguous" targets are possible dependencies only.
CONFIRMED_RESOLUTIONS = ("resolved", "out_of_scope")


def site_relationship(ref_kind: str, origin: str) -> str:
    """Relationship type of a call site (the ``CASE`` of the dependency table repeats this mapping)."""
    if origin.startswith(BINDING_ORIGINS):
        return "binding"
    if origin.startswith("bridge:") and ref_kind in ("call", "maybe_call", "dynamic_call"):
        return "bridge"
    return _REF_RELATIONSHIP.get(ref_kind, ref_kind)


def weakest_confidence(values: list[str]) -> str:
    """Return the weakest confidence among ``values`` (``exact`` if empty)."""
    if not values:
        return "exact"
    return max(values, key=lambda v: CONFIDENCE_RANK.get(v, len(CONFIDENCES)))
