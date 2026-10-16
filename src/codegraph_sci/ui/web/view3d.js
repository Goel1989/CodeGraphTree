/* CodeGraph-Sci 3D view: connections between functions and files (3d-force-graph).
   Data comes from GraphQuery.graph3d; expansion and selection go through the PyWebView js_api when present. */
(function () {
  "use strict";
  const LANG_COLORS = { fortran: "#a371f7", python: "#58a6ff", c: "#8b949e", cpp: "#f0883e" };
  const LINK_COLORS = { calls: "#6e7681", bridges: "#f0883e", binds: "#d2a8ff", dispatches: "#3fb950",
                        implements: "#56d364", uses: "#388bfd", defines: "#30363d", inherits: "#db61a2" };
  const initial = JSON.parse(document.getElementById("graph-data").textContent);
  const state = { nodes: new Map(), links: new Map(), hover: null, neighbours: new Set(), hoverLinks: new Set() };

  const linkKey = (l) => `${idOf(l.source)}|${idOf(l.target)}|${l.kind}`;
  function idOf(end) { return typeof end === "object" ? end.id : end; }

  function merge(data) {
    for (const n of data.nodes) if (!state.nodes.has(n.id)) state.nodes.set(n.id, { ...n });
    for (const l of data.links) {
      const k = linkKey(l);
      if (!state.links.has(k) && state.nodes.has(l.source) && state.nodes.has(l.target)) state.links.set(k, { ...l });
    }
  }

  function visibleData() {
    const showFiles = document.getElementById("files").checked;
    const nodes = [...state.nodes.values()].filter((n) => showFiles || n.kind !== "file");
    const ids = new Set(nodes.map((n) => n.id));
    const links = [...state.links.values()].filter((l) => ids.has(idOf(l.source)) && ids.has(idOf(l.target)));
    return { nodes, links };
  }

  function nodeColor(n) {
    if (n.is_root) return "#f2c94c";
    if (state.hover && !state.neighbours.has(n.id) && state.hover !== n.id) return "rgba(90,100,110,0.35)";
    if (n.kind === "file") return "#c9d1d9";
    if (n.kind === "external") return "#484f58";
    if (n.kind === "entry_point") return "#ff7b72";
    return LANG_COLORS[n.lang] || "#8b949e";
  }

  function tooltip(n) {
    const where = n.file ? `${n.file}${n.line ? ":" + n.line : ""}` : "outside the repository";
    return `<b>${escapeHtml(n.label)}</b><br><span style="color:#8b98a5">${escapeHtml(n.kind)} · ${escapeHtml(n.lang || "-")}</span>`
      + `<br>${escapeHtml(where)}<br>callers ${n.fan_in} · callees ${n.fan_out}`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  const graph = ForceGraph3D({ controlType: "orbit" })(document.getElementById("graph"))
    .backgroundColor("#0f1419")
    .nodeId("id")
    .nodeLabel(tooltip)
    .nodeColor(nodeColor)
    .nodeVal((n) => (n.kind === "file" ? 7 : 1 + Math.log2(1 + n.fan_in)))
    .nodeOpacity(0.92)
    .linkColor((l) => (state.hoverLinks.size && !state.hoverLinks.has(linkKey(l)) ? "rgba(60,60,60,0.25)"
                                                                                     : LINK_COLORS[l.kind] || "#6e7681"))
    .linkWidth((l) => (l.kind === "defines" ? 0.3 : Math.min(4, 0.5 + Math.log2(1 + l.count))))
    .linkDirectionalArrowLength((l) => (document.getElementById("arrows").checked && l.kind !== "defines" ? 3.5 : 0))
    .linkDirectionalArrowRelPos(1)
    .linkDirectionalParticles((l) => (document.getElementById("particles").checked
                                      && (l.kind === "bridges" || l.kind === "binds") ? 2 : 0))
    .linkDirectionalParticleWidth(1.6)
    .linkLabel((l) => `${l.kind} · ${l.count} call(s) · ${l.confidence}`)
    .onNodeHover((n) => {
      state.hover = n ? n.id : null;
      state.neighbours = new Set();
      state.hoverLinks = new Set();
      if (n) {
        for (const l of state.links.values()) {
          if (idOf(l.source) === n.id || idOf(l.target) === n.id) {
            state.neighbours.add(idOf(l.source)); state.neighbours.add(idOf(l.target)); state.hoverLinks.add(linkKey(l));
          }
        }
      }
      refreshStyle();
      document.getElementById("graph").style.cursor = n ? "pointer" : null;
    })
    .onNodeClick((n) => { focus(n); showDetails(n); if (api()) api().select(n.id); })
    .onNodeRightClick((n) => expand(n));

  function refreshStyle() { graph.nodeColor(graph.nodeColor()).linkColor(graph.linkColor()); }
  function api() { return window.pywebview && window.pywebview.api ? window.pywebview.api : null; }

  function focus(n) {
    const distance = 90;
    const r = 1 + distance / Math.hypot(n.x || 1, n.y || 1, n.z || 1);
    graph.cameraPosition({ x: (n.x || 1) * r, y: (n.y || 1) * r, z: (n.z || 1) * r }, n, 900);
  }

  function showDetails(n) {
    const box = document.getElementById("details");
    const ins = [...state.links.values()].filter((l) => idOf(l.target) === n.id && l.kind !== "defines").length;
    const outs = [...state.links.values()].filter((l) => idOf(l.source) === n.id && l.kind !== "defines").length;
    box.innerHTML = `<h3>${escapeHtml(n.label)}</h3><code>${escapeHtml(n.id)}</code><br>`
      + `${escapeHtml(n.file || "")}${n.line ? ":" + n.line : ""}<br>`
      + `shown: ${ins} incoming, ${outs} outgoing link(s)<br>`
      + (api() ? "Right-click: expand its neighbours" : "Open in CodeGraph-Sci to expand");
    box.style.display = "block";
  }

  async function expand(n) {
    if (!api()) return;
    const data = await api().expand(n.id);
    merge(data);
    graph.graphData(visibleData());
    updateInfo(data.truncated);
  }

  function updateInfo(truncated) {
    const nodes = state.nodes.size, links = state.links.size;
    document.getElementById("info").textContent =
      `${nodes} node(s), ${links} link(s) · root ${initial.root} · mode ${initial.mode}`
      + (initial.hidden_noise ? ` · ${initial.hidden_noise} utility link(s) hidden` : "")
      + (truncated || initial.truncated ? " · limit reached: right-click a node to explore further" : "")
      + " · drag to rotate, scroll to zoom, click to focus";
  }

  function legend() {
    const langs = Object.entries(LANG_COLORS).map(([k, c]) => `<div><i style="background:${c}"></i>${k}</div>`).join("");
    const kinds = ["calls", "bridges", "binds", "dispatches", "uses", "defines"]
      .map((k) => `<div><b class="line" style="background:${LINK_COLORS[k]}"></b>${k}</div>`).join("");
    document.getElementById("legend").innerHTML =
      `${langs}<div><i style="background:#c9d1d9"></i>file</div><div><i style="background:#f2c94c"></i>root</div><hr style="border-color:#2d3743">${kinds}`;
  }

  document.getElementById("fit").onclick = () => graph.zoomToFit(600, 40);
  for (const id of ["files", "arrows", "particles"]) {
    document.getElementById(id).onchange = () => { graph.graphData(visibleData()); refreshStyle(); };
  }
  document.getElementById("search").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    const q = e.target.value.trim().toLowerCase();
    if (!q) return;
    const hit = [...state.nodes.values()].find((n) => n.label.toLowerCase() === q)
      || [...state.nodes.values()].find((n) => n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q));
    if (hit) { const live = graph.graphData().nodes.find((n) => n.id === hit.id); if (live) { focus(live); showDetails(live); } }
  });

  merge(initial);
  legend();
  graph.graphData(visibleData());
  updateInfo(initial.truncated);
  setTimeout(() => graph.zoomToFit(800, 60), 1500);
})();
