from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from codegraph_sci.core.facts import (
    ArgFact,
    DataAccess,
    Definition,
    FileFacts,
    IncludeRef,
    LocalSymbol,
    Reference,
    decode_facts,
    encode_facts,
)
from codegraph_sci.core.graph import (
    AggregateEdge,
    CallSiteRecord,
    DataAccessRecord,
    EdgeRecord,
    FileRecord,
    GraphBundle,
    InventoryRecord,
    NodeRecord,
    NodeStatRecord,
    PluginRecord,
    ScanRunRecord,
)
from codegraph_sci.core.ids import c_uid, cpp_uid, fortran_uid, py_uid, variant_uid
from codegraph_sci.store.db import SchemaVersionError, open_db
from codegraph_sci.store.export import export_dict, export_json
from codegraph_sci.store.writer import write_full, write_incremental


def sample_bundle() -> GraphBundle:
    b = GraphBundle()
    b.files = [FileRecord("src/b.f90", "fortran", "free", "aa", 10, "utf-8"),
               FileRecord("src/a.c", "c", None, "bb", 20, "latin-1")]
    b.inventory = [InventoryRecord("src/a.c", "c", None, 1.0, "extension"),
                   InventoryRecord("src/b.f90", "fortran", "free", 1.0, "extension")]
    b.nodes = [
        NodeRecord("f:solve", "solve", "routine", "f_subroutine", "fortran", "src/b.f90", 1, 9),
        NodeRecord("f:helper", "helper", "routine", "f_function", "fortran", "src/b.f90", 10, 20,
                   attrs={"doc": "helper doc"}),
        NodeRecord("c:main", "main", "routine", "c_function", "c", "src/a.c", 1, 5),
        NodeRecord("ext:intrinsic:sin", "sin", "external", "intrinsic", None),
    ]
    b.call_sites = [
        CallSiteRecord("f:solve", "src/b.f90", 3, 7, "call", "helper", "f:helper", "resolved", "exact",
                       "native:fortran", "HAVE_MPI"),
        CallSiteRecord("f:solve", "src/b.f90", 4, 7, "call", "helper", "f:helper", "resolved", "resolved",
                       "native:fortran"),
        CallSiteRecord("c:main", "src/a.c", 2, 3, "call", "solve_", None, "ambiguous", "ambiguous",
                       "native:c", None, ["f:solve", "f:helper"]),
        CallSiteRecord("f:helper", "src/b.f90", 12, 9, "maybe_call", "sin", "ext:intrinsic:sin", "external",
                       "exact", "native:fortran"),
    ]
    b.data_accesses = [DataAccessRecord("f:solve", "f:helper", None, "reads", "literal", "src/b.f90", 5,
                                        "native:fortran")]
    b.edges = [EdgeRecord("f:solve", "f:helper", "calls", 2, "resolved", ["native:fortran"], ["HAVE_MPI"])]
    b.node_stats = [NodeStatRecord("f:helper", fan_in=1), NodeStatRecord("f:solve", fan_out=1, impact_size=1)]
    b.file_edges = [AggregateEdge("src/b.f90", "src/a.c", "calls", 1)]
    b.dir_edges = [AggregateEdge("src", "src", "calls", 2)]
    b.plugins = [PluginRecord("fortran", "adapter", "1.0")]
    b.scan_run = ScanRunRecord("t0", "t1", "/repo", None, 1, "abc", [], {"files": 2})
    b.facts_cache = {"k1": b"\x00blob"}
    return b


def test_uids() -> None:
    assert fortran_uid("SOLVE") == "f:solve"
    assert fortran_uid("Get", "MyMod") == "f:mymod::get"
    assert c_uid("helper", "src\\x.c") == "c:helper@src/x.c"
    assert cpp_uid("ns::A::run", ["const int &", "double *"]) == "cpp:ns::A::run(const int&,double*)"
    assert cpp_uid("ns::A::run", ["void"]) == "cpp:ns::A::run()"
    assert py_uid("pkg.mod", "Cls.meth") == "py:pkg.mod.Cls.meth"
    assert variant_uid("f:x", 1) == "f:x" and variant_uid("f:x", 2) == "f:x#2"


