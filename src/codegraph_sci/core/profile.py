"""Types of the analysis profile (``analysis_profile.yaml``, §3.2). Reading/writing lives in inventory."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from codegraph_sci.core.versions import PROFILE_VERSION_FORMAT


@dataclass
class Scope:
    include: list[str] = field(default_factory=list)  # empty = whole repository
    exclude: list[str] = field(default_factory=list)


@dataclass
class LanguageEntry:
    files: int
    adapter: str  # native:<lang>, keywords:<lang>, none
    variants: list[str] = field(default_factory=list)
    lines: int = 0
    source: str | None = None  # ai, manual
    status: str | None = None  # proposed, approved, rejected


@dataclass
class Preprocessor:
    defines: dict[str, str] = field(default_factory=dict)
    keep_all_branches: bool = True


@dataclass
class FileOverride:
    glob: str
    language: str
    reason: str = ""
    variant: str | None = None


@dataclass
class IgnoredGroup:
    ext: str
    files: int = 0
    reason: str = ""


@dataclass
class RuleRef:
    id: str
    kind: str  # bridge, language
    source: str  # ai, manual
    status: str  # proposed, approved, rejected
    file: str


@dataclass
class HistoryEntry:
    version: int
    change: str
    by: str


@dataclass
class AnalysisProfile:
    profile_version: int = 1
    format_version: int = PROFILE_VERSION_FORMAT
    scope: Scope = field(default_factory=Scope)
    languages: dict[str, LanguageEntry] = field(default_factory=dict)
    include_paths: list[str] = field(default_factory=list)
    preprocessor: Preprocessor = field(default_factory=Preprocessor)
    file_overrides: list[FileOverride] = field(default_factory=list)
    ignored: list[IgnoredGroup] = field(default_factory=list)
    exclude_dirs: list[str] = field(default_factory=list)
    packs: list[str] = field(default_factory=list)
    rules: list[RuleRef] = field(default_factory=list)
    history: list[HistoryEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        def lang(entry: LanguageEntry) -> dict[str, Any]:
            data: dict[str, Any] = {"files": entry.files, "lines": entry.lines, "adapter": entry.adapter}
            if entry.variants:
                data["variants"] = sorted(entry.variants)
            if entry.source:
                data["source"] = entry.source
            if entry.status:
                data["status"] = entry.status
            return data

        def override(o: FileOverride) -> dict[str, Any]:
            data: dict[str, Any] = {"glob": o.glob, "language": o.language, "reason": o.reason}
            if o.variant:
                data["variant"] = o.variant
            return data

        return {
            "profile_version": self.profile_version,
            "format_version": self.format_version,
            "scope": {"include": list(self.scope.include), "exclude": list(self.scope.exclude)},
            "languages": {k: lang(v) for k, v in sorted(self.languages.items())},
            "include_paths": sorted(self.include_paths),
            "preprocessor": {"defines": dict(sorted(self.preprocessor.defines.items())),
                             "keep_all_branches": self.preprocessor.keep_all_branches},
            "file_overrides": [override(o) for o in self.file_overrides],
            "ignored": [{"ext": g.ext, "files": g.files, "reason": g.reason} for g in self.ignored],
            "exclude_dirs": list(self.exclude_dirs),
            "packs": list(self.packs),
            "rules": [{"id": r.id, "kind": r.kind, "source": r.source, "status": r.status, "file": r.file}
                      for r in self.rules],
            "history": [{"version": h.version, "change": h.change, "by": h.by} for h in self.history],
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> AnalysisProfile:
        scope = data.get("scope") or {}
        pre = data.get("preprocessor") or {}
        return AnalysisProfile(
            profile_version=int(data["profile_version"]),
            format_version=int(data.get("format_version", PROFILE_VERSION_FORMAT)),
            scope=Scope(include=list(scope.get("include", [])), exclude=list(scope.get("exclude", []))),
            languages={
                name: LanguageEntry(files=int(v.get("files", 0)), adapter=str(v.get("adapter", "none")),
                                    variants=list(v.get("variants", [])), lines=int(v.get("lines", 0)),
                                    source=v.get("source"), status=v.get("status"))
                for name, v in (data.get("languages") or {}).items()
            },
            include_paths=list(data.get("include_paths", [])),
            preprocessor=Preprocessor(defines={str(k): str(v) for k, v in (pre.get("defines") or {}).items()},
                                      keep_all_branches=bool(pre.get("keep_all_branches", True))),
            file_overrides=[FileOverride(glob=o["glob"], language=o["language"], reason=o.get("reason", ""),
                                         variant=o.get("variant"))
                            for o in data.get("file_overrides", [])],
            ignored=[IgnoredGroup(ext=g["ext"], files=int(g.get("files", 0)), reason=g.get("reason", ""))
                     for g in data.get("ignored", [])],
            exclude_dirs=list(data.get("exclude_dirs", [])),
            packs=list(data.get("packs", [])),
            rules=[RuleRef(**r) for r in data.get("rules", [])],
            history=[HistoryEntry(**h) for h in data.get("history", [])],
        )
