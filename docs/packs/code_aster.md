# Test Case #1 — Code_Aster (Domain Pack `code_aster`)

**Repository location:** `docs/packs/code_aster.md`  
**Pack:** `code_aster` (domain pack shipped with the product, `packs/code_aster/`)  
**Document version:** 0.2 (October 16, 2026) — incorporates two external reviews  
**Reference codebase version:** 17.5.7 (checks in §10)  
**Status:** starter corpus 17.5.7: 16/16 expectations (`docs/validation/code_aster_start.md`); precision and recall not measured yet (manual review pending).

> **This file is codebase-specific.** It is only used when working on the `code_aster` pack and its corpora. Nothing below may appear in the core (`src/codegraph_sci/`): the isolation rule in `docs/architecture.md` (§6.4) applies strictly. If a rule cannot be expressed in the generic pack format (`docs/architecture.md`, §3.8), extend the pack format **generically**, never the core for a single codebase.

---

## 1. Why This Test Case

Code_Aster is an open-source finite element solver (under GPL) that combines, in a single repository, all the challenges targeted by CodeGraph-Sci:

- all four languages supported in v1 (Python, C++, C, Fortran) and their cross-language bridges;
- realistic scale (~18,000 files and subroutines);
- an in-house memory manager (JEVEUX) whose objects are named at runtime, and global arrays (`zr`, `zi`…) whose accesses look syntactically like function calls;
- number-based and catalog-driven dispatchers (elementary routines, constitutive laws);
- ubiquitous utility routines that make raw call graphs unreadable;
- a large regression test suite linked to user commands.

---

## 2. Codebase Layers and Exercised Capabilities

| Layer | Directory | Language | Exercised CodeGraph-Sci Capabilities |
| :--- | :--- | :--- | :--- |
| Commands and orchestration | `code_aster/` | Python | Python adapter; `entry_points` capability (command catalogs) |
| Bindings | `bibcxx/` | C++ | C++ adapter; `pybind11`, `python_extension`, `prefix_calls` bridges |
| C interface layer | `bibc/` | C | C adapter; `fortran_c` bridge; `external_symbols` (MED, HDF5, MPI) |
| Numerical kernels | `bibfor/` | Preprocessed Fortran 90 (`.F90`) | Fortran adapter (local symbols, included headers); `noise`, `extraction`, `memory_access`, `dispatch` capabilities |
| Catalogs | `catalo/` (declarative Python) or `.cata` | Python / text | `catalogs` capability, `enrich.py` |
| Regression tests | `astest/` | `.comm` command files | `tests` capability |

---

## 3. Pack Rules

### 3.1. Utility Routines (Noise)

- **Hidden by default:** `jemarq`, `jedema`, `utmess`, `assert` (`ASSERT` macro), `infniv`.
- **Optional hiding:** `jeexin`, `jelira`, `dismoi`, `getv*`, and `rcvalb` / `rcvala` (heavily called material property lookups).
- `jeveuo`, `wkvect`, `jecreo`, `jedetr` are not merely hidden: they are **converted into data accesses** (§3.3).
- Automatic hub detection (`generic_noise`) recovers most of this list automatically.

### 3.2. JEVEUX Global Arrays: `zi`, `zr`, `zc`, `zl`, `zk8`, `zk16`, `zk24`, `zk32`, `zk80`

- Legacy access to JEVEUX objects uses these global arrays: `zr(iad + k)`. Syntactically, this looks like a function call.
- They are declared in an included header (`#include "jeveux.h"`) as `COMMON` blocks. The generic architecture rule (§3.7: array declared in an included file or `COMMON` block → data access) handles them automatically as long as `jeveux.h` is resolved via the profile include paths.
- Safety net if the header declaration is unavailable: `extraction.known_arrays` in the pack (§4).
- **Why not simply hide them as noise:** hiding only hides nodes in the UI, whereas false call sites would remain in the graph and distort fan-in/fan-out counts, impact size, and paths. No call site may be created for them.
- Verifiable expectation: zero call sites targeting `f:zr`, `f:zi`… (§5).

### 3.3. JEVEUX Memory Manager: Three-Level Object Precision

