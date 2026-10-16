from __future__ import annotations

import random
import time

import pytest

from codegraph_sci.algo.graph import bounded_bfs, impact_sizes, k_shortest_simple_paths, tarjan_scc


def brute_impact(n: int, succ: list[list[int]]) -> list[int]:
    out = []
    for v in range(n):
        count = 0
        for u in range(n):
            if u == v:
                continue
            seen, stack = {u}, [u]
            found = False
            while stack and not found:
                x = stack.pop()
                for y in succ[x]:
                    if y == v:
                        found = True
                        break
                    if y not in seen:
                        seen.add(y)
                        stack.append(y)
            count += found
        out.append(count)
    return out


def test_tarjan_simple() -> None:
    succ = [[1], [2], [0, 3], [4], [3], []]
    comps = tarjan_scc(6, succ)
    assert sorted(comps) == [[0, 1, 2], [3, 4], [5]]
    order = {tuple(c): i for i, c in enumerate(comps)}
    assert order[(3, 4)] < order[(0, 1, 2)]  # reverse topological


def test_tarjan_deep_chain_no_recursion_limit() -> None:
    n = 200_000
    succ = [[i + 1] for i in range(n - 1)] + [[0]]
    comps = tarjan_scc(n, succ)
    assert len(comps) == 1 and len(comps[0]) == n


@pytest.mark.parametrize("seed", range(5))
def test_impact_matches_brute_force(seed: int) -> None:
    rng = random.Random(seed)
    n = 40
    succ = [sorted({rng.randrange(n) for _ in range(rng.randint(0, 3))} - {v}) for v in range(n)]
    assert impact_sizes(n, succ) == brute_impact(n, succ)


def test_bounded_bfs_and_paths() -> None:
    succ = [[1, 2], [3], [3], [4], []]
    depth, truncated = bounded_bfs([0], succ, max_depth=2)
    assert depth == {0: 0, 1: 1, 2: 1, 3: 2} and truncated
    paths, _ = k_shortest_simple_paths(0, 4, succ, k=5)
    assert paths == [[0, 1, 3, 4], [0, 2, 3, 4]]
    paths, _ = k_shortest_simple_paths(0, 4, succ, k=5, max_len=2)
    assert paths == []


@pytest.mark.slow
def test_impact_15000_nodes_time() -> None:
    rng = random.Random(42)
    n = 15000
    succ = [sorted({rng.randrange(n) for _ in range(6)} - {v}) for v in range(n)]
    start = time.perf_counter()
    sizes = impact_sizes(n, succ)
    elapsed = time.perf_counter() - start
    print(f"\nimpact sizes of 15000 routines (90000 edges): {elapsed:.2f} s, max {max(sizes)}")
    assert elapsed < 60
