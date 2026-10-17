# Changelog

## Lot 0 — Portable Skeleton
- Repository layout (§3.16), `pyproject.toml`, import-linter contracts (§3.4), `tools/check.py`.
- `cgs --version`, `cgs selftest` (Qt, tree-sitter grammars, SQLite FTS5, data directory, CPU instruction sets, network guard).
- Network guard (`core/netguard.py`) installed on startup of `cgs` and the desktop application.
- Empty PySide6 main window with "About" dialog.
- `tools/build_portable.py` + two-executable PyInstaller spec (folder mode), Linux glibc 2.28 container, Linux + Windows CI.
- Measurement: portable Windows folder without AI = 129 MB.

## Lot 1 — Data Model and Storage
- `core/`: model vocabulary (§3.5), identities (`ids.py`), facts (§3.7) with compressed canonical JSON, graph records, analysis profile types.
- `store/`: versioned SQLite schema (§3.6), bulk write to a temporary file followed by atomic replacement, indexes created at the end, WAL mode for incremental updates (single transaction), facts cache; rejects unknown schema versions.
- `cgs export json`: sorted canonical export.
- Measurement: 1,000,000 call sites written in 5.4 s (Windows, SSD).

## Lot 2 — Language Inventory and Analysis Profile
- `inventory/`: directory traversal (`.gitignore`, excluded directories, symlink loops, unreadable files), configurable extension table (`extensions.yaml`), binary detection, content signatures (`#!`, mode lines, weighted keywords), repository context (`.h` C/C++, `.inc` Fortran), include paths, dialect variants (fixed/free form, preprocessor, Python 2), coverage report.
- `analysis_profile.yaml`: safe loading (`yaml.safe_load`) and strict JSON schema; version incremented only when content changes.
- `cgs inventory <folder>` (table or `--json`); project directory outside the repository (`core/project.py`).
- `inventory_mixed` fixture.
- Measurement: inventory of 15,000 files in 13.9 s (Windows).

## Lot 3 — Reference Mini-Codebases
- 15 fixtures (Fortran x8, Python, C, C++ x2, mini_hybrid, partial_scope, robustness) with `src/`, hand-written `expected_inventory.json` and `expected_graph.json`; JSON schemas for expected files.
- Deterministic multi-language synthetic repository generator (`tests/synthetic/generate.py`).
- Inventory: a `.h` included only by Fortran is classified as Fortran.
- Architecture Appendix D: extraction conventions specified.

## Lot 4 — Fortran Adapter
- Parser benchmark suite (`tools/bench_fortran.py`, report `docs/bench/fortran_parsers.md`); decision D18: custom logical statement parser.
- `extract/fortran/`: preprocessing (fixed/free form, columns 1–72, continuations, `;`, masked strings, `#if` branches preserved with conditions, `#include`/`INCLUDE` resolved), program units (modules, internal procedures, generic interfaces, derived types and type-bound procedures, `#2` variants), local symbols (arguments, arrays, `EXTERNAL`, `COMMON`, declarations from included files), `name(...)` rule from §3.7, intrinsic functions.
- Independent pattern extractor (fallback and dual extraction); fuzzing test (Hypothesis).
- All 9 Fortran fixtures produce the exact expected facts.

## Lot 5 — Python, C, and C++ Adapters
- `extract/python/`: `ast` module (local/enclosing/module/builtin scopes, relative imports, decorators, inheritance, simple propagation `x = Class()` and `h = getattr(m, "f")`), tree-sitter fallback for Python 2 and invalid files.
- `extract/cfamily.py` (C and C++, tree-sitter): definitions with §3.5 identities (normalized C++ signatures, file-qualified `static`, out-of-class methods), inheritance, partial macro expansion (file and included headers), preprocessor conditions, argument types for overload resolution, macro blocks (`PYBIND11_MODULE`); fallback pattern extractor.
- `extract/preproc.py`: shared preprocessor condition tracking.
- Python, C, C++, and `mini_hybrid` fixtures produce the exact expected facts; adapter fuzzing.

