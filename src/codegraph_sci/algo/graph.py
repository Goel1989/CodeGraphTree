"""Graph algorithms in plain Python (§3.3, D16): iterative Tarjan, condensation, impact sizes, bounded walks.

Nodes are integers ``0..n-1``; adjacency lists are lists of lists of integers.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Sequence


def tarjan_scc(n: int, succ: Sequence[Sequence[int]]) -> list[list[int]]:
    """Strongly connected components, iterative (no recursion limit).

    Components are returned in reverse topological order (a component comes before the
    components that reach it); members are sorted.
    """
    index = [-1] * n
    low = [0] * n
    on_stack = [False] * n
    stack: list[int] = []
    comps: list[list[int]] = []
    counter = 0
    for root in range(n):
        if index[root] != -1:
            continue
        work: list[tuple[int, int]] = [(root, 0)]
        while work:
            v, i = work[-1]
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on_stack[v] = True
            edges = succ[v]
            if i < len(edges):
                work[-1] = (v, i + 1)
                w = edges[i]
                if index[w] == -1:
                    work.append((w, 0))
                elif on_stack[w]:
                    low[v] = min(low[v], index[w])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    comp.append(w)
                    if w == v:
                        break
                comps.append(sorted(comp))
    return comps


def condensation(n: int, succ: Sequence[Sequence[int]]) -> tuple[list[int], list[list[int]], list[set[int]]]:
    """Returns (component of each node, components in topological order, successors of each component)."""
    comps = list(reversed(tarjan_scc(n, succ)))  # topological order: sources first
    comp_of = [0] * n
    for ci, members in enumerate(comps):
        for v in members:
            comp_of[v] = ci
    csucc: list[set[int]] = [set() for _ in comps]
    for v in range(n):
        cv = comp_of[v]
        for w in succ[v]:
            cw = comp_of[w]
            if cw != cv:
                csucc[cv].add(cw)
    return comp_of, comps, csucc


def impact_sizes(n: int, succ: Sequence[Sequence[int]]) -> list[int]:
    """For each node v: number of other nodes u that can reach v (transitive callers).

    Bitset propagation (Python integers) over the condensation, in topological order.
    """
    comp_of, comps, csucc = condensation(n, succ)
    reach: list[int] = [0] * len(comps)  # bitset of nodes reaching the component (excluding its members)
    member_bits = [0] * len(comps)
    for ci, members in enumerate(comps):
        bits = 0
        for v in members:
            bits |= 1 << v
        member_bits[ci] = bits
    for ci in range(len(comps)):
        carried = reach[ci] | member_bits[ci]
        for cj in csucc[ci]:
            reach[cj] |= carried
    out = [0] * n
    for ci, members in enumerate(comps):
        base = reach[ci].bit_count()
        extra = len(members) - 1 if len(members) > 1 else 0
        for v in members:
            out[v] = base + extra
    return out


def bounded_bfs(starts: Iterable[int], succ: Sequence[Sequence[int]], *, max_depth: int | None = None,
                max_nodes: int = 100_000) -> tuple[dict[int, int], bool]:
    """Breadth-first walk. Returns ({node: depth}, truncated)."""
    depth: dict[int, int] = {}
    queue: deque[int] = deque()
    for s in starts:
        if s not in depth:
            depth[s] = 0
            queue.append(s)
    truncated = False
    while queue:
        v = queue.popleft()
        d = depth[v]
        if max_depth is not None and d >= max_depth:
            if succ[v]:
                truncated = truncated or any(w not in depth for w in succ[v])
            continue
        for w in succ[v]:
            if w not in depth:
                if len(depth) >= max_nodes:
                    return depth, True
                depth[w] = d + 1
                queue.append(w)
    return depth, truncated


def k_shortest_simple_paths(src: int, dst: int, succ: Sequence[Sequence[int]], *, k: int = 5, max_len: int = 15,
                            max_expansions: int = 200_000) -> tuple[list[list[int]], bool]:
    """Up to ``k`` simple paths from ``src`` to ``dst``, shortest first (bounded BFS over paths).

    Returns (paths, truncated). Deterministic: neighbours are visited in the given order.
    """
    # Prune: only nodes that can reach dst within max_len.
    n = len(succ)
    pred: list[list[int]] = [[] for _ in range(n)]
    for v in range(n):
        for w in succ[v]:
            pred[w].append(v)
    dist_to_dst, _ = bounded_bfs([dst], pred, max_depth=max_len)
    if src not in dist_to_dst:
        return [], False
    paths: list[list[int]] = []
    queue: deque[list[int]] = deque([[src]])
    expansions = 0
    while queue and len(paths) < k:
        path = queue.popleft()
        v = path[-1]
        if v == dst:
            paths.append(path)
            continue
        if len(path) > max_len:
            continue
        for w in succ[v]:
            if w in path or w not in dist_to_dst or len(path) + dist_to_dst[w] > max_len + 1:
                continue
            expansions += 1
            if expansions > max_expansions:
                return paths, True
            queue.append(path + [w])
    return paths, bool(queue) and len(paths) >= k