- **Access:** `call jeveuo(name, mode, ...)` with `mode = 'L'` (read) or `'E'` (write).
  - Legacy form: `call jeveuo(name, 'L', iad)` followed by `zr(iad)`, `zi(iad)`…
  - Modern form: `call jeveuo(name, 'E', vr=ptr)` using Fortran pointers (`vr=`, `vi=`, `vk8=`…).
- **Creation / destruction:** `wkvect`, `jecreo`, `jecrec` → `creates`; `jedetr` → `destroys`.
- **Object names:** keeping only the suffix (`.VALE`) would merge every field across the entire solver into a single unusable hub node. We therefore apply the three precision levels from the architecture (§3.5), in order:

| Level | Example | Handling |
| :--- | :--- | :--- |
| `literal` | Full string literal in code, e.g. `'&&OP0070.XXXX'` | Exact object; the `&&` prefix denotes a routine-local work object (`local_prefix_pattern: "^&&"`) |
| `symbolic` | `nomsd(1:19)//'.VALE'` | Preserved expression, scoped to the routine |
| `family` | `*.VALE`, `*.DESC`, `*.REFE`… | Object family, always recorded alongside; treated as a hub and hidden by default in TreeGraph views |

- Intermediate local variables (`vale = cham//'.VALE'` followed by `jeveuo(vale, ...)`) are tracked via simple local string propagation in the generic facts.
- **Out of scope for v1:** interprocedural string flow across routine arguments.

### 3.4. Dispatchers and Catalogs

- **Elementary routines:** option evaluation goes through `calcul`, which loops over element groups and calls `te0000`, which dispatches to `te0xxx` routines via `SELECT CASE`.
- **Constitutive laws:** `lc0000` dispatches to `lc0xxx` routines.
- **Catalogs:** declarative Python modules in `catalo/cataelem/` map `(option, element_type)` to `te` numbers.
- The pack is **versioned per Code_Aster release** (`covers` key).

### 3.5. Entry Points: User Commands

- A command (e.g. `STAT_NON_LINE`) declared in a Python command catalog with an operator number (`op=70`) is linked via `implements` to Fortran routine `op0070`.
- **Not all commands have a Fortran operator:** in recent versions, some commands are orchestrated in Python (`MACRO(`) before calling deeper Fortran routines. In that case, the entry point links to its Python implementation (`fallback_target`).
- Nodes `entry:<COMMAND>` (`kind: entry_point`, `subtype: command`) serve as natural starting points for user exploration.

### 3.6. Cross-Language Bridges

- **C/C++ → Fortran:** interface macros `CALLO_<ROUTINE>` / `CALL_<ROUTINE>`.
  - Semantics: `CALLO_JEVEUO(...)` → strip prefix (`JEVEUO`) → lowercase → target `f:jeveuo`.
  - Prefixes are matched longest-first: `CALLO_` before `CALL_`.
  - `DEFS*` macros **declare** Fortran-callable C functions: they create `binding` nodes, never call sites.
- **Python → C++:** compiled extension module `libaster` → `bridges` entry with `extension_modules`.
- **Fortran interfaces:** `#include "asterfort/<routine>.h"` header files.
- **Preprocessor:** configuration macros such as `ASTER_HAVE_MPI`; both branches are kept and call sites are annotated with their condition.

### 3.7. External Constitutive Laws (MFront)

- Constitutive laws generated in C++ by MFront and called from Fortran produce `bridges` edges when the generated code is present in the analyzed repository.

### 3.8. Regression Tests (`astest/`)

- `.comm` files: used commands → entry points → reachable routines (static over-approximation).
- Optional `gcov` / `lcov` coverage import for exact mapping.
- Key question answered: **"which regression test cases should be re-run after modifying `mmbouc`?"**

---

## 4. `rules.yaml` Draft (Format Version 1)

