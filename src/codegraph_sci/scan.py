"""``cgs scan``: deterministic pipeline Inventory -> Extract -> Link -> Index -> store (§3.3).

The scan reads only the analysis profile; it never calls the AI. Extraction runs file by file
(in worker processes for large repositories), each file with a time limit; a failure is recorded
and never blocks the analysis. Facts are cached (key: file + included files + adapter + parameters).
"""

from __future__ import annotations

import concurrent.futures as cf
import os
import posixpath
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codegraph_sci.algo.index import aggregate_edges, data_edges, file_and_dir_edges, node_statistics
from codegraph_sci.core.facts import FileFacts, ParseError, SourceFile, decode_facts, encode_facts
from codegraph_sci.core.graph import (
    DataAccessRecord,
    EdgeRecord,
    FileRecord,
    GraphBundle,
    InventoryRecord,
    PluginRecord,
    ScanRunRecord,
)
from codegraph_sci.core.plugins import ExtractContext, LanguageAdapter, decode_bytes, sha256_bytes
from codegraph_sci.core.profile import AnalysisProfile
from codegraph_sci.core.project import Project
from codegraph_sci.core.versions import APP_VERSION
from codegraph_sci.enrich.apply import PackEngine
from codegraph_sci.enrich.noise import hidden, noise_map
from codegraph_sci.enrich.packs import BUILTIN_PACKS, default_search_paths, load_packs
from codegraph_sci.extract.c import CAdapter
from codegraph_sci.extract.context import make_include_resolver
from codegraph_sci.extract.cpp import CppAdapter
from codegraph_sci.extract.fortran import FortranAdapter
from codegraph_sci.extract.python import PythonAdapter
from codegraph_sci.inventory.profile_io import (
    load_profile,
    profile_from_inventory,
    profile_sha256,
    save_profile,
)
from codegraph_sci.inventory.report import skipped_list
from codegraph_sci.inventory.run import InventoryResult, run_inventory
from codegraph_sci.link.linker import Linker
from codegraph_sci.store.cache import cache_key, get_facts, load_cache, previous_files
from codegraph_sci.store.writer import write_full, write_incremental

Progress = Callable[[dict[str, Any]], None]
IN_PROCESS_LIMIT = 48
MAX_FILE_BYTES = 8 * 1024 * 1024  # above: analysis limited (definitions not extracted) and reported


def keyword_profile_paths(project: Project, profile: AnalysisProfile) -> list[Path]:
    """Keyword profiles of the languages the profile maps to ``keywords:<language>`` (rules/languages/)."""
    out = []
    for lang, entry in sorted(profile.languages.items()):
        if entry.adapter.startswith("keywords:") and entry.status in (None, "approved"):
            path = project.rules_dir / "languages" / f"{lang}.yaml"
            if path.is_file():
                out.append(path)
    return out


def all_adapters(keyword_profiles: list[str]) -> dict[str, LanguageAdapter]:
    from codegraph_sci.extract.keywords import KeywordAdapter, load_keyword_profile

    adapters = native_adapters()

    for path in keyword_profiles:
        prof = load_keyword_profile(Path(path))
        if prof.status == "approved" and prof.language not in adapters:
            adapters[prof.language] = KeywordAdapter(prof)
    return adapters


def native_adapters() -> dict[str, LanguageAdapter]:
    return {"fortran": FortranAdapter(), "python": PythonAdapter(), "c": CAdapter(), "cpp": CppAdapter()}


class ScanCancelled(Exception):
    pass


@dataclass
class ScanOptions:
    jobs: int = max(1, (os.cpu_count() or 2) - 1)
    timeout_s: float = 60.0
    full: bool = False  # ignore the cache
    extra_known_arrays: set[str] = field(default_factory=set)
    cancel: Callable[[], bool] | None = None
    native_bridges: bool = True
    bridge_rules: list[dict[str, Any]] = field(default_factory=list)
    keyword_profiles: list[Path] = field(default_factory=list)
    packs: list[str] = field(default_factory=list)


@dataclass
class ScanResult:
    db_path: Path
    stats: dict[str, Any]


