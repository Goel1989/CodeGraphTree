"""Files that are not analyzed code, by category, for the separate zone of the files 3D view."""

from __future__ import annotations

from typing import Any

from codegraph_sci.inventory.detect import file_ext
from codegraph_sci.inventory.run import InventoryResult

NON_CODE_LIMIT = 5000  # files listed in the scan statistics (the counts stay exact)

CATEGORY_BY_EXT = {
    "docs": {".md", ".txt", ".rst", ".pdf", ".doc", ".docx", ".odt", ".tex", ".html", ".htm", ".rtf", ".adoc"},
    "data": {".csv", ".tsv", ".json", ".dat", ".xml", ".h5", ".hdf5", ".nc", ".npy", ".npz", ".mat", ".med",
             ".mmed", ".vtk", ".vtu", ".unv", ".msh", ".mail", ".comm", ".export", ".xlsx", ".xls", ".parquet",
             ".db", ".sqlite"},
    "configuration": {".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".properties", ".env", ".lock"},
    "images": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".bmp", ".ico", ".tif", ".tiff", ".webp", ".eps"},
    "archives": {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".whl", ".jar"},
}
_BY_EXT = {ext: cat for cat, exts in CATEGORY_BY_EXT.items() for ext in exts}


def category(path: str, status: str) -> str | None:
    """Category of a non-code file, or None for a source file that is analyzed."""
    if status == "source":
        return None
    if status == "not_covered":
        return "code (not analyzed)"
    by_ext = _BY_EXT.get(file_ext(path.rsplit("/", 1)[-1]).lower())
    if by_ext is not None:
        return by_ext
    if status == "binary":
        return "binary"
    if status == "unknown":
        return "unknown type"
    return "other"


def non_code_stats(result: InventoryResult) -> dict[str, Any]:
    """``{"counts": {category: n}, "files": [[path, category], ...], "truncated": bool}`` (sorted)."""
    pairs = sorted((cat, e.path) for e in result.entries if (cat := category(e.path, e.status)) is not None)
    counts: dict[str, int] = {}
    for cat, _path in pairs:
        counts[cat] = counts.get(cat, 0) + 1
    return {"counts": dict(sorted(counts.items())), "files": [[p, c] for c, p in pairs[:NON_CODE_LIMIT]],
            "truncated": len(pairs) > NON_CODE_LIMIT}