```yaml
pack: code_aster
version: "0.2"
format_version: 1
covers: { code_aster: ">=16" }
identifiers: [jeveuo, jemarq, jedema, utmess, wkvect, te0000, lc0000, rcvalb,
              libaster, bibfor, bibcxx, bibc, astest, asterfort, CALLO_]
detect:
  all_path: ["bibfor/", "bibcxx/", "code_aster/"]
noise:
  hide: [jemarq, jedema, utmess, assert, infniv]
  optional: [jeexin, jelira, dismoi, "getv*", rcvalb, rcvala]
  auto_detect_hubs: { min_fan_in: 300, max_fan_out: 3 }
extraction:
  known_arrays: [zi, zr, zc, zl, zk8, zk16, zk24, zk32, zk80]
memory_access:
  - { routine: jeveuo, name_arg: 1, mode_arg: 2, modes: { "L": reads, "E": writes },
      object_key: [literal, local_prefix, symbolic, family], local_prefix_pattern: "^&&" }
  - { routine: wkvect, name_arg: 1, effect: creates,
      object_key: [literal, local_prefix, symbolic, family], local_prefix_pattern: "^&&" }
  - { routine: jecreo, name_arg: 1, effect: creates,
      object_key: [literal, local_prefix, symbolic, family], local_prefix_pattern: "^&&" }
  - { routine: jedetr, name_arg: 1, effect: destroys,
      object_key: [literal, local_prefix, symbolic, family], local_prefix_pattern: "^&&" }
dispatch:
  - { routine: te0000, select_on: "numc", target_pattern: "te{case:04d}" }
  - { routine: lc0000, select_on: "numlcEff", target_pattern: "lc{case:04d}" }
entry_points:
  - kind: command
    glob: "code_aster/Cata/Commands/*.py"
    pattern: 'nom\s*=\s*"(?P<name>\w+)".*?op\s*=\s*(?P<op>\d+)'
    multiline: true
    target: "f:op{op:04d}"
    fallback_target: "py:code_aster.Commands.{name_lower}"
bridges:
  - { from: cpp, to: fortran, call_prefixes: ["CALLO_", "CALL_"], name_transform: [strip_prefix, lowercase] }
  - { from: cpp, to: fortran, declaration_patterns: ['DEFS\w*\(\s*(?P<name>\w+)'] }
  - { from: python, to: cpp, extension_modules: [libaster] }
tests:
  - { kind: regression_case, glob: "astest/*.comm", uses_entry_points: true, coverage: optional }
glossary: glossary_code_aster.md
```

---

## 5. Corpora and Expectations

Two corpora, as specified in the architecture (§5.4): a **starter corpus** whose expectations are scoped to its subset of directories, and a **full corpus** for end-to-end paths.

### 5.1. Starter Corpus (Lot 7)

```yaml
# tests/corpus/code_aster_start/manifest.yaml
corpus: code_aster_start
source: { path: "<local source path>", revision: "<exact reference tag>" }
license: GPL-3.0
packs: [code_aster]
scope: ["code_aster/", "bibcxx/", "bibc/", "bibfor/nonlinear/", "bibfor/cont_algo/", "bibfor/cont_defi/"]
# the rest of the repository is indexed (definitions only): calls outside the scope are marked out_of_scope
```

```yaml
# tests/corpus/code_aster_start/expectations.yaml
inventory:
  languages: { fortran: { min_files: 100 }, python: { min_files: 10 }, cpp: { min_files: 10 }, c: { min_files: 1 } }
  max_unknown_rate: 0.01
expect:
  - node: "f:mmbouc"
  - node: "f:nmstat"
  - hidden: "f:utmess"
  - hidden: "f:jemarq"
  - no_call_to: ["f:zr", "f:zi", "f:zc", "f:zl", "f:zk8", "f:zk16", "f:zk24", "f:zk32", "f:zk80"]
  - writes: { routine: "f:nmstat", data: "data:mem:*.VALE", key_kind: family }
  - out_of_scope_allowed: ["f:op*", "f:te*", "f:lc*"]
metrics:
  min_recall_definitions: 0.99
  min_recall_call_sites: 0.97
  min_precision_resolved: 0.98
  min_precision_lower_bound: 0.95
  max_unresolved_rate: 0.02
  max_parse_failure_rate: 0.02
```

### 5.2. Full Corpus (Lot 14)

```yaml
# tests/corpus/code_aster_full/manifest.yaml
corpus: code_aster_full
source: { path: "<local source path>", revision: "<same exact tag>" }
license: GPL-3.0
packs: [code_aster]
scope: ["."]
```

### 5.3. Reference Sample

Manually verified links and locations (~150 per language, plus a "bridges" group) are saved in `reference_sample.yaml` for each corpus with the exact code revision, and replayed automatically.

### 5.4. AI Completion Test (Architecture Lot 13)

Remove the prefix `bridges` entry from the pack and run the completion loop. Expected:

