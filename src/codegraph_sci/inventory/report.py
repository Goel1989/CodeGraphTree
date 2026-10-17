"""Inventory output: JSON form and text table."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from typing import Any

from codegraph_sci.inventory.run import InventoryResult


def accounting(result: InventoryResult) -> dict[str, Any]:
    """Every discovered entry counted by kind, eligibility and reason (sorted)."""
    def counts(values: list[str]) -> dict[str, int]:
        return dict(sorted(Counter(values).items()))

    return {"total": len(result.items), "by_kind": counts([i.kind for i in result.items]),
            "by_eligibility": counts([i.eligibility for i in result.items]),
            "by_reason": counts([i.reason for i in result.items if i.reason is not None]),
            "issues": len(result.issues)}


def inventory_dict(result: InventoryResult, *, entries: bool = False) -> dict[str, Any]:
    """JSON form of the inventory; ``entries`` also lists every discovered entry."""
    data: dict[str, Any] = {
        "files": {e.path: {"lang": e.lang, "variant": e.variant, "status": e.status,
                           "decided_by": e.decided_by, "confidence": e.confidence}
                  for e in result.entries},
        "coverage": {k: {"files": c.files, "lines": c.lines, "adapter": c.adapter, "variants": c.variants}
                     for k, c in result.coverage.items()},
        "include_paths": result.include_paths,
        "unknown_groups": {k: {"files": len(v), "examples": v[:3]} for k, v in result.unknown_groups.items()},
        "ignored": result.ignored_count,
        "binary": result.binary_count,
        "problems": [{"path": p.path, "message": p.message} for p in result.problems],
        "skipped_dirs": skipped_list(result),
        "policy": result.policy,
        "accounting": accounting(result),
        "issues": [{"path": i.path, "kind": i.kind, "message": i.message} for i in result.issues],
    }
    if entries:
        data["entries"] = [asdict(i) for i in result.items]
    return data


def skipped_list(result: InventoryResult, limit: int | None = None) -> list[dict[str, Any]]:
    """Skipped folders, largest first (then by path); ``limit`` keeps the first ones."""
    items = sorted(result.skipped_dirs, key=lambda s: (-s.files, s.path))
    if limit is not None:
        items = items[:limit]
    return [{"path": s.path, "reason": s.reason, "files": s.files} for s in items]


def inventory_table(result: InventoryResult) -> str:
    lines = [f"Repository: {result.root}", "",
             f"{'Language':<18}{'Files':>8}{'Lines':>11}  {'Adapter':<18}Variants"]
    for cov in result.coverage.values():
        lines.append(f"{cov.lang:<18}{cov.files:>8}{cov.lines:>11}  {cov.adapter:<18}{', '.join(cov.variants)}")
    covered = [c for c in result.coverage.values() if c.adapter != "none"]
    missing = [c for c in result.coverage.values() if c.adapter == "none"]
    lines.append("")
    lines.append(f"Covered languages: {', '.join(c.lang for c in covered) or '-'}")
    if missing:
        lines.append(f"Known but not covered: {', '.join(f'{c.lang} ({c.files})' for c in missing)}")
    if result.unknown_groups:
        groups = ", ".join(f"{ext} ({len(paths)})" for ext, paths in result.unknown_groups.items())
        lines.append(f"Unknown files by extension: {groups}")
    lines.append(f"Ignored: {result.ignored_count} non-source files, {result.binary_count} binary files")
    counted = accounting(result)
    lines.append(f"Entries ({result.policy} inventory): {counted['total']}; "
                 + ", ".join(f"{k} {v}" for k, v in counted["by_eligibility"].items()))
    if result.include_paths:
        lines.append(f"Include paths: {', '.join(result.include_paths)}")
    for s in skipped_list(result, 20):
        lines.append(f"Skipped: {s['path']} ({s['reason']}, {s['files']} file{'s' if s['files'] != 1 else ''})")
    if len(result.skipped_dirs) > 20:
        lines.append(f"Skipped: … {len(result.skipped_dirs) - 20} more (see --json)")
    if result.skipped_dirs:
        lines.append("To analyze every sub-folder: cgs profile all-subfolders <folder> on")
    for problem in result.problems:
        lines.append(f"warning: {problem.path}: {problem.message}")
    return "\n".join(lines) + "\n"
