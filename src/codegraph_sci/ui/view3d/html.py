"""Self-contained HTML page of the 3D view: vendored 3d-force-graph, app script and graph data inline."""

from __future__ import annotations

import dataclasses
import json
from importlib import resources
from typing import Any

from codegraph_sci.query.types import Graph3D

VENDOR_VERSION = "3d-force-graph 1.80.1 (MIT, bundles three.js r186, MIT)"


def _web(name: str) -> str:
    return resources.files("codegraph_sci.ui.web").joinpath(name).read_text(encoding="utf-8")


def graph_dict(graph: Graph3D) -> dict[str, Any]:
    return dataclasses.asdict(graph)


def _safe_json(data: Any) -> str:
    """JSON that cannot close the surrounding <script> element."""
    text = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return text.replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def build_html(graph: Graph3D, title: str) -> str:
    vendor = resources.files("codegraph_sci.ui.web").joinpath("vendor/3d-force-graph.min.js").read_text(
        encoding="utf-8")
    page = _web("view3d.html")
    for key, value in (("{{TITLE}}", f"CodeGraph-Sci 3D — {title}".replace("<", "&lt;")),
                       ("{{GRAPH_JSON}}", _safe_json(graph_dict(graph))),
                       ("{{APP_JS}}", _web("view3d.js"))):
        page = page.replace(key, value)
    return page.replace("{{VENDOR_JS}}", vendor.replace("</script", "<\\/script"))
