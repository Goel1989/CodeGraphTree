"""Deterministic, incremental tree layout for the TreeGraph views (§3.12, point 7).

Columns by depth (left to right). Expanding a node places its children in the next column,
centred on the parent when there is room, below what is already placed otherwise: nodes
already on screen never move. Linear in the number of placed nodes; same expansions in the
same order give the same positions.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LAYOUT_VERSION = 1


@dataclass
class TreeLayout:
    dx: float = 260.0
    dy: float = 34.0
    positions: dict[str, tuple[float, float]] = field(default_factory=dict)
    depth: dict[str, int] = field(default_factory=dict)
    next_free: dict[int, float] = field(default_factory=dict)  # per column: first free y

    def place_root(self, node_id: str) -> tuple[float, float]:
        self.positions = {node_id: (0.0, 0.0)}
        self.depth = {node_id: 0}
        self.next_free = {0: self.dy}
        return self.positions[node_id]

    def place_children(self, parent_id: str, child_ids: list[str]) -> dict[str, tuple[float, float]]:
        """Positions of the new children of ``parent_id`` (ids already placed are skipped)."""
        if parent_id not in self.positions:
            raise KeyError(parent_id)
        new = [c for c in child_ids if c not in self.positions]
        if not new:
            return {}
        px, py = self.positions[parent_id]
        d = self.depth[parent_id] + 1
        start = py - (len(new) - 1) * self.dy / 2
        start = max(start, self.next_free.get(d, -1e18))
        out: dict[str, tuple[float, float]] = {}
        for i, c in enumerate(new):
            pos = (px + self.dx, start + i * self.dy)
            self.positions[c] = pos
            self.depth[c] = d
            out[c] = pos
        self.next_free[d] = start + len(new) * self.dy
        return out

    def place_parents(self, child_id: str, parent_ids: list[str]) -> dict[str, tuple[float, float]]:
        """Positions of the new upstream callers of ``child_id`` in column ``depth - 1``."""
        if child_id not in self.positions:
            raise KeyError(child_id)
        new = [p for p in parent_ids if p not in self.positions]
        if not new:
            return {}
        cx, cy = self.positions[child_id]
        d = self.depth[child_id] - 1
        start = cy - (len(new) - 1) * self.dy / 2
        start = max(start, self.next_free.get(d, -1e18))
        out: dict[str, tuple[float, float]] = {}
        for i, p in enumerate(new):
            pos = (cx - self.dx, start + i * self.dy)
            self.positions[p] = pos
            self.depth[p] = d
            out[p] = pos
        self.next_free[d] = start + len(new) * self.dy
        return out

    def bounds(self) -> tuple[float, float, float, float]:
        if not self.positions:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [p[0] for p in self.positions.values()]
        ys = [p[1] for p in self.positions.values()]
        return (min(xs), min(ys), max(xs), max(ys))

