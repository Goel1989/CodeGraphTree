from __future__ import annotations

from codegraph_sci.core.facts import SourceFile
from codegraph_sci.core.plugins import ExtractContext
from codegraph_sci.extract.c import CAdapter
from codegraph_sci.extract.cfamily import collect_macros
from codegraph_sci.extract.cmacro import callees_of, declared_name, expand_text

HEADER = """
#define F_FUNC(UN, LN) LN##_
#define F_FUNC(UN, LN) LN
#define CALL0(UN, LN) F_FUNC(UN, LN)()
#define CALLO_JEDEMA() CALL0(JEDEMA, jedema)
#define DEFS(UN, LN, a, la) F_FUNC(UN, LN)(a, la)
#define STR(x) #x
#define LOG(fmt, ...) log_msg(fmt, __VA_ARGS__)
"""


def test_expansion_chain_paste_and_first_definition_wins() -> None:
    macros = collect_macros(HEADER)
    assert expand_text("CALLO_JEDEMA()", macros).strip() == "jedema_()"
    assert callees_of(expand_text("CALLO_JEDEMA()", macros), macros) == ["jedema_"]
    assert declared_name("DEFS(JDCGET, jdcget, char *a, int la)", macros) == "jdcget_"
    assert expand_text("STR(hello)", macros) == '"hello"'
    assert callees_of(expand_text('LOG("%d", x, y)', macros), macros) == ["log_msg"]


def test_c_function_declared_by_macro_and_call_through_macros() -> None:
    text = HEADER + "\nint DEFS(R8PREM, r8prem, double *a, int la) { return 0; }\n" \
                    "void user(void) { CALLO_JEDEMA(); }\n"
    facts = CAdapter().extract(SourceFile("w.c", "c", None, "utf-8", text), ExtractContext())
    assert sorted(d.uid for d in facts.definitions) == ["c:r8prem_", "c:user"]
    assert [(r.target_text, r.hint.get("macro")) for r in facts.references] == [("jedema_", "CALLO_JEDEMA")]