## Lot 6 — Link, Index, and `cgs scan` Command
- `algo/`: iterative Tarjan SCC, condensation DAG, bitset transitive impact size, bounded BFS traversals, k shortest simple paths; Index stage (aggregated edges, `node_stats`, `file_edges`, `dir_edges`).
- `link/`: per-language symbol tables (case-insensitive Fortran, host/module/transitive `USE` scopes, generic interfaces, type-bound procedures, variants; Python with MRO; C with per-file `static`; C++ with inheritance, virtual calls, overload resolution by arity and types), known externals (intrinsics, libc, MPI, BLAS/LAPACK, HDF5), `out_of_scope` state.
- `scan.py` and `cgs scan`: profile loading, inventory, parallel extraction with per-file timeout, oversized files reported, facts cache (key includes included headers), JSON progress events, atomic or incremental write.
- All 15 fixtures produce their exact expected graph; two consecutive scans produce an identical export.
- Measurements (Windows, 8 cores): synthetic repository with 15,000 routines / 3,000 files / 121,387 call sites scanned in 50 s; incremental re-scan after 50 modifications in 16.5 s; impact size of 15,000 nodes in 0.06 s.

## Lot 7 — Validation Tools on Real Codebases (Checkpoint)
- `audit/` and `cgs audit`: `inventory` (consistency), `baseline` (independent text reference), `diff` (dual extraction per language), `invariants` (duplicates, unresolved sites grouped by pattern, uncalled routines, failures), `sample` / `recall-sample` (fixed-seed stratified samples), `review` (single-keystroke review), `report` (§2.1 metrics with Wilson confidence intervals), `accept` + `replay` (`reference_sample.yaml` replayed automatically), `corpus` (manifest + expectations).
- Templates `tests/corpus/code_aster_start` and `code_aster_full` (to be filled with local source path and revision).

## Lot 8 — Cross-Language Bridges
- Binding extraction: pybind11 modules (`m.def`), Python C-API extensions, `BIND(C, NAME=)` names on Fortran routines and interfaces.
- `link/bridges/`: native bridges `pybind11`, `python_extension`, `c_cpp`, `fortran_c` (trailing underscore, uppercase, g77 double underscore, `BIND(C)`); `prefix_calls` rules (longest-to-shortest prefix matching, explicit `name_transform`) and `declaration_patterns` (`binding` nodes, never call sites); approved profile rules (`rules/r-<n>.yaml`).
- `binds` / `bridges` edges, obsolete external nodes pruned; "bridges" stratum in precision sampling.
- Fixtures `bridge_pybind11`, `bridge_fortran_c`, `bridge_prefix_negative`, and `mini_hybrid` with bridges: exact graphs, full Python → C++ → C → Fortran chain recovered, zero unresolved sites.

## Lot 9 — Query API and Command Line
- `query/`: `GraphQuery` (§3.10) — `inventory`, `find` (FTS5 fuzzy search + names), `resolve`, `node`, `callers` / `callees` (distinct callers, files, line-by-line sites, noise hiding), `children` (routine, file, directory; paginated), `file_links`, `call_sites`, `paths` (bounded k simple paths, dispatch steps marked `possible`), `impact` (bounded transitive callers, entry points), `data_accesses`, `unresolved` (grouped by pattern), `scan_health`, `source` (staleness check: size/mtime then SHA-256).
- CLI commands `cgs callers`, `callees`, `find`, `file-links`, `path`, `impact`, `data`, `unresolved`, `health` (table or `--json`).
- Added indexes: `call_site_candidates(dst_node)`, `nodes(display_name)`.
- Measurements on synthetic repository (15,000 routines): callers of a hub 11 ms, children expansion 2 ms, search 7 ms, depth-3 impact 197 ms.