# ----------------------------------------------------------------- helpers
def python_module_namer(paths: list[str]) -> Callable[[str], str]:
    """Module names relative to the top of each package (directories holding ``__init__.py``)."""
    inits = {posixpath.dirname(p) for p in paths if p.endswith("/__init__.py") or p == "__init__.py"}

    def name(path: str) -> str:
        d = posixpath.dirname(path)
        top = None
        while d and d in inits:
            top = d
            d = posixpath.dirname(d)
        base = posixpath.dirname(top) if top is not None else ""
        rel = path[len(base) + 1:] if base else path
        for suffix in (".pyw", ".py"):
            if rel.endswith(suffix):
                rel = rel[: -len(suffix)]
        if rel.endswith("/__init__"):
            rel = rel[: -len("/__init__")]
        return rel.replace("/", ".")

    return name


def in_scope(path: str, profile: AnalysisProfile) -> bool:
    inc = [p.strip("/") for p in profile.scope.include if p.strip("/")]
    exc = [p.strip("/") for p in profile.scope.exclude if p.strip("/")]
    if inc and not any(path == p or path.startswith(p + "/") for p in inc):
        return False
    return not any(path == p or path.startswith(p + "/") for p in exc)


def git_revision(root: Path) -> str | None:
    head = root / ".git" / "HEAD"
    if not head.is_file():
        return None
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                             timeout=10, check=False)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def load_bridge_rules(project: Project, profile: AnalysisProfile) -> list[dict[str, Any]]:
    """Approved bridge rules of the profile (``rules/r-<n>.yaml``, format of a pack ``bridges[]`` entry)."""
    from codegraph_sci.inventory.profile_io import safe_load_yaml

    out: list[dict[str, Any]] = []
    for rule in profile.rules:
        if rule.kind != "bridge" or rule.status != "approved":
            continue
        data = safe_load_yaml(project.folder / rule.file)
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if isinstance(entry, dict):
                out.append({**entry, "id": rule.id})
    return out


# ------------------------------------------------------------- extraction
_WORKER: dict[str, Any] = {}


def _worker_init(root: str, include_paths: list[str], defines: dict[str, str], known_arrays: list[str],
                 py_paths: list[str], keyword_profiles: list[str] | None = None) -> None:
    root_path = Path(root)
    _WORKER["ctx"] = ExtractContext(include_paths=include_paths, defines=defines, known_arrays=set(known_arrays),
                                    resolve_include=make_include_resolver(root_path, include_paths),
                                    module_name=python_module_namer(py_paths))
    _WORKER["root"] = root_path
    _WORKER["adapters"] = all_adapters(keyword_profiles or [])


def _extract_job(path: str, lang: str, variant: str | None) -> tuple[str, bytes | None, str | None]:
    """Runs in a worker: returns (path, encoded facts, error)."""
    try:
        data = (_WORKER["root"] / path).read_bytes()
        if len(data) > MAX_FILE_BYTES:
            return path, None, f"file too large ({len(data) / 1e6:.0f} MB): not analysed"
        text, enc = decode_bytes(data)
        facts = _WORKER["adapters"][lang].extract(SourceFile(path, lang, variant, enc, text), _WORKER["ctx"])
        return path, encode_facts(facts), None
    except Exception as exc:  # noqa: BLE001 - recorded as a failed file, never blocking
        return path, None, f"{type(exc).__name__}: {exc}"


def _failed_facts(path: str, lang: str, message: str) -> FileFacts:
    return FileFacts(path=path, lang=lang, encoding="unknown", adapter=lang, adapter_version="-",
                     errors=[ParseError(message)])


