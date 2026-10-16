from __future__ import annotations

import random

from codegraph_sci.layout.tree import TreeLayout


def build(order: list[tuple[str, list[str]]]) -> dict[str, tuple[float, float]]:
    lay = TreeLayout()
    lay.place_root("r")
    for parent, children in order:
        lay.place_children(parent, children)
    return dict(lay.positions)


def test_same_input_same_positions() -> None:
    order = [("r", ["a", "b", "c"]), ("b", ["d", "e"]), ("a", ["f"])]
    assert build(order) == build(order)


def test_expansion_never_moves_placed_nodes_and_no_overlap() -> None:
    rng = random.Random(3)
    lay = TreeLayout()
    lay.place_root("n0")
    placed = ["n0"]
    counter = 1
    for _ in range(200):
        parent = placed[rng.randrange(len(placed))]
        before = dict(lay.positions)
        kids = [f"n{counter + i}" for i in range(rng.randint(1, 6))]
        counter += len(kids)
        lay.place_children(parent, kids)
        placed += kids
        assert all(lay.positions[k] == v for k, v in before.items())
    by_pos = {}
    for k, v in lay.positions.items():
        assert v not in by_pos, (k, by_pos.get(v))
        by_pos[v] = k


def test_children_centred_on_parent_when_room() -> None:
    lay = TreeLayout(dx=100, dy=10)
    lay.place_root("r")
    pos = lay.place_children("r", ["a", "b", "c"])
    assert pos == {"a": (100, -10), "b": (100, 0), "c": (100, 10)}
    assert lay.place_children("r", ["a"]) == {}
