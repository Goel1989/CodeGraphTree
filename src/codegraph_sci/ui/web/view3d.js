/* CodeGraph-Sci 3D view: connections between functions and files (3d-force-graph).
   Data comes from GraphQuery.graph3d. Two hosts:
   - "qt": QWebEngineView in the main window. Page -> Python: console messages "CGS:<json>";
     Python -> page: window.cgs.load(data) / window.cgs.merge(data).
   - "pywebview": separate window of `cgs view3d`, through window.pywebview.api (expand, select). */
(function () {
  "use strict";
  const HOST = window.CGS_HOST || "pywebview";
  const LANG_COLORS = { fortran: "#a371f7", python: "#58a6ff", c: "#8b949e", cpp: "#f0883e" };
  const LINK_COLORS = { calls: "#6e7681", bridges: "#f0883e", binds: "#d2a8ff", dispatches: "#3fb950",
                        implements: "#56d364", uses: "#388bfd", defines: "#30363d", inherits: "#db61a2",
                        includes: "#8b949e", imports: "#58a6ff" };
  const state = { nodes: new Map(), links: new Map(), hover: null, neighbours: new Set(), hoverLinks: new Set(),
                  meta: { root: "", mode: "functions", truncated: false, hidden_noise: 0 }, pendingFit: false };

  const linkKey = (l) => `${idOf(l.source)}|${idOf(l.target)}|${l.kind}`;
  function idOf(end) { return typeof end === "object" && end !== null ? end.id : end; }

  // ------------------------------------------------------------------ host bridge
  function pywebviewApi() { return window.pywebview && window.pywebview.api ? window.pywebview.api : null; }
  function send(message) { if (HOST === "qt") console.log("CGS:" + JSON.stringify(message)); }
  function canExpand() { return HOST === "qt" || pywebviewApi() !== null; }

  function notifySelect(id) {
    if (HOST === "qt") send({ event: "select", uid: id });
    else if (pywebviewApi()) pywebviewApi().select(id);
  }

  async function requestExpand(id) {
    if (HOST === "qt") { send({ event: "expand", uid: id }); return; }  // answer comes through cgs.merge
    const api = pywebviewApi();
    if (!api) return;
    const data = await api.expand(id);
    merge(data);
    redraw();
    updateInfo(data.truncated);
  }

  // ------------------------------------------------------------------ data
  function merge(data) {
    for (const n of data.nodes) if (!state.nodes.has(n.id)) state.nodes.set(n.id, { ...n });
    for (const l of data.links) {
      const k = linkKey(l);
      if (!state.links.has(k) && state.nodes.has(l.source) && state.nodes.has(l.target)) state.links.set(k, { ...l });
    }
  }

  function load(data) {
    state.nodes = new Map();
    state.links = new Map();
    state.hover = null;
    state.neighbours = new Set();
    state.hoverLinks = new Set();
    state.meta = { root: data.root, mode: data.mode, truncated: data.truncated, hidden_noise: data.hidden_noise };
    document.getElementById("details").style.display = "none";
    merge(data);
    redraw();
    updateInfo(data.truncated);
    state.pendingFit = true;
    setTimeout(() => fitIfVisible(false), 1200);
  }

  // A page loaded in a hidden tab has no size yet: fit the camera once it is shown.
  function visible() { return document.visibilityState === "visible" && window.innerWidth > 0 && window.innerHeight > 0; }
  function resize() { if (graph && visible()) graph.width(window.innerWidth).height(window.innerHeight); }
  function fitIfVisible(settled) {  // fit again until the layout has settled
    if (!graph || !state.pendingFit || !visible()) return;
    resize();
    if (settled) state.pendingFit = false;
    graph.zoomToFit(800, 60);
  }
  function shown() { resize(); setTimeout(() => fitIfVisible(false), 300); }
  window.addEventListener("resize", shown);
  document.addEventListener("visibilitychange", shown);

  function visibleData() {
    const showFiles = document.getElementById("files").checked || state.meta.mode === "files";
    const nodes = [...state.nodes.values()].filter((n) => showFiles || n.kind !== "file");
    const ids = new Set(nodes.map((n) => n.id));
    const links = [...state.links.values()].filter((l) => ids.has(idOf(l.source)) && ids.has(idOf(l.target)));
    return { nodes, links };
  }

  // ------------------------------------------------------------------ style
  function nodeColor(n) {
    if (n.is_root) return "#f2c94c";
    if (state.hover && !state.neighbours.has(n.id) && state.hover !== n.id) return "rgba(90,100,110,0.35)";
    if (n.kind === "file" && state.meta.mode !== "files") return "#c9d1d9";  // files mode: colour by language
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

  // ------------------------------------------------------------------ graph (WebGL may be unavailable)
  let graph = null;
  try {
    graph = ForceGraph3D({ controlType: "orbit" })(document.getElementById("graph"))
      .backgroundColor("#0f1419")
      .nodeId("id")
      .nodeLabel(tooltip)
      .nodeColor(nodeColor)
      .nodeVal((n) => (n.kind === "file" && state.meta.mode === "both" ? 7 : 1 + Math.log2(1 + n.fan_in)))
      .cooldownTime(6000)  // modest CPUs (C4): the layout settles within a few seconds
      .onEngineStop(() => fitIfVisible(true))
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
      .onNodeClick((n) => { focus(n); showDetails(n); notifySelect(n.id); })
      .onNodeRightClick((n) => requestExpand(n.id))
      .onLinkClick((l) => send({ event: "link", source: idOf(l.source), target: idOf(l.target), kind: l.kind }));
  } catch (err) {
    graph = null;
    document.getElementById("graph").textContent = "";
    send({ event: "error", message: "3D rendering unavailable: " + err });
  }

  function redraw() { if (graph) graph.graphData(visibleData()); }
  function refreshStyle() { if (graph) graph.nodeColor(graph.nodeColor()).linkColor(graph.linkColor()); }

  function focus(n) {
    if (!graph) return;
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
      + (canExpand() ? "Right-click: expand its neighbours" : "Open in CodeGraph-Sci to expand");
    box.style.display = "block";
  }

  function updateInfo(truncated) {
    const nodes = state.nodes.size, links = state.links.size;
    const text = nodes === 0 ? "No graph yet."
      : `${nodes} node(s), ${links} link(s) · mode ${state.meta.mode}`
        + (state.meta.hidden_noise ? ` · ${state.meta.hidden_noise} utility link(s) hidden` : "")
        + (truncated || state.meta.truncated ? " · limit reached: right-click a node to explore further" : "")
        + (graph ? " · drag to rotate, scroll to zoom, click to select, right-click to expand"
                 : " · 3D rendering unavailable on this machine (WebGL)");
    document.getElementById("info").textContent = text;
    send({ event: "loaded", nodes, links });
  }

  function legend() {
    const langs = Object.entries(LANG_COLORS).map(([k, c]) => `<div><i style="background:${c}"></i>${k}</div>`).join("");
    const kinds = ["calls", "bridges", "binds", "dispatches", "uses", "defines"]
      .map((k) => `<div><b class="line" style="background:${LINK_COLORS[k]}"></b>${k}</div>`).join("");
    document.getElementById("legend").innerHTML =
      `${langs}<div><i style="background:#c9d1d9"></i>file</div><div><i style="background:#f2c94c"></i>root</div><hr style="border-color:#2d3743">${kinds}`;
  }

  document.getElementById("fit").onclick = () => { if (graph) graph.zoomToFit(600, 40); };
  for (const id of ["files", "arrows", "particles"]) {
    document.getElementById(id).onchange = () => { redraw(); refreshStyle(); };
  }
  document.getElementById("search").addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || !graph) return;
    const q = e.target.value.trim().toLowerCase();
    if (!q) return;
    const hit = [...state.nodes.values()].find((n) => n.label.toLowerCase() === q)
      || [...state.nodes.values()].find((n) => n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q));
    if (hit) { const live = graph.graphData().nodes.find((n) => n.id === hit.id); if (live) { focus(live); showDetails(live); } }
  });

  window.cgs = {
    load,
    merge(data) { merge(data); redraw(); updateInfo(data.truncated); },
    shown,
    count() { return { nodes: state.nodes.size, links: state.links.size, webgl: graph !== null }; },
  };
  legend();
  load(JSON.parse(document.getElementById("graph-data").textContent));
  send({ event: "ready", webgl: graph !== null });
})();
