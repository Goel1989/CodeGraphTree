"""Stable symbol identities (§3.5). Every uid is built here, never by string formatting elsewhere."""

from __future__ import annotations

import hashlib
import json
import re

_WS = re.compile(r"\s+")


def norm_path(path: str) -> str:
    """Repository-relative path with forward slashes."""
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def fortran_uid(name: str, module: str | None = None) -> str:
    if module:
        return f"f:{module.lower()}::{name.lower()}"
    return f"f:{name.lower()}"


def fortran_module_uid(module: str) -> str:
    """Fortran modules have their own prefix: a module and a procedure may share a name."""
    return f"fmod:{module.lower()}"


def c_uid(name: str, static_file: str | None = None) -> str:
    if static_file:
        return f"c:{name}@{norm_path(static_file)}"
    return f"c:{name}"


def normalize_cpp_params(params: list[str]) -> str:
    """Normalize C++ parameter types: collapse spaces, drop parameter names handled by the caller."""
    cleaned = []
    for param in params:
        p = _WS.sub(" ", param.strip())
        p = re.sub(r"\s*([*&<>,])\s*", r"\1", p)
        if p and p != "void":
            cleaned.append(p)
    return ",".join(cleaned)


def cpp_uid(qualified_name: str, params: list[str] | None, static_file: str | None = None) -> str:
    """``cpp:<ns>::<Class>::<method>(<normalized param types>)``; ``params=None`` for a non-function."""
    base = f"cpp:{qualified_name}"
    if params is not None:
        base += f"({normalize_cpp_params(params)})"
    if static_file:
        base += f"@{norm_path(static_file)}"
    return base


def py_uid(module: str, qualname: str | None = None) -> str:
    return f"py:{module}.{qualname}" if qualname else f"py:{module}"


def kw_uid(language: str, name: str, path: str) -> str:
    return f"kw:{language}:{name}@{norm_path(path)}"


def occurrence_uid(symbol: str, path: str, start: int, end: int) -> str:
    """Source occurrence identity, separate from a language's semantic symbol identity."""
    payload = json.dumps([symbol, norm_path(path), start, end], ensure_ascii=False, separators=(",", ":"))
    return "occ:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_uid(path: str) -> str:
    return f"file:{norm_path(path)}"


def entry_uid(name: str) -> str:
    return f"entry:{name}"


def data_uid(key: str) -> str:
    return f"data:{key}"


def test_uid(test_id: str) -> str:
    return f"test:{test_id}"


def ext_uid(library: str, name: str) -> str:
    return f"ext:{library}:{name}"


def variant_uid(uid: str, index: int) -> str:
    """Preprocessor variant: the 2nd definition of the same uid becomes ``uid#2``."""
    return uid if index <= 1 else f"{uid}#{index}"


def uid_prefix(uid: str) -> str:
    return uid.split(":", 1)[0]
