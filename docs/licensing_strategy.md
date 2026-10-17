# CodeGraph-Sci — Licensing and Commercial Strategy

**Version:** 2.0 (October 17, 2026) — single product, dual licensing (decision D24); replaces version 1.1
(`strategie_licence.md`), which described Free/Pro/Enterprise feature tiers and license keys  
**Author:** Marian Bogdan Neagoe, PhD  
**Repository location:** `docs/licensing_strategy.md`

> This document is not used for day-to-day coding. Licensing constraints that affect the source code are summarized in
> `docs/architecture.md`, §7; the user-facing explanation is `LICENSING.md`. The commercial agreement, the CLA and
> evaluation terms must be reviewed by intellectual property counsel before the first commercial sale (§4).

---

## 1. Competitive Positioning

| Tool | Strengths | Limitations for our target |
| :--- | :--- | :--- |
| Doxygen / FORD | Free, Fortran call graphs, documentation | Unreadable static graphs at scale; no cross-language bridges; no codebase-specific data-flow semantics |
| SciTools Understand | Multi-language including Fortran, metrics, mature tool | General-purpose; ignores codebase-specific conventions; no local AI tailored to scientific computing |
| Sourcetrail (archived) | Excellent interactive exploration experience | Unmaintained, no Fortran support |
| CodeScene | Hotspots, Git history analysis | No cross-language call graph or scientific code semantics |
| Cloud AI assistants | Fluent explanations | Prohibited in many R&D/defense environments; structural hallucinations |

**Value proposition:** *trace a call from the user entry point down to the numerical kernel across all languages,
understand codebase-specific conventions through domain packs, and explain it locally — with source evidence for every
link.*

---

## 2. One Product, Two Licensing Paths

### 2.1. Decision

CodeGraph-Sci is **one product, one source tree, one feature set** (D24). Monetization is based on the legal right to
use the software commercially, and on services; it never depends on splitting the implementation.

| Audience | License | Rights |
| :--- | :--- | :--- |
| Students, researchers, educators, personal use, public research organizations, noncommercial organizations | **PolyForm Noncommercial 1.0.0** (`LICENSE`, unmodified standard text) | Use, study, modify and share for the purposes that license permits |
| Companies, engineering firms, paid consultants | **Commercial license** (`COMMERCIAL_LICENSE.md` + agreement) | Commercial use of the same software; services as agreed |

**What this combination guarantees:**

- **Same software for everyone:** commercial customers do not receive a technically different edition; there is no
  license key, no activation, no feature gate and no license telemetry.
- **No third party may resell or commercially exploit the code** without a commercial license.
- **The author is the sole party able to sell commercial licenses** — provided the necessary rights are held for every
  contribution (§2.3).
- **The commercial license covers CodeGraph-Sci, not the AI model:** the agreement states it and references the
  Apache 2.0 / MIT license of any bundled model.

**Key considerations:**

- **Terminology.** PolyForm Noncommercial is not an *open source* license under the OSI definition. The project is
  described as **"source-available, dual-licensed"**, never as "open source". Avoid "Free", "Pro", "Community Edition"
  or "Enterprise Edition" when they would imply different functionality.
- **Public research and noncommercial organizations.** PolyForm Noncommercial permits their use regardless of the
  source of funding.
- **Business use.** The intended policy is that any use by a for-profit business in its professional activities
  requires a commercial license. A stricter custom wording is kept as a draft for legal review
  (`docs/legal/community_license_strict_DRAFT.md`); it is not in force.
- **Corporate evaluation.** PolyForm Noncommercial does not cover commercial evaluation: a free, time-limited
  evaluation **agreement** (no key) can be offered (*to be reviewed*).
- **Future evolution.** Holding full rights, the author may later add an OSI-approved license (e.g. AGPLv3). Released
  versions remain usable under their original license.

### 2.2. Features

All features are part of the single product: language adapters and bridges, interactive exploration, search, paths,
impact, 3D views, noise filtering, generic packs and domain packs, local AI (identification, completion, explanations),
reports and future additions. Commercial value comes from the right to use them commercially and from services, not
from withholding them.

### 2.3. External Contributions

Dual licensing requires holding the necessary rights over all code. Every external contributor must sign a **CLA**
(Contributor License Agreement) — automatable via a GitHub bot — before any contribution (including adapters, bridges
or packs) can be merged. The CLA text, or the choice of a DCO instead, is pending legal review (`CONTRIBUTING.md`).

