from __future__ import annotations

import pytest
from tests.helpers import (
    expected_definitions,
    expected_references,
    extract_fixture,
    facts_definitions,
    facts_references,
    load_expected,
)

from codegraph_sci.core.facts import SourceFile
from codegraph_sci.core.plugins import ExtractContext
from codegraph_sci.extract.fortran import FortranAdapter, extract_patterns
from codegraph_sci.extract.fortran.source import prepare

FORTRAN_FIXTURES = ["fortran_basic", "fortran_fixed_form", "fortran_preproc", "fortran_ambiguity",
                    "fortran_arrays_includes", "fortran_advanced", "fortran_data", "fortran_traps",
                    "partial_scope"]


@pytest.mark.parametrize("name", FORTRAN_FIXTURES)
def test_fortran_facts_match_expected(name: str) -> None:
    facts = extract_fixture(name, FortranAdapter(), "fortran")
    expected = load_expected(name)
    files = set(facts)
    assert facts_definitions(facts) == expected_definitions(expected, files)
    scope = expected.get("profile", {}).get("scope", {}).get("include", [])
    in_scope = {f for f in files if not scope or any(f.startswith(s) for s in scope)}
    assert facts_references({k: v for k, v in facts.items() if k in in_scope}) == expected_references(
        expected, in_scope)
    for f in facts.values():
        assert not f.used_fallback, (f.path, f.errors)
    for uid, symbols in expected.get("local_symbols", {}).items():
        d = next(d for f in facts.values() for d in f.definitions if d.uid == uid)
        assert [[s.name, s.role] for s in d.local_symbols] == symbols
    for uid, cond in expected.get("definition_conditions", {}).items():
        d = next(d for f in facts.values() for d in f.definitions if d.uid == uid)
        assert d.condition == cond


def test_arrays_from_include_and_common_are_never_calls() -> None:
    facts = extract_fixture("fortran_arrays_includes", FortranAdapter(), "fortran")
    targets = {r.target_text.lower() for f in facts.values() for r in f.references}
    assert not targets & {"tbl", "rbuf", "xglob", "zr", "ibuf"}
    hints = {r.target_text.lower(): r.hint for f in facts.values() for r in f.references}
    assert hints["sqrt"] == {"intrinsic": True}
    inc = facts["arrays.f"].includes[0]
    assert inc.resolved_path == "vars.inc" and inc.sha256


def test_without_known_arrays_zr_is_a_maybe_call() -> None:
    from codegraph_sci.core.facts import SourceFile as SF

    text = "      SUBROUTINE U(I)\n      X = ZR(I)\n      END\n"
    facts = FortranAdapter().extract(SF("u.f", "fortran", "fixed", "ascii", text), ExtractContext())
    assert [(r.target_text, r.kind) for r in facts.references] == [("ZR", "maybe_call")]
    facts = FortranAdapter().extract(SF("u.f", "fortran", "fixed", "ascii", text),
                                     ExtractContext(known_arrays={"zr"}))
    assert facts.references == []


def test_unreadable_structure_switches_to_fallback() -> None:
    text = "subroutine broken(\n  call ((((\nsubroutine half\n  call real_one()\n"
    facts = FortranAdapter().extract(SourceFile("b.f90", "fortran", "free", "utf-8", text), ExtractContext())
    assert facts.used_fallback
    assert facts.errors and "statement parser failed" in facts.errors[0].message
    assert any(r.target_text == "real_one" for r in facts.references)


def test_pattern_extractor_on_fixed_form() -> None:
    from tests.helpers import FIXTURES

    text = (FIXTURES / "fortran_fixed_form" / "src" / "legacy.f").read_text(encoding="ascii")
    facts = extract_patterns("legacy.f", text, "ascii", "fixed")
    assert [d.uid for d in facts.definitions] == ["f:assemb", "f:elemk", "f:bound"]
    assert [(r.target_text, r.line, r.col) for r in facts.references] == [
        ("ELEMK", 6, 12), ("BOUND", 9, 12), ("ELEMK", 22, 12)]


def test_prepare_positions_and_strings() -> None:
    prepared = prepare("x = 'a;b' ; call f(1) ! call g\n", fixed_form=False)
    assert [s.orig for s in prepared.statements] == ["x = 'a;b'", "call f(1)"]
    assert prepared.statements[0].masked == "x = '___'"
    assert prepared.statements[1].at(5) == (1, 18)


def test_fuzz_fortran_never_crashes() -> None:
    from hypothesis import given, settings
    from hypothesis import strategies as st

    alphabet = st.sampled_from(list("abcdefghijklmnopqrstuvwxyz()=,'\"!&;%*/: \n\t#0123456789") +
                               ["call ", "subroutine ", "end", "function ", "module ", "#ifdef X\n", "#endif\n",
                                "interface\n", "contains\n", "type "])

    @settings(max_examples=300, deadline=None)
    @given(st.lists(alphabet, max_size=80).map("".join), st.booleans())
    def run(text: str, fixed: bool) -> None:
        facts = FortranAdapter().extract(
            SourceFile("z.f", "fortran", "fixed" if fixed else "free", "utf-8", text), ExtractContext())
        assert facts.path == "z.f"

    run()


def test_nested_interface_in_interface_body() -> None:
    """A dummy procedure declared by an interface inside an interface body must not close the routine."""
    text = (
        "subroutine outer(n)\n"
        "  interface\n"
        "    subroutine solver(f, n)\n"
        "      interface\n"
        "        subroutine f(x)\n"
        "          real :: x\n"
        "        end subroutine f\n"
        "      end interface\n"
        "      integer :: n\n"
        "    end subroutine solver\n"
        "  end interface\n"
        "  call solver(g, n)\n"
        "  call other(n)\n"
        "end subroutine outer\n"
    )
    facts = FortranAdapter().extract(SourceFile("o.f90", "fortran", "free", "utf-8", text), ExtractContext())
    assert facts.errors == []
    assert [(r.target_text, r.src) for r in facts.references] == [("solver", "f:outer"), ("other", "f:outer")]
    assert [d.uid for d in facts.definitions] == ["f:outer"]
