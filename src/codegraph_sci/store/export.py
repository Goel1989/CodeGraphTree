"""Canonical JSON export (``cgs export json``): ids replaced by uids and paths, everything sorted.

Two scans of the same repository with the same profile must give byte-identical exports.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from codegraph_sci.store.db import open_db


def _rows(con: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    cur = con.execute(sql)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def export_dict(db_path: Path | str) -> dict[str, Any]:
    con = open_db(db_path)
    try:
        files = _rows(con, "SELECT path, lang, variant, sha256, size, encoding, parse_status, adapter, "
                           "adapter_version, error FROM files ORDER BY path")
        inventory = _rows(con, "SELECT f.path, i.lang, i.variant, i.confidence, i.decided_by FROM inventory i "
                               "JOIN files f ON f.id = i.file_id ORDER BY f.path")
        nodes = _rows(con, "SELECT n.uid, n.display_name, n.kind, n.subtype, n.lang, f.path AS file, "
                           "n.line_start, n.line_end, n.in_scope, n.attrs FROM nodes n "
                           "LEFT JOIN files f ON f.id = n.file_id ORDER BY n.uid")
        for n in nodes:
            n["attrs"] = json.loads(n["attrs"] or "{}")
            n["in_scope"] = bool(n["in_scope"])
        sites = _rows(con, "SELECT s.id, src.uid AS src, f.path AS file, s.line, s.col, s.ref_kind, "
                           "s.target_text, dst.uid AS dst, s.resolution, s.confidence, s.origin, "
                           "c.expr AS condition FROM call_sites s JOIN nodes src ON src.id = s.src_node "
                           "JOIN files f ON f.id = s.file_id LEFT JOIN nodes dst ON dst.id = s.dst_node "
                           "LEFT JOIN conditions c ON c.id = s.condition_id")
        cands: dict[int, list[str]] = {}
        for site_id, uid in con.execute("SELECT c.site_id, n.uid FROM call_site_candidates c "
                                        "JOIN nodes n ON n.id = c.dst_node"):
            cands.setdefault(site_id, []).append(uid)
        for s in sites:
            s["candidates"] = sorted(cands.get(s.pop("id"), []))
        sites.sort(key=lambda s: (s["file"], s["line"], s["col"], s["src"], s["target_text"], s["ref_kind"]))
        data = _rows(con, "SELECT src.uid AS src, d.uid AS data, fam.uid AS family, a.mode, a.key_kind, "
                          "f.path AS file, a.line, a.origin FROM data_accesses a "
                          "JOIN nodes src ON src.id = a.src_node JOIN nodes d ON d.id = a.data_node "
                          "LEFT JOIN nodes fam ON fam.id = a.family_node JOIN files f ON f.id = a.file_id "
                          "ORDER BY f.path, a.line, src.uid, d.uid, a.mode")
        edges = _rows(con, "SELECT s.uid AS src, d.uid AS dst, e.kind, e.site_count, e.min_confidence, "
                           "e.origins, e.conditions FROM edges e JOIN nodes s ON s.id = e.src "
                           "JOIN nodes d ON d.id = e.dst ORDER BY s.uid, d.uid, e.kind")
        for e in edges:
            e["origins"] = json.loads(e["origins"])
            e["conditions"] = json.loads(e["conditions"])
        stats = _rows(con, "SELECT n.uid, s.fan_in, s.fan_out, s.fan_in_filtered, s.fan_out_filtered, "
                           "s.impact_size, s.impact_size_filtered, s.is_noise, s.noise_reason "
                           "FROM node_stats s JOIN nodes n ON n.id = s.node_id ORDER BY n.uid")
        for st in stats:
            st["is_noise"] = bool(st["is_noise"])
        file_edges = _rows(con, "SELECT a.path AS src, b.path AS dst, e.kind, e.count FROM file_edges e "
                                "JOIN files a ON a.id = e.src_file JOIN files b ON b.id = e.dst_file "
                                "ORDER BY a.path, b.path, e.kind")
        dir_edges = _rows(con, "SELECT src_dir AS src, dst_dir AS dst, kind, count FROM dir_edges "
                               "ORDER BY src_dir, dst_dir, kind")
        plugins = _rows(con, "SELECT name, type, version FROM plugins ORDER BY type, name")
    finally:
        con.close()
    return {"files": files, "inventory": inventory, "nodes": nodes, "call_sites": sites,
            "data_accesses": data, "edges": edges, "node_stats": stats, "file_edges": file_edges,
            "dir_edges": dir_edges, "plugins": plugins}


def export_json(db_path: Path | str) -> str:
    return json.dumps(export_dict(db_path), sort_keys=True, indent=1, ensure_ascii=False) + "\n"