def _run_parallel(jobs: list[tuple[str, str, str | None]], init_args: tuple[Any, ...], workers: int,
                  timeout_s: float, on_done: Callable[[str, bytes | None, str | None], None],
                  cancel: Callable[[], bool] | None) -> None:
    pending = list(jobs)
    while pending:
        executor = cf.ProcessPoolExecutor(max_workers=workers, initializer=_worker_init, initargs=init_args)
        futures = {executor.submit(_extract_job, *job): job for job in pending}
        pending = []
        remaining = set(futures)
        stalled = False
        try:
            while remaining:
                if cancel is not None and cancel():
                    raise ScanCancelled()
                done, remaining = cf.wait(remaining, timeout=timeout_s, return_when=cf.FIRST_COMPLETED)
                for fut in done:
                    path, blob, err = fut.result()
                    on_done(path, blob, err)
                if not done:
                    # No progress during the time limit: running files are stuck. Mark them failed
                    # and restart a fresh pool for the others.
                    for fut in remaining:
                        job = futures[fut]
                        if fut.running():
                            on_done(job[0], None, f"timeout after {timeout_s:.0f} s")
                        else:
                            pending.append(job)
                    stalled = True
                    break
        finally:
            if stalled:
                for proc in list(getattr(executor, "_processes", {}).values()):
                    proc.kill()
            executor.shutdown(wait=not stalled, cancel_futures=True)