## Code_Aster Validation (Lot 7) — Generic Improvements
- `code_aster_start` corpus: Code_Aster 17.5.7 partial checkout (`bibfor`, `bibcxx`, `bibc`, `code_aster`; 18,446 files) in `corpus_src/` (unversioned); manifest updated (v17 contact: `cont_*`).
- Inventory: include path inferred from `#include "asterfort/x.h"` → `bibfor/include`.
- Fortran: recursive preprocessor macro expansion (file and included headers) within statements while preserving macro source coordinates: macro-defined types, function-like macros, statement macros.
- Python: raised recursion limit during extraction; star imports, re-exports, and callable instances tracked by Link.
- C/C++: Python C-API and `py::`, `pybind11::`, `boost::`, `Eigen::` namespaces classified as external; smart pointers (`shared_ptr<X>`, `XxxPtr`); method-name fallback when receiver class is unknown.

## Lot 10 — Desktop Application (Initial Release)
- Main window (§3.11): inventory (force language, ignore extension → `cgs profile`), search, Callers / Callees panel with call sites, syntax-highlighted code inspector (highlighted call sites, double-click → called routine, "file changed" banner + Re-analyze), file explorer, lazy tree list (pages of 50, "+N more", "↺ already shown"), analysis health, filters (utilities, confidence, AI links, ambiguous sites).
- Queries executed in Qt thread pool; inventory, scan, and profile updates run in `cgs` subprocess with JSON progress and cancellation.
- `pytest-qt` tests: scenarios S1, S2, S10, and models.

## Lot 11 — Interactive TreeGraphs (Functions and Files)
- Incremental deterministic `TreeLayout` (`place_root`, `place_children`, `place_parents`) where already-placed nodes never move.
- Automatic detection of `main` (`default_roots`, `initial_subgraph`) displaying the first $N$ nodes on startup, directional arrows (`caller ──► callee`), click-to-expand all connected callers and callees (`connected_neighbors`), and "Paths to main" filter (`paths_from_main`, falling back to the shortest path when multiple paths exceed the threshold).

## Lot 12 — Packs, Keyword Language Profiles, and Noise Filtering
- `enrich/`: strict pack schema (§3.8) and safe loader; built-in packs `generic_noise` (hubs) and `generic_fortran` (`COMMON`, module variables); rule engine: `memory_access` (literal, local, symbolic, and family keys, simple string assignment propagation), `dispatch` (`SELECT CASE`), `catalogs`, `entry_points` (fallback target), `tests`; `noise.hide` / `optional` / `auto_detect_hubs`.
- `extract/keywords/`: keyword-based adapter (§3.9) and profile schema; `keywords_language` fixture (hand-written profile, 100% measured coverage).
- Fortran: data accesses (read/write), `SELECT CASE` branches, nested interfaces inside interface bodies.
- `pack_acme` and `fortran_data` (with pack) fixtures exact; core isolation test (§6.4).
- Code_Aster 17.5.7 (starter corpus): 0 failures, definition recall 99.6%, Fortran `CALL` recall 100%, unresolved rate 9.2% (Python/C++ idioms covered by pack).

## Code_Aster Validation — Follow-up
- C/C++: full preprocessor macro expansion (`extract/cmacro.py`: parameters, `#`, `##`, `__VA_ARGS__`, first-definition wins); macro-declared functions named after their expansion (`DEFS(X, x, …)` → `x_`). Effect on Code_Aster: 720 C/C++ → Fortran calls linked via `fortran_c` bridge (`CALL_*`/`CALLO_*` macros).
- Link: ambiguous call sites with more than 8 candidates drop candidate edges (eliminating false `get` hubs).
- Measurements (17.5.7 starter corpus, generic packs): 0 failures, definition recall 99.2%, Fortran `CALL` recall 100%, unresolved 8.5%; incremental re-scan ~50 s. Detected hubs: `assert`, `utmess`, `jeveuo`, `jemarq`, `jedema`… Regenerated review sheets (`tests/corpus/code_aster_start/review/`).

