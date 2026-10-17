# CodeGraph-Sci — Architecture and Implementation Plan

**Version:** 7.0 — execution document (October 16, 2026)  
**Author:** Marian Bogdan Neagoe, PhD  
**Purpose:** desktop application, 100% offline, identifying languages in a scientific or industrial codebase (Fortran, Python, C, C++ initially), building the "who calls who" graph across these languages, and answering the question "who calls what, and where?".

> **How to use this document.**
>
> - **§0 to §2:** what the application must do, and technical bottlenecks to address first.
> - **§3:** architecture, along with the contracts that the code must follow.
> - **§4 and §5:** implementation plan in numbered **lots**, each with its validation test, followed by the test strategy.
> - **§6 to §8 and appendices:** extensibility, license constraints, decisions, developer agent guidelines (Appendix C, to copy into `AGENTS.md`).
>
> This document is **generic**: no rule specific to an analyzed codebase appears here. Each codebase is a test case described in `docs/packs/<code>.md`. The business and licensing strategy is in `docs/strategie_licence.md`.

---

## 0. At a Glance

**What the application does.** Given a source code folder:

1. It **identifies present languages**, file by file, and verifies that it can analyze all of them.
2. If a language or a cross-language bridge is unknown, the **local AI defines missing keywords** (definitions of functions and subroutines, calls, includes, cross-language bridges). Its proposals are automatically validated, shown to the user with their effect on the graph, and saved in the project's **analysis profile**.
3. The analysis, **entirely deterministic**, builds the call graph from this profile and stores it in a local database. Each call observed in code is preserved as a **call site** (file, line, column, condition, origin).
4. A desktop window allows exploring it: for each routine, **how many routines call it and which ones**, what it calls, links between files, the path between two routines, and the impact of a change.

**Non-negotiable constraints**

| # | Constraint | Technical consequence |
| :--- | :--- | :--- |
| C1 | Desktop application, no web app | Python + Qt (PySide6) interface; neither browser nor server |
| C2 | 100% offline | No network access, no open ports, verified on the distributed application |
| C3 | Full version transferable on a USB drive | Portable folder with embedded Python, one per OS: Linux x86_64 (target: Ubuntu) and Windows x64 |
| C4 | Modest machine, CPU only | Interface never loads the entire graph; everything is precomputed and paginated; AI is only invoked on samples |
| C5 | Deterministic structure | Same repo + same analysis profile + same versions = same graph; AI prepares the profile, it never intervenes during analysis |
| C6 | Multi-language repositories from the start | The first test case mixes Fortran, Python, and C or C++: language inventory and all four adapters arrive in early lots |
| C7 | Extensible | New languages and new codebases added via plugins or keyword profiles, without modifying the core |
| C8 | No compiler available | Validation of analysis without compilation, through verified samples (§2.1) |

**Implementation order.** Built bottom-up; each lot finishes with a test that must pass before starting the next one (details in §4). Lot 7 is a **stop point**: as long as graph accuracy is not demonstrated, UI development does not start.

| Lot | Title | Depends on |
| :--- | :--- | :--- |
| 0 | Portable skeleton (USB drive, offline) | — |
| 1 | Data model and storage | 0 |
| 2 | Language inventory and analysis profile | 1 |
| 3 | Reference mini-codebases (tests written before code) | 2 |
| 4 | Fortran adapter (with parser benchmark) | 3 |
| 5 | Python, C, and C++ adapters | 3 |
| 6 | Link, Index, and `cgs scan` command | 4, 5 |
| 7 | Validation on a real codebase (Bottleneck V1, stop point) | 6 |
| 8 | Cross-language bridges | 6 |
| 9 | Query API and command line | 7, 8 |
| 10 | Desktop application: inventory, search, callers, inspector | 9 |
| 11 | Files and functions TreeGraph | 10 |
| 12 | Packs, keyword-based language profiles, noise filtering | 11 |
| 13 | AI: language identification and keyword completion | 12 |
| 14 | Test case #1 Pack | 13 |
| 15 | AI: explanations | 13 |
| 16 | Pro Edition, license compliance, and final release | 14, 15 |

---

## 1. What the application must do

### 1.1. Questions it answers

