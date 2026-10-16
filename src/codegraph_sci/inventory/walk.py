"""Repository walk: .gitignore, excluded directories, symlink loops, unreadable entries."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from codegraph_sci.inventory.gitignore import GitIgnore


@dataclass
class WalkProblem:
    path: str
    message: str


@dataclass
class WalkedFile:
    rel: str
    abs: Path
    size: int
    mtime_ns: int


def walk_repo(root: Path, excluded_dirs: set[str], extra_excluded: list[str] | None = None,
              problems: list[WalkProblem] | None = None) -> Iterator[WalkedFile]:
    """Yield files in a deterministic order (sorted names, depth first)."""
    root = root.resolve()
    gitignore = GitIgnore()
    extra = [p.strip("/") for p in (extra_excluded or [])]
    problems = problems if problems is not None else []
    visited: set[str] = set()

    def visit(directory: Path, rel_dir: str) -> Iterator[WalkedFile]:
        try:
            real = os.path.realpath(directory)
        except OSError as exc:
            problems.append(WalkProblem(rel_dir or ".", f"unreadable directory: {exc}"))
            return
        if real in visited:
            problems.append(WalkProblem(rel_dir or ".", "symbolic link loop (directory already visited)"))
            return
        visited.add(real)
        gi = directory / ".gitignore"
        if gi.is_file():
            try:
                gitignore.add_file(rel_dir, gi.read_text(encoding="utf-8", errors="replace"))
            except OSError as exc:
                problems.append(WalkProblem(f"{rel_dir}/.gitignore".lstrip("/"), f"unreadable: {exc}"))
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError as exc:
            problems.append(WalkProblem(rel_dir or ".", f"unreadable directory: {exc}"))
            return
        for entry in entries:
            rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            try:
                is_dir = entry.is_dir(follow_symlinks=True)
                is_file = entry.is_file(follow_symlinks=True)
            except OSError as exc:
                problems.append(WalkProblem(rel, f"unreadable: {exc}"))
                continue
            if is_dir:
                if entry.name in excluded_dirs or any(rel == e or rel.startswith(e + "/") for e in extra):
                    continue
                if gitignore.ignored(rel, True):
                    continue
                yield from visit(Path(entry.path), rel)
            elif is_file:
                if gitignore.ignored(rel, False):
                    continue
                try:
                    st = entry.stat(follow_symlinks=True)
                except OSError as exc:
                    problems.append(WalkProblem(rel, f"unreadable: {exc}"))
                    continue
                yield WalkedFile(rel, Path(entry.path), st.st_size, st.st_mtime_ns)
            elif entry.is_symlink():
                problems.append(WalkProblem(rel, "broken or looping symbolic link"))

    yield from visit(root, "")