## Lot 13 — AI: Unknown Language Identification and Keyword Completion (Mock Model; Real GGUF Optional)
- Pro extension: `cgs ai-worker` (separate subprocess, JSON over stdin/stdout, no ports), `cgs complete` (Roles 1 and 2), `cgs ai-approve` (one-click approval), registered via `codegraph_sci.commands` entry point (core never imports Pro).
- Models: deterministic recorded-response mock (`tests/ai/`) and `llama-cpp-python` (CPU GGUF, JSON-schema constrained output, temperature 0), loaded only when installed.
- Automated verification gates replaying Link on cached facts: gain ≥ 50%, zero regression, plausible targets ≥ 90%, two-sample stability, new-links ceiling; diff preview of added/removed links; written to profile (`proposed`, or `approved` in automatic mode).
- Fixtures `unknown_extension`, `bridge_unknown_prefix`; keyword profile proposed from technical documentation.

## Lot 14 — Code_Aster Pack (Starter Corpus)
- `code_aster` pack (`src/codegraph_sci_pro/packs/`): noise rules, JEVEUX arrays, memory accesses (`jeveuo`, `wkvect`, `jecreo`, `jecrec`, `jedetr`), `te0000`/`lc0000` dispatchers, commands (`OPER`/`MACRO`); items verified against 17.5.7 (`docs/packs/code_aster.md` §7); glossary for local AI.
- Pack discovery: project folder, `CGS_PACKS_PATH`, portable folder, Pro extension (located without importing).
- Starter corpus: 16/16 expectations met (265 commands, `te0000` → 600 elementary routines, `lc0000` → 86 constitutive laws, 3,528 JEVEUX accesses).

## 3D view (3d-force-graph via PyWebView)
- Audit of commit 44659bc (English translation, TreeGraph navigation to `main`): all checks green (168 tests).
- `GraphQuery.graph3d()`: bounded, deterministic neighbourhood (callers and callees) in `functions`, `files` or `both` mode (files defining routines, file-to-file links).
- `cgs view3d <routine> [--mode] [--depth] [--max-nodes] [--export page.html]`: PyWebView window in its own process, no HTTP server, no port, CSP forbidding network access; vendored 3d-force-graph 1.80.1 (three.js r186). Click = select in the main window; right-click = expand on demand; search, legend, arrows, flow particles on cross-language bridges.
- Desktop app: "3D view" button and mode selector; selection comes back through stdout events.
- Decision D20 (Streamlit rejected: web server and port, contrary to C1/C2); optional extra `view3d` (`pywebview`).

## 3D graphs in the main window (decision D21)
- The "Functions TreeGraph" and "Files TreeGraph" tabs are replaced by **Functions 3D** and **Files 3D**: the 3d-force-graph page embedded in a `QWebEngineView` (`ui/graph3d_view.py`). Start at `main`, follow the selection, right-click to expand a node, "Paths to main", depth and node ceiling (300 by default), optional defining files; click on a link lists its call sites.
- `GraphQuery.graph3d_main_paths(target, mode)`; the 3D page now serves two hosts (Qt bridge through console messages, or PyWebView `js_api`), survives a missing WebGL, fits the camera once the layout settles, and colours files by language in files mode.
- Offline: CSP, Qt's off-the-record profile, request interceptor allowing only `file`, `data`, `blob`; no server, no port.
- The 2D `ui/treegraph.py` and the "3D view" toolbar button (separate PyWebView process) are removed; `cgs view3d` stays available.
- Portable build: Qt WebEngine is no longer excluded.

## Dark & orange interface (decision D22)
- Frameless window with a 28 px orange title bar (minimize, maximize, close; drag to move, double-click to maximize, edges to resize).
- Icon rail (Explore, Project) and a list of views with the active one on an orange gradient; search and file explorer below it.
- Header band with the view title in capitals; hero card of the selected routine with 48 × 48 badges (callers, callees) and buttons opening popovers (Show in, Filters, Analysis).
- Dark theme everywhere: style sheet and Fusion palette (`ui/theme.py`), code colours and site highlights for a dark editor, 3D page in the same colours.
- Opening a project now stops the inventory or analysis still running for the previous one.