### 2.4. Analyzed Codebases and Test Corpora

- Analyzing a codebase modifies neither its license nor that of CodeGraph-Sci.
- Test corpora are **never committed** to the repository: only their manifests (local path, revision) are versioned
  (architecture, §5.4). The review sheets quoting single lines of a corpus are a legal-review item
  (`docs/repository_migration_assessment.md`).
- Any published demonstration containing excerpts from an analyzed codebase must comply with that codebase's license
  (e.g. GPL code → GPL demonstration with attribution, in a separate folder or repository). Each `docs/packs/<code>.md`
  specifies this.
- Names of analyzed codebases belong to their respective owners: nominative fair use ("compatible with …") without
  implying endorsement or partnership.

### 2.5. Third-Party Licenses

- `THIRD_PARTY_NOTICES.md` lists every redistributed component and its license (Python: PSF; PySide6 / Qt, including
  Qt WebEngine and Chromium: LGPL-3.0 and Chromium notices; tree-sitter and grammars: MIT; PyYAML, jsonschema: MIT;
  pywebview: BSD-3-Clause; PyInstaller bootloader: GPL-2.0 with bootloader exception; optional llama-cpp-python: MIT,
  pypdf: BSD-3-Clause). The reference list of dependencies is `docs/architecture.md`, §3.15.
- **fxtran is GPL-3.0**: never bundled in the default distribution; usable only as a separately installed external
  tool after license review.
- **PySide6 / Qt (LGPL-3.0)**: dynamically linked, replaceable libraries; license text and notices included; Qt and
  PySide6 source code or a written offer included (architecture, §7).
- **Automated check** (Lot 16): license audit of dependencies with an allowlist (MIT, BSD, Apache 2.0, ISC, PSF, LGPL
  after review); any new dependency under GPL/AGPL or a noncommercial license fails the build. The portable folder
  includes the license texts (`licenses/`).
- Model weight licenses are displayed in the UI and recorded with the model provenance (§2.7).

### 2.6. Offerings and Revenue Streams

- **Community path:** free for the uses permitted by PolyForm Noncommercial.
- **Commercial licenses:** for example per named user (consultants, small teams) or per site/team — the same software
  in every case; pricing and scope are set in the agreement.
- **Services:** support and maintenance contracts, version-maintained domain packs, custom domain packs for in-house
  solvers, integration (e.g. CI reports), legacy code audits and architecture mapping, training.
- **Evaluation:** free time-limited evaluation agreement for companies (*to be reviewed*).

### 2.7. Optional Bundled AI Model

- The portable variant with a bundled model (`tools/build_portable.py --with-model`) redistributes the model weight
  file; the software and its features are the same as without it.
- Apache 2.0 and MIT licenses permit redistribution provided the license text, author notices (and `NOTICE` file for
  Apache 2.0, if any) are included and trademarks are not misused. If quantized by the publisher, the modification is
  stated.
- The model's license continues to apply to the end user, which is why the "Apache 2.0 or MIT only" rule is to be enforced
  via `models.lock` (planned, Lot 15).
- Noncommercial models (e.g. Qwen2.5-3B and Qwen2.5-Coder-3B under the *Qwen Research* license) are never bundled or
  offered.

---

## 3. Compliance Without License Keys

Version 1.1 planned an Ed25519 license-key system (signed payload, offline activation, clock-rollback detection,
compiled Pro wheel). It is **withdrawn** (D24): CodeGraph-Sci has no license key, no activation, no feature gate and no
license telemetry. Target customers pay for legal compliance, support and updates; compliance is contractual
(agreement, licensee name in the agreement, audit clause if counsel recommends it). Nothing in the software checks a
license or sends data to the copyright holder.

---

## 4. Legal Review Checklist (before the first commercial release)

Exact copyright holder; definitions of "business", "commercial use", "for-profit entity" and "affiliate"; freelancers
and sole proprietors; non-profits; universities and laboratories funded by companies; consultants using CodeGraph-Sci
for clients; internal enterprise use; evaluation; redistribution and modifications; patents; external contributions
(CLA vs DCO); third-party dependency compatibility; local AI model licenses; governing law and jurisdiction; warranty
disclaimer; limitation of liability; commercial support and maintenance terms.
