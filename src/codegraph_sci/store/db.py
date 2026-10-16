"""Opening project databases with schema-version checks."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path

from codegraph_sci.core.versions import DB_SCHEMA_VERSION


class SchemaVersionError(RuntimeError):
    """The database was written by an unknown (newer or older) schema version."""


def schema_sql() -> str:
    return resources.files("codegraph_sci.store").joinpath("schema.sql").read_text(encoding="utf-8")


def indexes_sql() -> str:
    return resources.files("codegraph_sci.store").joinpath("indexes.sql").read_text(encoding="utf-8")


def check_version(con: sqlite3.Connection, path: Path | str) -> None:
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if version != DB_SCHEMA_VERSION:
        raise SchemaVersionError(
            f"{path}: database schema version {version} is not supported "
            f"(expected {DB_SCHEMA_VERSION}); re-run the analysis"
        )


def open_db(path: Path | str, *, read_only: bool = True) -> sqlite3.Connection:
    """Open an existing project database; refuses an unknown schema version."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no project database at {path}")
    if read_only:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
    else:
        con = sqlite3.connect(str(path), check_same_thread=False)
    try:
        check_version(con, path)
    except Exception:
        con.close()
        raise
    con.execute("PRAGMA foreign_keys=OFF")
    return con