## Every sub-folder, and what is left out
- The inventory reports each folder (or `.gitignore`d file) it leaves out, with its reason (default exclusion, .gitignore, profile) and file count: `cgs inventory`, `skipped_dirs` in the JSON output and the scan statistics, Inventory view.
- New profile option `all_subfolders` (`cgs profile all-subfolders <folder> on|off`, "Analyze all subfolders" box in the Inventory view): analyze every sub-folder, ignoring `.gitignore` and the default exclusions; `.git`, `.hg`, `.svn` and the profile's `exclude_dirs` still apply.

## Whole-project view: groups, links between folders, non-code files (decision D23)
- Functions 3D and Files 3D open on the whole project: every node and link when it fits under the node ceiling, otherwise one sphere per group of linked routines or files (separate or parallel programs), an "isolated" sphere and a "more groups" sphere; a click opens a group, "All groups" comes back.
- Links between two folders are flagged (`cross_dir`) and drawn in their own colour ("between folders" box).
- Files that are not analyzed code are classified (docs, data, configuration, images, archives, binary, unknown type, code without adapter), recorded by the analysis and set apart in a grey grid in Files 3D ("non-code files" box).
- `GraphQuery.groups`, `graph3d_overview`, `graph3d_group`, `non_code_files`; Code_Aster: 275 function groups (main program 7,538 functions, elementary routines 601, behaviour laws 87) in about 1 s.

## Fixes from the external code review
- Fortran: a generic interface named like its specific procedure (`interface helper` / `module procedure helper`) now resolves to the procedure (the call and the `implements` link were lost).
- Fortran: intrinsic subroutines called with `CALL` (`system_clock`, `c_f_pointer`, `cpu_time`, `mvbits`, …) are external intrinsics, no longer unresolved; a routine of the repository with the same name still wins. Fortran adapter 1.5 (cached facts are re-extracted).
- `CallerReport.unresolved_sites` / `ambiguous_sites`: `cgs callers|callees` and the window summary say which call sites are not counted, instead of a bare "calls 0 routine(s)".
- `cgs … | head` ends quietly (broken pipe, and EINVAL on Windows).
- `README.md`; coding rule 16 (coherent changes, no degradation; when in doubt, report before changing).

## One product (decision D24, corrective audit phase 1)
- `codegraph_sci_pro` is merged into the product: the local AI moves to `codegraph_sci.ai`, its commands (`ai-worker`, `complete`, `ai-approve`) to `codegraph_sci/cli_ai.py`, registered directly by `cgs`; the `pro` entry point is removed.
- The `code_aster` domain pack moves to `packs/code_aster/` at the repository root (data outside the core, rule 7); pack discovery uses the installation's `packs/` folder, and the portable build now copies it.
- New import contract: `scan` and `audit` never import the AI (rule 8).
- `tools/build_portable.py --with-model` replaces `--edition ai`: two portable variants of the same software, not editions.

## Dual licensing documents (corrective audit phase 2)
- `LICENSE`: exact, unmodified text of the PolyForm Noncommercial License 1.0.0 (downloaded from polyformproject.org, SHA-256 `ffcca388…94cc8`).
- `NOTICE` (copyright and PolyForm `Required Notice:` line), `LICENSING.md` (one product, two licensing paths, examples, no telemetry, no feature gating), `COMMERCIAL_LICENSE.md` (contact channel to be announced), `CONTRIBUTING.md` (English-only rule, coding rules, CLA pending legal review), `THIRD_PARTY_NOTICES.md` (license audit of every redistributed component, from installed metadata).
- `docs/legal/community_license_strict_DRAFT.md`: stricter business-use rule, marked DRAFT — LEGAL REVIEW REQUIRED, not in force.
- `docs/strategie_licence.md` becomes `docs/licensing_strategy.md` v2.0: Free/Pro/Enterprise feature tiers and the Ed25519 license-key system are withdrawn (D24); legal review checklist.
- The portable folder's `licenses/` now receives `LICENSE`, `NOTICE`, `LICENSING.md`, `COMMERCIAL_LICENSE.md` and `THIRD_PARTY_NOTICES.md`.

