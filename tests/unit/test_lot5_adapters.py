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

from codegraph_sci.core.facts import FileFacts, SourceFile
from codegraph_sci.core.plugins import ExtractContext, LanguageAdapter
from codegraph_sci.extract.c import CAdapter
from codegraph_sci.extract.cpp import CppAdapter
from codegraph_sci.extract.fortran import FortranAdapter
from codegraph_sci.extract.python import PythonAdapter, module_name_for, resolve_relative

ADAPTERS: dict[str, LanguageAdapter] = {"c": CAdapter(), "cpp": CppAdapter(), "python": PythonAdapter(),
                                        "fortran": FortranAdapter()}


def extract_all(name: str) -> dict[str, FileFacts]:
    facts: dict[str, FileFacts] = {}
    for lang, adapter in ADAPTERS.items():
        facts.update(extract_fixture(name, adapter, lang))
    return facts


@pytest.mark.parametrize("name", ["python_basic", "c_basic", "cpp_basic", "cpp_overloads", "mini_hybrid"])
def test_facts_match_expected(name: str) -> None:
    facts = extract_all(name)
    expected = load_expected(name)
    files = set(facts)
    assert facts_definitions(facts) == expected_definitions(expected, files)
    assert facts_references(facts) == expected_references(expected, files)
    fallback = {p for p, f in facts.items() if f.used_fallback}
    assert fallback == set(expected.get("fallback_files", []))


def test_overloads_have_distinct_identities() -> None:
    facts = extract_all("cpp_overloads")
    uids = sorted(d.uid for d in facts["ops.cpp"].definitions)
    assert {"cpp:ops::scale(int)", "cpp:ops::scale(double)", "cpp:ops::scale(int,int)"} <= set(uids)
    template_call = next(r for r in facts["ops.cpp"].references if r.line == 9)
    assert template_call.hint["arg_types"] == ["T"]
    literal_call = next(r for r in facts["ops.cpp"].references if r.line == 16)
    assert literal_call.hint["arg_types"] == ["double"] and literal_call.args[0].value == 2.5


def test_static_homonyms_stay_distinct() -> None:
    facts = extract_all("c_basic")
    assert [d.uid for d in facts["util_a.c"].definitions if d.name == "helper"] == ["c:helper@util_a.c"]
    assert [d.uid for d in facts["util_b.c"].definitions if d.name == "helper"] == ["c:helper@util_b.c"]


def test_python2_file_is_read_by_fallback() -> None:
    facts = extract_all("python_basic")
    old = facts["legacy/old.py"]
    assert old.used_fallback and old.errors and "SyntaxError" in old.errors[0].message


def test_python_module_names() -> None:
    assert module_name_for("pkg/sub/mod.py") == "pkg.sub.mod"
    assert module_name_for("pkg/__init__.py") == "pkg"
    assert resolve_relative("pkg.app", False, 1, "core") == "pkg.core"
    assert resolve_relative("pkg", True, 1, None) == "pkg"
    assert resolve_relative("a.b.c", False, 2, "x") == "a.x"


def test_malformed_files_never_crash() -> None:
    ctx = ExtractContext()
    for lang, text in [("python", "def broken(:\n    return ((\n"),
                       ("cpp", "namespace { class X { void f( { } }\nint g() { return h(; }\n"),
                       ("c", "int f( { return ; \n"), ("fortran", "subroutine broken(\n  call ((((\n")]:
        facts = ADAPTERS[lang].extract(SourceFile(f"x.{lang}", lang, None, "utf-8", text), ctx)
        assert facts.errors or facts.used_fallback


def test_fuzz_adapters_never_crash() -> None:
    from hypothesis import given, settings
    from hypothesis import strategies as st

    tokens = st.sampled_from(list("abcxyz(){}[];,.:=*&<>\"'#\n\t ") +
                             ["def ", "class ", "import ", "from ", "return ", "namespace ", "template<", "::",
                              "#define F(x) g(x)\n", "#include \"a.h\"\n", "static ", "int ", "void ", "->",
                              "if ", "lambda ", "@", "self.", "async ", "yield "])

    @settings(max_examples=150, deadline=None)
    @given(st.lists(tokens, max_size=60).map("".join), st.sampled_from(["python", "c", "cpp"]))
    def run(text: str, lang: str) -> None:
        facts = ADAPTERS[lang].extract(SourceFile(f"f.{lang}", lang, None, "utf-8", text), ExtractContext())
        assert facts.lang == lang

    run()
