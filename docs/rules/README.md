# Writing analysis rules

This guide explains how to describe a language, a cross-language bridge or the conventions of a code base, how to
test them, and how to activate them. Rules are plain data (YAML and JSON): they never execute code. Everything
here works offline and without the AI.

## 1. Where rules live

Rules belong to a project folder (the folder that holds `analysis_profile.yaml` and `project.sqlite`):

```text
<project>/rules/
  languages/
    <language>/
      language.yaml                 language package (package format 1)
      tests/
        basic.source                a representative source file
        basic.expected.json         what the package must extract from it
  bridges/
    <bridge>.yaml                   bridge rule (bridge format 1)
    tests/<bridge>_basic/           a small repository that uses the bridge
    tests/<bridge>_basic.expected.json
  projects/
    <pack>.yaml                     project pack (pack format 1): conventions of one code base
    tests/<pack>_basic/             a small repository that follows the conventions
    tests/<pack>_basic.expected.json
```

A language package can also be installed for every project in `<data dir>/languages/` (user level).

Schemas, all versioned:

| Rule | Schema |
| --- | --- |
| Language package | `src/codegraph_sci/extract/language_package.schema.json` (keyword rules: `extract/keywords/language.schema.json`) |
| Bridge rule | `src/codegraph_sci/enrich/schemas/bridge_rule.schema.json` (the rule itself: `pack.schema.json`, `$defs/bridge`) |
| Project pack | `src/codegraph_sci/enrich/schemas/pack.schema.json` (architecture §3.8) |

## 2. Workflow

| Step | Command | Result |
| --- | --- | --- |
| Create | `cgs rules new language <name> <repository> [--project P] [--extension .ext]` (also `bridge`, `project`) | A rule from its template, with one passing test case, status `proposed` |
| Validate | `cgs rules validate <rule file>` | YAML syntax, schema, pattern limits and declared test files; errors name the file, the key and the value |
| Test | `cgs rules test <rule file>` | Each test case: `PASS`, or `FAIL` with every missing and unexpected fact |
| Activate | `cgs rules activate <rule file>` | Validates, runs the tests (at least one, all must pass), checks that the selection stays unambiguous, then approves |

Exit codes: `0` success, `1` invalid rule or failing test, `2` usage error. A rule that is not activated is never
used by an analysis. Activation records a line in the profile history. `cgs languages <repository>` shows the
language package selected for each language (built-in < user < project) and the inactive ones.

## 3. Tutorial: a language package from scratch

We describe *minilang*, a small scripting language stored in `.mini` files. Create these three files in
`<project>/rules/` (or start from `cgs rules new language minilang <repository> --extension .mini` and replace
its content).

<!-- file: languages/minilang/language.yaml -->
```yaml
# minilang: language package written from the guide (docs/rules/README.md).
package_format: 1
language: minilang
version: "1.0"
status: proposed
description: Small scripting language with modules, procedures and includes.
extensions: [".mini"]
backend: keywords
rules:
  case_sensitive: false
  comments: {line: ["//"]}
  strings: ['"']
  definitions:
    - {keywords: ["module"], name: after_keyword, end_keywords: ["endmodule"], kind: module}
    - {keywords: ["def"], name: after_keyword, end_keywords: ["enddef"], kind: routine}
  calls:
    - {keywords: ["invoke"], name: after_keyword}
    - {style: name_then_paren, only_known_names: true}
  includes:
    - {keywords: ["include"], target: after_keyword}
naming:
  case_sensitive: false
  qualification: lexical
relationships: [calls, maybe_calls, includes]
resolution:
  confidence: heuristic
  capabilities: [names]
limitations:
  - "Procedures are found by keyword: no types, no overloads, scopes limited to the nesting of definitions."
tests:
  - {source: tests/basic.source, expected: tests/basic.expected.json}
provenance:
  source: manual
  document: "minilang reference card"
```

The test source exercises every rule, including the traps (a keyword inside a comment and inside a string):