## Engine reliability (decision D25, corrective audit phase 3)
- `cgs audit corpus`: expectations end PASS, FAIL or SKIP (`required: false` for optional ones); exit codes 0 (all required PASS), 1 (a required FAIL), 2 (configuration: manifest, expectations, sources, revision, packs), 3 (internal error); never 0 when validation did not run.
- The manifest is authoritative: the audit profile is rebuilt from the inventory and the manifest, required packs must load, the Git revision is verified; the report (`--json`) records manifest, expectations and audit-profile hashes, source revision, tool, adapter and pack versions.
- Per-file extraction deadlines in worker processes (`extract_pool.py`): a stuck file kills only its own worker and is stored with `parse_status = timeout`; extraction used to run without any deadline for small analyses or `jobs=1`. Workers now honour `keep_all_branches`.
- FULL / OUTLINE extraction: out-of-scope files keep only definitions and includes; the mode is part of the facts and of the cache key. Code_Aster: identical definitions on 3,000 sampled Fortran files, 39% less parsing time for them.
- Fix: a backspace character had replaced `\b` in the Fortran END SELECT pattern since lot 12, so nested SELECT CASE values could be attributed to the wrong selector (Fortran adapter 1.6). New test: no control character in project sources.
- Code_Aster 17.5.7 re-validated with the new audit: exit code 0, 16 PASS / 0 FAIL / 0 SKIP, revision verified; graph identical (47,161 call edges); full re-extraction of 18,438 files in 91 s (803 s for the previous full analysis on the same machine; the shares of OUTLINE, worker processes and machine load were not isolated).

## Reproducibility and measurement (decision D26, corrective audit phase 4)
- Dependency locks: `requirements.lock` (runtime, redistributed) and `requirements-dev.lock` (build, development), generated offline by `tools/lock_dependencies.py`; CI installs from them and checks the environment; `build_portable` refuses an unlocked environment. Hashes are added at release time (network needed).
- Phase instrumentation: `phases_ms` (inventory, cache lookup, extraction wall/FULL/OUTLINE, link, enrich, index, SQLite write, total) and per-mode file counts in every scan.
- `cgs benchmark <folder> [--changed N]`: cold, unchanged and changed rescans with the machine description. `docs/bench/scan_benchmark.md`: on an 8-CPU Windows machine, rescan after 50 changed files 10.8–10.9 s (synthetic, 3,000 files) and 25.9 s (Code_Aster sample, 18,438 files), dominated by the rebuild after extraction.
- `GraphQuery.reference_categories()` and `cgs health`: non-resolved references by category (external_known, out_of_scope, ambiguous, dynamic, parser_limitation, unknown); Python modules outside the standard library are no longer counted as known externals.
- `tools/prepare_corpus.py`: fetch a corpus at the exact revision of its manifest (repository, sparse folders).
- `docs/validation/code_aster_start.md` / `.json`: Code_Aster 17.5.7 validation with provenance (tag and commit, manifest, expectations and audit-profile hashes, versions, machine): 16 PASS / 0 FAIL / 0 SKIP; unresolved call sites 8.53% (target 2% not met), split by category; precision and recall not measured yet (review sheets not filled).

## Final consistency (corrective audit phase 5)
- Offline promise stated precisely (no cloud service, analysed code never sent; Python-level socket guard, not an operating-system sandbox) in README, About dialog, constraint C2 and decision D3.
- Performance table: targets kept, with a "Measured (documented)" column; unmeasured items say so. README and pack status no longer claim validation beyond the measured expectations.
- Architecture repository tree matches the repository; planned items (`models.lock`, `tests/portable`) are marked.
- `docs/migration_report.md`: changes by phase, tests, Definition of Done status, remaining risks, legal-review items and decisions pending with the owner.

