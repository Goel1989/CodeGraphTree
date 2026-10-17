# CodeGraph-Sci — Licensing and Commercial Strategy

**Version:** 3.0 (October 18, 2026) — single product, open source under GPL-3.0-or-later with a commercial
license (decision D37); version 2.0 used PolyForm Noncommercial 1.0.0 for the community path (D24), version 1.1
(`strategie_licence.md`) described Free/Pro/Enterprise feature tiers and license keys  
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
| Everyone, for any purpose (students, researchers, public organizations, companies, consultants) | **GNU GPL v3 or later** (`LICENSE`, unmodified FSF text) | Run, study, modify and share; distributed versions stay under the GPL with their source code |
| Vendors integrating it into proprietary products, or needing other terms | **Commercial license** (`COMMERCIAL_LICENSE.md` + agreement) | Distribution without the GPL obligations, warranty and support as agreed |

**What this combination guarantees:**

- **Same software for everyone:** commercial customers do not receive a technically different edition; there is no
  license key, no activation, no feature gate and no license telemetry.
- **No third party may distribute the code in a proprietary product** without a commercial license; anyone may use
  it, and redistribute it under the GPL.
- **The author is the sole party able to sell commercial licenses** — provided the necessary rights are held for every
  contribution (§2.3).
- **The commercial license covers CodeGraph-Sci, not the AI model:** the agreement states it and references the
  Apache 2.0 / MIT license of any bundled model.

**Key considerations:**

- **Terminology.** GPL-3.0-or-later is an OSI-approved open source license: the project is described as **"open
  source (GPL-3.0-or-later), with a commercial license available"**. Avoid "Free", "Pro", "Community Edition" or
  "Enterprise Edition" when they would imply different functionality.
- **Business use.** Internal use by companies is free under the GPL; revenue comes from commercial licenses for
  proprietary integration and redistribution, and from services. Charging for internal use is not possible with an
  open source license; the earlier draft that aimed at it (`docs/legal/community_license_strict_DRAFT.md`) is obsolete.
- **Why GPL rather than AGPL or a permissive license.** CodeGraph-Sci is an offline desktop application, so the network
  clause of the AGPL adds little; a permissive license (MIT, Apache 2.0) would remove the reason to buy a commercial
  license. The GPL matches the scientific ecosystem (Code_Aster is GPL-3.0) and is compatible with every dependency
  (Qt and PySide6 under LGPL-3.0). GPL-2.0-only is excluded: it is incompatible with the Apache 2.0 parts bundled by
  PyInstaller.
- **Earlier versions.** Versions released under PolyForm Noncommercial 1.0.0 keep that license.

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
  after review); any new dependency under GPL/AGPL or a noncommercial license fails the build, because it would prevent
  the commercial license (the project's own GPL does not change this rule). The portable folder
  includes the license texts (`licenses/`).
- Model weight licenses are displayed in the UI and recorded with the model provenance (§2.7).

### 2.6. Offerings and Revenue Streams

- **Open source path:** free for everyone under GPL-3.0-or-later.
- **Commercial licenses:** for example per named user (consultants, small teams) or per site/team — the same software
  in every case; pricing and scope are set in the agreement.
- **Services:** support and maintenance contracts, version-maintained domain packs, custom domain packs for in-house
  solvers, integration (e.g. CI reports), legacy code audits and architecture mapping, training.
- **Evaluation:** not needed: anyone may evaluate the software under the GPL.

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

Exact copyright holder; relicensing of earlier PolyForm versions; scope of the commercial license (proprietary
integration, redistribution, derived works); patents; external contributions (CLA vs DCO: a CLA is required to keep
offering the commercial license); third-party dependency compatibility, including Qt/PySide6 under LGPL-3.0 inside a
commercially licensed product; local AI model licenses; governing law and jurisdiction; warranty disclaimer; limitation
of liability; commercial support and maintenance terms.
