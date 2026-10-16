"""Detection of CPU instruction sets (used to pick the inference backend variant)."""

from __future__ import annotations

import sys
from pathlib import Path

# Windows IsProcessorFeaturePresent identifiers.
_WIN_FEATURES = {"sse3": 13, "sse4_1": 37, "sse4_2": 38, "avx": 39, "avx2": 40, "avx512f": 41}
_LINUX_FLAGS = {"sse3": "pni", "sse4_1": "sse4_1", "sse4_2": "sse4_2", "avx": "avx", "avx2": "avx2",
                "avx512f": "avx512f"}


def instruction_sets() -> dict[str, bool]:
    """Return a sorted mapping feature -> available (best effort, never raises)."""
    result = {name: False for name in sorted(_WIN_FEATURES)}
    try:
        if sys.platform == "win32":
            import ctypes

            kernel32 = ctypes.windll.kernel32
            for name, code in _WIN_FEATURES.items():
                result[name] = bool(kernel32.IsProcessorFeaturePresent(code))
        else:
            text = Path("/proc/cpuinfo").read_text(encoding="ascii", errors="replace")
            flags: set[str] = set()
            for line in text.splitlines():
                if line.startswith("flags"):
                    flags = set(line.split(":", 1)[1].split())
                    break
            for name, flag in _LINUX_FLAGS.items():
                result[name] = flag in flags
    except Exception:  # noqa: BLE001 - detection is informative only
        pass
    return result
