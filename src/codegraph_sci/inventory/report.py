"""Inventory output: JSON form and text table."""

from __future__ import annotations

from typing import Any

from codegraph_sci.inventory.run import InventoryResult


def inventory_dict(result: InventoryResult) -> dict[str, Any]:
    return {
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
    }


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
    if result.include_paths:
        lines.append(f"Include paths: {', '.join(result.include_paths)}")
    for problem in result.problems:
        lines.append(f"warning: {problem.path}: {problem.message}")
    return "\n".join(lines) + "\n"
