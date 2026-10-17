"""Repository walk: every sub-folder, minus .gitignore, excluded directories, symlink loops, unreadable entries.

Skipped folders (and files ignored by ``.gitignore``) are reported with their reason and file count, so that the
user sees what is left out; ``all_subfolders`` walks everything except version-control metadata.

Discovery is separate from analysis selection (requirements plan phase 2): only analyzable files are yielded, and
``entries`` receives every other discovered entry (directories, excluded files, broken links, special files) with
the reason why it is not analyzed. ``complete`` also walks excluded folders to record their content, which is
never yielded, so never read nor parsed. Behaviour:

* empty directory: recorded, walked, no file;
* unreadable directory or file: recorded as unreadable, with a discovery problem;
* symbolic link inside the root: followed (a folder already visited is a loop: recorded, not walked);
* symbolic link to a target outside the root: followed as before, recorded with its target, and flagged;
* broken symbolic link: recorded and flagged; special files (sockets, devices, pipes): recorded, never read;
* version-control metadata (``.git``, ``.hg``, ``.svn``): recorded, never walked nor counted.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from codegraph_sci.inventory.gitignore import GitIgnore

VCS_DIRS = frozenset({".git", ".hg", ".svn"})  # never walked, never in the skipped-folder report
COUNT_LIMIT = 100_000  # files counted in one skipped folder (bounded work on huge trees)

# Reasons why a discovered entry is not analyzed (stable phrases, stored in the project database).
REASON_DEFAULT = "default exclusion"
REASON_GITIGNORE = ".gitignore"
REASON_PROFILE = "profile"
REASON_VCS = "version-control metadata"
REASON_LOOP = "symbolic link loop"
REASON_BROKEN_LINK = "broken symbolic link"
REASON_UNREADABLE = "unreadable"
REASON_SPECIAL = "not a regular file"


@dataclass
class WalkProblem:
    path: str
    message: str
    kind: str = "unreadable"  # unreadable, loop, broken_link, external_link


@dataclass
class WalkedFile:
    rel: str
    abs: Path
    size: int
    mtime_ns: int
    link_target: str | None = None  # the file is reached through this symbolic link


@dataclass
class WalkedEntry:
    """A discovered entry that is not yielded as an analyzable file."""

    rel: str  # "." for the root
    kind: str  # directory, file, symlink (not followed), special
    eligibility: str  # not_applicable (walked directory), excluded, unreadable, not_source
    reason: str | None = None
    walked: bool = False  # directories
    files: int | None = None  # files below a folder that was not walked (bounded), else None
    size: int | None = None
    link_target: str | None = None


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


def _link_target(entry: os.DirEntry[str]) -> str | None:
    """Target of a symbolic link as written in the link (``/`` separators), or None for a plain entry."""
    try:
        if not entry.is_symlink():
            return None
        return os.readlink(entry.path).replace(os.sep, "/")
    except OSError:
        return None


def _outside(path: str, root_real: str) -> bool:
    try:
        return os.path.commonpath([os.path.realpath(path), root_real]) != root_real
    except (OSError, ValueError):  # another drive, or unresolvable
        return True


def walk_repo(root: Path, excluded_dirs: set[str], extra_excluded: list[str] | None = None,
              problems: list[WalkProblem] | None = None, *, all_subfolders: bool = False,
              skipped: list[SkippedDir] | None = None, entries: list[WalkedEntry] | None = None,
              complete: bool = False) -> Iterator[WalkedFile]:
    """Yield analyzable files in a deterministic order (sorted names, depth first).

    ``all_subfolders``: ignore ``.gitignore`` and the default excluded directory names (version-control metadata and
    the profile's own exclusions still apply). ``skipped`` receives what was left out, sorted by path. ``entries``
    receives every other discovered entry; ``complete`` walks excluded folders to record their content too.
    """
    root = root.resolve()
    root_real = os.path.realpath(root)
    gitignore = GitIgnore()
    extra = [p.strip("/") for p in (extra_excluded or [])]
    problems = problems if problems is not None else []
    found: list[WalkedEntry] = entries if entries is not None else []
    out: list[SkippedDir] = []
    visited: set[str] = set()

    def visit(directory: Path, rel_dir: str, inherited: str | None, link: str | None) -> Iterator[WalkedFile]:
        name = rel_dir or "."
        try:
            real = os.path.realpath(directory)
        except OSError as exc:
            problems.append(WalkProblem(name, f"unreadable directory: {exc}"))
            found.append(WalkedEntry(name, "directory", "unreadable", REASON_UNREADABLE, link_target=link))
            return
        if real in visited:
            problems.append(WalkProblem(name, "symbolic link loop (directory already visited)", "loop"))
            found.append(WalkedEntry(name, "directory", "excluded", REASON_LOOP, link_target=link))
            return
        visited.add(real)
        gi = directory / ".gitignore"
        if not all_subfolders and gi.is_file():
            try:
                gitignore.add_file(rel_dir, gi.read_text(encoding="utf-8", errors="replace"))
            except OSError as exc:
                problems.append(WalkProblem(f"{rel_dir}/.gitignore".lstrip("/"), f"unreadable: {exc}"))
        try:
            listing = sorted(os.scandir(directory), key=lambda e: e.name)
        except OSError as exc:
            problems.append(WalkProblem(name, f"unreadable directory: {exc}"))
            found.append(WalkedEntry(name, "directory", "unreadable", REASON_UNREADABLE, link_target=link))
            return
        found.append(WalkedEntry(name, "directory", "excluded" if inherited else "not_applicable", inherited,
                                 walked=True, link_target=link))
        for entry in listing:
            rel = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            target = _link_target(entry)
            try:
                is_dir = entry.is_dir(follow_symlinks=True)
                is_file = entry.is_file(follow_symlinks=True)
            except OSError as exc:
                problems.append(WalkProblem(rel, f"unreadable: {exc}"))
                found.append(WalkedEntry(rel, "symlink" if target else "file", "unreadable", REASON_UNREADABLE,
                                         link_target=target))
                continue
            if target is not None and (is_dir or is_file) and _outside(entry.path, root_real):
                problems.append(WalkProblem(rel, f"symbolic link to {target}, outside the root (followed)",
                                            "external_link"))
            if is_dir:
                if entry.name in VCS_DIRS:
                    found.append(WalkedEntry(rel, "directory", "excluded", REASON_VCS, link_target=target))
                    continue
                reason = inherited
                if reason is None:
                    if any(rel == e or rel.startswith(e + "/") for e in extra):
                        reason = REASON_PROFILE
                    elif not all_subfolders and entry.name in excluded_dirs:
                        reason = REASON_DEFAULT
                    elif not all_subfolders and gitignore.ignored(rel, True):
                        reason = REASON_GITIGNORE
                    if reason is not None:
                        count = count_files(Path(entry.path))
                        out.append(SkippedDir(rel, reason, count))
                        if not complete:
                            found.append(WalkedEntry(rel, "directory", "excluded", reason, files=count,
                                                     link_target=target))
                            continue
                yield from visit(Path(entry.path), rel, reason, target)
            elif is_file:
                excluded = inherited
                if excluded is None and not all_subfolders and gitignore.ignored(rel, False):
                    excluded = REASON_GITIGNORE
                    out.append(SkippedDir(rel, REASON_GITIGNORE, 1))
                try:
                    st = entry.stat(follow_symlinks=True)
                except OSError as exc:
                    problems.append(WalkProblem(rel, f"unreadable: {exc}"))
                    found.append(WalkedEntry(rel, "file", "unreadable", REASON_UNREADABLE, link_target=target))
                    continue
                if excluded is not None:
                    found.append(WalkedEntry(rel, "file", "excluded", excluded, size=st.st_size, link_target=target))
                    continue
                yield WalkedFile(rel, Path(entry.path), st.st_size, st.st_mtime_ns, target)
            elif target is not None:
                problems.append(WalkProblem(rel, "broken or looping symbolic link", "broken_link"))
                found.append(WalkedEntry(rel, "symlink", "unreadable", REASON_BROKEN_LINK, link_target=target))
            else:
                found.append(WalkedEntry(rel, "special", "not_source", REASON_SPECIAL))

    yield from visit(root, "", None, None)
    if skipped is not None:
        skipped.extend(sorted(out, key=lambda s: s.path))
