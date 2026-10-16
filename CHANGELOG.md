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
