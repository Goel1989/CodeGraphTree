# Code_Aster Glossary (`code_aster` pack)

Domain vocabulary provided to the local AI (explanations, Lot 15). Generic terms only, without source code excerpts.

- **JEVEUX**: Code_Aster memory manager; objects are named by character strings (e.g. `<sd>.VALE`) and accessed via `jeveuo` (`'L'` read, `'E'` write), created by `wkvect`/`jecreo`/`jecrec`, and destroyed by `jedetr`.
- **`zi`, `zr`, `zc`, `zl`, `zk8`… `zk80`**: global arrays (`COMMON` blocks from `jeveux.h`) providing address-based access to JEVEUX object contents.
- **Work object `&&…`**: temporary JEVEUX object local to a routine.
- **Data Structure (SD)**: collection of JEVEUX objects sharing a prefix (field, matrix, result…); suffixes such as `.VALE`, `.DESC`, `.REFE`… denote its components.
- **`opXXXX`**: Fortran routine implementing an operator (user command), e.g. `op0070` for `STAT_NON_LINE`.
- **`te0000` / `teXXXX`**: dispatch to elementary routines (computing an option on a finite element type).
- **`lc0000` / `lcXXXX`**: dispatch to constitutive law routines.
- **Computation option**: name of an elementary computation (e.g. `RIGI_MECA` for mechanical stiffness).
- **Test case**: command file (`.comm`) in the `astest/` validation suite.
- **`CALL_X` / `CALLO_X`**: C/C++ macros that call Fortran routine `x`; **`DEFS…`**: macros that define a C function callable from Fortran.
- **`libaster`**: compiled Python extension module (pybind11) exposing the C++ core to the `code_aster/` Python layer.
- **`UTMESS`**: user message emission (info, warning, error); **`ASSERT`**: internal assertion check.
