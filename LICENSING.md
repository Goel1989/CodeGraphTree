# Licensing

> This page explains the licensing model in plain language. It is not legal advice and does not replace the license
> texts: `LICENSE` (GNU GPL version 3) and a signed commercial agreement prevail. The commercial policy below has
> **not yet been reviewed by legal counsel**; items marked *to be confirmed* may change.

## One software product, two licensing paths

CodeGraph-Sci is **open source software** and **one product with one source tree and one feature set**. Every user
receives the same source code and the same functionality. The two paths differ only in the **legal terms**:

| Path | Document | For |
| :--- | :--- | :--- |
| **Open source** | `LICENSE` — GNU General Public License, version 3 or (at your option) any later version (`GPL-3.0-or-later`) | Everyone, for any purpose, under the GPL terms |
| **Commercial** | `COMMERCIAL_LICENSE.md` and a separate agreement with the copyright holder | Uses that the GPL terms do not allow, such as distribution inside a proprietary product |

## Open source path (GPL-3.0-or-later)

Anyone may run, study, modify and share CodeGraph-Sci, **including for commercial purposes and inside a company**,
under the GPL. In short:

- running the software, privately or at work, imposes nothing;
- if you **distribute** the software, modified or not (including inside another program), you must do so under the GPL,
  with its corresponding source code, its license notices, and without adding restrictions;
- the software comes without warranty.

Read `LICENSE` for the exact terms.

## Commercial path

A commercial license is intended for organizations that cannot or do not want to follow the GPL terms, for example:

- integrating CodeGraph-Sci, or code derived from it, into a **proprietary product** distributed without its source
  code;
- redistributing it under other terms (for example with a vendor's own license);
- obtaining a warranty, an indemnity or contractual support (*to be confirmed after legal review*).

Commercial customers receive **the same software**, not a technically different edition. Support, maintenance,
integration, domain packs for in-house codes and training may be offered as services, to any user.

## Examples (intended policy, to be confirmed)

| Situation | Path |
| :--- | :--- |
| A student or a laboratory studies a Fortran code base | Open source (GPL) |
| An engineer of a company explores the company's solver at work | Open source (GPL): internal use is allowed |
| A consultant uses it to audit a client's code for a fee | Open source (GPL); support from the author is a separate service |
| A company publishes a modified version with its source code under the GPL | Open source (GPL) |
| A company ships it, or code derived from it, inside a closed-source product | Commercial |

## No license telemetry, no feature gating

- CodeGraph-Sci **never sends source code, analysis results or licensing data** to the copyright holder or to any
  remote service to validate a license. It has no license key, no activation and no license server.
- A commercial license grants **legal rights only**: it does not unlock a different implementation. No functionality
  depends on the license.

## Contributions

External contributions follow `CONTRIBUTING.md`, including its contribution-rights policy: offering the commercial
path requires the copyright holder to hold the rights needed to license every part of the software under both paths
(contributor license agreement, pending legal review).

## Earlier versions

Versions published before this change were offered under the PolyForm Noncommercial License 1.0.0; they keep that
license. The copyright holder, holding every right, relicensed the project under GPL-3.0-or-later (decision D37,
`docs/architecture.md`).

## Commercial contact

The official commercial contact channel is **to be announced by the copyright holder** and will be published in
`COMMERCIAL_LICENSE.md`. No personal contact information is stored in the software.

## Third-party components

Third-party software keeps its own license (see `THIRD_PARTY_NOTICES.md`). Every redistributed component is under a
license compatible with GPL-3.0-or-later (MIT, BSD, PSF, MIT-0, LGPL-3.0 for Qt and PySide6). Neither licensing path
changes the license of third-party components, of an optional local AI model, or of the code bases you analyse.
