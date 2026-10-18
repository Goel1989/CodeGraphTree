# CodeGraph-Sci — Architecture and Implementation Plan

**Version:** 8.0 — execution document, updated to the implementation (October 17, 2026; changes in Appendix A)  
**Author:** Marian Bogdan Neagoe, PhD  
**Purpose:** offline desktop application (no cloud service; analysed code never sent to a remote service), identifying languages in a scientific or industrial codebase (Fortran, Python, C, C++ initially), building the "who calls who" graph across these languages, and answering the question "who calls what, and where?".

> **How to use this document.**
>
> - **§0 to §2:** what the application must do, and technical bottlenecks to address first.
> - **§3:** architecture, along with the contracts that the code must follow.
> - **§4 and §5:** implementation plan in numbered **lots**, each with its validation test, followed by the test strategy.
> - **§6 to §8 and appendices:** extensibility, license constraints, decisions, developer agent guidelines (Appendix C, to copy into `AGENTS.md`).
>
> This document is **generic**: no rule specific to an analyzed codebase appears here. Each codebase is a test case described in `docs/packs/<code>.md`. The business and licensing strategy is in `docs/licensing_strategy.md` (user-facing summary: `LICENSING.md`).

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
| C2 | Offline | No cloud service needed; analysed source code never sent to a remote service; analysis and optional local AI run on the user's machine. CodeGraph-Sci processes refuse network sockets (Python-level guard, `core/netguard.py`, and `pytest-socket` in tests) and open no port; web pages are restricted by CSP and a request interceptor. This is not an operating-system network sandbox: an absolute "network access impossible" guarantee would be a separate OS-level confinement requirement. Tests of the packaged application without network: Lot 16 |
| C3 | Full version transferable on a USB drive | Portable folder with embedded Python, one per OS: Linux x86_64 (target: Ubuntu) and Windows x64 |
| C4 | Modest machine, CPU only | Interface never loads the entire graph; everything is precomputed and paginated; AI is only invoked on samples |
| C5 | Deterministic structure | Same repo + same analysis profile + same versions = same graph; AI prepares the profile, it never intervenes during analysis |
| C6 | Multi-language repositories from the start | The first test case mixes Fortran, Python, and C or C++: language inventory and all four adapters arrive in early lots |
| C7 | Extensible | New languages and new codebases added via plugins or keyword profiles, without modifying the core |
| C8 | No compiler available | Validation of analysis without compilation, through verified samples (§2.1) |

**Implementation order.** Built bottom-up; each lot finishes with a test that must pass before starting the next one (details in §4). Lot 7 is a **stop point**: as long as graph accuracy is not demonstrated, UI development does not start. *Status note:* the UI lots were built while the manual part of Lot 7 (precision and recall review sheets) was still pending; the automatic Lot 7 checks pass, the stop-point criteria are not yet demonstrated (`docs/migration_report.md`).

| Lot | Title | Depends on | Status (October 17, 2026) |
| :--- | :--- | :--- | :--- |
| 0 | Portable skeleton (USB drive, offline) | — | Done; tests on clean machines without network pending (Lot 16) |
| 1 | Data model and storage | 0 | Done |
| 2 | Language inventory and analysis profile | 1 | Done (with skipped-folder report and `all_subfolders`) |
| 3 | Reference mini-codebases (tests written before code) | 2 | Done |
| 4 | Fortran adapter (with parser benchmark) | 3 | Done (adapter 1.6) |
| 5 | Python, C, and C++ adapters | 3 | Done |
| 6 | Link, Index, and `cgs scan` command | 4, 5 | Done (FULL/OUTLINE extraction and per-file deadlines, D25) |
| 7 | Validation on a real codebase (Bottleneck V1, stop point) | 6 | Partial: tools and automatic checks done, starter corpus 16/16; manual precision/recall review pending |
| 8 | Cross-language bridges | 6 | Done |
| 9 | Query API and command line | 7, 8 | Done (query times not measured) |
| 10 | Desktop application: inventory, search, callers, inspector | 9 | Done (shell of D22) |
| 11 | Files and functions graph views | 10 | Done as 3D graphs (D21, D23), replacing the TreeGraph |
| 12 | Packs, keyword-based language profiles, noise filtering | 11 | Done |
| 13 | AI: language identification and keyword completion | 12 | Partial: pipeline tested with the mock model only |
| 14 | Test case #1 Pack | 13 | Partial: starter corpus done; full corpus not prepared |
| 15 | AI: explanations | 13 | Not started |
| 16 | Dual licensing, license compliance, and final release | 14, 15 | Partial: licensing documents done (D24); compliance audit, SBOM, signing and offline tests of the package pending |

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

Both 3D graphs **open on the overview of the whole project** (decision D23): every node and every link — inside a folder or between folders, the latter drawn in their own colour — when the project fits under the node ceiling; otherwise one sphere per **group** (a connected set of routines or files linked to nothing outside it: separate or parallel programs), sized by its member count, plus an "isolated" sphere (members linked to nothing) and a "more groups" sphere. A click opens a group with all its links; "All groups" comes back. In Files 3D, the files that are not analyzed code (docs, data, configuration, images, archives, binary, unknown type, code without adapter) are set apart in a grey grid below the code, never linked. In both 3D graphs a node is drawn once whatever the number of paths reaching it (cycles and shared calls stay legible); the drawn neighbourhood is bounded by a depth and a node ceiling (decision D21, which replaced the 2D TreeGraphs).

### 1.3. Non-functional requirements

Reference machine: 4-core laptop, 8 GB RAM, no dedicated GPU. These targets are **metrics to measure** (lots 2, 6, 7, 9, 11, 13); they will be adjusted based on actual measurements. No target is a promise until it is reproduced in a documented benchmark (`cgs benchmark`, `docs/bench/`); measurements so far were made on an 8-CPU development machine, **not on the reference machine**.

| Metric | Target | Measured (documented) |
| :--- | :--- | :--- |
| Language inventory of a ~15,000 file repository | < 1 min | 13.9 s for 15,000 files (lot 2); 4.8–5.1 s on the 18,438-file Code_Aster sample (`docs/bench/scan_benchmark.md`) |
| Full analysis of the same repository | < 15 min | 87.5 s on the Code_Aster sample (cold, `docs/bench/scan_benchmark.md`) |
| Re-analysis after modifying at most 50 files | < 30 s | 10.8–10.9 s (synthetic, 3,000 files) and 25.9 s (Code_Aster sample) (`docs/bench/scan_benchmark.md`) |
| AI-assisted preparation (identification + completion) | At most 3 iterations of 10 model calls; each call < 60 s | Not measured (only the mock model is tested) |
| Opening an already analyzed project | < 3 s | Not measured |
| Callers of a routine (count + list) | < 100 ms | Not measured |
| Expanding a node in a 3D graph | < 200 ms | Not measured |
| Concurrently rendered nodes | 300 by default (configurable); beyond that, "+N" grouping | Implemented (node ceiling, group spheres) |
| Application RAM usage, without AI | < 1.5 GB on test case #1 | Not measured |
| Interface during an analysis | Remains responsive (analysis in separate process) | Checked by the UI tests (scan in a subprocess); not timed |

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
- **Without a model** (no model installed or bundled), everything works: unknown languages are reported, and keyword profiles can be written manually.

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

The interface never manipulates the entire graph. Strategies are detailed in §3.12: precomputations during analysis, paginated queries, capped rendered node count, an overview by connected groups when a project exceeds the ceiling, a 3D force layout stopped after a few seconds, labels on hover only. On the storage side, database is built via bulk inserts with indexes created at the end (§3.6).

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
│ Code inspector · Analysis health · AI                          │
└──────┬────────────────────────┬────────────────────────┬───────┘
       │ threads                │ subprocesses           │ pipes
       │ (read)                 │ (progress)             │ (JSON)
┌──────▼──────┐   ┌─────────────▼─────────────┐   ┌──────▼───────┐
│ Query       │   │ cgs inventory             │   │ AI Worker    │
│ API         │   │ cgs scan (deterministic)  │   │              │
│ query/      │   │ reads profile; extraction │   │ GGUF model   │
│             │   │ workers, 1 deadline/file  │   │              │
└──────┬──────┘   └─────────────┬─────────────┘   └──────┬───────┘
       │ reads                  │ writes                 │ proposes
       └───────────┬────────────┘                        │
          ┌────────▼────────┐               ┌────────────▼───────┐
          │ <project>.sqlite│               │ analysis profile   │
          └─────────────────┘               └────────────────────┘

