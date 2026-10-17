"""Repository walk: every sub-folder, minus .gitignore, excluded directories, symlink loops, unreadable entries.

Skipped folders (and files ignored by ``.gitignore``) are reported with their reason and file count, so that the
user sees what is left out; ``all_subfolders`` walks everything except version-control metadata.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from codegraph_sci.inventory.gitignore import GitIgnore

VCS_DIRS = frozenset({".git", ".hg", ".svn"})  # never walked, never reported
COUNT_LIMIT = 100_000  # files counted in one skipped folder (bounded work on huge trees)


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


@dataclass
class SkippedDir:
    """A folder (or a file ignored by ``.gitignore``) left out of the walk."""

    path: str
    reason: str  # "default exclusion", ".gitignore" or "profile"
    files: int  # files below it (at most COUNT_LIMIT)


def count_files(directory: Path, limit: int = COUNT_LIMIT) -> int:
    count = 0
    stack = [directory]
    while stack and count < limit:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                        else:
                            count += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return min(count, limit)


def walk_repo(root: Path, excluded_dirs: set[str], extra_excluded: list[str] | None = None,
              problems: list[WalkProblem] | None = None, *, all_subfolders: bool = False,
              skipped: list[SkippedDir] | None = None) -> Iterator[WalkedFile]:
    """Yield files in a deterministic order (sorted names, depth first).

    ``all_subfolders``: ignore ``.gitignore`` and the default excluded directory names (version-control metadata and
    the profile's own exclusions still apply). ``skipped`` receives what was left out, sorted by path.
    """
    root = root.resolve()
    gitignore = GitIgnore()
    extra = [p.strip("/") for p in (extra_excluded or [])]
    problems = problems if problems is not None else []
    out: list[SkippedDir] = []
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
        if not all_subfolders and gi.is_file():
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
                if entry.name in VCS_DIRS:
                    continue
                reason = None
                if any(rel == e or rel.startswith(e + "/") for e in extra):
                    reason = "profile"
                elif not all_subfolders and entry.name in excluded_dirs:
                    reason = "default exclusion"
                elif not all_subfolders and gitignore.ignored(rel, True):
                    reason = ".gitignore"
                if reason is not None:
                    out.append(SkippedDir(rel, reason, count_files(Path(entry.path))))
                    continue
                yield from visit(Path(entry.path), rel)
            elif is_file:
                if not all_subfolders and gitignore.ignored(rel, False):
                    out.append(SkippedDir(rel, ".gitignore", 1))
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
    if skipped is not None:
        skipped.extend(sorted(out, key=lambda s: s.path))
