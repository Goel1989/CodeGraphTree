# CodeGraph-Sci — Licensing and Commercial Strategy

**Version:** 1.1 (October 16, 2026) — updated from architecture v4 for the offline portable edition and v7  
**Author:** Marian Bogdan Neagoe, PhD  
**Repository location:** `docs/strategie_licence.md`

> This document is not used for day-to-day coding. Licensing constraints that affect the source code are summarized in `docs/architecture.md`, §7. The commercial agreement, CLA, and evaluation terms should be reviewed by intellectual property counsel prior to the first commercial sale.

---

## 1. Competitive Positioning

| Tool | Strengths | Limitations for our target |
| :--- | :--- | :--- |
| Doxygen / FORD | Free, Fortran call graphs, documentation | Unreadable static graphs at scale; no cross-language bridges; no codebase-specific data-flow semantics |
| SciTools Understand | Multi-language including Fortran, metrics, mature tool | General-purpose; ignores codebase-specific conventions; no local AI tailored to scientific computing |
| Sourcetrail (archived) | Excellent interactive exploration experience | Unmaintained, no Fortran support |
| CodeScene | Hotspots, Git history analysis | No cross-language call graph or scientific code semantics |
| Cloud AI assistants | Fluent explanations | Prohibited in many R&D/defense environments; structural hallucinations |

**Value proposition:** *trace a call from the user entry point down to the numerical kernel across all languages, understand codebase-specific conventions through Domain Packs, and explain it locally — with source evidence for every link.*

---

## 2. Dual-Licensing and Monetization Strategy

### 2.1. Decision: PolyForm Noncommercial + Commercial Dual License

| Audience | License | Rights |
| :--- | :--- | :--- |
| Students, researchers, educators, personal use, public research organizations | **PolyForm Noncommercial 1.0.0** (`LICENSE` file) | Use, study, modify, and share free of charge for noncommercial purposes |
| Companies, engineering firms, paid consultants | **Commercial License** (`COMMERCIAL_LICENSE.md` + contract) | Commercial use of the core, Pro/Enterprise extensions, support |

**What this combination guarantees:**

- **Zero royalties** to model authors: only Apache 2.0 / MIT models are used and distributed with their license in the AI edition (§2.7).
- **No third party may resell or commercially exploit the code** without a commercial license.
- **The author is the sole party able to sell commercial licenses** — provided 100% of copyright is held: every external contribution must be covered by a CLA (§2.3), otherwise it cannot be included in the commercial edition.
- **The commercial license covers CodeGraph-Sci code, not the AI model:** the contract states this explicitly and references the Apache 2.0 / MIT license of the bundled model.

**Key considerations:**

- **Terminology.** PolyForm NC is not an *open source* license under the OSI definition, which excludes commercial-use restrictions. The project must be described as **"source-available, dual-licensed"** rather than "open source".
- **PolyForm NC public research exception.** Public research organizations, educational institutions, and government agencies may use the core free of charge regardless of funding source. Proprietary Pro extensions remain paid products.
- **Corporate evaluation.** Because PolyForm NC does not permit commercial evaluation of the core, a **free 30-day evaluation license** is provided (standard Ed25519 key, §3).
- **Future evolution.** Holding full rights (via the CLA), the author may later add an OSI-approved open source license (e.g. AGPLv3) if desired. Previously released versions remain usable under their original license.
- **Legal review.** Commercial agreement, CLA, and evaluation terms should be reviewed by IP counsel before the first sale.

### 2.2. Feature Breakdown

| Feature | Community | Pro | Enterprise |
| :--- | :---: | :---: | :---: |
| Python, C, C++, Fortran adapters; core bridges | ✓ | ✓ | ✓ |
| Interactive exploration, search, paths, impact | ✓ | ✓ | ✓ |
| Manual noise filter + automatic hub folding (`generic_noise`) | ✓ | ✓ | ✓ |
| HTML / SVG export | ✓ | ✓ | ✓ |
| Generic Fortran data flows (`generic_fortran`) *(TBD)* | — | ✓ | ✓ |
| Official version-maintained Domain Packs for public codes | — | ✓ | ✓ |
| Local AI engine, summary cards, document RAG | — | ✓ | ✓ |
| Architecture reports (Markdown / PDF) | — | ✓ | ✓ |
| Advanced metrics, Git hotspots | — | ✓ | ✓ |
| Local MCP server *(TBD)* | — | ✓ | ✓ |
| Custom packs for in-house codes (declarative format) *(TBD)* | — | — | ✓ |
| CI integration: architecture diff, merge-request reports | — | — | ✓ |
| Support | Community | Email | Contractual, version-maintained packs |

### 2.3. External Contributions

Dual licensing requires holding rights over all core code. Every contributor must sign a **CLA** (Contributor License Agreement) — automatable via a GitHub bot — before any external contribution (including adapters, bridges, or community packs) can be merged.

### 2.4. Analyzed Codebases and Test Corpora

- Analyzing a codebase modifies neither its license nor that of CodeGraph-Sci.
- Test corpora are **never committed** to the repository: only their manifests (local path, revision) are versioned (architecture, §5.4).
- Any published demonstration containing excerpts from an analyzed codebase must comply with that codebase's license (e.g. GPL code → GPL demonstration with attribution, in a separate folder/repository). Each `docs/packs/<code>.md` specifies this.
- Names of analyzed codebases belong to their respective owners: nominative fair use ("compatible with …") without implying endorsement or partnership.

