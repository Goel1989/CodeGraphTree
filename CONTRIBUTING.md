# Contributing to CodeGraph-Sci

## Language: English only

English is the only language of the project, whatever language the instructions or discussions use. Source code,
identifiers, comments, docstrings, messages, logs, CLI commands, options and help, UI labels, configuration and schema
keys, database names, documentation, tests, reports, branch names, commit messages and release notes are written in
English. When an instruction is given in another language, translate its **intent**; never copy its wording into the
repository.

Exceptions: code bases analysed by CodeGraph-Sci keep their original language, and test fixtures that intentionally
represent foreign-language source code may keep it (their surrounding test names, comments and expected messages stay
English). Do not add a translation of the product: if localization is ever added, English stays the default locale and
translations live in dedicated resources. `tests/unit/test_english_only.py` checks project-owned files.

## Coding rules

Read `AGENTS.md` and `docs/architecture.md` before changing the code. In particular:

- one lot or one topic at a time, tests written before the code that makes them pass;
- respect the contracts and the package dependencies (`import-linter`); record any contract change in
  `docs/architecture.md`;
- determinism, no network access, no open port, no runtime network dependency;
- no codebase-specific identifier in `src/codegraph_sci/` (domain knowledge goes into packs, under `packs/`);
- every change coherent with the existing code and without degradation; when in doubt, ask before changing (rule 16);
- one product, one feature set: never add a license check, edition flag or feature gate.

Run the whole check before proposing a change:

```bash
.venv/Scripts/python tools/check.py
```

Use small, thematic commits with English messages.

## Contribution rights

CodeGraph-Sci is dual-licensed (`LICENSING.md`). The copyright holder must therefore hold, for every contribution,
the rights needed to offer it under both the community license and commercial licenses.

- External contributions require a signed **Contributor License Agreement (CLA)** before they can be merged.
- The CLA text, and the choice between a CLA and a Developer Certificate of Origin, are **pending legal review**.
  Until the CLA is published, external pull requests cannot be merged; issues and bug reports are welcome.