- the AI proposes the `CALLO_` / `CALL_` prefixes with `strip_prefix` + `lowercase` transformation;
- the proposal passes all automated verification gates, including negative tests;
- it resolves at least 80% of unresolved C++ → Fortran calls.

---

## 6. Walkthrough Scenario

- **Starter scope (Lots 7 to 11):** `code_aster/`, `bibcxx/`, `bibc/`, `bibfor/nonlinear/`, `bibfor/cont_*` — Python, C++, C, and Fortran identified by inventory.
- **Walkthrough:** language inventory, exploration around `nmstat` and `mmbouc`, noise filtering (before / after), absence of false calls to `zr` / `zi`, analysis health.
- **After Lots 8 and 14:** full path `STAT_NON_LINE` → leaf Fortran routine, JEVEUX accesses by precision level, associated regression test cases.

---

## 7. License and Trademark

- Code_Aster is distributed under GPL by EDF. Analyzing it poses no licensing issue for CodeGraph-Sci.
- **Demonstrations:** exact source revision recorded; provenance of every excerpt (file, line, revision) recorded; excerpts accompanied by the Code_Aster license notice; published under GPL with attribution in a separate folder/repository.
- **No Code_Aster source code** is included in any commercial distribution of CodeGraph-Sci.
- The Code_Aster name belongs to EDF: nominative fair use ("compatible with Code_Aster"), without implying endorsement.

---

## 8. Validation Checklist

1. Reference version: v16, v17, or both.
2. Declaration of `zi`, `zr`, `zc`, `zl`, `zk8`… in `jeveux.h` (`COMMON` block) and corresponding include path.
3. Work object naming pattern (`'&&<ROUTINE>.xxx'`) and reliability of the `&&` prefix as a local-object marker.
4. `op=NN` → `op00NN` mapping, supervisor role, and commands without a Fortran operator.
5. Role of `calcul`, selection variables, and actual targets of `te0000` and `lc0000`.
6. Catalog format for the selected version (`catalo/cataelem/` in Python or `.cata`) and `enrich.py` implementation.
7. Exact form of `CALLO_` / `CALL_` / `DEFS*` macros and name transformation to Fortran routines; negative test identifiers.
8. `asterfort/<routine>.h` interface headers as signature sources.
9. Compiled Python extension module name (`libaster`) and command catalog locations.
10. Final list of noise routines (including `rcvalb` / `rcvala`), compared against automatic hub detection.

---

## 9. Codebase Glossary

- **JEVEUX:** Code_Aster memory and named-object manager (vectors, collections, databases).
- **`zi`, `zr`, `zk8`…:** global arrays used for address-based access to JEVEUX object contents (legacy style).
- **SD:** Code_Aster data structure, a set of JEVEUX objects sharing a common name prefix.
- **`te0xxx` / `lc0xxx`:** elementary routines (finite element computations) / constitutive law integration routines.
- **`op0xxx`:** Fortran routines implementing user operators (commands).
- **`.comm`:** command file for a study or regression test case.

---

## 10. Verifications on Version 17.5.7 (October 16, 2026)

- **`zr`, `zi`… arrays:** declared in `jeveux.h` (`COMMON` blocks); zero call sites created (`no_call_to` expectation verified).
- **`jeveuo`:** modes `'L'` (522 calls in `bibfor/nonlinear`) and `'E'` (185).
- **Dispatchers:** `te0000` selects on `numc` (`select case (numc)`, 600 branches); `lc0000` selects on `numlcEff`.
- **Commands:** `code_aster/Cata/Commands/*.py`, form `NAME = OPER(nom="NAME", op=70, …)`; macro commands without a Fortran operator (`MACRO(`) link to `code_aster/CodeCommands/<file>.py`.
- **C/C++ → Fortran bridges:** `CALL_X` / `CALLO_X` macros are `#define`s in `bibc/include/aster_fort_*.h` expanding to `F_FUNC(X, x)` → `x_`; Fortran-callable C functions are declared via `DEFS…(X, x, …)`. Generic C macro expansion in the core plus the `fortran_c` bridge handle v17 directly; the prefix rule remains in the pack for builds without headers.
- **`mmalgo`** was replaced in v17; the starter corpus expectation uses `mmbouc` (contact loop).
- **`libaster`:** pybind11 module defined by `PYBIND11_MODULE(libaster, mod)` in `bibcxx/PythonBindings/LibAster.cxx`.