No network ports, no connections: strictly files, function calls,
subprocesses, and pipes. cgs scan never calls AI.
```

- **Main process:** Qt interface (with Qt WebEngine for the 3D graphs). Never reads source files for analysis and never executes long queries itself.
- **Query threads:** each query (callers, expand, search) runs in a Qt threadpool thread, with its own read-only SQLite connection, returning results via signals.
- **Analysis process:** interface spawns `cgs inventory` then `cgs scan` (same CLI executable) as subprocesses, reads progress (one JSON line per event), and can cancel them. A parser crash cannot crash the UI; a file exceeding its deadline is stored with `parse_status = timeout` (only that file: its worker process is killed and replaced, the other files continue), and analysis proceeds.
- **AI process:** dedicated subprocess loading the model; communicates via stdin/stdout (one JSON message per line). **No network ports**, even internally. Never called by `cgs scan`.
- **Project files:** analysis profile (`analysis_profile.yaml`, adopted rules) and SQLite database.

### 3.2. Language inventory and analysis profile

**Deterministic step: `cgs inventory <folder>`**

1. **Repository traversal:** walks **every sub-folder** of the selected folder (depth first, sorted names); by default it obeys `.gitignore` and the default excluded directory names (`build`, `.venv`, `node_modules`, caches…), plus the profile's `exclude_dirs`. Every folder (or `.gitignore`d file) left out is **reported** with its reason (`default exclusion`, `.gitignore`, `profile`) and file count: `cgs inventory`, `skipped_dirs` in the inventory JSON and in the scan statistics, and the Inventory view. The profile option `all_subfolders: true` (`cgs profile all-subfolders <folder> on`, or the "Analyze all subfolders" box of the Inventory view) ignores `.gitignore` and the default exclusions; version-control metadata (`.git`, `.hg`, `.svn`) and `exclude_dirs` still apply. The key is written only when true, so existing profiles keep their hash. Binary files (null bytes) are ignored; symlink loops and unreadable files are logged without blocking traversal.
   **Persistent inventory (D28):** discovery is separate from analysis selection. Every discovered entry (directory, file, link, special file) is recorded with its parent, extension, size, language and detection evidence, analysis **eligibility** (`eligible`, `excluded`, `not_source`, `unsupported_language`, `unreadable`, `not_applicable` for walked directories), **status** (files: `pending`, then the analysis status; directories: `walked`, `not_walked`) and the **reason** it is not analyzed; discovery problems are recorded as issues (`unreadable`, `loop`, `broken_link`, `external_link`). Two policies (profile key `inventory_policy`, written only when not the default; `cgs profile inventory-policy <folder> analysis|complete`): **analysis** (default) records an excluded folder as one entry with its file count; **complete** walks excluded folders too and records their content (language from the extension only), never read nor parsed. Empty directories are recorded; an unreadable entry is recorded as unreadable; a folder already visited through a symbolic link is a loop (recorded, not walked); a symbolic link to a target outside the root is still followed, recorded with its target and flagged; broken links and special files are recorded; version-control metadata is recorded but never walked nor counted. `cgs inventory --json [--entries]` reports the policy, the accounting by kind, eligibility and reason, and the issues.
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
| **Extract** | One file + language + included files | *Facts*: definitions with local symbols, unresolved call sites, data accesses, directives, includes — **FULL** for files in the analysis scope, **OUTLINE** (definitions and includes only) for the others | `extract/` (one adapter per language, or keyword adapter) | Per file, in worker processes (`extract_pool.py`), **one deadline per file**; cache keyed by file, includes, adapter version, parameters and extraction mode (§3.6) |
| **Link** | All facts | Resolved, ambiguous, external, out-of-scope, or unresolved call sites; nodes | `link/` (symbol table + bridges) | Global; normalizes names (casing, mangling) |
| **Enrich** | Graph | Hiding, data accesses, dispatches, entry points, tests | `enrich/` (packs) | Declarative frozen rules |
| **Index** | Enriched graph | Aggregated edges, counts, file/directory links, impact size, full-text search | `store/`, `algo/` | Standard Python algorithms (§3.6) |
| **Diagnostic** | Database | Analysis health; unresolved and ambiguous sites grouped by pattern; non-resolved references by category (§3.5) | `audit/`, `query/` | Used by user and, if enabled, by AI |

- **Re-analysis:** the Extract step is only re-run for files whose cache key changed (file, an included file, its adapter, extraction settings, or extraction mode); subsequent steps are re-run entirely. Measured (`docs/bench/scan_benchmark.md`): after 50 changed files, the rebuild after extraction (cache lookup, inventory, index, write) dominates the rescan time.
- **Partial analysis:** if the profile restricts `scope`, files outside it are extracted in **OUTLINE** mode (D25): definitions with their attributes and includes only, no references, data accesses or directives (the Fortran parser skips executable statements except `SELECT CASE`; since D32 every adapter honours the mode: Python skips expressions, decorators and base classes, C/C++ skip call expressions inside bodies, keyword languages apply no call rule; definitions are identical to FULL). The mode is chosen before the files are scheduled, is part of the cache identity, and moving a file into scope forces a FULL extraction. A call to a routine defined outside scope points to an `out_of_scope` node: not counted as "unresolved".
- **Extraction workers:** files are extracted in worker processes (`extract_pool.py`, count = `jobs`, default cores − 1) with **one deadline per file**; a late file kills only its own worker, which is replaced, and is stored with `parse_status = timeout`. Results are kept in memory and written in one database write at the end of the scan.
- **Statistics:** each scan records in `scan_runs.stats` the counts per resolution, `phases_ms` (inventory, cache lookup, extraction wall time and summed FULL/OUTLINE time, link, enrich, index, total), file counts per extraction mode, the skipped folders and the non-code files (`cgs benchmark` adds the SQLite write time).
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
| `scan` (`scan.py`, `extract_pool.py`) | Pipeline orchestration; extraction worker processes with per-file deadlines | `core`, `algo`, `inventory`, `extract`, `link`, `enrich`, `store` |
| `corpus_audit`, `benchmark` | `cgs audit corpus` (authoritative manifest, PASS/FAIL/SKIP), `cgs benchmark` (measured phases) | `scan`, `query`, `audit`, `inventory`, `enrich`, `core` |
| `cli` (`cli.py`, `cli_query.py`, `cli_ai.py`) | `cgs` command | everything above; `cli_ai` alone imports `ai` |
| `ui` | Desktop application | `core`, `query`, `layout` — **never** `extract`, `link`, `enrich`, `store`, `scan`, `audit` or `ai` directly (indirect imports allowed) |
| `ai` | Local AI (§3.13): models, worker process, completion of the profile | `core`, `inventory`, `extract`, `link`, `enrich`, `store`, `query`, `scan` |

These rules are enforced by `import-linter` (six contracts: core imports nothing internal; leaf packages only use core; leaf packages are independent; query only uses core, store, algo; ui only uses core, query, layout; **the analysis never uses the AI** — `scan`, `audit`, `corpus_audit` and `benchmark` never import `ai` or `cli_ai`).

### 3.5. Data model

**Symbol identity.** Each symbol has a stable, unique `uid` used everywhere internally, and a user-friendly `display_name` for the UI.

| Language | `uid` format | Notes |
| :--- | :--- | :--- |
| Fortran | `f:<name>`; module procedure `f:<module>::<name>` | Lowercase (case-insensitive language) |
| C | `c:<name>`; `static` function: `c:<name>@<file>` | Two `static` functions with same name in two files are distinct symbols |
| C++ | `cpp:<ns>::<Class>::<method>(<normalized param types>)` | Signature is part of identity; `display_name` omits it |
| Python | `py:<module>.<qualified name>` | — |
| Keyword profile | `kw:<language>:<qualified name>@<file>` | File and lexical scope distinguish homonyms; repeated occurrences receive `#2`, `#3`, etc. |
| Others | `file:<path>`, `entry:<name>`, `data:<key>`, `test:<id>`, `ext:<library>:<name>` | Paths relative to repository root, using `/` |

- **Preprocessor variants:** if a routine is defined across multiple `#ifdef` branches, each receives a suffix `#2`, `#3`… and preserves its condition.
- **Overloads and generic interfaces:** when a call cannot disambiguate (types unknown statically), call site retains **all candidate targets** and becomes `ambiguous`.

**Identity of occurrences (D27):** definition nodes record `attrs.symbol_uid` (the adapter's semantic
identity) and `attrs.occurrence_uid` (SHA-256 of symbol identity, relative file and source span).
Graph nodes continue to preserve separate definition occurrences; source positions select the owner
of a call when the same symbol is defined more than once in one file. Existing C/C++ signatures,
internal linkage and declaration/binding conventions remain unchanged. Keyword names with multiple
definitions are ambiguous, never resolved by choosing the first file. Lexical qualification preserves
identity but does not claim complete language-specific scope resolution.

**Call site identity.** Every call or usage observed in code is a **site**: file, line, column, caller routine, target text as written. Site preserves its preprocessor condition, origin, confidence, and resolution state:

| State (`resolution`) | Meaning |
| :--- | :--- |
| `resolved` | Unique target in repository |
| `ambiguous` | Multiple candidate targets |
| `external` | Outside the repository: known library (MPI, BLAS…), intrinsic function, Python module not found in the repository (assumed external), or method of an unknown receiver (no target node) |
| `out_of_scope` | Target defined in repository, outside analyzed scope |
| `unresolved` | No target found |

A graph **edge** aggregates sites sharing (caller, callee, type): carries count, lowest confidence, set of origins, and conditions. Fast queries use edges; line-by-line navigation uses call sites.

**Reference categories (diagnostic, D26).** For reporting, every site not resolved to a routine of the scope is put in exactly one category, first matching rule, without changing its stored resolution: `external_known` (recognised libraries and intrinsics, C++ standard library, Python standard library), `out_of_scope`, `ambiguous`, `dynamic` (dynamic call, procedure pointer or dummy procedure, Python attribute call), `parser_limitation` (file analysed by the fallback extractor, or C/C++ member call whose receiver type is not inferred), `unknown` (everything else, including imports not found and Python modules outside the standard library). An unverified external is never counted as known.

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
      parse_status, adapter, adapter_version, error, mtime_ns, cache_key)
      -- parse_status: ok, fallback, failed, timeout, outline (outside the scope), not_analyzed
inventory(file_id, lang, variant, confidence, decided_by)
inventory_entries(path TEXT PRIMARY KEY, parent, kind, extension, size, files, lang, variant,
                  confidence, evidence, eligibility, status, reason, link_target)   -- D28: every entry
inventory_issues(path, kind, message)        -- discovery problems: unreadable, loop, broken_link, external_link
nodes(id INTEGER PRIMARY KEY, uid TEXT UNIQUE, display_name, kind, subtype, lang,
      file_id, line_start, line_end, in_scope, attrs JSON)
conditions(id INTEGER PRIMARY KEY, expr TEXT UNIQUE)              -- preprocessor guards
call_sites(id INTEGER PRIMARY KEY, src_node, file_id, line, col, ref_kind, target_text,
           dst_node, resolution, confidence, origin, condition_id,
           evidence JSON)        -- one site = one line; evidence: bridge resolutions only (D31, schema 3)
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
          plugins JSON, stats JSON)    -- stats: counts, phases_ms, files per mode, skipped_dirs, non_code