<!-- file: languages/minilang/tests/basic.source -->
```text
include shared
// invoke ignored: comments are blanked before matching
module tools
  def trim
  enddef
endmodule
def setup
enddef
def run
  invoke setup
  log("invoke ignored inside a string")
  total = measure(3)
enddef
def measure
enddef
```

The expected result lists every definition and every reference, with its source coordinates:

<!-- file: languages/minilang/tests/basic.expected.json -->
```json
{
 "definitions": [
  {"name": "trim", "kind": "routine", "line_start": 4, "line_end": 5, "parent": "tools"},
  {"name": "tools", "kind": "module", "line_start": 3, "line_end": 6, "parent": null},
  {"name": "setup", "kind": "routine", "line_start": 7, "line_end": 8, "parent": null},
  {"name": "run", "kind": "routine", "line_start": 9, "line_end": 13, "parent": null},
  {"name": "measure", "kind": "routine", "line_start": 14, "line_end": 15, "parent": null}
 ],
 "references": [
  {"from": null, "target": "shared", "kind": "use", "line": 1, "col": 9},
  {"from": "run", "target": "setup", "kind": "call", "line": 10, "col": 10},
  {"from": "run", "target": "log", "kind": "maybe_call", "line": 11, "col": 3},
  {"from": "run", "target": "measure", "kind": "maybe_call", "line": 12, "col": 11}
 ]
}
```

Then:

```bash
cgs rules validate <project>/rules/languages/minilang/language.yaml
cgs rules test <project>/rules/languages/minilang/language.yaml
cgs rules activate <project>/rules/languages/minilang/language.yaml
```

A repository file to analyze with it (here `src/app.mini` in the repository):

<!-- file: src/app.mini -->
```text
include tools
def main
  invoke start
  report(1)
enddef
def start
enddef
def report
enddef
```

`cgs scan <repository> --project <project>` now reads `.mini` files: `main` calls `start` and `report`. The order of
definitions in the expected file does not matter; every entry must match exactly.

## 4. How keyword extraction works

**Definition matching.** A definition starts on a line whose first word is one of the `keywords` of a
`definitions` entry, followed by a name (`name: after_keyword`): letters, digits, `_` and `.`. It ends on the next
line whose first word is one of the `end_keywords` of any definition rule (the innermost open definition is
closed). `kind` is `routine`, `module` or `type`. A definition still open at the end of the file is closed there
and reported as an extraction error.

**Name and scope capture.** Definitions nest: a definition opened inside another one is qualified by its parents
(`tools.trim`), and its node identity is `kw:<language>:<qualified name>@<file>`. With `case_sensitive: false`,
names and keywords are compared in lower case (the display name keeps the spelling). Two definitions with the same
qualified name in one file get `#2`, `#3`. Calls are linked by name; a name defined in several files is
`ambiguous`, with every candidate kept.

**Call versus declaration detection.** A line that opens a definition is never a call. A call is either a keyword
followed by a name (`calls: [{keywords: [...], name: after_keyword}]`, reference kind `call`) or, with
`style: name_then_paren`, a name followed by `(` (reference kind `maybe_call`). With `only_known_names: true` a
`maybe_call` becomes a call only if a definition of that name exists; otherwise it is dropped, so array accesses or
built-in functions do not become false calls. Definition and call keywords are never taken as call names.

**Comments and strings.** Line comments (`comments.line`), block comments (`comments.block`, pairs of start and end
markers) and string contents (`strings`, up to three characters per quote) are replaced by spaces before any
matching. Positions do not move, so coordinates stay exact. Escaped quotes inside strings are handled.

**Imports and includes.** An `includes` entry reads the word after its keyword (letters, digits, `.`, `/`, `-`,
optionally quoted) and records a `use` reference from the file. It is linked to a file of the same language whose
name without extension matches; the result is a `uses` edge between files. Includes are never expanded.

**Source coordinates.** Every reference keeps its file, line and column (1-based, the first character of the name
as written) and its kind; definitions keep their first and last lines. Expected test results compare exactly these
values, so a change of coordinates is a failing test.