def test_facts_roundtrip() -> None:
    facts = FileFacts(
        path="a.f90", lang="fortran", encoding="utf-8", adapter="fortran", adapter_version="1",
        definitions=[Definition("f:a", "a", "routine", "f_subroutine", "a", (1, 3),
                                local_symbols=[LocalSymbol("x", "array", "local")])],
        references=[Reference("f:a", "b", "call", 2, 5, [ArgFact("1", 1), ArgFact("'R'", "R")], "X")],
        data_accesses=[DataAccess("f:a", "common:blk", "reads", "literal", 2)],
        includes=[IncludeRef("inc.h", "inc.h", "ff", 1)],
    ).sort()
    again = decode_facts(encode_facts(facts))
    assert again == facts
    assert encode_facts(again) == encode_facts(facts)


def test_roundtrip_bundle_db_export(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite"
    write_full(db, sample_bundle())
    data = export_dict(db)
    assert [f["path"] for f in data["files"]] == ["src/a.c", "src/b.f90"]
    assert len(data["nodes"]) == 4 and len(data["call_sites"]) == 4
    amb = [s for s in data["call_sites"] if s["resolution"] == "ambiguous"][0]
    assert amb["candidates"] == ["f:helper", "f:solve"] and amb["dst"] is None
    first = [s for s in data["call_sites"] if s["line"] == 3][0]
    assert first["condition"] == "HAVE_MPI" and first["dst"] == "f:helper"
    assert data["edges"][0]["site_count"] == 2
    assert [n["uid"] for n in data["nodes"]] == ["c:main", "ext:intrinsic:sin", "f:helper", "f:solve"]
    assert data["nodes"][2]["attrs"] == {"doc": "helper doc"}
    con = open_db(db)
    assert con.execute("SELECT count(*) FROM search_fts WHERE search_fts MATCH 'helper'").fetchone()[0] == 1
    assert con.execute("SELECT facts FROM facts_cache").fetchone()[0] == b"\x00blob"
    con.close()


def test_two_writes_identical(tmp_path: Path) -> None:
    write_full(tmp_path / "a.sqlite", sample_bundle())
    write_full(tmp_path / "b.sqlite", sample_bundle())
    assert export_json(tmp_path / "a.sqlite") == export_json(tmp_path / "b.sqlite")
    write_incremental(tmp_path / "b.sqlite", sample_bundle())
    assert export_json(tmp_path / "a.sqlite") == export_json(tmp_path / "b.sqlite")


def test_interrupted_write_keeps_previous_db(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite"
    write_full(db, sample_bundle())
    before = export_json(db)

    def boom(step: str) -> None:
        if step == "call_sites":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        write_full(db, sample_bundle(), progress=boom)
    assert export_json(db) == before
    assert not (tmp_path / "p.sqlite.tmp").exists()
    with pytest.raises(KeyboardInterrupt):
        write_incremental(db, sample_bundle(), progress=boom)
    assert export_json(db) == before


def test_unknown_schema_version_refused(tmp_path: Path) -> None:
    db = tmp_path / "p.sqlite"
    write_full(db, sample_bundle())
    con = sqlite3.connect(db)
    con.execute("PRAGMA user_version=999")
    con.commit()
    con.close()
    with pytest.raises(SchemaVersionError):
        open_db(db)


def test_cli_export(tmp_path: Path) -> None:
    from codegraph_sci.cli import main
    from codegraph_sci.core import netguard

    db = tmp_path / "p.sqlite"
    write_full(db, sample_bundle())
    out = tmp_path / "out.json"
    try:
        assert main(["export", "json", str(db), "-o", str(out)]) == 0
    finally:
        netguard.uninstall()
    assert json.loads(out.read_text(encoding="utf-8"))["files"][0]["path"] == "src/a.c"


@pytest.mark.slow
def test_write_one_million_sites(tmp_path: Path) -> None:
    n_nodes, n_sites = 15_000, 1_000_000
    b = GraphBundle()
    b.files = [FileRecord(f"src/f{i:04d}.f90", "fortran") for i in range(3000)]
    b.nodes = [NodeRecord(f"f:r{i:05d}", f"r{i:05d}", "routine", None, "fortran", f"src/f{i % 3000:04d}.f90")
               for i in range(n_nodes)]
    b.call_sites = [
        CallSiteRecord(f"f:r{i % n_nodes:05d}", f"src/f{i % 3000:04d}.f90", i % 5000 + 1, 1, "call", "x",
                       f"f:r{(i * 7) % n_nodes:05d}", "resolved", "exact", "native:fortran")
        for i in range(n_sites)
    ]
    start = time.perf_counter()
    write_full(tmp_path / "big.sqlite", b)
    elapsed = time.perf_counter() - start
    print(f"\n1M call sites written in {elapsed:.1f} s")
    assert elapsed < 120
