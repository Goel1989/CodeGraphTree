"""Declared bridge mechanisms (requirements plan phase 5).

Every bridge declares its languages, binding mechanism, matching conditions, name transformation, module or file
constraints, candidate-selection policy, the evidence it relies on, and its identifier and version. A site resolved
by a bridge records the mechanism that matched (``CallSiteRecord.evidence``), so the reason of every
cross-language link can be shown.

Evidence kinds:

* ``binding_declaration``: the source declares the binding (``BIND(C, NAME=...)``, ``m.def`` of pybind11, a
  ``PyMethodDef`` table, a declaration macro of a rule);
* ``naming_convention``: a documented compiler or linker convention relates the two names (Fortran name
  decoration, C linkage of C++ declarations); it is used only when exactly one target exists;
* ``rule``: an explicit project rule (call prefix and name transformation).
"""

from __future__ import annotations

from dataclasses import dataclass

NATIVE_VERSION = "1.0"


@dataclass(frozen=True)
class Mechanism:
    name: str
    evidence: str  # binding_declaration, naming_convention, rule
    description: str


@dataclass(frozen=True)
class BridgeSpec:
    id: str
    version: str
    source_languages: tuple[str, ...]
    target_languages: tuple[str, ...]
    mechanisms: tuple[str, ...]
    matching: str
    transform: str
    constraints: str
    candidates: str  # unique, keep_ambiguous
    description: str


MECHANISMS = {m.name: m for m in (
    Mechanism("bind_c_name", "binding_declaration",
              "C name given by BIND(C, NAME=...) on a Fortran procedure or interface"),
    Mechanism("trailing_underscore", "naming_convention", "Fortran name decoration: lower case plus one underscore"),
    Mechanism("g77_double_underscore", "naming_convention",
              "g77 decoration: two underscores when the Fortran name contains one"),
    Mechanism("uppercase_name", "naming_convention", "Fortran name decoration in upper case, without underscore"),
    Mechanism("same_name", "naming_convention", "Fortran call to a C function of the same lower-case name"),
    Mechanism("c_linkage_same_name", "naming_convention",
              "C and C++ share the symbol of a function with C linkage (extern \"C\")"),
    Mechanism("pybind11_module", "binding_declaration", "PYBIND11_MODULE declares a Python extension module"),
    Mechanism("pybind11_def", "binding_declaration", "m.def(\"name\", &function) binds a Python name"),
    Mechanism("pyext_module", "binding_declaration", "PyInit_<module> declares a Python extension module"),
    Mechanism("pyext_def", "binding_declaration", "a PyMethodDef table entry binds a Python name"),
    Mechanism("prefix_call", "rule", "call prefix of a rule, then its name transformation"),
    Mechanism("declaration_macro", "binding_declaration", "a declaration pattern of a rule names the target"),
)}

NATIVE_BRIDGES = (
    BridgeSpec("pybind11", NATIVE_VERSION, ("python",), ("cpp", "c"), ("pybind11_module", "pybind11_def"),
               "Python call or import of a module declared by PYBIND11_MODULE",
               "Python name -> function bound by m.def", "module name declared in the analyzed sources",
               "unique", "Python calls into pybind11 extension modules"),
    BridgeSpec("python_extension", NATIVE_VERSION, ("python",), ("c", "cpp"), ("pyext_module", "pyext_def"),
               "Python call or import of a module declared by PyInit_<module>",
               "Python name -> C function of the PyMethodDef table", "module name declared in the analyzed sources",
               "unique", "Python calls into C extension modules (Python C API)"),
    BridgeSpec("c_cpp", NATIVE_VERSION, ("c", "cpp"), ("c", "cpp"), ("c_linkage_same_name",),
               "unresolved call whose exact name is a C function (from C++) or a single non-static C++ function "
               "(from C)", "none", "none", "unique",
               "Calls between C and C++ through C linkage"),
    BridgeSpec("fortran_c", NATIVE_VERSION, ("c", "cpp", "fortran"), ("fortran", "c"),
               ("bind_c_name", "trailing_underscore", "g77_double_underscore", "uppercase_name", "same_name"),
               "unresolved call; BIND(C, NAME=...) first, then Fortran name decoration",
               "decoration removed (from C) or added (from Fortran)", "none", "unique",
               "Calls between C/C++ and Fortran"),
)


def native_bridge(bridge_id: str) -> BridgeSpec:
    return next(b for b in NATIVE_BRIDGES if b.id == bridge_id)