-- Later lots
summaries(node_id, content_hash, model_id, prompt_version, text)   -- Lot 15 (created, unused yet)
layout_cache(key, layout_version, data JSON)                        -- Lot 11 (created, unused since D21)
```

**Schema version** (`PRAGMA user_version`): **3** since D31 (2: `inventory_entries`, `inventory_issues`, D28;
3: `call_sites.evidence`). A
database of another version is rebuilt by the next analysis (full write); its facts cache is still reused, since
cached blobs carry their own facts format version. Readers refuse another version ("re-run the analysis").

**Indexes** (created **after** inserts): `call_sites(src_node)`, `call_sites(dst_node)`, `call_sites(file_id, line)`, `call_sites(resolution, target_text)`, `data_accesses(src_node)`, `data_accesses(data_node)`, `edges(src, kind)`, `edges(dst, kind)`, `nodes(file_id)`.

**Writing and performance**

- **Full analysis:** database is constructed in a temporary file (`<project>.sqlite.tmp`), journal disabled during build (`PRAGMA journal_mode=OFF`, `PRAGMA synchronous=OFF`), bulk inserts (`executemany` in 50,000-row chunks), indexes created at the end, then `ANALYZE` and atomic file rename: UI never sees a half-written DB.
- **Incremental re-analysis:** WAL mode (`PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`); UI continues reading while writing.
- **Volume:** ~1 million call sites for 15,000 files. One row per site, mostly integers, represents tens of MBs, writes in seconds via bulk inserts, and is read via index for line-by-line inspector navigation.
- **Facts cache (D27):** key = cache identity version + facts format version + relative file path + file SHA-256 + included-file hashes + adapter name/version and parser runtime versions + extraction settings (inventory language and variant, preprocessor macros, **ordered** include paths, known arrays, `keep_all_branches`) + effective Python module name + **extraction mode**. Keyword adapter versions contain the SHA-256 of their canonical profile. Every include lookup records its source file, target, resolved path and hash, including nested and unsuccessful lookups. Cache validation repeats those lookups, so a new or shadowing header invalidates the affected facts. Linking always runs again; bridge/resolution-only changes do not invalidate extraction. Content is canonical JSON compressed with `zlib`, never `pickle`. Facts format **2** rejects old blobs explicitly; the next scan rebuilds them, without changing the database schema.
- The schema carries a version number; an older version database is migrated or re-analyzed.

### 3.7. Plugin contracts and facts

```python
class LanguageAdapter(Protocol):
    name: str                      # "fortran", "python", "c", "cpp", "keywords:<language>"
    version: str
    languages: list[str]           # inventory languages it can read
    def extract(self, file: SourceFile, ctx: ExtractContext) -> FileFacts: ...
        # ctx: include paths, macros, timeout, names known as arrays, keep_all_branches,
        #      outline (True for files outside the scope: definitions and includes only)

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
    attrs: dict        # e.g. select_cases (dispatch), specifics (generic interface), bind names

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
    variant: str | None
    extraction_mode: str                         # "full", or "outline" for files outside the scope
    include_lookups: list[IncludeLookup]         # every include lookup (source, target, resolved path, hash),
                                                 # including nested and unsuccessful ones: replayed to validate
                                                 # the cache (facts format 2)
