"""Process-wide guard that forbids any network socket (constraint C2: 100 % offline)."""

from __future__ import annotations

import socket
from typing import Any

_ALLOWED_FAMILIES = {getattr(socket, "AF_UNIX", -1)}


class NetworkAccessError(RuntimeError):
    """Raised when code tries to open a network socket."""


_installed = False
_original_socket = socket.socket


class _GuardedSocket(_original_socket):
    def __init__(self, family: Any = -1, *args: Any, **kwargs: Any) -> None:
        fam = socket.AF_INET if family == -1 else family
        if fam not in _ALLOWED_FAMILIES:
            raise NetworkAccessError(f"network access is forbidden (socket family {fam!r})")
        super().__init__(family, *args, **kwargs)


def install() -> None:
    """Replace ``socket.socket`` so that any network socket creation fails."""
    global _installed
    if _installed:
        return
    socket.socket = _GuardedSocket  # type: ignore[misc]
    _installed = True


def is_installed() -> bool:
    return _installed


def uninstall() -> None:
    global _installed
    socket.socket = _original_socket  # type: ignore[misc]
    _installed = False