### 2.5. Third-Party Licenses

- `THIRD_PARTY_LICENSES.md` registry generated automatically (Python: PSF; PySide6 / Qt: LGPL-3.0; tree-sitter and grammars: MIT; PyYAML, jsonschema: MIT; llama.cpp / llama-cpp-python: MIT; pypdf: BSD-3; cryptography: Apache-2.0 / BSD; PyInstaller: GPL-2.0 with bootloader exception). The reference list is maintained in `docs/architecture.md`, §3.15.
- **fxtran is GPL-3.0**: it is never bundled in the default distribution; it may only be invoked as a separately installed external tool after license review.
- **PySide6 / Qt (LGPL-3.0)**: dynamically linked, replaceable libraries, license text and notices included, Qt/PySide6 source code or written offer included (architecture, §7).
- **Automated CI check** (`pip-licenses`) with an allowlist (MIT, BSD, Apache 2.0, ISC, EPL-2.0, LGPL after review): any new dependency under GPL/AGPL or a noncommercial license fails the build. The portable distribution bundles these libraries and includes their license texts (`licenses/` directory).
- Model weight licenses are displayed in the UI and recorded alongside model provenance (§2.7).

### 2.6. Offerings and Revenue Streams

- **Community:** free for all noncommercial use (PolyForm NC).
- **Pro:** annual subscription per named user — consultants, small teams.
- **Enterprise:** site or team license, contractual support, version-maintained packs, custom packs, CI integration.
- **Services:** custom Domain Pack for an in-house solver, legacy code audit and architecture mapping delivered with report, training.
- **Evaluation:** 30-day Pro evaluation key issued by the same mechanism (§3).

### 2.7. AI Model Bundled in the AI Edition

- The AI portable edition bundles the model weight file and therefore **redistributes** the weights.
- Apache 2.0 and MIT licenses permit redistribution provided the license text, author notices (and `NOTICE` file for Apache 2.0, if any) are included and trademarks are not misused. If quantized by the publisher, the modification is stated.
- The model's license continues to apply to the end user, which is why the "Apache 2.0 or MIT only" rule is enforced via `models.lock`.
- Noncommercial models (e.g. Qwen2.5-3B and Qwen2.5-Coder-3B under the *Qwen Research* license) are never bundled or offered.

---

## 3. Cryptographic License Key System (Ed25519)

### 3.1. Realistic Goal

In a Python application, no software lock is unbreakable: a determined user can patch the check. Target customers (large enterprises, defense, energy) pay for **legal compliance, support, and updates**, not because of a technical lock. The system therefore aims to:

- make compliant use effortless, even on air-gapped workstations;
- make non-compliant use visible;
- **never penalize an honest customer.**

### 3.2. Signed Payload

```json
{
  "v": 1,
  "kid": "2026-A",
  "license_id": "L-2026-0042",
  "licensee": "ACME Aero — Structures Dept.",
  "tier": "enterprise",
  "features": ["packs", "ai", "reports", "ci"],
  "seats": 10,
  "window_start": "2026-11-01",
  "window_end": "2026-11-08",
  "duration_days": 365,
  "issued_at": "2026-10-30"
}
```

- Compact serialization (canonical JSON or CBOR) + Ed25519 signature (64 bytes), encoded in Crockford Base32 in groups of 5 with checksum: `CGWIN-XXXXX-XXXXX-…`. Also deliverable as a **license file**.
- `kid` identifies the signing key: the software embeds multiple public keys, allowing **key rotation** without invalidating existing licenses.

### 3.3. Offline Activation

- Activation window (`window_start` → `window_end`) and post-activation duration (`duration_days`).
- No hardware fingerprinting by default: seat count (`seats`) is governed by contract, and **the licensee's name is displayed** in the UI and watermarked in exported reports.
- For customers requiring node-locking: **offline challenge-response** binding.
- Renewal: simply enter a new key, 100% offline.

### 3.4. Clock Rollback: Tolerant Detection

- Local *high-water mark* (most recent observed timestamp) stored with a **tolerance** (e.g. 48 h) for time zones, DST changes, and NTP drift.
- **Scanned file modification times (`mtime`) are never used as a lock criterion:** archive extractions, `cp -p`, NFS mounts, and CI caches legitimately produce "future" timestamps.
- On inconsistency: warning, followed by a grace period (e.g. 14 days) prompting for a new key; **never** blocks the core or causes data loss.

### 3.5. Revocation and Private Key

- Offline revocation is impossible → favor 1-year terms with renewal.
- Ed25519 private key stored off any network-connected development machine (hardware token or encrypted vault), with offline backup.
- The key-generation script lives in a **separate private repository**, never in the public repository tree.

### 3.6. Pro Code Distribution

- Private repository `codegraph-sci-pro`, distributed as a **compiled wheel** (Cython or Nuitka) to protect pack know-how.
- Loaded by the core via Python entry points (`codegraph_sci.plugins`); the core runs standalone without it.