# ------------------------------------------------------------------- scan
def scan(project: Project, options: ScanOptions | None = None, progress: Progress | None = None) -> ScanResult:
    options = options or ScanOptions()
    say = progress or (lambda _e: None)
    started = datetime.now(UTC).isoformat(timespec="seconds")
    t0 = time.perf_counter()
    root = project.root
    say({"event": "start", "root": str(root)})

    def check_cancel() -> None:
        if options.cancel is not None and options.cancel():
            raise ScanCancelled()

    # Profile: the analysis reads only this file (created by the inventory if missing).
    if project.profile_path.is_file():
        profile = load_profile(project.profile_path)
    else:
        profile = profile_from_inventory(run_inventory(root, None))
        save_profile(project.profile_path, profile)
    kw_paths = [str(p) for p in keyword_profile_paths(project, profile) + list(options.keyword_profiles)]
    adapters = all_adapters(kw_paths)
    from codegraph_sci.extract.keywords import KeywordAdapter

    keyword_exts = {ext: name for name, a in adapters.items() if isinstance(a, KeywordAdapter)
                    for ext in a.profile.extensions}
    inventory: InventoryResult = run_inventory(root, profile, keyword_extensions=keyword_exts)
    say({"event": "inventory", "files": len(inventory.entries)})
    check_cancel()

    sources = [e for e in inventory.source_files() if e.lang in adapters]
    py_paths = [e.path for e in sources if e.lang == "python"]
    packs = load_packs(sorted(set(profile.packs) | set(options.packs), key=lambda n: (n not in BUILTIN_PACKS, n)),
                       default_search_paths(project.folder))
    known_arrays = set(options.extra_known_arrays) | {a for pk in packs for a in pk.known_arrays}
    ctx = ExtractContext(include_paths=profile.include_paths, defines=dict(profile.preprocessor.defines),
                         known_arrays=known_arrays,
                         keep_all_branches=profile.preprocessor.keep_all_branches,
                         resolve_include=make_include_resolver(root, profile.include_paths),
                         module_name=python_module_namer(py_paths))
    params = ctx.params()

    # Cache from the previous analysis.
    old_cache = {} if options.full else load_cache(project.db_path)
    old_files = {} if options.full else previous_files(project.db_path)
    sha_cache: dict[str, str | None] = {}

    def current_sha(rel: str) -> str | None:
        if rel not in sha_cache:
            try:
                sha_cache[rel] = sha256_bytes((root / rel).read_bytes())
            except OSError:
                sha_cache[rel] = None
        return sha_cache[rel]

    def key_for(facts: FileFacts, file_sha: str, lang: str | None) -> str:
        adapter = adapters[str(lang)]
        includes = sorted({f"{i.resolved_path}:{current_sha(i.resolved_path)}" for i in facts.includes
                           if i.resolved_path})
        return cache_key(file_sha, includes, adapter.name, adapter.version, {**params, "lang": lang})

    facts_by_path: dict[str, FileFacts] = {}
    keys: dict[str, str] = {}
    shas: dict[str, str] = {}
    to_extract: list[tuple[str, str, str | None]] = []
    reused = 0
    for e in sources:
        sha = current_sha(e.path)
        if sha is None:
            continue
        shas[e.path] = sha
        prev = old_files.get(e.path)
        if prev and prev[0] == sha and prev[1]:
            cached = get_facts(old_cache, prev[1])
            if cached is not None and key_for(cached, sha, e.lang) == prev[1]:
                facts_by_path[e.path] = cached
                keys[e.path] = prev[1]
                reused += 1
                continue
        to_extract.append((e.path, str(e.lang), e.variant))

    errors: dict[str, str] = {}
    total = len(to_extract)
    done_count = 0

    def on_done(path: str, blob: bytes | None, err: str | None) -> None:
        nonlocal done_count
        done_count += 1
        lang = lang_of.get(path, "unknown")
        if blob is not None:
            facts_by_path[path] = decode_facts(blob)
        else:
            errors[path] = err or "unknown error"
            facts_by_path[path] = _failed_facts(path, str(lang), errors[path])
        if done_count % 50 == 0 or done_count == total:
            say({"event": "extract", "done": done_count, "total": total})

    lang_of: dict[str, str] = {e.path: str(e.lang) for e in sources}
    say({"event": "extract", "done": 0, "total": total, "cached": reused})
    if total <= IN_PROCESS_LIMIT or options.jobs <= 1:
        _WORKER.clear()
        _worker_init(str(root), profile.include_paths, dict(profile.preprocessor.defines),
                     sorted(known_arrays), py_paths, kw_paths)
        _WORKER["ctx"] = ctx
        for path, lang, variant in to_extract:
            check_cancel()
            on_done(*_extract_job(path, lang, variant))
    else:
        init_args = (str(root), profile.include_paths, dict(profile.preprocessor.defines),
                     sorted(known_arrays), py_paths, kw_paths)
        _run_parallel(to_extract, init_args, options.jobs, options.timeout_s, on_done, options.cancel)
    for path, _lang, _variant in to_extract:
        if path not in errors and path in facts_by_path:
            keys[path] = key_for(facts_by_path[path], shas[path], lang_of[path])
    check_cancel()

    # Link (in-scope files fully, the others as a light definitions index).
    timings = {"extract": round(time.perf_counter() - t0, 2)}
    say({"event": "link"})
    full = [f for p, f in sorted(facts_by_path.items()) if in_scope(p, profile)]
    outline = [f for p, f in sorted(facts_by_path.items()) if not in_scope(p, profile)]
    file_info = {e.path: (e.lang, e.lines) for e in inventory.entries if e.status == "source"}
    rules = list(options.bridge_rules) + [b for pk in packs for b in pk.bridges] + load_bridge_rules(project, profile)

    def read_text(rel: str) -> str | None:
        try:
            return decode_bytes((root / rel).read_bytes())[0]
        except OSError:
            return None

    origins = {lang: f"keywords:{lang}" for lang in adapters if lang not in native_adapters()}
    link = Linker(full, outline, file_info, origins, bridge_rules=rules, native_bridges=options.native_bridges,
                  read_text=read_text).run()
    check_cancel()

    # Index.
    timings["link"] = round(time.perf_counter() - t0 - sum(timings.values()), 2)
    say({"event": "index"})
    edges = aggregate_edges(link.call_sites, link.struct_edges)
    data_on = any((pk.data.get("data") or {}).get("fortran_common") or (pk.data.get("data") or {}).get(
        "fortran_module_variables") for pk in packs)
    data_records = [DataAccessRecord(a.src, a.data, a.family, a.mode, a.key_kind, a.file, a.line,
                                     "pack:generic_fortran") for a in link.data_accesses if data_on]
    if not data_on:
        link.nodes = [n for n in link.nodes if n.kind != "data"]
    # Declarative pack rules: memory manager, dispatch, catalogs, entry points, tests.
    enrichment = PackEngine(packs, full, {n.uid: n for n in link.nodes}, [e.path for e in inventory.entries],
                            read_text, outline).run()
    link.nodes = sorted(link.nodes + enrichment.nodes, key=lambda n: n.uid)
    data_records += enrichment.data
    merged: dict[tuple[str, str, str], EdgeRecord] = {}
    for de in data_edges([a for a in data_records if a.origin == "pack:generic_fortran"]) + enrichment.edges:
        key = (de.src, de.dst, de.kind)
        if key in merged:
            merged[key].site_count += de.site_count
        else:
            merged[key] = EdgeRecord(de.src, de.dst, de.kind, de.site_count, de.min_confidence, list(de.origins), [])
    edges = sorted(edges + list(merged.values()), key=lambda e: (e.src, e.dst, e.kind))
    reasons = {**noise_map(link.nodes, edges, packs), **enrichment.noise}
    stats_records = node_statistics(link.nodes, edges, hidden(reasons), reasons)
    file_edges, dir_edges = file_and_dir_edges(link.nodes, link.call_sites)

    bundle = GraphBundle()
    for e in inventory.entries:
        if e.status != "source":
            continue
        f = facts_by_path.get(e.path)
        status = "ok"
        if e.path in errors:
            status = "failed"
        elif f is not None and f.used_fallback:
            status = "fallback"
        elif e.lang not in adapters:
            status = "not_analyzed"
        elif not in_scope(e.path, profile):
            status = "outline"
        bundle.files.append(FileRecord(
            e.path, e.lang, e.variant, shas.get(e.path), e.size, f.encoding if f else None, status,
            f.adapter if f else None, f.adapter_version if f else None,
            errors.get(e.path) or ("; ".join(x.message for x in f.errors[:3]) if f and f.errors else None),
            e.mtime_ns, keys.get(e.path)))
        bundle.inventory.append(InventoryRecord(e.path, e.lang, e.variant, e.confidence, e.decided_by))
    known_files = {f.path for f in bundle.files}
    for n in link.nodes:
        if n.file and n.file not in known_files:
            bundle.files.append(FileRecord(n.file, n.lang, None, current_sha(n.file), 0, None, "not_analyzed"))
            known_files.add(n.file)
    bundle.nodes = link.nodes
    bundle.call_sites = link.call_sites
    bundle.data_accesses = data_records
    bundle.edges = edges
    bundle.node_stats = stats_records
    bundle.file_edges, bundle.dir_edges = file_edges, dir_edges
    bundle.plugins = [PluginRecord(a.name, "adapter", a.version) for a in adapters.values()]
    bundle.plugins += [PluginRecord(pk.name, "pack", pk.version) for pk in packs]
    bundle.facts_cache = {keys[p]: encode_facts(facts_by_path[p]) for p in keys if p in facts_by_path}
    stats: dict[str, Any] = {
        "files_source": len(sources), "files_extracted": total, "files_cached": reused,
        "files_failed": len(errors), "files_fallback": sum(1 for f in facts_by_path.values() if f.used_fallback),
        **link.stats, "edges": len(edges), "seconds": round(time.perf_counter() - t0, 2),
        "all_subfolders": profile.all_subfolders, "skipped_dirs": skipped_list(inventory, 200),
        "skipped_total": {"entries": len(inventory.skipped_dirs),
                          "files": sum(s.files for s in inventory.skipped_dirs)},
        "timings": {**timings, "index": round(time.perf_counter() - t0 - sum(timings.values()), 2)},
    }
    bundle.scan_run = ScanRunRecord(started, datetime.now(UTC).isoformat(timespec="seconds"), str(root),
                                    git_revision(root), profile.profile_version, profile_sha256(profile),
                                    [{"name": p.name, "type": p.type, "version": p.version} for p in bundle.plugins],
                                    {**stats, "app_version": APP_VERSION})
    say({"event": "write"})
    project.folder.mkdir(parents=True, exist_ok=True)
    if project.db_path.exists() and not options.full:
        write_incremental(project.db_path, bundle)
    else:
        write_full(project.db_path, bundle)
    stats["seconds"] = round(time.perf_counter() - t0, 2)
    say({"event": "done", **stats})
    return ScanResult(project.db_path, stats)
