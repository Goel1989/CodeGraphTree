# Third-Party Notices

CodeGraph-Sci uses and, in its portable folder, redistributes the third-party components below. Each keeps its own
license; neither CodeGraph-Sci licensing path changes it. Versions are those of the reference environment
(October 2026); licenses were read from the installed package metadata and license files.

> Status: this inventory is complete for the current dependencies. Shipping the **full license texts** of every
> redistributed component in the portable `licenses/` folder, the LGPL source offer for Qt/PySide6 and an SBOM remain
> Lot 16 tasks (`docs/architecture.md`, §7), together with a legal review of the obligations below.

## Redistributed in the portable folder

| Component | Version | License | Notes |
| :--- | :--- | :--- | :--- |
| Python | 3.12 | PSF-2.0 | Embedded interpreter |
| PySide6, PySide6-Essentials, PySide6-Addons, shiboken6 | 6.12.0 | LGPL-3.0-only (also offered under GPL) | Used under LGPL-3.0: separate, replaceable dynamic libraries; Qt/PySide6 sources or a written offer must be provided |
| Qt 6 (bundled by PySide6), including Qt WebEngine | 6.12 | LGPL-3.0-only | Qt WebEngine bundles **Chromium** and its third-party components (BSD-3-Clause and others); their notices are shipped by Qt in `resources/` and `translations/qtwebengine_locales/` |
| PyYAML | 6.0.3 | MIT | |
| jsonschema | 4.26.0 | MIT | |
| jsonschema-specifications | 2025.9.1 | MIT | Dependency of jsonschema |
| referencing | 0.37.0 | MIT | Dependency of jsonschema |
| rpds-py | 2026.9.1 | MIT | Dependency of referencing |
| attrs | 26.1.0 | MIT | Dependency of jsonschema |
| typing_extensions | 4.16.0 | PSF-2.0 | Dependency of referencing |
| tree-sitter | 0.26.0 | MIT | |
| tree-sitter-fortran | 0.6.0 | MIT | Used by `cgs selftest` and the parser benchmark |
| tree-sitter-python | 0.25.0 | MIT | |
| tree-sitter-c | 0.24.2 | MIT | |
| tree-sitter-cpp | 0.23.4 | MIT | |
| 3d-force-graph | 1.80.1 | MIT | Vendored in `src/codegraph_sci/ui/web/vendor/` with its license text |
| three.js | r186 | MIT | Bundled inside 3d-force-graph; license text vendored |
| pywebview | 5.4 | BSD-3-Clause | Standalone 3D window (`cgs view3d`) |
| bottle | 0.13.4 | MIT | Dependency of pywebview |
| proxy_tools | 0.1.0 | MIT | Dependency of pywebview |
| pythonnet | 3.2.1 | MIT | Dependency of pywebview (Windows) |
| clr_loader | 0.3.1 | MIT | Dependency of pythonnet |
| cffi | 2.1.1 | MIT-0 | Dependency of clr_loader |
| pycparser | 3.11 | BSD-3-Clause | Dependency of cffi |
| SQLite | (Python stdlib) | Public domain | |
| PyInstaller bootloader | 6.22.3 | GPL-2.0 with bootloader exception | The exception allows distributing the frozen application under its own license; runtime hooks from pyinstaller-hooks-contrib are Apache-2.0 (legal review item) |

## Build and development only (not redistributed)

PyInstaller (GPL-2.0 with exception), pyinstaller-hooks-contrib (Apache-2.0 / GPL-2.0), altgraph (MIT), pefile (MIT),
pywin32-ctypes (BSD-3-Clause), setuptools (MIT), packaging (Apache-2.0 OR BSD-2-Clause), and the development tools of
the `dev` extra (pytest, pytest-qt, pytest-socket, hypothesis, ruff, mypy, import-linter, type stubs).

## Optional, not shipped by default

| Component | License | Notes |
| :--- | :--- | :--- |
| llama-cpp-python (llama.cpp) | MIT | Runs a local AI model when installed |
| pypdf | BSD-3-Clause | Reads PDF documents given to the AI |
| Local AI model (`.gguf`) | Apache-2.0 or MIT only (`models.lock`, planned) | When a model is bundled, its license text and any `NOTICE` file are shipped with it; models under noncommercial licenses are never bundled |
| fxtran | GPL-3.0 | Never bundled; usable only as a separately installed external tool after license review |

## Analysed code bases

Code bases analysed by CodeGraph-Sci keep their own licenses. No analysed source code is redistributed with the
product. The manual review sheets of `tests/corpus/code_aster_start/review/` quote single lines of Code_Aster
(GPL-3.0) for verification purposes; their status is a legal-review item
(`docs/repository_migration_assessment.md`).