**Backend limitations.** Keyword extraction is heuristic: links carry the confidence `heuristic`. It does not know
types, overloads, scopes other than nesting, preprocessors, or calls through variables. When a language needs
them, use a parser-backed backend (section 8).

## 5. Expected results

Language test (`*.expected.json` next to the source):

| Key | Content |
| --- | --- |
| `definitions` | `name`, `kind`, `line_start`, `line_end`, `parent` (name of the enclosing definition, or `null`) |
| `references` | `from` (name of the enclosing definition, `null` at file level), `target` (as written), `kind` (`call`, `maybe_call`, `use`), `line`, `col` |
| `allow_errors` | optional, `true` to accept extraction errors (unclosed definitions) |

A section left out is not compared. Repository test (bridges and project packs): `edges` that must exist and
`absent_edges` that must not, each `{"src": <uid>, "dst": <uid>, "kind": <edge kind>}`. Every bridge needs a
negative case (`absent_edges`): an identifier that looks like the prefix but must not be linked.

## 6. Bridges

`cgs rules new bridge <name> <repository>` writes `rules/bridges/<name>.yaml`:

```yaml
bridge_format: 1
name: c_to_fortran
version: "1.0"
rule:
  from: c
  to: fortran
  call_prefixes: ["CALL_"]
  name_transform: [strip_prefix, lowercase]
tests:
  - {repo: tests/c_to_fortran_basic, expected: tests/c_to_fortran_basic.expected.json}
provenance: {source: manual}
```

`rule` has the format of a `bridges[]` entry of a pack (architecture §3.8): `call_prefixes` (tried longest first),
`name_transform`, `declaration_patterns` (they create binding nodes, never calls), `extension_modules`, and:

| Key | Meaning |
| --- | --- |
| `candidates` | `keep_ambiguous` (default): several targets make an ambiguous site with every candidate; `unique`: link only a single target |
| `require_declaration` | `true`: link a prefix call only if a `declaration_patterns` match names its target (needs `declaration_patterns`) |
| `files`, `target_files` | globs of the caller files, and of the files targets may come from |
| `mechanism` | a short label of the documented mechanism (for example `wrapper macro`), shown in the evidence |

Each resolved site records its evidence: the rule and its version, the mechanism (`prefix_call`, or
`declaration_macro` when a declaration names the target), the binding declaration, the transformed name, the
candidate selection and the reason (`cgs callees` shows the mechanism and the declaration; `--json` and
`cgs export json` give the whole evidence). Each repository test is
scanned with this rule alone. Activation adds the rule to the profile (`rules:`, approved).

## 7. Project packs

`cgs rules new project <name> <repository>` writes `rules/projects/<name>.yaml`, a pack (architecture §3.8:
noise, known arrays, memory access, dispatch, catalogs, entry points, bridges, tests) with a `validation` list of
repository tests. The `pack` key must match the file name. Activation adds the pack to the profile (`packs:`).

## 8. Native backends

A language that needs a real parser is described by a package whose `backend` is `native:<name>`, without
`rules`. The adapter is Python code implementing `LanguageAdapter` (architecture §3.7), installed as a separate
distribution that declares it in the entry point group `codegraph_sci.language_backends`. YAML never names a
module or a function: the package only refers to the installed backend by name.

## 9. Resource limits and safety

- Rule files are read with `yaml.safe_load` and validated against their schema; tags that build objects are refused.
- A rule file is at most 1 MiB.
- Keyword lists hold at most 200 words of at most 64 characters (letters, digits, `_`); they are matched as literal
  words, never as regular expressions.
- Configurable regular expressions (pack `entry_points[].pattern`, `memory_access[].local_prefix_pattern`, bridge
  `declaration_patterns`) are at most 500 characters, must compile, and may not use backreferences or nested
  quantifiers such as `(a+)+`, the constructs that make matching time explode.
- Extraction runs in worker processes with a per-file deadline; a file that exceeds it is recorded as `timeout`.