| Priority | Question | Example answer |
| :--- | :--- | :--- |
| **At opening** | Which languages does this repo contain, and are they all covered? | "Fortran 9,120 files, Python 2,400, C++ 1,830, C 210 — all covered; 40 `.xyz` files: unknown language, keywords proposed by AI" |
| **Default** | How many routines call `X`, and which ones? | "`X` is called by 37 routines across 21 files" + list (routine, file, line of each call) |
| 1 | What does `X` call? | List of called routines, with call lines |
| 1 | Which files are linked to this file? | Called and calling files, with number of calls |
| 2 | How does `A` reach `B`? | Possible call paths from `A` to `B` across languages, with nature of each step |
| 2 | If I modify `X`, what is affected? | Transitive callers, entry points, tests |
| 3 | What data does `X` read or write? | `COMMON` blocks, module variables, memory objects described by a pack, with their precision level |
| 3 | Which tests should be re-run after a modification? | Ranked list (with a pack describing the codebase's tests) |

### 1.2. Application views

| View | Content | Usage |
| :--- | :--- | :--- |
| **Language inventory** | Per language: file and line count, adapter used (native, keyword profile, none); unrecognized files; AI proposals and their status | Know what is analyzed and how |
| **Search** | Single field: routines, files, modules (fuzzy search) | Starting point for any exploration |
| **Callers / Callees panel** | Count + sortable list; double-click → code at call line | Answer to the default question |
| **Functions 3D** | 3D graph (3d-force-graph) of the callers and callees around a routine, starting at `main`; right-click expands a node, "Paths to main" keeps only the chains from `main` | Understand a call chain |
| **Files 3D** | Same principle at file level: link = at least one call, thickness = call count; click on a link → detailed calls | Understand module architecture |
| **File explorer** | Repository directory tree with language, routine count, and link count per file | Traditional navigation |
| **Code inspector** | Read-only syntax-highlighted source, call lines highlighted; click on call → called routine; alert if file changed since analysis | Read code |
| **Analysis health** | Analyzed, fallback, failed files; grouped ambiguous and unresolved sites; validation metrics | Know if the graph can be trusted |

In both 3D graphs a node is drawn once whatever the number of paths reaching it (cycles and shared calls stay legible); the drawn neighbourhood is bounded by a depth and a node ceiling (decision D21, which replaced the 2D TreeGraphs).

### 1.3. Non-functional requirements

Reference machine: 4-core laptop, 8 GB RAM, no dedicated GPU. These targets are **metrics to measure** (lots 2, 6, 7, 9, 11, 13); they will be adjusted based on actual measurements.

| Metric | Target |
| :--- | :--- |
| Language inventory of a ~15,000 file repository | < 1 min |
| Full analysis of the same repository | < 15 min |
| Re-analysis after modifying at most 50 files | < 30 s |
| AI-assisted preparation (identification + completion) | At most 3 iterations of 10 model calls; each call < 60 s |
| Opening an already analyzed project | < 3 s |
| Callers of a routine (count + list) | < 100 ms |
| Expanding a node in a 3D graph | < 200 ms |
| Concurrently rendered nodes | 300 by default (configurable); beyond that, "+N" grouping |
| Application RAM usage, without AI | < 1.5 GB on test case #1 |
| Interface during an analysis | Remains responsive (analysis in separate process) |

### 1.4. What static analysis can and cannot tell

- It provides **possible execution paths**: everything that code *can* call.
- The path **actually followed** during execution depends on input data: a `SELECT CASE` picks a branch at runtime. Path steps going through a dispatch are displayed as "possible". A pack can narrow paths from an entry point or option; it cannot guess them without running code.
- Each displayed link has a **confidence level** (`exact`, `resolved`, `heuristic`, `ambiguous`), an **origin** (native adapter, keyword profile, bridge, AI-proposed rule…), and evidence (call sites): the user always knows what underlies what they see.
- For data, **an approximate link flagged as such is better than false precision**: an access whose exact object is unknown is attached to an object family and marked accordingly (§3.5).

### 1.5. Role of AI

Local AI has three roles, in order of priority:

1. **Identify languages** that deterministic inventory could not recognize (unknown or ambiguous extension, file without extension), using extension and content of a few sample files.
2. **Verify all elements needed to build the graph are present, and otherwise define missing keywords:**
   - for a language without an adapter: definition keywords (function, subroutine, procedure…), call, include, comment and string markers → a **keyword-based language profile** (§3.9);
   - for unresolved calls: cross-language bridge prefixes or keywords (e.g. macro prefix calling a Fortran routine from C++) → a **bridge rule**.
   AI can rely on technical documentation provided by the user; otherwise, on its prior language knowledge.
3. **Explain** a routine based on what the graph provides, with verified citations.

**How AI remains compatible with determinism and correctness**

- Its proposals are **automatically checked** (§3.13). These checks measure plausibility, not truth: a target that exists is not necessarily the right one. This is why, by default, the user **validates in one click** after seeing a preview of added and removed links. An automatic adoption mode exists, configurable per project (§3.13).
- An adopted proposal is **written to the project's analysis profile**, a frozen, versioned file. Analysis only reads this profile: it never calls AI.
- Links stemming from an AI-proposed rule remain **marked as such** (`origin`, `heuristic` confidence) and can be hidden in one click.
- **Without a model** (edition without AI), everything works: unknown languages are reported, and keyword profiles can be written manually.

---

## 2. Technical bottlenecks and how to overcome them

### 2.1. Bottleneck V1 — Accurate extraction in a multi-language repository, without a compiler

**Why it is difficult**

- **Recognizing the language of each file:** `.h` can be C or C++, `.inc` can be Fortran or something else, some files have no extension, `.F90` must go through the preprocessor, `.f` is often fixed-form.
- **Fortran:** preprocessor (`#ifdef`, `#include`); fixed and free forms; `x = f(i)` is either a function call or an array access, and the array declaration is often in an included file or a `COMMON` block; intrinsic functions; generic interfaces, procedures passed as arguments; "call x" inside a comment or string literal.
- **C and C++:** macros hiding calls, overloads (two methods with the same name), `static` functions with the same name in different files, templates.
- **Python:** dynamic calls; legacy Python 2 files that Python 3's `ast` module cannot parse.
- **Everywhere:** legacy encodings (Latin-1 with accented comments), Windows line endings, very large or malformed files.

**How to prove correctness without a compiler.** Automated checks in `cgs audit` (Lot 7):

| Check | Principle | What it measures |
| :--- | :--- | :--- |
| Reference mini-codebases | Small hand-written repos whose expected inventory and graph are known exactly | Accuracy on every pitfall |
| Inventory consistency | Language of each file checked against context: a `.h` included by C++ files is C++, a `.inc` included by Fortran is Fortran | Misattributed files |
| Independent textual baseline | Simple line-by-line search for definitions (`SUBROUTINE`, `FUNCTION`, `def`, `class`…) and `CALL` statements outside comments and strings | **Cross-check** of recall. This baseline is itself imperfect: discrepancies with the graph are investigated, not taken as ground truth |
| Dual extraction | Two different extractors per language (parser and pattern-based extractor); each disagreement is listed and categorized | Errors specific to either tool |
| **Precision sample** | Stratified draw of resolved links: one group per language, plus a "bridges" group; ~150 links per group (fixed seed), manually verified in a review sheet (one keystroke per link) | **Precision**, with confidence interval |
| **Recall sample** | Random draw of code locations (lines likely to contain a call); human marks calls actually present; compared with extracted call sites | **Recall** of call sites, with confidence interval |
| Invariants | Duplicate definitions, unresolved sites, never-called routines, failed files | Overall consistency |

Manually verified samples are **recorded** (`reference_sample.yaml` in the corpus). They become an automated regression test: manual effort (a few hours) is only performed once per corpus.

**Metrics and thresholds** (on test case #1, for each of its languages; lower bounds = 95% Wilson score interval):

| Metric | Definition | Threshold |
| :--- | :--- | :--- |
| File attribution | Source files assigned to a covered language or explicitly classified (ignored, unknown) | ≥ 99% |
| Failed files | Neither parser nor fallback succeeded | ≤ 2% |
| Definition recall | Definitions found compared to textual baseline, discrepancies examined | ≥ 99% |
| Call site recall | Estimated by recall sample | ≥ 97%, lower bound ≥ 93% |
| Resolved link precision | Estimated by precision sample | ≥ 98%, lower bound ≥ 95% |
| Bridge precision | "Bridges" group in sample (after Lot 8) | ≥ 95%, lower bound ≥ 90% |
| Ambiguous sites | Sites with multiple candidate targets | Measured and explained |
| Unresolved sites (excluding known externals and out-of-scope) | — | ≤ 2%, all grouped and explained |

With 150 links and at most 2 errors, the lower bound of precision exceeds 95%: this determines sample size.

**Plan B** if criteria are not met: switch main parser among permissive-license candidates evaluated in Lot 4 (§3.15), strengthen pattern-based extractor, or add rules to the pack. fxtran (GPL-3.0) is only considered as an external tool after license review (§7). Decision is recorded in §8.

If a compiler becomes available later, it will provide an additional check (object file symbols); it is not required.

### 2.2. Bottleneck V2 — Running from a USB drive, offline

Addressed **as early as Lot 0**, before any feature: a folder containing Python, Qt, and libraries, starting on a clean machine without network. Known watchpoints:

- A *venv* is not relocatable (contains absolute paths): embedded Python is used inside the folder (PyInstaller, directory mode).
- "One-file" mode is excluded: it unpacks on every launch, which is very slow from a USB drive.
- **Linux compatibility:** an executable only starts on systems whose C library (glibc) is at least as new as the build machine's. The Linux version is built in a glibc 2.28 container (AlmaLinux or Rocky Linux 8): it starts on Ubuntu 20.04+ as well as RHEL/Rocky 8 workstations common in industry. Note: `manylinux` Python builds are unsuitable because PyInstaller requires a shared Python library; use Python compiled with a shared library (to verify in Lot 0).
- Ubuntu 22.04: Qt 6.5+ needs `libxcb-cursor0`, missing by default; the library is bundled or its absence detected with a clear message.
- **Older processors:** an inference library compiled for AVX2 or AVX-512 crashes ("illegal instruction") on a CPU lacking them. llama.cpp is compiled with runtime instruction selection (CPU engine variants) or shipped in two variants (baseline and AVX2); `cgs selftest` displays detected instruction sets.
- **Windows:** paths exceeding 260 characters (application declared long-path aware); unsigned executables may trigger SmartScreen or antivirus (signing planned in Lot 16).

### 2.3. Bottleneck V3 — Smooth performance on a modest machine

The interface never manipulates the entire graph. Strategies are detailed in §3.12: precomputations during analysis, paginated queries, capped rendered node count, grouping, background layout, level-of-detail zoom. On the storage side, database is built via bulk inserts with indexes created at the end (§3.6).

### 2.4. Bottleneck V4 — Useful AI on CPU without breaking determinism

**Challenges:** small CPU model is slow and error-prone; cannot feed 15,000 files into it; a plausible rule is not necessarily correct.

**Countermeasures:**

- **Deterministic first:** extension and content-signature inventory handles vast majority of files; AI only sees unknown file groups and unresolved sites.
- **Short, grouped samples:** AI receives a summary (counts, a few code excerpts) per group, never the full repository.
- **Keywords, not code:** AI fills simple templates (keyword lists, prefixes, name transforms, comment markers) rather than writing regexes; the core converts them into rules.
- **Schema-constrained generation:** model output is always a valid file.
- **Automated quantitative checks**, followed by **change preview and one-click validation** (§3.13); bounded model call count (§1.3).
- **Tests without model:** in CI, a mock model returns recorded responses; the entire pipeline is tested deterministically. Tests with the real model run on development machines.

---

## 3. Architecture

### 3.1. Overview

```text
┌────────────────────────────────────────────────────────────────┐
│ DESKTOP APPLICATION (PySide6) — main process                   │
│ Inventory · Search · Callers · 3D graphs                       │
│ Code inspector · Analysis health · AI (Pro)                    │
└──────┬────────────────────────┬────────────────────────┬───────┘
       │ threads                │ subprocesses           │ pipes
       │ (read)                 │ (progress)             │ (JSON)
┌──────▼──────┐   ┌─────────────▼─────────────┐   ┌──────▼───────┐
│ Query       │   │ cgs inventory             │   │ AI Worker    │
│ API         │   │ cgs scan (deterministic)  │   │ (Pro)        │
│ query/      │   │ reads profile             │   │ GGUF model   │
└──────┬──────┘   └─────────────┬─────────────┘   └──────┬───────┘
       │ reads                  │ writes                 │ proposes
       └───────────┬────────────┘                        │
          ┌────────▼────────┐               ┌────────────▼───────┐
          │ <project>.sqlite│               │ analysis profile   │
          └─────────────────┘               └────────────────────┘

No network ports, no connections: strictly files, function calls,
subprocesses, and pipes. cgs scan never calls AI.
```

- **Main process:** Qt interface. Never reads source files for analysis and never executes long queries itself.
- **Query threads:** each query (callers, expand, search) runs in a Qt threadpool thread, with its own read-only SQLite connection, returning results via signals.
- **Analysis process:** interface spawns `cgs inventory` then `cgs scan` (same CLI executable) as subprocesses, reads progress (one JSON line per event), and can cancel them. A parser crash cannot crash the UI; a file exceeding its timeout is flagged as failed, and analysis proceeds.
- **AI process (Pro):** dedicated subprocess loading the model; communicates via stdin/stdout (one JSON message per line). **No network ports**, even internally. Never called by `cgs scan`.
- **Project files:** analysis profile (`analysis_profile.yaml`, adopted rules) and SQLite database.

### 3.2. Language inventory and analysis profile

**Deterministic step: `cgs inventory <folder>`**

1. **Repository traversal:** walks **every sub-folder** of the selected folder (depth first, sorted names); by default it obeys `.gitignore` and the default excluded directory names (`build`, `.venv`, `node_modules`, caches…), plus the profile's `exclude_dirs`. Every folder (or `.gitignore`d file) left out is **reported** with its reason (`default exclusion`, `.gitignore`, `profile`) and file count: `cgs inventory`, `skipped_dirs` in the inventory JSON and in the scan statistics, and the Inventory view. The profile option `all_subfolders: true` (`cgs profile all-subfolders <folder> on`, or the "Analyze all subfolders" box of the Inventory view) ignores `.gitignore` and the default exclusions; version-control metadata (`.git`, `.hg`, `.svn`) and `exclude_dirs` still apply. The key is written only when true, so existing profiles keep their hash. Binary files (null bytes) are ignored; symlink loops and unreadable files are logged without blocking traversal.
2. **Extensions table** (configurable):

| Extensions | Language | Note |
| :--- | :--- | :--- |
| `.f`, `.for`, `.f77`, `.ftn` | Fortran | Fixed-form by default |
| `.f90`, `.f95`, `.f03`, `.f08` | Fortran | Free-form |
| `.F`, `.F90`, `.FOR`… (uppercase) | Fortran | Runs through preprocessor |
| `.py` | Python | Python 2 detected and flagged |
| `.c` | C | — |
| `.cc`, `.cpp`, `.cxx`, `.hpp`, `.hh`, `.hxx` | C++ | — |
| `.h` | **C or C++** | Decided in step 4 |
| `.inc`, `.fi`, `.fh` | **Fortran or other** | Decided in step 4 |
| Others (`.pyx`, `.cu`, `.m`…) | Known but not covered in v1 | Flagged in inventory |

3. **Content signatures**, for extensionless or ambiguous files: `#!` line (e.g. `#!/usr/bin/env python`), editor mode lines (`-*- mode: f90 -*-`), and characteristic keyword scoring on top lines with fixed weights (e.g. `subroutine`, `end do` for Fortran; `namespace`, `template`, `::` for C++; `def`, `import` for Python).
4. **Repository context:** a `.h` included by C++ files, or containing `class`, `namespace`, or `template`, is C++; otherwise C. A `.inc` included by Fortran files is Fortran. Directories containing included files form **include paths** in the profile.
5. **Result per file:** language, variant (fixed/free form, preprocessor, Python 2), confidence, rule that decided. Unrecognized files are grouped by extension.
6. **Coverage report:** per language, file and line counts, and available adapter — native, keyword profile, or none.

**Optional AI step (Lot 13):** for each group of unrecognized files, AI receives the extension and start of three sample files, answering: language, existing adapter to use (e.g. `.ftn` → Fortran) or need for a keyword profile (§3.9). Then, after a first analysis, it inspects unresolved sites (§3.13).

**The analysis profile** consolidates all decisions in a project file. Analysis reads only this file:

```yaml
# <project>/analysis_profile.yaml
profile_version: 4
scope: { include: ["src/"], exclude: ["src/third_party/"] }    # detailed analysis scope
languages:
  fortran: { files: 9120, adapter: native:fortran, variants: [fixed, free, preprocessed] }
  python:  { files: 2400, adapter: native:python }
  cpp:     { files: 1830, adapter: native:cpp }
  c:       { files: 210,  adapter: native:c }
  acme_script: { files: 40, adapter: keywords:acme_script, source: ai, status: approved }
include_paths: ["include/", "src/common/"]
preprocessor: { defines: { HAVE_MPI: "1" }, keep_all_branches: true }
file_overrides:
  - { glob: "include/*.h", language: cpp, reason: "included by C++ files" }
  - { glob: "legacy/*.inc", language: fortran, reason: "included by Fortran files" }
ignored:
  - { ext: ".dat", files: 300, reason: "data" }
packs: [generic_noise, generic_fortran]
rules:
  - { id: r-0001, kind: bridge, source: ai, status: approved, file: rules/r-0001.yaml }
history:
  - { version: 4, change: "rule r-0001 approved", by: "user" }
```

- The profile is versioned; each run logs the hash of the profile used.
- The user can edit the profile in the UI (force language, ignore file group, approve/reject rule); each edit increments the version.

### 3.3. The analysis pipeline

```text
 cgs inventory ──► analysis profile ◄──── AI (optional, Lot 13):
                         │                 unknown languages, missing keywords
                         ▼                               ▲
   Extract → Link → Enrich → Index ──► Diagnostic ───────┘
   └──────────── cgs scan: deterministic ───────────┘
```

| Step | Input | Output | Where | Properties |
| :--- | :--- | :--- | :--- | :--- |
| **Inventory** | Repository | Language of each file, include paths, coverage report | `inventory/` | Deterministic; < 1 min |
| **Extract** | One file + language + included files | *Facts*: definitions with local symbols, unresolved call sites, data accesses, directives, includes | `extract/` (one adapter per language, or keyword adapter) | Per file, in parallel, with timeout; cache (§3.6) |
| **Link** | All facts | Resolved, ambiguous, external, out-of-scope, or unresolved call sites; nodes | `link/` (symbol table + bridges) | Global; normalizes names (casing, mangling) |
| **Enrich** | Graph | Hiding, data accesses, dispatches, entry points, tests | `enrich/` (packs) | Declarative frozen rules |
| **Index** | Enriched graph | Aggregated edges, counts, file/directory links, impact size, full-text search | `store/`, `algo/` | Standard Python algorithms (§3.6) |
| **Diagnostic** | Database | Analysis health; unresolved and ambiguous sites grouped by pattern | `audit/` | Used by user and, if enabled, by AI |

- **Re-analysis:** the Extract step is only re-run for files whose cache key changed (file, an included file, its adapter, or extraction settings); subsequent steps are re-run entirely, which is fast.
- **Partial analysis:** if profile restricts `scope`, a lightweight pass still indexes **definitions** across the whole repository (names only). A call to a routine defined outside scope points to an `out_of_scope` node: not counted as "unresolved".
- **Index step computations:** strongly connected components (iterative Tarjan algorithm to avoid Python recursion limits), condensed graph, then impact size of each node by bitset propagation (Python big ints) in topological order; on raw graph and filtered graph.

### 3.4. Package breakdown and dependency rules

| Package | Role | Allowed imports |
| :--- | :--- | :--- |
| `core` | Data model, identifiers, analysis profile (types), format versions | (no internal imports) |
| `algo` | Graph algorithms: iterative Tarjan, condensation, bitsets, bounded traversals | `core` |
| `inventory` | Language detection, coverage report, profile read/write | `core` |
| `extract` | Native adapters and keyword-based adapter | `core` |
| `link` | Symbol table, cross-language bridges | `core` |
| `enrich` | Pack engine, schemas, generic packs | `core` |
| `store` | SQLite schema, read, write, cache | `core` |
| `query` | Query API (§3.10) | `core`, `store`, `algo` |
| `layout` | Tree layouts (deterministic); not used by the UI since D21 | `core` |
| `audit` | Diagnostic and validation checks (§2.1) | `core`, `inventory`, `extract`, `store`, `query` |
| `scan` | Pipeline orchestration | `core`, `algo`, `inventory`, `extract`, `link`, `enrich`, `store` |
| `cli` | `cgs` command | `inventory`, `scan`, `query`, `audit` |
| `ui` | Desktop application | `core`, `query`, `layout` — **never** `extract`, `link`, `enrich`, or `store` directly |
| `codegraph_sci_pro` | AI, codebase packs, licensing | all of core; core never imports it |

These rules are enforced by `import-linter` starting in Lot 0.

### 3.5. Data model

**Symbol identity.** Each symbol has a stable, unique `uid` used everywhere internally, and a user-friendly `display_name` for the UI.

| Language | `uid` format | Notes |
| :--- | :--- | :--- |
| Fortran | `f:<name>`; module procedure `f:<module>::<name>` | Lowercase (case-insensitive language) |
| C | `c:<name>`; `static` function: `c:<name>@<file>` | Two `static` functions with same name in two files are distinct symbols |
| C++ | `cpp:<ns>::<Class>::<method>(<normalized param types>)` | Signature is part of identity; `display_name` omits it |
| Python | `py:<module>.<qualified name>` | — |
| Keyword profile | `kw:<language>:<name>` | — |
| Others | `file:<path>`, `entry:<name>`, `data:<key>`, `test:<id>`, `ext:<library>:<name>` | Paths relative to repository root, using `/` |

- **Preprocessor variants:** if a routine is defined across multiple `#ifdef` branches, each receives a suffix `#2`, `#3`… and preserves its condition.
- **Overloads and generic interfaces:** when a call cannot disambiguate (types unknown statically), call site retains **all candidate targets** and becomes `ambiguous`.

**Call site identity.** Every call or usage observed in code is a **site**: file, line, column, caller routine, target text as written. Site preserves its preprocessor condition, origin, confidence, and resolution state:

| State (`resolution`) | Meaning |
| :--- | :--- |
| `resolved` | Unique target in repository |
| `ambiguous` | Multiple candidate targets |
| `external` | Known external library (MPI, BLAS…) or intrinsic function |
| `out_of_scope` | Target defined in repository, outside analyzed scope |
| `unresolved` | No target found |

A graph **edge** aggregates sites sharing (caller, callee, type): carries count, lowest confidence, set of origins, and conditions. Fast queries use edges; line-by-line navigation uses call sites.

**Node kinds:** `kind` takes a value from a fixed list; `subtype` is open and provided by plugins.

| `kind` | Meaning | `subtype` (examples) |
| :--- | :--- | :--- |
| `file` | Source file | — |
| `module` | Module, package, namespace | `py_module`, `f_module`, `cpp_namespace` |
| `type` | Class, struct, derived type | `py_class`, `cpp_class`, `f_derived_type` |
| `routine` | Function, subroutine, method, procedure, program | `f_subroutine`, `f_function`, `f_program`, `cpp_method`, `py_function`, `kw_routine` |
| `interface` | Generic or abstract interface | `f_generic_interface` |
| `binding` | Cross-language symbol exposure or declaration | `pybind11_def`, `bind_c`, `macro_declaration` |
| `data` | Shared data | `common_block`, `module_variable`, `c_global`, `memory_object` |
| `entry_point` | User or external entry point | `command`, `program_main`, `external_callback` |
| `dispatch_target` | Catalog entry or dispatch branch | `catalog_entry`, `case_branch` |
| `test_case` | Test or testcase | `unit_test`, `regression_case` |
| `external` | Out-of-repository symbol | `mpi`, `blas`, `intrinsic`, `system` |

**Edge kinds:** `contains`, `calls`, `uses`, `inherits`, `binds`, `bridges`, `implements`, `dispatches`, `reads`, `writes`, `creates`, `destroys`, `exercises`.

**Shared data: three precision levels.** An access to data (`COMMON` block, module variable, memory manager object described by a pack) is linked to the most specific identifiable object and always to its family:

| Level (`key_kind`) | Fictional example | Meaning |
| :--- | :--- | :--- |
| `literal` | `data:mem:solver.state.VALUES` | Name fully known in code |
| `symbolic` | `data:mem:f:update_state:name//'.VALUES'` | Name computed at runtime: expression is preserved, local to routine |
| `family` | `data:mem:*.VALUES` | Object family with same suffix; useful for high-level overviews; auto-treated as hub (hidden by default in the graphs) |

Each access carries its level (`resolution` of access): UI distinguishes "writes object X" from "writes an object in family X".

### 3.6. SQLite schema

```sql
-- Analyzed content
files(id INTEGER PRIMARY KEY, path TEXT UNIQUE, lang, variant, sha256, size, encoding,
      parse_status, adapter, adapter_version, error)
inventory(file_id, lang, variant, confidence, decided_by)
nodes(id INTEGER PRIMARY KEY, uid TEXT UNIQUE, display_name, kind, subtype, lang,
      file_id, line_start, line_end, in_scope, attrs JSON)
conditions(id INTEGER PRIMARY KEY, expr TEXT UNIQUE)              -- preprocessor guards
call_sites(id INTEGER PRIMARY KEY, src_node, file_id, line, col, ref_kind, target_text,
           dst_node, resolution, confidence, origin, condition_id)  -- one site = one line
call_site_candidates(site_id, dst_node)                            -- targets of ambiguous sites
data_accesses(id INTEGER PRIMARY KEY, src_node, data_node, family_node, mode,
              key_kind, file_id, line, origin)
facts_cache(cache_key TEXT PRIMARY KEY, facts BLOB)                -- canonical compressed JSON (zlib)

-- Precomputations for UI (Index step)
edges(src, dst, kind, site_count, min_confidence, origins JSON, conditions JSON)
node_stats(node_id, fan_in, fan_out, fan_in_filtered, fan_out_filtered,
           impact_size, impact_size_filtered, is_noise, noise_reason)
file_edges(src_file, dst_file, kind, count)       -- Files 3D graph
dir_edges(src_dir, dst_dir, kind, count)          -- Directory grouping
search_fts                                        -- FTS5: names, paths, header comments

-- Traceability
plugins(name, type, version)
scan_runs(id, started_at, finished_at, root, git_rev, profile_version, profile_sha256,
          plugins JSON, stats JSON)

-- Later lots
summaries(node_id, content_hash, model_id, prompt_version, text)   -- Lot 15
layout_cache(key, layout_version, data JSON)                        -- Lot 11
```

**Indexes** (created **after** inserts): `call_sites(src_node)`, `call_sites(dst_node)`, `call_sites(file_id, line)`, `call_sites(resolution, target_text)`, `data_accesses(src_node)`, `data_accesses(data_node)`, `edges(src, kind)`, `edges(dst, kind)`, `nodes(file_id)`.

**Writing and performance**

- **Full analysis:** database is constructed in a temporary file (`<project>.sqlite.tmp`), journal disabled during build (`PRAGMA journal_mode=OFF`, `PRAGMA synchronous=OFF`), bulk inserts (`executemany` in 50,000-row chunks), indexes created at the end, then `ANALYZE` and atomic file rename: UI never sees a half-written DB.
- **Incremental re-analysis:** WAL mode (`PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`); UI continues reading while writing.
- **Volume:** ~1 million call sites for 15,000 files. One row per site, mostly integers, represents tens of MBs, writes in seconds via bulk inserts, and is read via index for line-by-line inspector navigation.
- **Facts cache:** key = file SHA-256 + recursive SHA-256 of **all included files** + adapter name and version + profile parameters affecting extraction (language, variant, preprocessor macros, include paths). Content: canonical JSON compressed with `zlib` (standard library). **Never `pickle`** (security risks and cross-version incompatibility).
- The schema carries a version number; an older version database is migrated or re-analyzed.

### 3.7. Plugin contracts and facts

```python
class LanguageAdapter(Protocol):
    name: str                      # "fortran", "python", "c", "cpp", "keywords:<language>"
    version: str
    languages: list[str]           # inventory languages it can read
    def extract(self, file: SourceFile, ctx: ExtractContext) -> FileFacts: ...
        # ctx: include paths, macros, timeout, names known as arrays

class Bridge(Protocol):
    name: str                      # "pybind11", "fortran_c", "prefix_calls", ...
    version: str
    languages: tuple[str, str]
    def link(self, symbols: SymbolTable, facts: Iterable[FileFacts],
             params: dict) -> Iterable[SiteResolution]: ...

class DomainPack(Protocol):
    name: str
    version: str
    def detect(self, repo: RepoInfo) -> float: ...           # 0..1
    def rules(self) -> PackRules: ...                        # loaded & validated rules.yaml
    def enrich(self, graph: GraphView) -> GraphPatch: ...    # optional

@dataclass
class SourceFile:
    path: str; lang: str; variant: str | None; encoding: str; text: str

@dataclass
class LocalSymbol:     # visible declaration in routine (especially Fortran)
    name: str
    role: str          # "array", "scalar", "dummy", "dummy_procedure", "external",
                       # "function", "intrinsic", "parameter"
    source: str        # "local", "include:<path>", "common:<block>", "module:<name>"

@dataclass
class Definition:      # routine, type, module, data...
    uid: str; display_name: str; kind: str; subtype: str; name: str
    span: tuple[int, int]; signature: str | None; doc: str | None
    local_symbols: list[LocalSymbol]

@dataclass
class Reference:       # a call or use site, unresolved at this stage
    src: str; target_text: str
    kind: str          # "call", "maybe_call", "use", "include", ...
    line: int; col: int; args: list[ArgFact]     # arguments, with literal value if known
    condition: str | None                        # preprocessor guard

@dataclass
class IncludeRef:
    text: str; resolved_path: str | None; sha256: str | None

@dataclass
class FileFacts:
    path: str; lang: str; encoding: str; adapter: str; adapter_version: str
    definitions: list[Definition]
    references: list[Reference]
    data_accesses: list[DataAccess]              # COMMON, globals, INTENT...
    directives: list[Directive]                  # #ifdef...
    includes: list[IncludeRef]                   # for cache key and declarations
    errors: list[ParseError]
    used_fallback: bool
```

- Each file's language comes from inventory (profile); adapter does not guess it.
- Facts have identical structure across all languages: core only knows this format.
- Literal arguments (strings, constants, values obtained through simple propagation of local variables) are preserved. This enables a pack or rule to interpret specific calls (memory manager, macros) without re-parsing code.
- Facts are **sorted** (by line, column, then name) before storage: essential for determinism.

**Fortran rule for `name(...)` in an expression** (applied by adapter, then Link):

1. `name` declared as array — locally, in dummy argument, `COMMON` block, included file, or used module — → **data access**, not a call;
2. `name` is a Fortran intrinsic function (fixed list: `sin`, `max`, `size`…) → `external` site (`ext:intrinsic:<name>`), hidden by default;
3. `name` declared `EXTERNAL` or as function → `call` site;
4. `name` appears in pack's `extraction.known_arrays` list (missing declaration) → data access;
5. otherwise → `maybe_call` site, decided by Link: function defined in repo → call; module array → data; otherwise `ambiguous` site, grouped separately in diagnostic so as not to pollute genuine unresolved sites.

### 3.8. Domain Packs format

A pack is primarily a declarative `rules.yaml` file; Python (`enrich`) is only added if declarative format is insufficient.

**Loading:** `yaml.safe_load` exclusively, followed by JSON schema validation (`enrich/schemas/pack.schema.json`). Unknown keys, invalid types, or unsupported format versions cause loading failure with a message specifying file, key, and offending value. The same rules apply to language profiles (§3.9), bridge rules, and analysis profiles.

**Format specification, version 1**

| Key | Type | Required | Precise meaning |
| :--- | :--- | :--- | :--- |
| `pack` | string | yes | Pack name (lowercase and `_`) |
| `version` | string `MAJ.MIN` | yes | Pack version |
| `format_version` | integer | yes | Format version; unsupported version is rejected |
| `identifiers` | list of strings | yes | Codebase identifiers forbidden in core (§6.4) |
| `covers` | `{code: range}` | no | Analyzed codebase versions covered, e.g. `">=16,<18"` |
| `detect.any_path` | list of paths | no | Pack suggested if **at least one** path exists |
| `detect.all_path` | list of paths | no | Pack suggested if **all** paths exist; if both given, both must be satisfied |
| `noise.hide` | list of names (`*` wildcards allowed) | no | Routines hidden by default ("+N" badge, revealable) |
| `noise.optional` | list of names | no | Routines **suggested** for hiding, visible by default |
| `noise.auto_detect_hubs` | `{min_fan_in, max_fan_out}` | no | Hub detection thresholds, proposed for hiding |
| `extraction.known_arrays` | list of names | no | Names always treated as arrays (never calls) when declaration is missing |
| `memory_access[]` | objects (below) | no | Memory manager calls → data accesses |
| `dispatch[]` | `{routine, select_on, target_pattern}` | no | Each `SELECT CASE` branch on `select_on` → `dispatches` edge to `target_pattern` (`{case}` = branch value, e.g. `elem_{case:03d}`) |
| `catalogs[]` | `{glob, format, entry, target}` | no | Each entry in a config file (`yaml`, `json`, `python`) → target |
| `entry_points[]` | `{kind, glob, pattern, multiline, target, fallback_target}` | no | Entry points; `fallback_target` used if `target` does not exist in repository |
| `bridges[]` | objects (below) | no | Cross-language links |
| `tests[]` | `{kind, glob, uses_entry_points, coverage}` | no | Test discovery |
| `glossary` | path | no | Domain vocabulary for AI |

**`memory_access[]`** — `{routine, name_arg, mode_arg, modes, effect, object_key, local_prefix_pattern}`:

- either `mode_arg` + `modes` (literal arg value → `reads` or `writes`), or `effect` (`creates` or `destroys`);
- `object_key`: **ordered** list of strategies attempted in order — `literal` (fully known name), `local_prefix` (name starting with `local_prefix_pattern`, routine-local), `symbolic` (retained expression), `family` (static suffix); access is linked to the most specific object found **and** its family.

**`bridges[]`** — `{from, to, call_prefixes, name_transform, declaration_patterns, extension_modules}`:

- `call_prefixes`: attempted **longest to shortest**; a call `PREFIX` + `NAME(...)` yields a site toward the target produced by applying `name_transform`;
- `name_transform`: ordered list of operations among `strip_prefix` (default, first), `lowercase`, `uppercase`, `append_underscore`, `strip_underscore`;
- `declaration_patterns`: patterns that **declare** a routine from the other language (prototype, declaration macro). They create `binding` nodes, **never call sites**;
- `extension_modules`: compiled modules exposed to Python.

Every bridge rule must be accompanied by positive **and negative** tests (identifiers resembling prefix without matching, `bridge_prefix_negative` fixture).

```yaml
# Fictional example
pack: acme_solver
version: "0.1"
format_version: 1
identifiers: [mem_get, elem_dispatch, acme_core, FCALL_]
covers: { acme_solver: ">=3,<5" }
detect: { all_path: ["src/kernels/", "acme/"] }
noise:
  hide: [log_msg, check_err]
  optional: [get_property]
  auto_detect_hubs: { min_fan_in: 300, max_fan_out: 3 }
extraction:
  known_arrays: [rbuf, ibuf]
memory_access:
  - { routine: mem_get, name_arg: 1, mode_arg: 2, modes: { "R": reads, "W": writes },
      object_key: [literal, local_prefix, symbolic, family], local_prefix_pattern: "^TMP_" }
dispatch:
  - { routine: elem_dispatch, select_on: itype, target_pattern: "elem_{case:03d}" }
entry_points:
  - { kind: command, glob: "acme/commands/*.py",
      pattern: 'Command\(name="(?P<name>\w+)", routine="(?P<target>\w+)"\)',
      target: "f:{target}", fallback_target: "py:acme.commands.{name}" }
bridges:
  - { from: cpp, to: fortran, call_prefixes: ["FCALL_"], name_transform: [strip_prefix, lowercase] }
  - { from: cpp, to: fortran, declaration_patterns: ['FDECL\((?P<name>\w+)'] }
  - { from: python, to: cpp, extension_modules: [acme_core] }
tests:
  - { kind: regression_case, glob: "tests/cases/*.inp", uses_entry_points: true }
glossary: docs/glossary.md
```

**AI-proposed bridge rules** follow the exact format of a `bridges` entry, in a dedicated file (`rules/r-<n>.yaml`) referenced by the profile.

### 3.9. Keyword-based language profiles

For a language lacking a native adapter, the **keyword adapter** (`extract/keywords/`) reads a profile containing only keyword lists and markers. The core converts them into extraction rules deterministically. A profile can be written by hand or proposed by AI.

```yaml
# <project>/rules/languages/acme_script.yaml — fictional example
language: acme_script
version: 1
format_version: 1
source: ai                    # ai | manual
status: approved              # proposed | approved | rejected
extensions: [".acs"]
case_sensitive: false
comments: { line: ["#"], block: [["/*", "*/"]] }
strings: ['"', "'"]
line_continuation: "\\"
definitions:
  - { keywords: ["proc", "function"], name: after_keyword, end_keywords: ["endproc", "endfunction"], kind: routine }
calls:
  - { keywords: ["run"], name: after_keyword }            # run name(...)
  - { style: name_then_paren, only_known_names: true }    # name(...) if name is defined somewhere
includes:
  - { keywords: ["use"], target: after_keyword }
coverage:                     # measured, never assumed
  sample_files: 12
  definitions_recall: 0.97
  calls_precision: 0.93
evidence:
  document: "docs/acme_script_manual.pdf"                 # user-provided technical document, if any
  samples: ["scripts/a.acs", "scripts/b.acs"]
```

- **Deliberately limited scope:** a keyword profile provides **heuristic** extraction. It does not resolve scopes, complex nesting, or overloads. Its links carry `heuristic` confidence.
- **Measured coverage:** a profile is deemed usable only with measured coverage on a fixture or verified sample (`coverage` block); otherwise UI displays "unmeasured".
- `only_known_names: true` prevents treating every parenthesized expression as a call: only names defined in repo (or declared external) are kept.

### 3.10. Query API (contract between engine, CLI, and UI)

```python
CALL_PATH = {"calls", "bridges", "binds", "implements", "dispatches"}   # execution paths
FILE_DEPENDENCY = {"uses", "contains"}                                   # file dependencies

class GraphQuery:
    def __init__(self, db_path: Path, *, read_only: bool = True): ...
    def inventory(self) -> InventoryReport: ...
    def find(self, text: str, kinds: set[str] | None = None, limit: int = 50) -> list[NodeSummary]: ...
    def node(self, uid: str) -> NodeDetail: ...
    def callers(self, uid: str, *, hide_noise: bool = True) -> CallerReport: ...
        # CallerReport: count, file_count, items = [(caller, sites=[CallSite])]
    def callees(self, uid: str, *, hide_noise: bool = True) -> CalleeReport: ...
    def children(self, uid: str, *, direction: Direction, level: Level,
                 edge_kinds: set[str] = CALL_PATH, offset: int = 0, limit: int = 50,
                 hide_noise: bool = True) -> Page[TreeItem]: ...
        # direction: CALLERS or CALLEES; level: ROUTINE, FILE, or DIRECTORY
    def file_links(self, file_uid: str, *, direction: Direction) -> list[FileLink]: ...
    def call_sites(self, src_uid: str, dst_uid: str) -> list[CallSite]: ...
        # CallSite: file, line, col, condition, origin, confidence, resolution
    def paths(self, src_uid: str, dst_uid: str, *, edge_kinds: set[str] = CALL_PATH,
              k: int = 5, max_len: int = 15) -> list[Path]: ...
        # Path = steps (uid, edge kind, confidence, possible: bool); possible=True for dispatch
    def impact(self, uid: str, *, edge_kinds: set[str] = CALL_PATH,
               max_depth: int | None = None) -> ImpactReport: ...
    def data_accesses(self, uid: str) -> list[DataAccessView]: ...   # with literal/symbolic/family level
    def unresolved(self, *, group_by: str = "pattern", include_ambiguous: bool = False,
                   limit: int = 50) -> list[SiteGroup]: ...
    def source(self, file_uid: str, start: int, end: int) -> SourceExcerpt: ...
        # SourceExcerpt.stale = True if file on disk changed since analysis
    def scan_health(self) -> ScanHealth: ...
    def default_roots(self, *, hide_noise: bool = True) -> DefaultRoots: ...
        # deterministic detection of primary entry point (main_routine, main_file)
    def initial_subgraph(self, root_uid: str | None = None, *, level: Level = Level.ROUTINE,
                         max_nodes: int = 25, hide_noise: bool = True) -> SubgraphReport: ...
        # breadth-first subgraph of first N nodes from main (or root_uid)
    def connected_neighbors(self, uid: str, *, level: Level = Level.ROUTINE,
                            limit: int = 50, hide_noise: bool = True) -> NeighborsReport: ...
        # direct callers and callees of a clicked node (routine, file, or directory)
    def paths_from_main(self, target_uid: str, *, root_uid: str | None = None,
                        level: Level = Level.ROUTINE, max_paths: int = 4,
                        max_len: int = 15) -> MainPathReport: ...
        # paths from main to target_uid; fallback to shortest path if > max_paths
```

- All lists are **paginated** (`offset`, `limit`) and stably sorted.
- Basic queries (`callers`, `callees`, `children`, `file_links`, `default_roots`, `connected_neighbors`) are simple SQL queries indexed on precomputed tables: none load the graph into memory.
- `paths`, `paths_from_main`, `initial_subgraph`, and `impact` explicitly use an edge kind set (execution path or file dependency); they traverse breadth-first with bounds (depth, node count), stopping cleanly at limit and signaling it.
- `source` compares on-disk file fingerprint with analysis fingerprint (size and mtime first, then SHA-256 if needed): a displayed line always matches the evidence used to build the link, or UI warns that it has changed.
- CLI and UI share this exact API: what is tested in CLI is what the UI renders.

### 3.11. Desktop application

**Main window**

| Area | Content |
| :--- | :--- |
| Title bar | Frameless window (D22): 28 px orange gradient bar with the title on the left and minimize / maximize / close on the right; drag moves, double-click maximizes; a 5 px outer margin resizes the window |
| Left, column 1 | Icon rail (50 px): open folder, view groups **Explore** and **Project** (active group framed in orange), About |
| Left, column 2 | Views of the active group (Explore: Functions 3D, Files 3D, Tree list; Project: Inventory, Analysis health; active view on an orange gradient), then search box and results, then repository file explorer |
| Centre, level 1 | Header band: title of the active view in capitals, project path |
| Centre, level 2 | Hero card: the selected routine (name, kind, language, identifier, location, callers and impact summary) with 48 × 48 px square badges and buttons: callers, callees, "Show in" (views), Filters (hide utilities, min confidence, hide AI links, hide ambiguous sites), Analysis (Analyze, Cancel, force language, ignore extension, open folder); the buttons open dark popovers |
| Centre, level 3 | Details panel: the active view; on its right the code inspector and the Callers (N) / Callees (M) panel |
| Status bar | Analysis in progress, analysis health, active filters |

**Qt components**

- Text lists and trees: lazy `QAbstractItemModel` (`canFetchMore` / `fetchMore`) requesting children in pages of 50 from `GraphQuery.children`.
- **3D graphs** (`ui/graph3d_view.py`, decision D21): `Graph3DView` = toolbar (From main, Paths to main, depth, node ceiling, defining files) + `QWebEngineView` showing the vendored 3d-force-graph page (`ui/web/`), written once per process to a private temporary file. Data comes only from `GraphQuery` in a `QueryRunner` thread: `graph3d(root, mode, depth, max_nodes)` for a neighbourhood, `graph3d(uid, depth=1)` merged on right-click, `graph3d_main_paths(target, mode)` for "Paths to main" (shortest path only when there are too many). Python → page: `runJavaScript("cgs.load(…)" / "cgs.merge(…)")`; page → Python: console messages `CGS:{"event": select | expand | link | ready | loaded | error, …}` read by `QWebEnginePage.javaScriptConsoleMessage`. Offline by construction: page CSP without any network source, Qt's off-the-record default profile, a `QWebEngineUrlRequestInterceptor` blocking every scheme other than `file`, `data`, `blob`, navigation refused elsewhere; no server, no port. Without WebGL (offscreen tests, very old GPU) the page still loads and answers, and says that 3D rendering is unavailable. `AA_ShareOpenGLContexts` is set before the `QApplication` is created, and the window is deleted before it.
- Inspector: read-only `QPlainTextEdit` + per-language `QSyntaxHighlighter` (rules provided by adapter; for keyword profile, keywords highlighted). If `SourceExcerpt.stale` is true: banner "This file has changed since analysis" and "Re-analyze" button.
- Path view: each step displays its type (call, bridge, dispatch); dispatch steps are flagged "possible".
- Background tasks: `QThreadPool` for queries; `QProcess` for inventory, analysis, and AI.
- Settings: `QSettings` in INI format, in the data folder (§3.14).
- **Standalone 3D window** (`ui/view3d/`, `cgs view3d`, optional): the same page in a **PyWebView** window running in its **own process** (PyWebView has its own GUI loop), for use outside the main window. Data: `GraphQuery.graph3d(root, mode=functions|files|both, depth, max_nodes)` — a bounded, deterministic neighbourhood (callers and callees) plus, in `both` mode, the files defining the routines (`defines` links) and the links between those files. The page is self-contained (vendored JavaScript, data inline) and carries a Content-Security-Policy forbidding every network access; there is **no HTTP server and no port** (`http_server=False`, file URL, `js_api` bridge). Right-click expands a node on demand (`View3DApi.expand`); a click prints one JSON line `{"event": "select", "uid": …}` on stdout. `--export page.html` writes the same page without a window.

**Workflow when opening a folder:** inventory → display languages and their coverage → if elements are missing and AI is available, prompt "Complete with AI" → analysis → auto-detection of `main` and display of its neighbourhood in `Functions 3D` and `Files 3D` → click on a node → panels and inspector follow; right-click → its neighbours are added (or, with "Paths to main", only the paths from `main`).

### 3.12. Graphical performance strategies (CPU only)

1. **Never the whole graph in UI:** only what is displayed, fetched from database.
2. **Precomputations during analysis:** caller/callee counts (raw and filtered), impact size, file and directory links (`file_edges`, `dir_edges`).
3. **Pagination:** 50 children per expansion; beyond that, a "+N more" node expanding on demand.
4. **Rendered node ceiling** (300 by default): beyond that, UI proposes switching to file or directory level.
5. **Aggregation levels:** directory → file → routine; step down one level via double-click.
6. **Hubs and data families hidden by default** in the graphs, with the hidden count shown.
7. **3D force layout** in the WebGL page (3d-force-graph), stopped after 6 s (`cooldownTime`) so that a modest CPU is not kept busy; the camera is fitted once the layout settles. The deterministic tree layout of `layout/tree.py` is no longer used by the UI (D21).
8. **Labels on hover only** (tooltips), no text sprites: the cost of a frame does not grow with label length.
9. **Lightweight rendering on large views:** a right-click adds at most 150 nodes and never goes past the node ceiling; directional particles only on bridges and bindings, and can be switched off.
10. **Unobtrusive analysis:** analysis process at low priority, worker count = cores − 1, facts streamed to database.
11. **Partial analysis:** ability to restrict detailed analysis to specific directories (§3.3).

### 3.13. Local AI (Pro extension)

**Execution:** `cgs ai-worker` subprocess loading a GGUF model with `llama-cpp-python`, on CPU (threads = cores − 1), with 4 to 8k token context. JSON communication over stdin/stdout; streamed responses; zero temperature and fixed seed. Inference library selects CPU instruction set dynamically at startup (§2.2).

**Models:** strictly Apache 2.0 or MIT licensed, listed in `models.lock` (file, SHA-256, license). Initial CPU candidates: Qwen2.5-Coder-1.5B-Instruct (Apache 2.0) and Phi-4-mini-instruct (MIT), Q4 quantized. Final choice decided on Lot 13 benchmark.

**Role 1 — Identify unknown languages (Lot 13)**

- Input, per group of unrecognized files: extension, file count, start of three sample files, list of already covered languages.
- Output (schema-constrained): language name, existing adapter to use, or keyword profile request; short rationale.
- Automated check: if an existing adapter is proposed, it must parse sample files without error and find definitions.

**Role 2 — Define missing keywords (Lot 13)**

The completion loop:

1. Initial analysis performed with current profile.
2. Diagnostic (`GraphQuery.unresolved`, `scan_health`) deterministically summarizes gaps: languages without adapter; unresolved sites grouped by pattern (same prefix, same source language, same files), with sample code lines; files with zero definitions found.
3. AI receives this summary (and user-provided technical document if present) and fills a template: keyword language profile (§3.9) or bridge rule (`bridges` format, §3.8).
4. **Automated checks**, replaying Link through Index steps on already-extracted facts (fast):

| Check | Threshold (configurable) |
| :--- | :--- |
| File conforms to schema | Mandatory |
| Gain: targeted unresolved sites now resolved | ≥ 50% |
| No explosion: new sites per line of code | Below fixed ceiling |
| No regression: existing edges unchanged, fixtures stay green | Mandatory |
| Plausible targets: new sites point to existing definitions | ≥ 90% |
| Stability: similar rates on a second file sample | Difference < 10 points |
| Negative tests: rule does not match examples resembling pattern without being it | Mandatory |

5. **Adoption**
   - **Default mode — one-click validation:** UI presents a change preview (count of added/removed links, with code excerpts); user approves or rejects.
   - **Automatic mode**, configurable per project: adoption upon passing checks, links tagged "AI".
   - Automatic mode only becomes default if benchmark demonstrates, on reference corpora, adopted rule precision of at least 98% (lower bound ≥ 95%).
   - A proposal failing checks is **rejected**, with failure reason displayed.
6. At most 3 iterations; loop terminates when progress halts.
7. Final analysis runs with validated profile: it is deterministic.

**Role 3 — Explain (Lot 15)**

- Deterministically assembled context within token budget: routine code, callers list, callee summaries, read/written data, pack glossary.
- Mandatory citations (`[f:assemble_matrix L120]`); UI verifies that every cited identifier exists and flags invalid citations.
- Numbers (caller count, impact) always come from queries, never from the model.
- Precomputed summaries bottom-up from leaves to root in background, cached by code fingerprint.

**Tests:** a **mock model** (recorded responses) tests the full pipeline in CI deterministically; real model runs on development machines for benchmarking.

### 3.14. Portable version (USB drive)

```text
CodeGraph-Sci-1.0-linux-x86_64/          (or -windows-x64)
├── CodeGraph-Sci                         desktop application (CodeGraph-Sci.exe on Windows)
├── cgs                                   CLI (cgs.exe on Windows)
├── _internal/                            embedded Python, Qt, libraries
├── packs/                                installed packs (rules.yaml)
├── models/                               AI edition: .gguf model + license + provenance.json
├── licenses/                             licenses & notices of all components, LGPL source offer
├── data/                                 projects and settings (portable mode)
└── README.txt
```

- **Two editions:** without AI (~300 MB, measured in Lot 0) and with AI (1 to 3 GB additional depending on model).
- **Two executables** sharing the same `_internal/` directory, produced by a single PyInstaller spec: desktop app and CLI.
- **Data location:** default on local disk (`~/.codegraph-sci/` on Linux, `%LOCALAPPDATA%\CodeGraph-Sci\` on Windows) because SQLite is slow on USB drives. "Portable mode" option writes to `data/` next to the app.
- **Build:** `tools/build_portable.py` (PyInstaller) produces the directory, archive, and SHA-256 hash. Linux: glibc 2.28 container (§2.2); Windows: CI Windows runner. Network is only used at build time; finished folder makes zero network access.
- **Bundled model:** AI edition contains model file and license text, as required by Apache 2.0 and MIT (§7).

### 3.15. Technical choices and dependencies

| Component | Usage | License |
| :--- | :--- | :--- |
| Python 3.12 | Sole application language | PSF |
| PySide6 (Qt 6) | Desktop UI | LGPL-3.0 (obligations detailed in §7) |
| Qt WebEngine (part of PySide6, Chromium) | Embedded 3D graphs of the main window (§3.11, D21); about +300 MB in the portable folder | LGPL-3.0 (+ Chromium notices) |
| pywebview *(optional extra `view3d`)* + bottle, proxy_tools, pythonnet (Windows) | Standalone 3D window `cgs view3d` (§3.11), separate process, no server | BSD-3-Clause / MIT |
| 3d-force-graph 1.80.1 (bundles three.js r186) | 3D rendering, vendored in `ui/web/vendor/` with its licences (SHA-256 `13088340…23be9`) | MIT |
| py-tree-sitter + Fortran, C, C++, Python grammars | Parsers (Python 2: fallback to tree-sitter grammar) | MIT (`tree-sitter-fortran` wheel verified; otherwise `tree-sitter-language-pack` or build at packaging) |
| `ast` (standard library) | Python 3 parser | PSF |
| sqlite3 + FTS5, `zlib`, `json` (standard library) | Project DB, full-text search, compressed cache | Public domain / PSF |
| In-house graph algorithms (`algo/`) | Iterative Tarjan, condensation, bitsets, bounded traversals | — (project code; NetworkX no longer needed) |
| PyYAML (`safe_load` only), jsonschema | Profiles, packs, and strict validation | MIT |
| fparser, LFortran *(Fortran benchmark candidates, Lot 4)* | Alternative Fortran parsers | BSD-3 |
| fxtran *(excluded from default distribution)* | Fortran parser, external tool only after license review | GPL-3.0 |
| PyInstaller | Portable folder bundling | GPL-2.0 with exception allowing proprietary distribution |
| llama-cpp-python *(Lot 13)* | CPU model execution | MIT |
| pypdf *(Lot 13)* | Parsing user-supplied technical docs | BSD-3 |
| cryptography *(Lot 16)* | Ed25519 license keys | Apache-2.0 / BSD |
| pytest, pytest-qt, pytest-socket, hypothesis, ruff, mypy, import-linter | Development and testing | MIT / BSD / MPL-2.0 (hypothesis) |

Every new dependency must be vetted through this list and through license audit (Lot 16).

### 3.16. Repository structure

```text
codegraph-sci/                         development repo (private until release)
├── AGENTS.md                          agent guidelines (Appendix C)
├── CHANGELOG.md
├── pyproject.toml
├── requirements.lock                  pinned dependencies with hashes
├── models.lock                        approved models (Apache 2.0 / MIT)
├── docs/
│   ├── architecture.md                this document
│   ├── strategie_licence.md
│   └── packs/<code>.md                one file per analyzed codebase
├── src/
│   ├── codegraph_sci/                 core (released under PolyForm NC)
│   │   ├── core/
│   │   ├── algo/                      tarjan.py, closure.py, paths.py
│   │   ├── inventory/                 extensions.yaml, signatures, context, profile
│   │   ├── extract/                   fortran/  python/  c/  cpp/  keywords/
│   │   ├── link/                      symbols.py, bridges/
│   │   ├── enrich/                    pack engine, schemas/, generic_noise/, generic_fortran/
│   │   ├── store/                     schema.sql, writer.py, reader.py, cache.py
│   │   ├── query/
│   │   ├── layout/
│   │   ├── audit/                     baseline, diff, sample, recall_sample, invariants
│   │   ├── scan.py
│   │   ├── cli.py
│   │   └── ui/                        app.py, main_window.py, models/, views/, workers.py
│   └── codegraph_sci_pro/             Pro extensions (eventually private repo)
│       ├── packs/<code>/
│       ├── ai/                        worker.py, identify.py, complete.py, explain.py, prompts/
│       └── license/
├── tests/
│   ├── unit/
│   ├── fixtures/<name>/               src/ + expected_inventory.json + expected_graph.json
│   ├── synthetic/generate.py
│   ├── corpus/<code>/                 manifest.yaml + expectations.yaml + reference_sample.yaml
│   ├── ai/                            recorded mock model responses
│   ├── robustness/                    malformed files, difficult paths, fuzzing
│   ├── ui/                            pytest-qt
│   └── portable/                      portable folder checks (network, ports, glibc)
├── tools/
│   ├── check.py                       ruff + mypy + import-linter + pytest (network blocked)
│   └── build_portable.py
└── packaging/
    ├── codegraph_sci.spec
    ├── linux-glibc228.Containerfile
    └── licenses/
```

---

## 4. Implementation plan by lots

### 4.0. Usage instructions

**Rules common to all lots ("Definition of Done")**

- Lot tests pass, as does `python tools/check.py` (ruff, mypy strict, import-linter, pytest with network blocked via pytest-socket).
- No dependencies outside §3.15 list; no network access; no codebase-specific identifiers in core.
- If a contract (§3.5 to §3.10) changes, this document is updated in the same lot.
- An entry is added to `CHANGELOG.md`.

**Standard prompt to give to developer agent**

```text
Read AGENTS.md, then docs/architecture.md (§3 and Lot N in §4).
Implement only Lot N "<title>".
Respect contracts from §3.5 to §3.10 and dependency rules from §3.4.
The lot is done when its validation tests and python tools/check.py pass.
Do not start the next lot.
```

### Lot 0 — Portable skeleton

- **Objective:** resolve Bottleneck V2 before any functional feature.
- **Deliverables:** repo structure (§3.16), `pyproject.toml`, `tools/check.py`, `import-linter` contracts; `cgs --version` and `cgs selftest` commands; blank PySide6 window with "About"; `tools/build_portable.py`, two-executable PyInstaller spec, glibc 2.28 Linux build container; Linux + Windows CI.
- **`cgs selftest` verifies:** loading Qt, a tree-sitter grammar, SQLite with FTS5; writing into data folder; CPU instruction sets; absence of any network access.
- **Validation tests:** `tools/check.py` passes; built folder, copied to USB drive, boots on a clean machine (or VM) **without network** on Ubuntu 22.04, Ubuntu 24.04, and Windows 10/11 (and Rocky Linux 8 if available); `cgs selftest` passes in all environments; on Linux, app runs in a networkless namespace (`unshare -n`).
- **Depends on:** —.

### Lot 1 — Data model and storage

- **Objective:** shared format for all subsequent work.
- **Deliverables:** `core/` (identities from §3.5, facts from §3.7, analysis profile type, version numbers); `store/` (§3.6 schema with `call_sites`, bulk inserts to temp file followed by atomic rename, deferred index creation, WAL mode for incremental, compressed JSON cache); canonical sorted JSON export (`cgs export json`).
- **Validation tests:** lossless roundtrip facts → DB → export; two writes of identical facts produce identical export; interrupted analysis leaves no half-written DB; clean rejection of unknown DB version; writing 1 million synthetic sites within target time (measured and logged).
- **Depends on:** Lot 0.

### Lot 2 — Language inventory and analysis profile

- **Objective:** determine, prior to analysis, languages present in repo and which are covered.
- **Deliverables:** `inventory/` (§3.2): repo traversal, binary detection, configurable extension table, content signatures, context rules (`.h`, `.inc`), include paths, unrecognized file grouping, coverage report; `analysis_profile.yaml` read/write (safe loading, strict schema); `cgs inventory <folder>` command (table or JSON); `inventory_mixed` fixture (§5.2).
- **Validation tests:** on `inventory_mixed`, every file receives expected language and variant (including `.h` in C and C++, Fortran `.inc`, extensionless file with `#!`, ignored binary file, grouped unknown extension, flagged symlink loop); two inventories of same repo produce identical profile; inventory of synthetic repo (§5.3) runs in under 1 minute.
- **Depends on:** Lot 1.

### Lot 3 — Reference mini-codebases (before extractors)

- **Objective:** author expected answers before writing code that extracts them, for all four languages and their combinations.
- **Deliverables:** fixtures from §5.2 marked "Lot 3", each with hand-written `src/`, `expected_inventory.json`, and `expected_graph.json` (including call sites); multi-language synthetic repo generator (§5.3).
- **Validation tests:** every expected file complies with its schema; inventory (Lot 2) of each fixture matches `expected_inventory.json`; generator outputs identical repo for identical seed.
- **Depends on:** Lot 2.

### Lot 4 — Fortran adapter

- **Objective:** produce facts for a Fortran file.
- **Deliverables:**
  - first, a **comparative benchmark** of permissive-license Fortran parsers (tree-sitter-fortran, fparser, LFortran) on fixtures and sample real files from test case (fixed-form, preprocessor included): failure rate, runtime, definition and site accuracy; main parser selected based on benchmark, recorded in §8;
  - then `extract/fortran/`: decoding (UTF-8, fallback Latin-1, logged); fixed and free formats; preprocessor (`#ifdef` branches kept with conditions, `#include` resolved via include paths); **local symbols** of each routine (arrays, arguments, `EXTERNAL`, `COMMON`, included file declarations); `name(...)` rule from §3.7 with intrinsic function list; **independent pattern extractor**, used for fallback and dual extraction; per-file timeout.
- **Validation tests:** for each Fortran fixture, produced facts exactly match expected (definitions, local symbols, sites, lines, columns, conditions); in `fortran_arrays_includes`, no array declared in an include file or `COMMON` yields a call site, and intrinsics are marked `external`; intentionally unreadable file triggers fallback without interrupting analysis; benchmark report recorded.
- **Depends on:** Lot 3.

### Lot 5 — Python, C, and C++ adapters

- **Objective:** cover remaining languages of initial test case.
- **Deliverables:** `extract/python/` (`ast` for Python 3, tree-sitter fallback for Python 2 or invalid files); `extract/c/` and `extract/cpp/` (tree-sitter, partial macro expansion, fallback pattern extractor); identities from §3.5 (C++ signatures, file-qualified `static` functions); multiple candidates for indistinguishable overload calls.
- **Validation tests:** for each Python, C, and C++ fixture, produced facts match expected exactly; in `cpp_overloads`, two overloads have distinct identities and an ambiguous call yields an `ambiguous` site with both candidates; homonymous `static` functions remain distinct; a Python 2 file parses via fallback and is flagged.
- **Depends on:** Lot 3.

### Lot 6 — Link, Index, and `cgs scan` command

- **Objective:** transform a multi-language codebase folder into a complete database.
- **Deliverables:** `link/` (per-language symbol table — case-insensitive for Fortran —, site resolution, `maybe_call` decision, generic interfaces, external and intrinsic symbols, lightweight out-of-scope definition index and `out_of_scope` state); `algo/` (iterative Tarjan, condensation, bitset impact size, bounded traversals); Index step (aggregated edges, `node_stats`, `file_edges`, `dir_edges`, FTS5); `scan.py` (profile reading, parallelism, per-file timeout, cache key incorporating included files, JSON progress); `cgs scan <folder>` command.
- **Validation tests:** each fixture, including `mini_hybrid` without bridges, produces a graph and sites identical to `expected_graph.json`; consecutive runs produce identical export; re-analysis without changes re-extracts zero files; modifying one file re-extracts only that file, **modifying an included file re-extracts all files including it**; `partial_scope`: calls outside scope become `out_of_scope`, not `unresolved`; `robustness`: no file stalls analysis; synthetic repo analyzes within target time (§1.3), and impact size computed across 15,000 routines within logged time and memory.
- **Depends on:** Lots 4 and 5.

### Lot 7 — Validation on a real codebase (Bottleneck V1, stop point)

- **Objective:** prove, without a compiler, that inventory and graph for each language are accurate at scale on real code.
- **Deliverables:** `audit/` and commands `cgs audit inventory` (inventory consistency), `cgs audit baseline` (textual baseline), `cgs audit diff` (dual extraction), `cgs audit sample` (stratified precision sample, review sheet, one key per link), `cgs audit recall-sample` (recall sample), `cgs audit invariants`, `cgs audit report` (§2.1 metrics with confidence intervals); review storage in `reference_sample.yaml` and auto-replay; manifest and expectations for **starter corpus** #1 (§5.4).
- **Validation tests:** §2.1 criteria met on starter corpus #1 for each language; replay of `reference_sample.yaml` passes automatically. Otherwise: Plan B (§2.1), then re-measure.
- **Stop point:** until these criteria are satisfied, UI lots (10 and beyond) do not start.
- **Depends on:** Lot 6.

### Lot 8 — Cross-language bridges

- **Objective:** trace calls across language boundaries.
- **Deliverables:** bridges `python_extension`, `pybind11`, `fortran_c` (name mangling, `BIND(C)`), `prefix_calls` (longest-to-shortest prefixes, explicit `name_transform`, declarations distinct from calls, §3.8), `external_symbols`; fixtures `bridge_pybind11`, `bridge_fortran_c`, and `bridge_prefix_negative`; "bridges" group added to precision sample.
- **Validation tests:** each bridge fixture yields expected sites; `bridge_prefix_negative` produces zero false links; declaration macro creates a `binding` node and no call site; in `mini_hybrid`, the path Python → C++ → C → Fortran is recovered and unresolved sites drop to zero; bridge precision satisfies §2.1 on starter corpus.
- **Depends on:** Lot 6.

### Lot 9 — Query API and command line

- **Objective:** answer §1.1 questions headlessly.
- **Deliverables:** `query/` (§3.10, explicit edge kinds, detailed paths, source freshness verification); commands `cgs callers <routine>` (default question: count + list with files and lines), `cgs callees`, `cgs file-links`, `cgs path`, `cgs impact`, `cgs find`, `cgs data`, `cgs unresolved`, `cgs health`; table or JSON output.
- **Validation tests:** exact answers on all fixtures; path crossing dispatch marks step "possible"; file modified after analysis flagged stale by `source`; execution times comply with §1.3 on starter corpus and synthetic repo; `paths` and `impact` stop cleanly at bounds.
- **Depends on:** Lots 7 and 8.

### Lot 10 — Desktop application: inventory, search, callers, inspector

- **Objective:** default question presented in a GUI window over a multi-language repo.
- **Deliverables:** main window (§3.11); project creation, subprocess inventory and analysis with progress and cancellation; Inventory view (language override and file group exclusion saved to profile); search; Callers / Callees panel; code inspector with "modified file" banner; file explorer; lazy tree list; Analysis Health panel (with Lot 7 metrics).
- **Validation tests:** pytest-qt model tests; user scenarios S1, S2, S7, S8, S10 (§5.6); interface remains responsive during starter corpus analysis.
- **Depends on:** Lot 9.

### Lot 11 — Files and functions TreeGraph

- **Objective:** two visual graph views.
- **Deliverables:** `layout/tree.py` (deterministic tree layout); TreeGraph view (`QGraphicsView`) in both directions (callees, callers) and routine, file, directory levels; color per language; "+N" pagination, "↺ already shown" marks, hubs and data families hidden by default, level of detail, layout cache. *(The TreeGraph view was replaced by the embedded 3D graphs, decision D21.)*
- **Validation tests:** identical input produces identical coordinates; expansion < 200 ms; 300 nodes rendered smoothly on reference machine; scenarios S3, S4, S5.
- **Depends on:** Lot 10.

### Lot 12 — Packs, keyword-based language profiles, noise filtering

- **Objective:** host codebase-specific domain knowledge and languages without a native adapter.
- **Deliverables:** `enrich/`: JSON schemas from §3.8 (pack, bridge rule, language profile, analysis profile), safe loading and precise error messages; `generic_noise` pack (hub detection); `generic_fortran` pack (COMMON, module variables, `INTENT`); three-tier data accesses (§3.5); `extract/keywords/`: keyword adapter with coverage measurement (§3.9); "+N hidden utilities" badge and "AI links" filter in UI; isolation test (§6.4).
- **Validation tests:** `pack_acme` fixture yields expected data accesses (with levels) and dispatches; pack with unknown key, invalid type, or Python object YAML tag is rejected with precise message; `keywords_language` fixture with hand-written profile yields expected graph and measured coverage; on starter corpus, known utilities suggested as hubs; isolation test passes.
- **Depends on:** Lot 11.

### Lot 13 — AI: language identification and keyword completion

- **Objective:** AI identifies unrecognized languages and derives missing keywords without compromising determinism or correctness.
- **Deliverables:** `cgs ai-worker` (subprocess, JSON over stdin/stdout, schema-constrained generation, runtime CPU instruction selection); Role 1 (identification) and Role 2 (completion loop) from §3.13, with automated checks, change preview, one-click validation, optional automatic mode, and profile writing; reading user-provided docs (text, Markdown, PDF); "AI Proposals" view; `cgs complete` command; mock model and recorded responses for tests; model benchmark measuring adopted rule precision.
- **Validation tests:**
  - with mock model (CI): full pipeline produces expected profile; proposal failing any check (including negative tests) is rejected; preview displays exact added/removed links; consecutive runs with same profile produce identical graph; zero network ports open;
  - with real model (dev machine): on `unknown_extension`, language is identified; on `keywords_language` without profile, proposed profile reproduces ≥ 90% of expected edges; on `bridge_unknown_prefix`, bridge prefix is found and unresolved sites drop by ≥ 80%; each model call < 60 s on reference machine; AI boots on CPU without AVX2.
- **Depends on:** Lot 12.

### Lot 14 — Test case #1 Pack

- **Objective:** validate core on complete real codebase.
- **Deliverables:** pack described in `docs/packs/<code>.md` (rules, optional `enrich.py`); expectations for **full corpus** #1 (§5.4); comparison between hand-crafted and AI-proposed bridge rules (Lot 13) on this codebase.
- **Validation tests:** all expectations for starter and full corpora pass; zero regressions on fixtures; isolation test passes; AI vs manual comparison report recorded.
- **Depends on:** Lot 13.

### Lot 15 — AI: explanations

- **Deliverables:** context assembly (§3.13, Role 3); citation verification; background summaries; AI panel in UI; benchmark extension (30 to 50 annotated routines).
- **Validation tests:** 100% of cited identifiers verified; initial tokens in < 15 s, complete response in < 60 s on reference machine; benchmark scores recorded for candidate models.
- **Depends on:** Lot 13.

### Lot 16 — Pro Edition, license compliance, and final release

- **Deliverables:**
  - separation of `codegraph_sci_pro` package (private repo, compiled distribution); Ed25519 license key (see `docs/strategie_licence.md`);
  - **compliance as explicit task**: automated dependency license audit; Software Bill of Materials (SBOM); comprehensive `licenses/` directory (license texts and notices for every embedded component, Apache 2.0 `NOTICE` files, model license); Qt/PySide6 LGPL obligations (§7); verification that no GPL tool is bundled by default; review of analyzed code snippets in demos;
  - portable editions with and without AI; Windows binary code signing.
- **Validation tests:** installation on clean networkless machines (Ubuntu 22.04 & 24.04, Windows 10 & 11, Rocky Linux 8 if available); zero network traffic or listening ports during analysis, UI navigation, and model inference, verified on distributed package; missing or expired license never blocks core functionality; compliance checklist fully verified.
- **Depends on:** Lots 14 and 15.

---

## 5. Testing strategy

### 5.1. Test levels

| Level | Content | When |
| :--- | :--- | :--- |
| Unit | Isolated functions (language detection, name normalization, decoding, graph algorithms, layout…) | On every commit |
| Fixtures | Mini-repos with exact expected inventory, graph, and sites (§5.2) | On every commit |
| Robustness | Malformed files, huge files, tricky paths, random data (hypothesis fuzzing) | On every adapter change |
| Synthetic | Generated large-scale multi-language repo (§5.3) | Performance benchmarks, relevant lots |
| AI (mock model) | Identification and completion pipeline with recorded responses | On every change in Lots 13 & 15 |
| AI (real model) | Evaluation benchmark and AI fixtures | On dev machine, upon model or prompt change |
| Real corpora | Test cases, partial expectations, and reference samples (§5.4) | Regularly, and at end of Lots 7, 8, 14, 16 |
| Interface | Qt models and user scenarios (§5.6) | On every UI lot |
| Distributed app | Built package on clean offline machines, network and port audit | Lots 0 & 16, and on releases |

### 5.2. Fixtures catalog

| Fixture | What it tests | Lot |
| :--- | :--- | :--- |
| `inventory_mixed` | `.f`, `.f90`, `.F90`, `.py`, `.c`, `.cpp`, `.h` (C and C++), `.inc` (Fortran), extensionless file with `#!`, binary file, unknown extension, symlink loop | 2 |
| `fortran_basic` | `SUBROUTINE`, `FUNCTION`, `MODULE`, `PROGRAM`, `CALL`, `USE` | 3 |
| `fortran_fixed_form` | F77 fixed-form: column rules, column 6 continuation, `C` and `*` comments | 3 |
| `fortran_preproc` | `#ifdef` / `#else`, `#include`, macros; site-attached conditions; same routine across two branches | 3 |
| `fortran_ambiguity` | `f(i)` function vs array, `EXTERNAL`, explicit interfaces | 3 |
| `fortran_arrays_includes` | Arrays declared in include files and `COMMON`, intrinsic functions, `known_arrays` | 3 |
| `fortran_advanced` | Generic interfaces, type-bound procedures, procedure pointers, `RECURSIVE` | 3 |
| `fortran_data` | `COMMON`, module variables, `INTENT` | 3 |
| `fortran_traps` | "call x" in comment or string, mixed casing, Latin-1, Windows line endings | 3 |
| `python_basic` | Relative imports, classes, methods, decorators, dynamic calls (`heuristic`), Python 2 file | 3 |
| `c_basic` | Functions, macros, two homonymous `static` functions across two files | 3 |
| `cpp_basic`, `cpp_overloads` | Classes, macros; distinct overloads, ambiguous call → ambiguous site | 3 |
| `mini_hybrid` | Python + C++ + C + Fortran repo: inventory, per-language graphs, full chain with bridges | 3, 8 |
| `partial_scope` | Analysis restricted to subfolder: calls outside become `out_of_scope` | 3 |
| `robustness` | Malformed file, huge file, paths with spaces/accents/> 260 chars, unreadable file | 3 |
| `bridge_pybind11` | pybind11 module and its invocation from Python | 8 |
| `bridge_fortran_c` | `BIND(C)`, name mangling | 8 |
| `bridge_prefix_negative` | Identifiers resembling bridge prefix without matching; declaration macros | 8 |
| `pack_acme` | Memory manager (3 key levels), dispatch, catalog, entry points with fallback | 12 |
| `keywords_language` | Fictional language + technical manual; hand-written profile (Lot 12), AI-proposed (Lot 13) | 12, 13 |
| `unknown_extension` | Files of known language under unusual extension | 13 |
| `bridge_unknown_prefix` | C++ → Fortran calls via undeclared macro prefix | 13 |

Each fixture contains `src/` (sample files with neutral names), `expected_inventory.json`, and `expected_graph.json` (expected nodes, sites, and edges with lines, columns, confidence, and origin), authored by hand.

### 5.3. Synthetic repository

`tests/synthetic/generate.py --routines 15000 --files 3000 --langs fortran,python,cpp,c --seed 42` generates a deterministic multi-language codebase with cross-language calls and high-fan-in routines (hubs). Its inventory and graph are known by construction; same arguments yield identical codebases. Used for performance tests (§1.3), including writing ~1 million sites without relying on proprietary code, verifying that extracted graph exactly matches generated ground truth.

### 5.4. Real-world corpora

Each analyzed codebase yields **two corpora**:

- a **starter corpus**, scoped to a subset of directories, whose expectations test only within-scope definitions (Lot 7);
- a **full corpus**, covering all definitions, catalogs, and targets needed for end-to-end traversal (Lot 14).

```yaml
# tests/corpus/<code>_start/manifest.yaml
corpus: <code>_start
source: { path: "<local path to code>", revision: "<exact tag or commit>" }
license: "<license of analyzed code>"
packs: [<pack_name>]
scope: ["<subdirectories analyzed in detail>"]   # rest of repo is indexed (definitions only)
```

```yaml
# tests/corpus/<code>_start/expectations.yaml — fictional example
inventory:
  languages: { fortran: { min_files: 100 }, python: { min_files: 10 }, cpp: { min_files: 10 } }
  max_unknown_rate: 0.01
expect:
  - node: "f:assemble_matrix"
  - callers_count: { node: "f:assemble_matrix", min: 10, max: 15 }
  - edge: { src: "py:solver.api.run", dst: "cpp:Solver::run()", kind: binds }
  - path: { from: "entry:RUN", to: "f:assemble_matrix", max_len: 12, edge_kinds: call_path }
  - no_call_to: ["f:rbuf"]                         # arrays, never calls
  - hidden: "f:log_msg"
  - writes: { routine: "f:update_state", data: "data:mem:*.VALUES", key_kind: family }
metrics:
  min_recall_definitions: 0.99
  min_recall_call_sites: 0.97                       # recall sample
  min_precision_resolved: 0.98                      # precision sample, per language
  min_precision_lower_bound: 0.95
  max_unresolved_rate: 0.02
  max_parse_failure_rate: 0.02
```

- `reference_sample.yaml` stores manually checked links and locations (tagged with code revision); replayed automatically.
- Codebase sources are never tracked in Git; manifest specifies local location and exact commit. All corpora run regularly: adding a new codebase must not break existing ones.

### 5.5. Cross-cutting tests

| Test | Principle |
| :--- | :--- |
| Determinism | Same repo + same profile → identical canonical exports on Linux and Windows |
| AI outside analysis | `cgs scan` never spawns AI process (verified) |
| Offline code level | Entire test suite runs with network socket blocked (pytest-socket) |
| Offline distributed app | On Linux, app launches and functions in network namespace (`unshare -n`); on Linux and Windows, zero listening ports during analysis, UI navigation, and inference |
| Safe loading | `yaml.safe_load` exclusively; YAML files with Python object tags rejected; strict schemas; zero `pickle` |
| Robustness | Malformed sources, very large files (beyond limit, analysis truncated and logged), tricky paths, symlink loops, unreadable files, timeouts; random data sent to adapters (hypothesis fuzzing) without crashing |
| Inspector consistency | File modified after analysis flagged "stale" |
| Cache | Modifying an included file invalidates files that include it |
| Isolation | Zero pack-declared identifiers in core (§6.4) |
| Package dependencies | §3.4 rules enforced by import-linter |
| Performance | §1.3 targets measured on synthetic repo and starter corpus |
| Licensing | All dependencies tracked in §3.15 list (automated audit in Lot 16) |

### 5.6. User scenarios

| # | Scenario | Expected outcome |
| :--- | :--- | :--- |
| S1 | Open multi-language folder, run inventory then analysis, cancel, re-run | Languages displayed with coverage; progress visible; clean cancellation; responsive UI |
| S2 | Search routine | "Called by N routines across M files"; double-click → code at call line |
| S3 | Functions 3D graph across 4 callee levels (right-click expansions) | Expansions in < 200 ms, each node drawn once |
| S4 | Files 3D graph of a file, then dive into routines | Weighted links, language colors, detailed calls on link click |
| S5 | Hide then reveal utilities | "+N" badge, decluttered graph |
| S6 | Path between two routines in different languages | Path displayed and highlighted, step types visible, dispatches marked "possible" |
| S7 | Modify file, re-analyze | Re-analysis in < 30 s, views updated |
| S8 | Run application from USB drive with network disconnected | Boots and functions completely |
| S9 | Repository with unknown language; "Complete with AI" | Language identified, keyword profile proposed with effect preview; approved/rejected; links marked "AI" |
| S10 | Modify file without re-analyzing, open in inspector | Banner "This file has changed since analysis" and "Re-analyze" button |

---

## 6. Extensibility

### 6.1. Adding a language

1. **Via AI (fastest):** inventory flags unknown language; completion loop proposes keyword profile (§3.9), checked, previewed, and approved. Providing a technical document improves the proposal. Profile coverage is measured before reliance.
2. **Manually:** author keyword profile directly.
3. **Native adapter** (highest precision), if a permissive tree-sitter grammar exists: create `extract/<language>/` implementing `LanguageAdapter`, add extension mapping, create `tests/fixtures/<language>/`, declare subtypes, color, and syntax highlighting.

### 6.2. Adding a bridge

- Usually, a `bridges` entry with prefixes and name transforms suffices (§3.8): hand-crafted or AI-proposed, always with positive and negative tests.
- Otherwise, create `link/bridges/<bridge>/` implementing `Bridge`, with a two-language fixture; each produced site carries `origin = "bridge:<bridge>"`.

### 6.3. Adding a codebase

1. Author `docs/packs/<code>.md`: codebase architecture, conventions, rules, validation targets, license.
2. Run inventory, then AI completion loop; incorporate proposals into `rules.yaml` (§3.8); only add `enrich.py` if needed.
3. Declare both corpora (starter and full) with expectations, then assemble reference sample.
4. **Acceptance criteria:** expectations green, §2.1 metrics satisfied, zero regressions, core unchanged — or extended generically and documented here.

### 6.4. Isolation rule

The core (`src/codegraph_sci/`, excluding generic packs) contains zero identifiers specific to an analyzed codebase. Each pack declares its `identifiers`; a test fails the build if they appear in core. Fixtures use neutral names. AI-proposed rules for a project reside in that project's folder, never in core.

---

## 7. Licensing constraints affecting code

- **Public code under PolyForm Noncommercial 1.0.0**, described as "source-available under a noncommercial license, with commercial licensing available separately", never as "open source". Pro extensions reside in `codegraph_sci_pro`, which core never imports.
- **Dependencies:** strictly those in §3.15 or equivalent licenses (MIT, BSD, Apache 2.0, ISC, PSF, MPL-2.0 for test tools, LGPL with dynamically linked libraries); never GPL or AGPL imported by code or bundled by default. fxtran (GPL-3.0) can only be used as a separately installed external tool after license review.
- **PySide6 and Qt (LGPL-3.0):** keep Qt libraries as separate, replaceable files in `_internal/` (no static linking); provide LGPL text and Qt notices in `licenses/`; provide Qt and PySide6 sources used or written offer to provide them; do not restrict user replacement. This modularity is necessary but not sufficient: full checklist is audited in Lot 16.
- **AI models:** strictly Apache 2.0 or MIT. AI edition bundles model file **and license text** (along with `NOTICE` file if present): redistribution requirement of these licenses.
- **Analyzed codebases:** exact revision and origin of any snippet in demos are recorded, with code license notice; no source code from analyzed codebases is bundled into commercial distribution without prior review.
- **User-supplied technical documents:** read locally, never copied into rules beyond brief rationale snippets.
- **External contributions:** Contributor License Agreement (CLA) signed prior to integration.
- **License key:** never locks core functionality or data (Lot 16).
- Commercial and legal details: `docs/strategie_licence.md`.

---

## 8. Decisions and open questions

### 8.1. Decisions made (October 16, 2026)

| # | Decision |
| :--- | :--- |
| D1 | Desktop application Python + Qt (PySide6); no web application |
| D2 | Operating systems: Linux x86_64 (target: Ubuntu) and Windows x64 |
| D3 | 100% offline operation; full version transferable on USB drive |
| D4 | Modest machines, CPU only: graphical lightweighting mandatory |
| D5 | Deterministic graph for a given analysis profile; AI prepares profile, never intervenes during analysis |
| D6 | Default question: how many routines call a routine, and which ones |
| D7 | Two graph views: files and functions (3D since D21) |
| D8 | No compiler: validation without compilation, via verified samples (§2.1) |
| D9 | Dual license: PolyForm NC + commercial license |
| D10 | AI edition of portable version includes model and its license — *hypothesis to confirm* |
| D11 | First test case mixes Fortran, Python, and C/C++: language inventory and four adapters starting in Lots 2–5 |
| D12 | *(updated in v7, to confirm)* AI identifies unrecognized languages and defines missing keywords; by default, user validates in one click after link preview; automatic adoption mode enabled per project |
| D13 | Plan contains only lots and dependencies, without milestones or calendar durations |
| D14 | Every observed call is preserved as a call site (one row in DB); edges aggregate sites |
| D15 | Linux build on glibc 2.28 base: compatible with Ubuntu 20.04+ and RHEL/Rocky 8+ |
| D16 | Graph algorithms written in-house (iterative Tarjan, bitsets); NetworkX removed |
| D17 | Fortran parser chosen via comparative benchmark on real files, among permissive candidates; fxtran (GPL-3.0) excluded from default distribution |
| D18 | *(Lot 4)* Main Fortran parser: **in-house logical statement analyzer** (fixed and free form, continuations, preprocessor branches preserved, exact positions). Benchmark on fixtures (`docs/bench/fortran_parsers.md`): only candidate with 100% recall and precision; tree-sitter-fortran fails on fixed form (text past col 72, `C`/`*` comments) and loses `#ifdef` branches; fparser fails on 4/23 files and is 25x slower; LFortran not evaluated (binary missing). Fallback and dual extraction: independent pattern extractor. **To confirm on real sample files from test case #1** (`python tools/bench_fortran.py <folder>`) |
| D22 | *(UI look)* Dark & orange theme (`ui/theme.py`: palette, style sheet, icons painted with QPainter, no image file) and a frameless shell (`ui/shell.py`: title bar, resize margins, popovers, hero card) replacing the toolbar, menu and docks. Window move and resize go through the platform (`startSystemMove` / `startSystemResize`) |
| D21 | *(3D in the main window)* The two 2D TreeGraphs (`QGraphicsView`) are **replaced** by two embedded 3D graphs (functions, files) drawn by the vendored 3d-force-graph page in a **`QWebEngineView`**: the user prefers the 3D display, and it fits in the current Qt UI, so **no web UI** is needed (C1 kept). Offline guarantees: CSP, off-the-record profile, request interceptor, no server, no port (C2). Cost: Qt WebEngine is now shipped in the portable build (about +300 MB). The PyWebView window of D20 remains as the optional `cgs view3d` command |
| D20 | *(3D view)* 3D visualization with 3d-force-graph in a **PyWebView** window running in a separate process, without HTTP server or port, JavaScript vendored. **Streamlit rejected**: it is a web application serving on a local port (violates C1 and C2). QtWebEngine not used at the time (size): revised by D21 |
| D19 | *(Lot 0)* Tree-sitter grammars: standalone wheels `tree-sitter-fortran`, `-python`, `-c`, `-cpp`; `tree-sitter-language-pack` ≥ 1.0 excluded because it downloads grammars at runtime (violates C2) |

### 8.2. Open questions

1. Confirm D10, or prefer that customer places model in `models/` themselves.
2. Confirm D12 (one-click validation by default, automatic adoption as option).
3. `generic_fortran` pack: in core (adoption appeal) or in Pro (commercial value)?
4. AI identification and completion: Pro only (current choice), or basic version in core?
5. Official support for RHEL/Rocky 8, or Ubuntu only (build supports both)?
6. Test case #2: which codebase, and what new challenge should it exercise?
7. Is a Windows runner available for Lot 0 tests, or is a virtual machine required?
8. Trademark and name availability for "CodeGraph-Sci" (trademark, domain name, PyPI).

---

## Appendix A — Version history

| Version | Content |
| :--- | :--- |
| v1 | Initial architecture centered on first test case |
| v2 | Data model, pipeline, security, licensing, testing, roadmap |
| v3 | Dual licensing; user installation; Apache 2.0 / MIT models |
| v4 | Generic document: extensions (languages, bridges, packs); separate test cases |
| v5 | Execution document: PySide6 desktop app, offline, portable; bottlenecks; validation without compiler; lot-based plan |
| v6 | Language inventory and analysis profile; multi-language repos from start; AI identifying languages and defining missing keywords; keyword profiles; 17 lots without calendar milestones |
| **v7** | **Integration of two external reviews:** call sites as ground truth and symbol identity (C++ signatures, `static` functions, variants); SQLite bulk writes, deferred indexing, atomic replacement, WAL for incremental; compressed JSON cache factoring in included files; local symbols and Fortran `name(...)` rule (included file and `COMMON` arrays, intrinsics); data at three precision levels; strict pack format spec and safe loading; explicit bridge prefix semantics and negative tests; partial analysis with `out_of_scope` state; separated metrics and stratified samples with confidence intervals, replayed reference sample; stop point at Lot 7; comparative benchmark of permissive Fortran parsers, fxtran (GPL-3.0) excluded by default; Linux build on glibc 2.28 and CPU AI compatible with older processors; NetworkX replaced by in-house algorithms; explicit edge kinds for paths; freshness check in inspector; one-click AI proposal validation by default; robustness, safe-loading, and network tests on distributed package; license compliance as explicit Lot 16 task |

## Appendix B — Glossary

- **Inventory:** detection of language of each file in repo and coverage report.
- **Analysis profile:** project file specifying scope, languages, adapters, include paths, packs, and rules; analysis reads only this file.
- **Call site:** an observed call or usage at an exact code location (file, line, column), with condition, origin, and resolution state.
- **Edge:** aggregation of call sites sharing caller, callee, and type.
- **Out of scope (`out_of_scope`):** target defined in repo but outside detailed analysis scope.
- **Language adapter:** plugin reading files of a language and producing facts; native (parser) or keyword-based.
- **Keyword-based language profile:** language specification via definition, call, include keywords and syntax markers; heuristic extraction with measured coverage.
- **Bridge:** rule or plugin connecting a symbol in one language to its target in another.
- **Completion loop:** analysis → diagnostic → AI proposals → automated checks → preview & validation → updated profile → re-analysis.
- **Domain Pack:** declarative rules capturing codebase-specific conventions.
- **Facts:** data extracted from a file prior to cross-file linking.
- **Fixture:** mini test repository with hand-crafted expected inventory and graph.
- **Starter / Full corpus:** real codebase used as test case, first on reduced scope, then in full.
- **Reference sample:** manually verified links and locations, recorded and replayed automatically.
- **Hub:** routine (or data family) connected to a very high number of routines, typically a utility.
- **TreeGraph:** visual expandable tree view, node by node, at function or file level (replaced by the 3D graphs, D21).
- **Portable folder:** standalone folder (including embedded Python) functioning when copied anywhere, including a USB drive.
- **Mock model:** AI replacement returning recorded responses for deterministic testing without inference engine.
- **GGUF:** model file format executed by llama.cpp.

## Appendix C — Developer agent guidelines (to copy into `AGENTS.md`)

(Copy of Appendix C from `docs/architecture.md`.)

1. Read `docs/architecture.md` (§3 and the requested lot) before coding. Only read a `docs/packs/<code>.md` file when working on that specific pack.
2. Implement **only one lot at a time**; stop when its validation tests pass. Do not start UI lots until Lot 7 is validated.
3. Respect the contracts (§3.5 to §3.10) and package dependencies (§3.4). Any contract change must be recorded in `docs/architecture.md`.
4. Write or update tests **before** writing the code that makes them pass.
5. No network access and no open ports, in both production code and tests.
6. No dependencies outside the list in §3.15.
7. No identifier specific to an analyzed codebase inside `src/codegraph_sci/`.
8. Determinism: sort every collection before writing it; no timestamps in facts; relative paths using `/`; analysis reads only the analysis profile and never calls AI.
9. A file's language comes from the inventory; no adapter guesses it.
10. Every observed call becomes a call site with file, line, column, condition, and origin; never merge two call sites in a way that loses this information.
11. Configuration files: `yaml.safe_load` and schema validation only; never `pickle`.
12. Every analyzed file has a maximum timeout; a failure is logged, never blocking.
13. The UI accesses data only through `GraphQuery`; no long-running query on the main thread.
14. Every AI feature must be testable with the mock model.
15. Typed Python 3.12 (`mypy` strict), formatted with `ruff`; identifiers, code, UI, comments, and documentation in English.

## Appendix D — Specified extraction conventions (Lot 3)

These conventions supplement §3.5 and §3.7; expected fixture graphs (`tests/fixtures/*/expected_graph.json`) follow them.

- **Additional identities:** Fortran module `fmod:<module>` (distinct from procedures, which may share name); derived type, generic interface, and internal procedure `f:<host>::<name>`; Python method `py:<module>.<Class>.<method>`, nested function `py:<module>.<func>.<inner>`; externals `ext:intrinsic:<name>`, `ext:libc:<name>`, `ext:python:<module>[.<name>]`, `ext:mpi:<name>`, `ext:blas:<name>`.
- **Nodes:** each source file has a `file:<path>` node; declarations (C/C++ prototypes, explicit/abstract `INTERFACE` blocks, pure virtual functions) do not create a definition. A file-level macro block (e.g. `PYBIND11_MODULE(...) { }`) is not a function: its calls have the file node as source.
- **Site location:** line and column (1-based) of the start of the target text as written (`target_text`): `ELEMK`, `c%area`, `self.check`, `ops::scale`. For a macro-hidden call, macro position and `target_text` = expanded called function. For an include, position of included filename; source is the file node.
- **Confidence:** `exact` = single target found by name; `resolved` = target selected by rule (receiver type, arity/argument types, `maybe_call` decided by Link, macro, preprocessor variants); `heuristic` = dynamic call (variable, `getattr`) or unresolved site; `ambiguous` = multiple candidates.
- **Preprocessor variants:** a call toward a routine defined across multiple variants (`f:x`, `f:x#2`) is `resolved` to the first, with all variants as candidates; an edge is created to each variant.
- **Conditions:** `#ifdef X` → `defined(X)`, `#ifndef X` / `#else` → `!defined(X)`, `#if E` → `E` (normalized spacing); nested conditions joined by ` && `.
- **Calls without static target:** procedure received as argument, procedure pointer, Python variable → `dynamic_call`, `unresolved` (or `resolved`/`heuristic` if simple propagation finds target, e.g. `h = getattr(m, "f")`).
- **Libraries:** Python call to module outside repo → `external` to `ext:python:…`; method call on unknown receiver with no method of that name in repo → `external` without target node.
- **Edges:** `calls` (`call`, `maybe_call`, `dynamic_call` sites having a target, including `external`, `out_of_scope`, and each candidate of ambiguous site), `uses` (`use`, `include`), `inherits`, `implements` (generic interface → specific procedures, without site), `contains` (structure).
- **Bridges (Lot 8):** `binding` nodes extracted from sources — `bind:pybind11:<module>[.<name>]` (`PYBIND11_MODULE`, `m.def`), `bind:pyext:<module>[.<name>]` (Python C-API: `PyInit_<module>`, `PyMethodDef` tables), `bind:decl:<name>@<file>` (rule declaration patterns). A site resolved by a bridge preserves its `ref_kind` and takes origin `bridge:<bridge>` (`bridge:prefix_calls@<rule>` for profile rule) and `resolved` confidence; its edge is `binds` for `pybind11` and `python_extension` (Python → compiled code), `bridges` for `fortran_c`, `c_cpp`, and `prefix_calls`. A structural `binds` edge links each `binding` node to its implementation. Native bridges (`pybind11`, `python_extension`, `c_cpp`, `fortran_c`) are active by default; they act only on unresolved or external sites.
- **Packs (Lot 12):** additional format key `data: {fortran_common, fortran_module_variables}` (generic pack `generic_fortran`). New profiles enable `generic_noise` and `generic_fortran`. Rule templates: `catalogs[].entry`/`target` and `entry_points[].target`/`fallback_target` are `str.format` templates (entry fields, named regex groups, `{file_stem}`). Memory keys: literal object `data:mem:<name>`, local object `data:mem:<routine>:<name>` (`local_prefix_pattern`, priority over `literal`), symbolic `data:mem:<routine>:<expression>`, family `data:mem:*<suffix>` (hidden by default). An ambiguous site with > 8 candidates retains zero candidates (no edge).
- **Keyword languages:** profiles `rules/languages/<language>.yaml` (schema `extract/keywords/language.schema.json`), identities `kw:<language>:<name>`, origin `keywords:<language>`.
