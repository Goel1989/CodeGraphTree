# Licensing

> This page explains the intended licensing model in plain language. It is not legal advice and does not replace the
> license texts: `LICENSE` (community path) and a signed commercial agreement (commercial path) prevail. The commercial
> policy below has **not yet been reviewed by legal counsel**; items marked *to be confirmed* may change.

## One software product, two licensing paths

CodeGraph-Sci is **one product with one source tree and one feature set**. Every user receives the same source code
and the same functionality. The difference between free and paid use is a matter of **legal rights**, not of
features:

| Path | Document | For |
| :--- | :--- | :--- |
| **Community / non-commercial** | `LICENSE` — PolyForm Noncommercial License 1.0.0 (standard text, unmodified) | Uses that license permits |
| **Commercial** | `COMMERCIAL_LICENSE.md` and a separate agreement with the copyright holder | Commercial use of the same software |

## Community path

The community path is available **only for the uses permitted by `LICENSE`**. In short, that license covers any
noncommercial purpose, personal use for research, experiment, testing, study or hobby without any anticipated
commercial application, and use by charitable organizations, educational institutions, public research
organizations, public safety or health organizations, environmental protection organizations and government
institutions. Read `LICENSE` for the exact terms, including the notice, patent, violation and liability clauses.

## Commercial path

A commercial license is intended to be required for:

- use by a for-profit company as part of its business activities, including internal use (*to be confirmed after
  legal review*; a stricter draft of this rule is kept in `docs/legal/community_license_strict_DRAFT.md`);
- paid consulting or services delivered with CodeGraph-Sci;
- integration into a commercial product or service;
- commercial redistribution.

Commercial customers receive **the same software**, not a technically different edition. Support, maintenance,
integration and training may be offered as services.

## Examples (intended policy, to be confirmed)

| Situation | Path |
| :--- | :--- |
| A student studies a Fortran code base at home | Community |
| A university laboratory analyses its solver for a publication | Community |
| A public research organization uses it in a project funded by a company | Community (`LICENSE`, "Noncommercial Organizations") |
| An engineer of a company explores the company's solver at work | Commercial |
| A consultant uses it to audit a client's code for a fee | Commercial |
| A company ships it inside a paid product, or redistributes it for a fee | Commercial |

## No license telemetry, no feature gating

- CodeGraph-Sci **never sends source code, analysis results or licensing data** to the copyright holder or to any
  remote service to validate a license. It has no license key, no activation and no license server.
- A commercial license grants **legal rights only**: it does not unlock a different implementation. No functionality
  depends on the license.

## Contributions

External contributions follow `CONTRIBUTING.md`, including its contribution-rights policy: dual licensing requires the
copyright holder to hold the rights needed to offer every part of the software under both paths.

## Commercial contact

The official commercial contact channel is **to be announced by the copyright holder** and will be published in
`COMMERCIAL_LICENSE.md`. No personal contact information is stored in the software.

## Third-party components

Third-party software keeps its own license (see `THIRD_PARTY_NOTICES.md`). Neither licensing path changes the
license of third-party components, of an optional local AI model, or of the code bases you analyse.