```

- Each file's language comes from inventory (profile); adapter does not guess it.
- **Language packages (D29):** every language is described by a versioned package (`extract/registry.py`, schema
  `extract/language_package.schema.json`, package format 1): language, version, extensions and detection hints
  (file names, shebang interpreters), dialects, backend, naming and scope rules, relationship types, resolution
  capabilities, limitations, test cases and provenance. Backends: `keywords` (declarative rules of §3.9, under
  `rules`) or `native:<name>` (a parser-backed `LanguageAdapter`: the four built-in ones, or an adapter installed
  separately that declares itself in the entry point group `codegraph_sci.language_backends`; configuration files
  never execute code). The four native adapters are packaged behind the same contract (`extract/languages/*.yaml`,
  extensions identical to the inventory table, checked by a test). **Precedence:** `builtin` < `user`
  (`<data dir>/languages/`) < `project` (`<project>/rules/languages/`) < packages given explicitly to a scan; each
  level holds `<name>.yaml` files or `<name>/package.yaml` folders, and a keyword profile of §3.9 is read as a
  keyword package (same adapter version, so caches stay valid). Only approved packages are active; a project
  package whose language the analysis profile marks `proposed` or `rejected` stays inactive. **Ambiguity is an
  error** naming both files: two packages of one level for a language, a higher-level package replacing another
  without `overrides: true`, two languages claiming one extension, file name or shebang, or a package claiming an
  extension the inventory decides by content (`.h`, `.inc`…). The inventory learns the extensions and hints of
  added packages; their extensions take precedence over "known but not covered". Extraction workers receive the
  selected packages, not file paths. `cgs languages <folder> [--json]` lists the selection and inactive packages.
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

**Rule workflow (D30):** rules are written, validated, tested and activated with `cgs rules new|validate|test|
activate` (`rules.py`, guide `docs/rules/README.md`, templates in `templates/rules/`). Layout of a project:
`rules/languages/<name>/language.yaml` (+ `tests/*.source`, `*.expected.json`), `rules/bridges/<name>.yaml` (bridge
format 1, `enrich/schemas/bridge_rule.schema.json`: the rule is a `bridges[]` entry, plus repository tests),
`rules/projects/<name>.yaml` (a pack, with an optional `validation` list of repository tests; packs are also found as
`<folder>/<name>.yaml`). A rule is created `proposed`; activation validates it, requires at least one test case and
all passing, checks that the language selection stays unambiguous, then approves it (file status, profile entry or
`rules:`/`packs:` of the profile, history line). Language tests compare definitions (name, kind, lines, parent) and
references (enclosing definition, target, kind, line, column); repository tests scan a small repository with the
rule alone and check `edges` and `absent_edges`. **Resource limits** (`core/patterns.py`): rule files ≤ 1 MiB;
configurable regular expressions ≤ 500 characters, compiled, without backreferences or nested quantifiers; keyword
lists ≤ 200 literal words of ≤ 64 characters.

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

**`bridges[]`** — `{from, to, call_prefixes, name_transform, declaration_patterns, extension_modules, id, version,
mechanism, candidates, require_declaration, files, target_files}`:

- `call_prefixes`: attempted **longest to shortest**; a call `PREFIX` + `NAME(...)` yields a site toward the target produced by applying `name_transform`;
- `name_transform`: ordered list of operations among `strip_prefix` (default, first), `lowercase`, `uppercase`, `append_underscore`, `strip_underscore`;
- `declaration_patterns`: patterns that **declare** a routine from the other language (prototype, declaration macro). They create `binding` nodes, **never call sites**;
- `extension_modules`: compiled modules exposed to Python.
- `candidates` (D31): `keep_ambiguous` (default) keeps every target of a homonym as an ambiguous site; `unique` links
  only a single target. A target is never picked among homonyms;
- `require_declaration`: a prefix call is linked only if a `declaration_patterns` match of the same rule names its
  target (the binding declaration is the evidence; a similar name alone is not);
- `files` / `target_files`: globs limiting the caller files and the files targets may come from (module or library
  constraints); `version` and `mechanism` (a documented label) are recorded in the evidence.

**Bridge declarations and evidence (D31).** Native bridges are declared in `core/bridge_catalog.py`: languages,
mechanisms, matching conditions, name transformation, constraints, candidate policy, identifier and version.
Mechanisms and their evidence kind: `bind_c_name`, `pybind11_module`, `pybind11_def`, `pyext_module`, `pyext_def`,
`declaration_macro` (**binding declaration** in the sources); `trailing_underscore`, `g77_double_underscore`,
`uppercase_name`, `same_name`, `c_linkage_same_name` (**naming convention** of compilers and linkers, used only
when exactly one target exists); `prefix_call` (**rule**). A site resolved by a bridge stores `evidence`: rule and
rule version, mechanism, evidence kind, binding declaration, transformed name, candidate selection and reason. The
query layer adds, for every site, the extraction rule (adapter and version of the file), the resolution rule
(origin), the candidate selection and a reason derived from the resolution. Bridges used by an analysis are recorded
in `plugins` (`bridge`, `bridge_rule` with their version).

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
    def inventory_entries(self, parent: str | None = None, *, eligibility: str | None = None,
                          kind: str | None = None, limit: int = 1000, offset: int = 0) -> list[InventoryItem]: ...
    def inventory_accounting(self) -> InventoryAccounting: ...   # policy, counts by kind/eligibility/status/reason
    def inventory_issues(self) -> list[InventoryIssue]: ...
    def find(self, text: str, kinds: set[str] | None = None, limit: int = 50) -> list[NodeSummary]: ...
    def node(self, uid: str) -> NodeDetail: ...
    def callers(self, uid: str, *, hide_noise: bool = True) -> CallerReport: ...
        # CallerReport: count, file_count, items = [(caller, sites=[CallSite])]
        # + unresolved_sites, ambiguous_sites: sites not counted in `count` (callees: the routine's open
        #   sites; callers: ambiguous sites listing it as a candidate), always shown next to the count
    def callees(self, uid: str, *, hide_noise: bool = True) -> CallerReport: ...
    def children(self, uid: str, *, direction: Direction, level: Level,
                 edge_kinds: set[str] = CALL_PATH, offset: int = 0, limit: int = 50,
                 hide_noise: bool = True) -> Page[TreeItem]: ...
        # direction: CALLERS or CALLEES; level: ROUTINE, FILE, or DIRECTORY
    def file_links(self, file_uid: str, *, direction: Direction) -> list[FileLink]: ...
    def call_sites(self, src_uid: str, dst_uid: str) -> list[CallSite]: ...
        # CallSite: file, line, col, condition, origin, confidence, resolution, evidence (D31: extraction,
        #   resolution_rule, candidate_selection, reason; bridges: rule_version, mechanism, binding, ...)
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
    def bridges(self) -> list[dict]: ...                     # bridges of the last analysis, with their declaration
    def dependencies(self, filters: DependencyFilter | None = None, *, sort: str = "path", descending: bool = False,
                     limit: int = 200, offset: int = 0) -> DependencyPage: ...
        # D33: one row per relationship occurrence (call sites + binding declarations): caller (uid, file, language),
        # target text, target (uid, file, language), candidates, relationship (call, dynamic_call, import, include,
        # inherit, bridge, binding, binding_declaration), line, col, resolution, confidence, rule, condition;
        # filtered, sorted and paged by SQLite
    def dependency_groups(self, level: str, filters: DependencyFilter | None = None, ...) -> DependencyPage: ...
        # entity, file or directory level: count and statuses per (source, target, relationship), with the filter
        # of its occurrences
    def dependency_evidence(self, row: DependencyRow) -> DependencyEvidence: ...   # source lines and evidence
    def graph3d_directories(self, *, max_nodes: int = 300) -> Graph3D: ...   # D34: directory level
    @staticmethod
    def link_evidence(source: str, target: str) -> DependencyFilter: ...    # rows behind a drawn link
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
    def files(self) -> list[dict]: ...                                  # file explorer rows
    def file_symbols(self, path: str) -> list[NodeSummary]: ...
    def sites_in_file(self, path: str) -> list[CallSite]: ...          # inspector highlights

    # 3D graphs (§3.11, D21, D23)
    def graph3d(self, root_uid: str, *, mode: str = "functions", depth: int = 2,
                max_nodes: int = 400, hide_noise: bool = True) -> Graph3D: ...
        # mode: functions, files, or both (routines + defining files); callers and callees, bounded
    def graph3d_main_paths(self, target_uid: str, *, mode: str = "functions", max_paths: int = 3,
                           max_len: int = 15) -> tuple[Graph3D, MainPathReport]: ...
    def groups(self, level: Level = Level.ROUTINE, *, hide_noise: bool = True) -> GroupsReport: ...
        # connected groups (union-find over CALL_PATH edges or file_edges), isolated members
    def graph3d_overview(self, *, mode: str = "functions", max_nodes: int = 300,
                         hide_noise: bool = True, include_noncode: bool = True) -> Graph3D: ...
        # everything when it fits, else one sphere per group (+ isolated, + more groups)
    def graph3d_group(self, group_id: str, *, mode: str = "functions", max_nodes: int = 300,
                      hide_noise: bool = True) -> Graph3D: ...
        # group_id: group:<representative>, isolated:<level>, more:<level>:<offset>
    def non_code_files(self) -> NonCodeReport: ...                      # from the last scan statistics
        # Graph3DNode: id, label, kind, lang, file, line, fan_in, fan_out, is_root, is_noise, size, note
        # Graph3DLink: source, target, kind, count, confidence, cross_dir (ends in different folders)

    # Diagnostic (D26)
    def reference_categories(self) -> ReferenceCategories: ...
        # counts per category (§3.5), per reference kind, examples, totals
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

- **Inventory view:** languages and coverage, unrecognized files, the folders left out of the analysis with their reason and file count, and the "Analyze all subfolders" box (profile option `all_subfolders`, §3.2), "Force language…" and "Ignore extension…" (written to the profile by `cgs profile`, then re-analysis).
- **Analysis health view:** files per status (including `timeout` and `outline`), call sites per resolution, unresolved rate, non-resolved references by category (§3.5), unresolved and ambiguous patterns, failed and fallback files.

**Qt components**

- Text lists and trees: lazy `QAbstractItemModel` (`canFetchMore` / `fetchMore`) requesting children in pages of 50 from `GraphQuery.children`.
- **3D graphs** (`ui/graph3d_view.py`, decision D21): `Graph3DView` = toolbar (All groups, From main, Paths to main, depth, node ceiling, defining files) + `QWebEngineView` showing the vendored 3d-force-graph page (`ui/web/`), written once per process to a private temporary file. Data comes only from `GraphQuery` in a `QueryRunner` thread: `graph3d(root, mode, depth, max_nodes)` for a neighbourhood, `graph3d(uid, depth=1)` merged on right-click, `graph3d_main_paths(target, mode)` for "Paths to main" (shortest path only when there are too many). Python → page: `runJavaScript("cgs.load(…)" / "cgs.merge(…)")`; page → Python: console messages `CGS:{"event": select | expand | link | ready | loaded | error, …}` read by `QWebEnginePage.javaScriptConsoleMessage`. Offline by construction: page CSP without any network source, Qt's off-the-record default profile, a `QWebEngineUrlRequestInterceptor` blocking every scheme other than `file`, `data`, `blob`, navigation refused elsewhere; no server, no port. Without WebGL (offscreen tests, very old GPU) the page still loads and answers, and says that 3D rendering is unavailable. `AA_ShareOpenGLContexts` is set before the `QApplication` is created, and the window is deleted before it.
- Inspector: read-only `QPlainTextEdit` + per-language `QSyntaxHighlighter` (rules provided by adapter; for keyword profile, keywords highlighted). If `SourceExcerpt.stale` is true: banner "This file has changed since analysis" and "Re-analyze" button.
- Paths: `cgs path` lists each step with its type (call, bridge, dispatch; dispatch steps flagged "possible"); in the window, "Paths to main" of the 3D graphs shows the paths from `main` to the selection.
- Background tasks (UI audit: no query on the GUI thread, including the lazy call tree; a project change drops late answers; Cancel kills the process tree and extraction workers exit with their parent): `QThreadPool` for queries; `QProcess` for inventory and analysis (the AI runs from `cgs complete` and `cgs ai-worker`, not from the window yet).
- Settings: `QSettings` in INI format, in the data folder (§3.14).
- **Groups and overview** (D23): `GraphQuery.groups(level)` computes the connected groups at query time (union-find over call edges `CALL_PATH`, or `file_edges`; about 1 s on Code_Aster, so no schema change); utility routines are left out when hidden, since they would glue unrelated programs together. `graph3d_overview(mode, max_nodes)` returns everything or the group spheres, `graph3d_group(id)` the content of a sphere (`group:<representative>`, `isolated:<level>`, `more:<level>:<offset>`), `non_code_files()` the non-code files recorded by the last analysis (scan statistics key `non_code`: exact counts per category, at most 5,000 paths). `Graph3DNode` gains `size` and `note`, `Graph3DLink` gains `cross_dir` (ends in different folders).
- **Standalone 3D window** (`ui/view3d/`, `cgs view3d`, optional): the same page in a **PyWebView** window running in its **own process** (PyWebView has its own GUI loop), for use outside the main window. Data: `GraphQuery.graph3d(root, mode=functions|files|both, depth, max_nodes)` — a bounded, deterministic neighbourhood (callers and callees) plus, in `both` mode, the files defining the routines (`defines` links) and the links between those files. The page is self-contained (vendored JavaScript, data inline) and carries a Content-Security-Policy forbidding every network access; there is **no HTTP server and no port** (`http_server=False`, file URL, `js_api` bridge). Right-click expands a node on demand (`View3DApi.expand`); a click prints one JSON line `{"event": "select", "uid": …}` on stdout. `--export page.html` writes the same page without a window.

**Workflow when opening a folder:** inventory → display languages, coverage and skipped folders → analysis (`cgs inventory`, then `cgs scan`, subprocesses; opening another project stops a running one) → `Functions 3D` and `Files 3D` open on the **overview of the whole project** (every node and link, or one sphere per group, D23), `main` being detected for "From main" and "Paths to main" → selecting a routine (search, file explorer, graph click) updates the hero card, the inspector and the Callers / Callees panel; a click on a sphere opens its group; right-click adds the neighbours of a node. The "Complete with AI" prompt of Lot 13 is available from the command line (`cgs complete`) and not yet in the window.

### 3.12. Graphical performance strategies (CPU only)

1. **Never the whole graph in UI:** only what is displayed, fetched from database.
2. **Precomputations during analysis:** caller/callee counts (raw and filtered), impact size, file and directory links (`file_edges`, `dir_edges`).
3. **Pagination:** 50 children per expansion in the tree list; at most 150 nodes added per right-click in the 3D graphs.
4. **Rendered node ceiling** (300 by default, configurable): a project above it is shown as one sphere per connected group (D23), a group above it is drawn up to the ceiling and flagged "limit reached".
5. **Aggregation levels:** functions and files views; groups of linked routines or files; isolated members and smaller groups gathered in buckets that open on demand.
6. **Hubs and data families hidden by default** in the graphs, with the hidden count shown.
7. **3D force layout** in the WebGL page (3d-force-graph), stopped after 6 s (`cooldownTime`) so that a modest CPU is not kept busy; the camera is fitted once the layout settles. The deterministic tree layout of `layout/tree.py` is no longer used by the UI (D21).
8. **Labels on hover only** (tooltips), no text sprites: the cost of a frame does not grow with label length.
9. **Lightweight rendering on large views:** a right-click adds at most 150 nodes and never goes past the node ceiling; directional particles only on bridges and bindings, and can be switched off.
10. **Unobtrusive analysis:** analysis in a separate process; extraction worker count = cores − 1 (configurable `jobs`); results written to the database once, at the end (atomic replacement for a full write, WAL for incremental). The process priority is not lowered.
11. **Partial analysis:** ability to restrict detailed analysis to specific directories (§3.3).

### 3.13. Local AI

**Status (October 17, 2026):** roles 1 and 2 are implemented (`codegraph_sci/ai/`, `cgs ai-worker`, `cgs complete`, `cgs ai-approve`) and tested with the **mock model** only; no real model has been benchmarked or bundled yet; role 3 is not started (Lot 15).

**Execution:** `cgs ai-worker` subprocess loading a GGUF model with `llama-cpp-python`, on CPU (threads = cores − 1), with 4 to 8k token context. JSON communication over stdin/stdout; streamed responses; zero temperature and fixed seed. Inference library selects CPU instruction set dynamically at startup (§2.2).

**Models:** strictly Apache 2.0 or MIT licensed, to be listed in `models.lock` (file, SHA-256, license; planned, Lot 15). Initial CPU candidates: Qwen2.5-Coder-1.5B-Instruct (Apache 2.0) and Phi-4-mini-instruct (MIT), Q4 quantized. Final choice decided on Lot 13 benchmark.

**Role 1 — Identify unknown languages (Lot 13)**

- Input, per group of unrecognized files: extension, file count, start of three sample files, list of already covered languages.
- Output (schema-constrained): language name, existing adapter to use, or keyword profile request; short rationale.
- Automated check: if an existing adapter is proposed, it must parse sample files without error and find definitions.

**Role 2 — Define missing keywords (Lot 13)**

The completion loop:

1. Initial analysis performed with current profile.
2. Diagnostic (`ai/diagnose.py`, `cgs ai-diagnose`, D35) deterministically classifies gaps: unknown language, known language without package, unsupported dialect, partial coverage (fallback extraction, keyword package without tests), repeated parser failures, unsupported binding mechanism. It also summarizes languages without adapter; unresolved sites grouped by pattern (same prefix, same source language, same files), with sample code lines; files with zero definitions found.
3. AI receives this summary (and user-provided technical document if present; a missing, unreadable or unsupported document (PDF without `pypdf`) is reported, never dropped silently) and fills a template: keyword language profile (§3.9) or bridge rule (`bridges` format, §3.8).
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

5. **Adoption (lifecycle of D35)**
   - **One lifecycle** for overrides, language packages, bridge rules and rule changes: `draft -> validated -> approved`, or `rejected`. Proposals are stored in `<project>/proposals/p-<n>.yaml` (content, checks, independent results, provenance: model, document reference and SHA-256, supporting passages, assumptions, examples; history). Generating, validating or rejecting never changes the active analysis and triggers no rescan.
   - **Default mode — explicit approval:** `cgs ai-proposals` lists them with the change preview; `cgs ai-approve <folder> p-<n>` activates a validated proposal (the only step that writes the profile or `rules/`), `--reject` rejects it; the next `cgs scan` applies it and never needs the AI.
   - **Language packages** are activated only through the rule workflow of D30, with test cases copied from expected results written independently of the AI (`cgs complete --expected <folder>`); matches of the proposed keywords are reported as a consistency check, never as a recall.
   - **Automatic mode**: only when the project policy is enabled (`cgs ai-policy <folder> --auto-approve on`, recorded in `ai_policy.yaml`); each automatic approval is recorded as `auto-policy` in the proposal history; links tagged "AI".
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
├── packs/                                domain packs shipped with the product (copied from packs/)
├── models/                               optional bundled .gguf model + license + provenance.json
├── licenses/                             LICENSE, NOTICE, LICENSING, COMMERCIAL_LICENSE, THIRD_PARTY_NOTICES
├── data/                                 projects and settings (portable mode)
└── README.txt
```

- **Two portable variants of the same software** (same features, D24): without a bundled model (about 620 MB measured with Qt WebEngine, D21; 129 MB in Lot 0 before it; a model can be added later) and with a bundled model (1 to 3 GB additional depending on model), built with `tools/build_portable.py --with-model`.
- **Two executables** sharing the same `_internal/` directory, produced by a single PyInstaller spec: desktop app and CLI.
- **Data location:** default on local disk (`~/.codegraph-sci/` on Linux, `%LOCALAPPDATA%\CodeGraph-Sci\` on Windows; `CGS_DATA_DIR` overrides it) because SQLite is slow on USB drives. "Portable mode" (`data/portable.flag`) writes to `data/` next to the app. Corpus audits use `<data>/audits/<corpus>` unless a project folder is given.
- **Build:** `tools/build_portable.py` (PyInstaller) produces the directory, archive, and SHA-256 hash, from an environment matching `requirements.lock` / `requirements-dev.lock` (refused otherwise). Linux: glibc 2.28 container (§2.2); Windows: CI Windows runner. Network is only used at build time; the finished folder is designed to work without network (C2) — its tests on machines without network are pending (Lot 16).
- **Bundled model:** the variant with a bundled model contains model file and license text, as required by Apache 2.0 and MIT (§7).

### 3.15. Technical choices and dependencies

| Component | Usage | License |
| :--- | :--- | :--- |
| Python 3.12 | Sole application language | PSF |
| PySide6 (Qt 6) | Desktop UI | LGPL-3.0 (obligations detailed in §7) |
| Qt WebEngine (part of PySide6, Chromium) | Embedded 3D graphs of the main window (§3.11, D21); about +300 MB in the portable folder | LGPL-3.0 (+ Chromium notices) |
| pywebview *(optional extra `view3d`)* + bottle, proxy_tools, pythonnet (Windows) | Standalone 3D window `cgs view3d` (§3.11), separate process, no server | BSD-3-Clause / MIT |
| 3d-force-graph 1.80.1 (bundles three.js r186) | 3D rendering, vendored in `ui/web/vendor/` with its licences (SHA-256 `13088340…23be9`) | MIT |
| py-tree-sitter + Fortran, C, C++, Python grammars | C and C++ parsers; Python 2 fallback; the Fortran grammar is only used by `cgs selftest` and the parser benchmark (D18) | MIT |
| `ast` (standard library) | Python 3 parser | PSF |
| sqlite3 + FTS5, `zlib`, `json` (standard library) | Project DB, full-text search, compressed cache | Public domain / PSF |
| In-house graph algorithms (`algo/`) | Iterative Tarjan, condensation, bitsets, bounded traversals | — (project code; NetworkX no longer needed) |
| PyYAML (`safe_load` only), jsonschema | Profiles, packs, and strict validation | MIT |
| fparser, LFortran *(Fortran benchmark candidates, Lot 4)* | Alternative Fortran parsers | BSD-3 |
| fxtran *(excluded from default distribution)* | Fortran parser, external tool only after license review | GPL-3.0 |
| PyInstaller (build only, `requirements-dev.lock`) | Portable folder bundling | GPL-2.0 with exception allowing proprietary distribution |
| llama-cpp-python *(Lot 13)* | CPU model execution | MIT |
| pypdf *(Lot 13)* | Parsing user-supplied technical docs | BSD-3 |
| pytest, pytest-qt, pytest-socket, hypothesis, ruff, mypy, import-linter | Development and testing | MIT / BSD / MPL-2.0 (hypothesis) |

Every new dependency must be vetted through this list and through license audit (Lot 16), and added to the locks (`tools/lock_dependencies.py --write`) and to `THIRD_PARTY_NOTICES.md` when redistributed. Exact versions: `requirements.lock`, `requirements-dev.lock` (D26).

### 3.16. Repository structure

```text
codegraph-sci/                         repository
├── README.md, CHANGELOG.md, AGENTS.md (Appendix C), CONTRIBUTING.md
├── LICENSE, NOTICE, LICENSING.md, COMMERCIAL_LICENSE.md, THIRD_PARTY_NOTICES.md
├── pyproject.toml
├── requirements.lock                  pinned runtime dependencies (tools/lock_dependencies.py; hashes added at release)
├── requirements-dev.lock              pinned build and development tools
├── models.lock                        approved models (Apache 2.0 / MIT) — planned (Lot 15), not created yet
├── Start_CodeGraph-Sci.bat            Windows launcher of the development environment
├── docs/
│   ├── architecture.md                this document
│   ├── licensing_strategy.md
│   ├── legal/                         drafts for legal review (not in force)
│   ├── packs/<code>.md                one file per analyzed codebase
│   ├── bench/                         parser benchmark (lot 4), scan benchmarks (cgs benchmark)
│   ├── validation/                    corpus validation reports with provenance
│   └── repository_migration_assessment.md
├── src/
│   └── codegraph_sci/                 the product (one package, D24)
│       ├── core/                      model, ids, facts, plugins, profile, project, paths, netguard
│       ├── algo/                      graph.py (Tarjan, condensation, impact), index.py
│       ├── inventory/                 walk, detect, extensions.yaml, profile schema and I/O, report, non-code files
│       ├── rules.py                   rule workflow (cgs rules), templates/rules/ (language, bridge, project)
│       ├── extract/                   fortran/  python/  c/  cpp/  keywords/, cfamily, cmacro, preproc,
│       │                              registry (language packages), languages/ (built-in package manifests)
│       ├── link/                      linker.py, externals.py, bridges/
│       ├── enrich/                    pack engine, noise, schemas/, generic_noise/, generic_fortran/
│       ├── store/                     schema.sql, indexes.sql, db.py, writer.py, cache.py, export.py
│       ├── query/                     api.py (GraphQuery), types.py
│       ├── layout/                    tree layout (not used by the UI since D21)
│       ├── audit/                     baseline, diff, sample, invariants, report, corpus expectations
│       ├── ai/                        models.py, worker.py, complete.py (local AI, §3.13)
│       ├── ui/                        app, main_window, shell, theme, graph3d_view, web/ (3D page), view3d/
│       ├── scan.py, extract_pool.py   analysis pipeline, extraction workers with per-file deadlines
│       ├── corpus_audit.py, benchmark.py
│       └── cli.py, cli_query.py, cli_ai.py, selftest.py
├── packs/<code>/                      domain packs shipped with the product (data, outside the core, rule 7)
├── tests/
│   ├── unit/
│   ├── ui/                            pytest-qt
│   ├── fixtures/<name>/               src/ + expected_inventory.json + expected_graph.json (incl. robustness/)
│   ├── synthetic/generate.py
│   ├── corpus/<code>/                 manifest.yaml + expectations.yaml (+ review sheets)
│   ├── ai/                            recorded mock model responses
│   └── portable/                      packaged-application checks (network, ports, glibc) — planned (Lot 16)
├── tools/
│   ├── check.py                       ruff + mypy + import-linter + pytest (network blocked)
│   ├── build_portable.py, lock_dependencies.py, prepare_corpus.py, bench_fortran.py
└── packaging/
    ├── codegraph_sci.spec, entry/
    ├── linux-glibc228.Containerfile
    └── README.txt                     read-me of the portable folder
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
- **Deliverables:** `link/` (per-language symbol table — case-insensitive for Fortran —, site resolution, `maybe_call` decision, generic interfaces, external and intrinsic symbols, lightweight out-of-scope definition index — OUTLINE extraction since D25 — and `out_of_scope` state); `algo/` (iterative Tarjan, condensation, bitset impact size, bounded traversals); Index step (aggregated edges, `node_stats`, `file_edges`, `dir_edges`, FTS5); `scan.py` (profile reading, parallelism, per-file timeout, cache key incorporating included files, JSON progress); `cgs scan <folder>` command.
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

### Lot 11 — Files and functions graph views (TreeGraph, replaced by 3D graphs)

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

### Lot 16 — Dual licensing, license compliance, and final release

- **Deliverables:**
  - one product package and one feature set (D24): licensing documents (`LICENSE`, `LICENSING.md`, `COMMERCIAL_LICENSE.md`, `NOTICE`, `THIRD_PARTY_NOTICES.md`); no license key, no activation, no feature gate;
  - **compliance as explicit task**: automated dependency license audit; Software Bill of Materials (SBOM); comprehensive `licenses/` directory (license texts and notices for every embedded component, Apache 2.0 `NOTICE` files, model license); Qt/PySide6 LGPL obligations (§7); verification that no GPL tool is bundled by default; review of analyzed code snippets in demos;
  - portable variants with and without a bundled model; Windows binary code signing.
- **Validation tests:** installation on clean networkless machines (Ubuntu 22.04 & 24.04, Windows 10 & 11, Rocky Linux 8 if available); zero network traffic or listening ports during analysis, UI navigation, and model inference, verified on distributed package; no license mechanism affects any functionality; compliance checklist fully verified.
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

**The manifest is authoritative** (`cgs audit corpus`, `codegraph_sci/corpus_audit.py`): the analysis profile of the
audit is rebuilt from the inventory of the sources and the manifest (scope, packs) — never taken from a user profile;
every required pack must load; when the sources are a Git checkout, the requested revision must be the commit or one
of its tags. The report (`--json`) records the SHA-256 of the manifest, the expectations and the audit profile, the
source revision (requested, commit, tags, verified), the tool version and the adapter and pack versions.

**Expectation states.** Each expectation ends `PASS`, `FAIL` or `SKIP`. Every expectation is required unless it says
`required: false`; a required expectation that cannot be evaluated (unsupported kind, query error) is a `FAIL` with its
reason; only an optional one may be `SKIP`. Exit codes: `0` every required expectation PASS, `1` a required FAIL, `2`
configuration error (manifest, expectations, sources, revision, packs), `3` internal audit error — never `0` when the
required validation did not run.

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
| Offline distributed app | On Linux, app launches and functions in network namespace (`unshare -n`); on Linux and Windows, zero listening ports during analysis, UI navigation, and inference — **planned (Lot 16), not run yet** |
| Safe loading | `yaml.safe_load` exclusively; YAML files with Python object tags rejected; strict schemas; zero `pickle` |
| Robustness | Malformed sources, very large files (beyond limit, analysis truncated and logged), tricky paths, symlink loops, unreadable files; per-file deadlines (blocked, slow, simultaneous and crashing extractors, `test_extract_timeouts`); random data sent to adapters (hypothesis fuzzing) without crashing |
| Inspector consistency | File modified after analysis flagged "stale" |
| Cache | Modifying an included file invalidates files that include it |
| Isolation | Zero pack-declared identifiers in core (§6.4) |
| Package dependencies | §3.4 rules enforced by import-linter |
| Performance | §1.3 targets measured with `cgs benchmark` on the synthetic repo and the starter corpus (`docs/bench/`) |
| Corpus audit | PASS/FAIL/SKIP and exit codes 0/1/2/3, manifest authority and provenance (`test_corpus_audit`) |
| Extraction modes | FULL in scope, OUTLINE outside, cache identity per mode, identical definitions, no call extraction in OUTLINE for every adapter (`test_outline_extraction`, `test_phase6_outline_modes`) |
| Repository hygiene | English-only project content (`test_english_only`), no control character in sources (`test_source_hygiene`), environment matching the locks (`test_dependency_lock`) |
| Licensing | All dependencies tracked in §3.15 list (automated audit in Lot 16) |

### 5.6. User scenarios

| # | Scenario | Expected outcome |
| :--- | :--- | :--- |
| S1 | Open multi-language folder, run inventory then analysis, cancel, re-run | Languages displayed with coverage; progress visible; clean cancellation; responsive UI |
| S2 | Search routine | "Called by N routines across M files"; double-click → code at call line |
| S3 | Functions 3D graph across 4 callee levels (right-click expansions) | Expansions in < 200 ms, each node drawn once |
| S4 | Files 3D graph of a file, then dive into routines | Weighted links, language colors, detailed calls on link click |
| S5 | Hide then reveal utilities | "+N" badge, decluttered graph |
| S6 | Path between two routines in different languages | Path listed with step types and dispatches marked "possible" (`cgs path`); in the window, "Paths to main" of the 3D graphs |
| S7 | Modify file, re-analyze | Re-analysis in < 30 s, views updated |
| S8 | Run application from USB drive with network disconnected | Boots and functions completely |
| S9 | Repository with unknown language; "Complete with AI" | Language identified, keyword profile proposed with effect preview; approved/rejected; links marked "AI" |
| S10 | Modify file without re-analyzing, open in inspector | Banner "This file has changed since analysis" and "Re-analyze" button |

---

## 6. Extensibility

### 6.1. Adding a language

0. **Language package (D29):** whatever the method below, the language ends up as a package (§3.7) placed in
   `<data dir>/languages/` (every project) or `<project>/rules/languages/` (one project): nothing in the core
   changes. `cgs languages` shows which package is selected.
1. **Via AI (fastest):** inventory flags unknown language; completion loop proposes keyword profile (§3.9), checked, previewed, and approved. Providing a technical document improves the proposal. Profile coverage is measured before reliance.
2. **Manually:** author keyword profile directly.
3. **Native adapter** (highest precision), if a permissive tree-sitter grammar exists: implement `LanguageAdapter` in a separately installed distribution that declares it in the entry point group `codegraph_sci.language_backends`, and describe it with a package whose backend is `native:<name>` (built-in adapters live in `extract/<language>/` with a manifest in `extract/languages/`); add extension mapping, create `tests/fixtures/<language>/`, declare subtypes, color, and syntax highlighting.

### 6.2. Adding a bridge

- Usually, a `bridges` entry with prefixes and name transforms suffices (§3.8): hand-crafted or AI-proposed, always with positive and negative tests.
- Otherwise, create `link/bridges/<bridge>/` implementing `Bridge`, with a two-language fixture; each produced site carries `origin = "bridge:<bridge>"`.

### 6.3. Adding a codebase

1. Author `docs/packs/<code>.md`: codebase architecture, conventions, rules, validation targets, license.
2. Run inventory, then AI completion loop; incorporate proposals into `rules.yaml` (§3.8); only add `enrich.py` if needed.
3. Declare both corpora (starter and full) with expectations, then assemble reference sample.
4. **Acceptance criteria:** expectations green, §2.1 metrics satisfied, zero regressions, core unchanged — or extended generically and documented here.
5. **Pack validation (D36):** like any project pack, the pack declares `validation` repositories (small, written for the pack, never copied from the code base) checked by `cgs rules test packs/<code>/rules.yaml`; the core is validated without any pack by the matrix of `tests/unit/test_phase10_generality.py`.

### 6.4. Isolation rule

The core (`src/codegraph_sci/`, excluding generic packs) contains zero identifiers specific to an analyzed codebase; domain packs live in `packs/<code>/` at the root of the repository or of the portable folder (D24). Each pack declares its `identifiers`; a test fails the build if they appear in core. Fixtures use neutral names. AI-proposed rules for a project reside in that project's folder, never in core.

---

## 7. Licensing constraints affecting code

- **Open source under GPL-3.0-or-later (D37)**, with a separate commercial license for uses the GPL does not allow (proprietary integration, redistribution under other terms). One product, one feature set: the commercial license grants rights, it does not unlock a different implementation (D24).
- **Dependencies:** strictly those in §3.15 or equivalent licenses (MIT, BSD, Apache 2.0, ISC, PSF, MPL-2.0 for test tools, LGPL with dynamically linked libraries); never GPL or AGPL imported by code or bundled by default (a GPL dependency would prevent the commercial license of D37). fxtran (GPL-3.0) can only be used as a separately installed external tool after license review.
- **PySide6 and Qt (LGPL-3.0):** keep Qt libraries as separate, replaceable files in `_internal/` (no static linking); provide LGPL text and Qt notices in `licenses/`; provide Qt and PySide6 sources used or written offer to provide them; do not restrict user replacement. This modularity is necessary but not sufficient: full checklist is audited in Lot 16.
- **AI models:** strictly Apache 2.0 or MIT. The variant with a bundled model includes the model file **and license text** (along with `NOTICE` file if present): redistribution requirement of these licenses.
- **Analyzed codebases:** exact revision and origin of any snippet in demos are recorded, with code license notice; no source code from analyzed codebases is bundled into commercial distribution without prior review.
- **User-supplied technical documents:** read locally, never copied into rules beyond brief rationale snippets.
- **External contributions:** Contributor License Agreement (CLA) signed prior to integration; the CLA text (or a DCO) is pending legal review, and external pull requests are not merged until then (`CONTRIBUTING.md`).
- **No license mechanism in the software** (D24): no license key, no activation, no telemetry; nothing in the code checks a license or changes a feature.
- Commercial and legal details: `LICENSING.md`, `COMMERCIAL_LICENSE.md`, `docs/licensing_strategy.md`; license texts and notices: `LICENSE` (GNU GPL v3, unmodified FSF text), `NOTICE`, `THIRD_PARTY_NOTICES.md`; contribution rights: `CONTRIBUTING.md`.

---

## 8. Decisions and open questions

### 8.1. Decisions made (D1–D18: October 16, 2026; D19–D26: during implementation, up to October 17, 2026)

| # | Decision |
| :--- | :--- |
| D1 | Desktop application Python + Qt (PySide6); no web application |
| D2 | Operating systems: Linux x86_64 (target: Ubuntu) and Windows x64 |
| D3 | Offline operation (no cloud service, analysed code never sent); full version transferable on USB drive |
| D4 | Modest machines, CPU only: graphical lightweighting mandatory |
| D5 | Deterministic graph for a given analysis profile; AI prepares profile, never intervenes during analysis |
| D6 | Default question: how many routines call a routine, and which ones |
| D7 | Two graph views: files and functions (3D since D21) |
| D8 | No compiler: validation without compilation, via verified samples (§2.1) |
| D9 | Dual license: GPL-3.0-or-later + commercial license, for the same software and features (D24, D37; PolyForm NC until D37) |
| D10 | Portable variant with a bundled model includes the model and its license — *hypothesis to confirm* |
| D11 | First test case mixes Fortran, Python, and C/C++: language inventory and four adapters starting in Lots 2–5 |
| D12 | *(updated in v7, to confirm)* AI identifies unrecognized languages and defines missing keywords; by default, user validates in one click after link preview; automatic adoption mode enabled per project |
| D13 | Plan contains only lots and dependencies, without milestones or calendar durations |
| D14 | Every observed call is preserved as a call site (one row in DB); edges aggregate sites |
| D15 | Linux build on glibc 2.28 base: compatible with Ubuntu 20.04+ and RHEL/Rocky 8+ |
| D16 | Graph algorithms written in-house (iterative Tarjan, bitsets); NetworkX removed |
| D17 | Fortran parser chosen via comparative benchmark on real files, among permissive candidates; fxtran (GPL-3.0) excluded from default distribution |
| D18 | *(Lot 4)* Main Fortran parser: **in-house logical statement analyzer** (fixed and free form, continuations, preprocessor branches preserved, exact positions). Benchmark on fixtures (`docs/bench/fortran_parsers.md`): only candidate with 100% recall and precision; tree-sitter-fortran fails on fixed form (text past col 72, `C`/`*` comments) and loses `#ifdef` branches; fparser fails on 4/23 files and is 25x slower; LFortran not evaluated (binary missing). Fallback and dual extraction: independent pattern extractor. **To confirm on real sample files from test case #1** (`python tools/bench_fortran.py <folder>`) |
| D19 | *(Lot 0)* Tree-sitter grammars: standalone wheels `tree-sitter-fortran`, `-python`, `-c`, `-cpp`; `tree-sitter-language-pack` ≥ 1.0 excluded because it downloads grammars at runtime (violates C2) |
| D20 | *(3D view)* 3D visualization with 3d-force-graph in a **PyWebView** window running in a separate process, without HTTP server or port, JavaScript vendored. **Streamlit rejected**: it is a web application serving on a local port (violates C1 and C2). QtWebEngine not used at the time (size): revised by D21 |
| D21 | *(3D in the main window)* The two 2D TreeGraphs (`QGraphicsView`) are **replaced** by two embedded 3D graphs (functions, files) drawn by the vendored 3d-force-graph page in a **`QWebEngineView`**: the user prefers the 3D display, and it fits in the current Qt UI, so **no web UI** is needed (C1 kept). Offline guarantees: CSP, off-the-record profile, request interceptor, no server, no port (C2). Cost: Qt WebEngine is now shipped in the portable build (about +300 MB). The PyWebView window of D20 remains as the optional `cgs view3d` command |
| D22 | *(UI look)* Dark & orange theme (`ui/theme.py`: palette, style sheet, icons painted with QPainter, no image file) and a frameless shell (`ui/shell.py`: title bar, resize margins, popovers, hero card) replacing the toolbar, menu and docks. Window move and resize go through the platform (`startSystemMove` / `startSystemResize`) |
| D23 | *(Whole-project view)* The 3D graphs open on an overview of everything: all nodes and links when they fit under the node ceiling, otherwise one sphere per connected group (separate or parallel programs), so that C4 still holds on large codes. Groups are computed at query time (fast enough, no schema change); non-code files come from the inventory and are stored in the scan statistics; links between folders are flagged |
| D24 | *(Single product)* CodeGraph-Sci is **one product, one source tree, one feature set**. The former `codegraph_sci_pro` package is merged: the local AI is `codegraph_sci.ai` (commands in `cli_ai.py`), domain packs are data in `packs/` at the root of the repository or of the portable folder (outside the core, rule 7). Free versus commercial use is a **licensing** distinction (open source license and separate commercial license, D37), never a technical feature gate: no license key, no activation, no telemetry. Supersedes the Pro separation of Lot 16 |
| D25 | *(Engine reliability, corrective audit P1)* (1) **FULL / OUTLINE extraction**: out-of-scope files are extracted for their definitions and includes only (the Fortran parser skips executable statements except SELECT CASE, whose values feed pack dispatch rules); the extraction mode is part of the facts (`extraction_mode`) and of the cache key, and an OUTLINE result is never reused as FULL. (2) **Per-file deadlines** in worker processes (`extract_pool.py`): a late file kills only its own worker and is stored as `timeout`; extraction never runs without a deadline (the deadline must be finite and positive since D27). Cost: about 0.6 s of worker start-up per analysis. (3) **Corpus audit**: PASS/FAIL/SKIP, exit codes 0/1/2/3, authoritative manifest and provenance |
| D26 | *(Reproducibility and measurement, corrective audit phase 4)* (1) **Dependency locks**: CI and releases install from `requirements.lock` / `requirements-dev.lock` (generated offline from the reference environment; hashes added at release time with network access), `build_portable` refuses a different environment. (2) **Phase instrumentation**: `phases_ms` and per-mode file counts in every scan, `cgs benchmark` (cold, unchanged and changed rescans); no performance claim without a documented benchmark (`docs/bench/scan_benchmark.md`). (3) **Reference categories** (`GraphQuery.reference_categories`, `cgs health`): every non-resolved site in one of external_known, out_of_scope, ambiguous, dynamic, parser_limitation, unknown — unverified externals are unknown, never known. (4) **Reproducible corpus**: `tools/prepare_corpus.py` fetches the exact revision named by the manifest; validation reports with provenance (`docs/validation/`) |
| D27 | *(Engine reliability, requirements plan phase 1, October 17, 2026)* (1) **Cache identity**: path, inventory language and variant, ordered include paths, recorded include lookups (replayed, so a new, shadowing or formerly missing header invalidates), effective Python module name, parser runtime versions, extraction mode, facts format 2 and identity version; a cached blob must belong to the same file; linking settings never invalidate extraction. (2) **Stable digests**: SHA-256 instead of Python `hash()` for keyword-profile versions and AI sample partitions. (3) **Deadlines**: workers acknowledge each task; the deadline runs from that acknowledgement, a result produced after it is refused, the deadline must be finite and positive (CLI and API; the in-process path is removed), a worker that cannot initialise stops the run. (4) **Cancellation**: checked up to the last moment before the database is published; a cancelled scan discards its partial results and leaves the previous database unchanged. (5) **Identity**: keyword identities qualified by scope and file (`kw:<language>:<qualified name>@<file>`), homonyms resolved as ambiguous; each definition node records `symbol_uid` and `occurrence_uid`, and a call is owned by the occurrence that contains it |
| D28 | *(Persistent inventory, requirements plan phase 2, October 17, 2026)* Discovery is separate from analysis selection: every discovered entry is stored (`inventory_entries`, schema 2) with eligibility, status and the reason it is not analyzed, and discovery problems are stored (`inventory_issues`). Policies `analysis` (default; an excluded folder is one counted entry) and `complete` (excluded content recorded, never read). Symbolic links leaving the root keep being followed (unchanged analysis), but are flagged. The previous `inventory` table and the skipped-folder report are unchanged; a database of schema 1 is rebuilt with its facts cache reused |
| D29 | *(Language packages, requirements plan phase 3, October 17, 2026)* One package contract for every language (keyword or native backend), one registry instead of hard-coded adapter lists, precedence builtin < user < project < explicit, explicit `overrides: true` to replace a package, and every ambiguous selection rejected with both files named. Native adapters stay deterministic parsers behind the contract; others are installed through the `codegraph_sci.language_backends` entry point group. Earlier keyword profiles remain valid packages. Behaviour changes: an approved package in `rules/languages/` is active without a profile entry (unless the profile marks it proposed or rejected); a package claiming an extension listed as known but not covered (e.g. `.jl`) now wins over that listing; a keyword profile for a built-in language is now an error instead of being ignored |
| D30 | *(Rule format and workflow, requirements plan phase 4, October 17, 2026)* Published schemas, templates, a guide whose tutorial is executed by the tests, and `cgs rules new|validate|test|activate`; layout `rules/languages|bridges|projects`; activation only after validation and at least one passing test; resource limits on configurable patterns and rule files. The existing AI approval path (`set_rule_status`) is unchanged and does not run tests yet (AI lifecycle, phase 9) |
| D31 | *(Bridges and evidence, requirements plan phase 5, October 17, 2026)* Native bridges declared in a catalog (mechanisms, evidence kinds, version); rule bridges gain `candidates`, `require_declaration`, `files`, `target_files`, `version`, `mechanism`; homonyms are kept as ambiguous candidates instead of the first being picked (rule bridges and declaration bindings); every bridge resolution stores its evidence (`call_sites.evidence`, schema 3) and the query layer exposes extraction rule, resolution rule, binding declaration, candidate selection and reason for every site. Native naming-convention bridges (Fortran decoration, C linkage) are kept, labeled as naming conventions; requiring declarations for them would change existing graphs and is left to the owner |
| D32 | *(FULL and OUTLINE in every adapter, requirements plan phase 6, October 17, 2026)* The OUTLINE contract of `ExtractContext.outline` is binding for every adapter: definitions (with their attributes and module context) and includes, no call analysis inside bodies, definitions identical to FULL. Python (ast and tree-sitter fallback), C/C++ (tree-sitter and pattern fallback) and keyword languages now skip the work instead of trimming it afterwards; cached facts are unchanged, so no adapter version changes. Measured on the synthetic code base: OUTLINE extraction 68–76 % of FULL |
| D33 | *(Dependency tables, requirements plan phase 7, October 17, 2026)* `GraphQuery.dependencies`, `dependency_groups` and `dependency_evidence`, `cgs deps` (CSV/JSON export) and the Explore › Dependencies view: every relationship occurrence with its own type (call, import, include, inherit, bridge, binding, binding declaration), filtered, sorted and paged in SQLite, aggregated per entity, file or directory with the occurrences reachable, each row leading to its source and evidence. No schema change: the table is a query over `call_sites` and `binds` edges |
| D34 | *(Interactive graphs, requirements plan phase 8, October 17, 2026)* Renderer-neutral `Graph3D` contract: nodes with group and scope, links with resolution status, `level` (entity, file, directory), `layout` description, and `GraphQuery.link_evidence` giving the dependency rows behind a link; `graph3d_directories` and the Folders 3D view; in the page: 2D/3D switch, reset, filters by link type, language, status and path, grouping by folder, language or module/class, cycles (strongly connected components) and entry points highlighted. A link click opens the same rows and evidence as the table. The renderer of D21 is kept |
| D35 | *(AI lifecycle, requirements plan phase 9, October 17, 2026)* One proposal lifecycle (draft, validated, approved or rejected) in a separate store; approval is the only activation and is explicit, or automatic only through a recorded project policy; the direct write of AI language overrides into the active profile is removed; language packages need independent expected results; deterministic diagnosis of six coverage gaps; documents carry their reference, passages and assumptions and their read failures are reported. Replaces the adoption step of D12 |
| D36 | *(Generality, requirements plan phase 10, October 17, 2026)* Code_Aster stays optional: its pack has the structure of any project pack (with a `validation` repository written for it) and no privileged activation; the regular CI runs an independent matrix of miniature fixtures (Python library without main, C, C++, Fortran, mixed-language bindings, keyword DSL) with the shipped packs hidden; `tools/check_wheel.py` builds the wheel offline and runs it outside the checkout. Domain packs remain data outside the wheel (D24) |
| D37 | *(Open source license, October 18, 2026)* The copyright holder relicenses CodeGraph-Sci under **GPL-3.0-or-later** (`LICENSE`: unmodified FSF text; `pyproject.toml`: SPDX expression), keeping the separate commercial license for uses the GPL does not allow (proprietary integration, redistribution under other terms). Chosen after a dependency audit: every redistributed component is MIT, BSD, PSF, MIT-0 or LGPL-3.0 (Qt, PySide6), all compatible; GPL-2.0-only excluded (Apache 2.0 parts bundled by PyInstaller); AGPL not needed for an offline desktop application. Internal use by companies becomes free; external contributions still require a CLA to keep the commercial path. Versions published before keep PolyForm Noncommercial 1.0.0. Supersedes the license part of D9 and D24 |

### 8.2. Open questions

1. Confirm D10, or prefer that customer places model in `models/` themselves.
2. Confirm D12 (one-click validation by default, automatic adoption as option).
3. ~~`generic_fortran` pack: in core or in Pro?~~ Resolved by D24: one product, every pack ships with it.
4. ~~AI identification and completion: Pro only, or basic version in core?~~ Resolved by D24: part of the product.
5. Official support for RHEL/Rocky 8, or Ubuntu only (build supports both)?
6. Test case #2: which codebase, and what new challenge should it exercise?
7. Is a Windows runner available for Lot 0 tests, or is a virtual machine required?
8. Trademark and name availability for "CodeGraph-Sci" (trademark, domain name, PyPI).
9. Legal review of the dual licensing (definitions of commercial use, CLA or DCO, LGPL and Chromium obligations, the Code_Aster lines quoted by the review sheets): checklist in `docs/licensing_strategy.md` §4.
10. Owner decisions listed in `docs/migration_report.md`: original root documents (`architecture_codegraph_sci_v7.md`, `pack_code_aster.md`, `strategie_licence.md`), tracking of the review sheets, commercial contact channel.

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
| v7 | **Integration of two external reviews:** call sites as ground truth and symbol identity (C++ signatures, `static` functions, variants); SQLite bulk writes, deferred indexing, atomic replacement, WAL for incremental; compressed JSON cache factoring in included files; local symbols and Fortran `name(...)` rule (included file and `COMMON` arrays, intrinsics); data at three precision levels; strict pack format spec and safe loading; explicit bridge prefix semantics and negative tests; partial analysis with `out_of_scope` state; separated metrics and stratified samples with confidence intervals, replayed reference sample; stop point at Lot 7; comparative benchmark of permissive Fortran parsers, fxtran (GPL-3.0) excluded by default; Linux build on glibc 2.28 and CPU AI compatible with older processors; NetworkX replaced by in-house algorithms; explicit edge kinds for paths; freshness check in inspector; one-click AI proposal validation by default; robustness, safe-loading, and network tests on distributed package; license compliance as explicit Lot 16 task |
| **v8** | **Updated to the implementation (October 17, 2026):** lot status column; 3D graphs in the main window replacing the TreeGraph (D21), dark & orange frameless shell (D22), whole-project overview by connected groups, links between folders and non-code files (D23); one product package with the local AI in `codegraph_sci.ai`, domain packs in `packs/`, dual licensing as a legal distinction only (D24); FULL/OUTLINE extraction, per-file deadlines in worker processes, corpus audit with PASS/FAIL/SKIP, exit codes and an authoritative manifest (D25); dependency locks, phase instrumentation and `cgs benchmark`, reference categories, reproducible corpus preparation and validation reports (D26); skipped-folder report and `all_subfolders`; precise offline wording; performance targets with their measured values; Query API, schema, facts, package rules, repository tree and agent rule 12 updated |

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
- **FULL / OUTLINE extraction:** complete facts for files in the analysis scope; definitions and includes only for the others (D25).
- **Group (3D overview):** set of routines or files linked to each other and to nothing outside the set; separate groups are separate or parallel programs (D23).
- **Reference category:** classification of a non-resolved reference site for reporting (§3.5, D26).
- **Dependency lock:** exact versions of the runtime and build dependencies (`requirements.lock`, `requirements-dev.lock`).
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
12. Every analyzed file has a deadline: it is extracted in a worker process that is killed beyond it, and the file is stored as `timeout`; a failure is logged, never blocking, and never affects another file.
13. The UI accesses data only through `GraphQuery`; no long-running query on the main thread.
14. Every AI feature must be testable with the mock model.
15. Typed Python 3.12 (`mypy` strict), formatted with `ruff`; identifiers, code, UI, comments, and documentation in English. English is the only project language even when instructions are given in another language: translate the intent, never copy the wording. Exceptions: analysed source code and fixtures that intentionally represent foreign-language code. Checked by `tests/unit/test_english_only.py`.
16. Every change must be coherent with the existing code, contracts and decisions, and must not degrade it (behaviour, precision, performance, determinism, readability): a fix comes with a non-regression test, and the whole check (`tools/check.py`) passes before and after. **When in doubt** (business or licensing choice, contract change, deletion of user material, effect on precision not measured), change nothing: report the point and the options to the user, and wait for their decision before modifying.

## Appendix D — Specified extraction conventions (Lot 3)

These conventions supplement §3.5 and §3.7; expected fixture graphs (`tests/fixtures/*/expected_graph.json`) follow them.

- **Additional identities:** Fortran module `fmod:<module>` (distinct from procedures, which may share name); derived type, generic interface, and internal procedure `f:<host>::<name>`; Python method `py:<module>.<Class>.<method>`, nested function `py:<module>.<func>.<inner>`; externals `ext:intrinsic:<name>`, `ext:libc:<name>`, `ext:python:<module>[.<name>]`, `ext:mpi:<name>`, `ext:blas:<name>`.
- **Nodes:** each source file has a `file:<path>` node; declarations (C/C++ prototypes, explicit/abstract `INTERFACE` blocks, pure virtual functions) do not create a definition. A file-level macro block (e.g. `PYBIND11_MODULE(...) { }`) is not a function: its calls have the file node as source.
- **Site location:** line and column (1-based) of the start of the target text as written (`target_text`): `ELEMK`, `c%area`, `self.check`, `ops::scale`. For a macro-hidden call, macro position and `target_text` = expanded called function. For an include, position of included filename; source is the file node.
- **Confidence:** `exact` = single target found by name; `resolved` = target selected by rule (receiver type, arity/argument types, `maybe_call` decided by Link, macro, preprocessor variants); `heuristic` = dynamic call (variable, `getattr`) or unresolved site; `ambiguous` = multiple candidates.
- **Preprocessor variants:** a call toward a routine defined across multiple variants (`f:x`, `f:x#2`) is `resolved` to the first, with all variants as candidates; an edge is created to each variant.
- **Conditions:** `#ifdef X` → `defined(X)`, `#ifndef X` / `#else` → `!defined(X)`, `#if E` → `E` (normalized spacing); nested conditions joined by ` && `.
- **Calls without static target:** procedure received as argument, procedure pointer, Python variable → `dynamic_call`, `unresolved` (or `resolved`/`heuristic` if simple propagation finds target, e.g. `h = getattr(m, "f")`).
- **Libraries:** Python call to module outside repo → `external` to `ext:python:…`; method call on unknown receiver with no method of that name in repo → `external` without target node. For reporting (§3.5), the first counts as `external_known` only for the Python standard library, the second as `dynamic` (Python) or `parser_limitation` (C/C++).
- **Edges:** `calls` (`call`, `maybe_call`, `dynamic_call` sites having a target, including `external`, `out_of_scope`, and each candidate of ambiguous site), `uses` (`use`, `include`), `inherits`, `implements` (generic interface → specific procedures, without site), `contains` (structure).
- **Bridges (Lot 8):** `binding` nodes extracted from sources — `bind:pybind11:<module>[.<name>]` (`PYBIND11_MODULE`, `m.def`), `bind:pyext:<module>[.<name>]` (Python C-API: `PyInit_<module>`, `PyMethodDef` tables), `bind:decl:<name>@<file>` (rule declaration patterns). A site resolved by a bridge preserves its `ref_kind` and takes origin `bridge:<bridge>` (`bridge:prefix_calls@<rule>` for profile rule) and `resolved` confidence; its edge is `binds` for `pybind11` and `python_extension` (Python → compiled code), `bridges` for `fortran_c`, `c_cpp`, and `prefix_calls`. A structural `binds` edge links each `binding` node to its implementation. Native bridges (`pybind11`, `python_extension`, `c_cpp`, `fortran_c`) are active by default; they act only on unresolved or external sites.
- **Packs (Lot 12):** additional format key `data: {fortran_common, fortran_module_variables}` (generic pack `generic_fortran`). New profiles enable `generic_noise` and `generic_fortran`. Rule templates: `catalogs[].entry`/`target` and `entry_points[].target`/`fallback_target` are `str.format` templates (entry fields, named regex groups, `{file_stem}`). Memory keys: literal object `data:mem:<name>`, local object `data:mem:<routine>:<name>` (`local_prefix_pattern`, priority over `literal`), symbolic `data:mem:<routine>:<expression>`, family `data:mem:*<suffix>` (hidden by default). An ambiguous site with > 8 candidates retains zero candidates (no edge).
- **Keyword languages:** profiles `rules/languages/<language>.yaml` (schema `extract/keywords/language.schema.json`), identities `kw:<language>:<name>`, origin `keywords:<language>`.
