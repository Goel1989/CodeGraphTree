"""Project folder layout: analysis profile, database, rules (outside the analysed repository)."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from codegraph_sci.core.paths import data_dir

PROJECT_FILE = "project.json"


@dataclass(frozen=True)
class Project:
    folder: Path
    root: Path  # analysed repository

    @property
    def profile_path(self) -> Path:
        return self.folder / "analysis_profile.yaml"

    @property
    def db_path(self) -> Path:
        return self.folder / "project.sqlite"

    @property
    def rules_dir(self) -> Path:
        return self.folder / "rules"

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / PROJECT_FILE).write_text(json.dumps({"root": str(self.root)}, indent=1) + "\n",
                                                encoding="utf-8")


def default_project_folder(root: Path) -> Path:
    root = root.resolve()
    digest = hashlib.sha256(str(root).lower().encode("utf-8")).hexdigest()[:8]
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", root.name or "root")
    return data_dir() / "projects" / f"{name}-{digest}"


def open_project(root: Path | str | None = None, folder: Path | str | None = None) -> Project:
    """Project of ``root`` (created if needed), or the project stored in ``folder``."""
    if folder is not None:
        folder = Path(folder)
        meta = folder / PROJECT_FILE
        if root is None:
            if not meta.is_file():
                raise FileNotFoundError(f"{folder}: not a CodeGraph-Sci project (no {PROJECT_FILE})")
            root = json.loads(meta.read_text(encoding="utf-8"))["root"]
        project = Project(folder.resolve(), Path(root).resolve())
    else:
        if root is None:
            raise ValueError("either a repository root or a project folder is required")
        project = Project(default_project_folder(Path(root)), Path(root).resolve())
    project.save()
    return project
