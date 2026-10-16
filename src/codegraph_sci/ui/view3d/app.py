"""PyWebView window of the 3D view, and its Python API called from JavaScript."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from codegraph_sci.query.api import GraphQuery
from codegraph_sci.ui.view3d.html import build_html, graph_dict


class View3DApi:
    """Exposed to the page as ``window.pywebview.api`` (no port: in-process bridge)."""

    def __init__(self, db: Path, mode: str = "both", hide_noise: bool = True, expand_depth: int = 1,
                 max_nodes: int = 150) -> None:
        self.db = Path(db)
        self.mode = mode
        self.hide_noise = hide_noise
        self.expand_depth = expand_depth
        self.max_nodes = max_nodes

    def expand(self, uid: str) -> dict[str, Any]:
        """Neighbours of a node, merged into the scene by the page."""
        mode = "files" if uid.startswith("file:") and self.mode != "files" else self.mode
        with GraphQuery(self.db) as q:
            graph = q.graph3d(uid, mode=mode, depth=self.expand_depth, max_nodes=self.max_nodes,
                              hide_noise=self.hide_noise)
        return graph_dict(graph)

    def select(self, uid: str) -> None:
        """Tell the desktop application which node was clicked (one JSON line on stdout)."""
        print(json.dumps({"event": "select", "uid": uid}), flush=True)


def run_window(db: Path, root: str, label: str, *, mode: str = "both", depth: int = 2, max_nodes: int = 400,
               hide_noise: bool = True) -> int:
    try:
        import webview  # PyWebView: optional dependency (3D view)
    except ImportError:
        print("error: the 3D view needs PyWebView (pip install pywebview)", file=sys.stderr)
        return 2
    with GraphQuery(db) as q:
        graph = q.graph3d(root, mode=mode, depth=depth, max_nodes=max_nodes, hide_noise=hide_noise)
    page = build_html(graph, label)
    # A local file rather than an HTML string: no size limit in the web view, and still no server.
    folder = Path(tempfile.mkdtemp(prefix="cgs-3d-"))
    path = folder / "view3d.html"
    path.write_text(page, encoding="utf-8")
    api = View3DApi(db, mode=mode, hide_noise=hide_noise)
    webview.create_window(f"CodeGraph-Sci 3D — {label}", url=path.as_uri(), js_api=api, width=1280, height=820,
                          background_color="#0f1419")
    webview.start(http_server=False, private_mode=True)
    print(json.dumps({"event": "closed"}), flush=True)
    return 0
