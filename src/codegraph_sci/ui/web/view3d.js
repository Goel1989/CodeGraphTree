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
  const CROSS_DIR = "#39c5cf";  // links between two folders
  const BUCKET_KINDS = new Set(["group", "isolated", "more"]);
  const state = { nodes: new Map(), links: new Map(), hover: null, neighbours: new Set(), hoverLinks: new Set(),
                  meta: { root: "", mode: "functions", truncated: false, hidden_noise: 0, level: "entity" },
                  pendingFit: false, dims: 3, groupBy: "", hidden: { kinds: new Set(), langs: new Set(),
                  statuses: new Set() }, path: "", cycleNodes: new Set(), cycleLinks: new Set(), entries: new Set() };
  const STATUS_COLORS = { ambiguous: "#d29922", external: "#484f58", out_of_scope: "#8957e5" };
  const GROUP_PALETTE = ["#58a6ff", "#3fb950", "#d2a8ff", "#f0883e", "#db61a2", "#39c5cf", "#e3b341", "#a5d6ff",
                         "#7ee787", "#ffa198", "#bc8cff", "#ff7b72"];

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
    state.meta = { root: data.root, mode: data.mode, truncated: data.truncated, hidden_noise: data.hidden_noise,
                   level: data.level || "entity" };
    document.getElementById("details").style.display = "none";
    merge(data);
    placeNonCode();
    buildFilters();
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

  // Non-code files: a fixed grid set apart from the code (one block per category), never linked.
  function placeNonCode() {
    const items = [...state.nodes.values()].filter((n) => n.kind === "noncode")
      .sort((a, b) => (a.note + a.label).localeCompare(b.note + b.label));
    // Just below the code, at a distance that grows with the size of the code graph.
    const code = state.nodes.size - items.length;
    const cols = Math.min(16, Math.max(6, Math.ceil(Math.sqrt(items.length)))), step = 7;
    const y0 = -(40 + 18 * Math.cbrt(Math.max(1, code))), x0 = -((cols - 1) * step) / 2;
    let row = 0, col = 0, category = null;
    for (const n of items) {
      if (category !== null && n.note !== category) { row += col === 0 ? 1 : 2; col = 0; }
      category = n.note;
      n.fx = x0 + col * step; n.fy = y0 - row * step; n.fz = 0;
      col += 1;
      if (col === cols) { col = 0; row += 1; }
    }
  }

  function visibleData() {
    const showFiles = document.getElementById("files").checked || state.meta.mode === "files";
    const showNonCode = document.getElementById("noncode").checked;
    const h = state.hidden, path = state.path;
    const nodes = [...state.nodes.values()].filter((n) => (showFiles || n.kind !== "file")
      && (showNonCode || n.kind !== "noncode") && !h.langs.has(n.lang || "-")
      && (!path || BUCKET_KINDS.has(n.kind) || (n.file || n.id.replace(/^dir:/, "")).startsWith(path)));
    const ids = new Set(nodes.map((n) => n.id));
    const links = [...state.links.values()].filter((l) => ids.has(idOf(l.source)) && ids.has(idOf(l.target))
      && !h.kinds.has(l.kind) && !h.statuses.has(l.status || "resolved"));
    analyse(nodes, links);
    return { nodes, links };
  }

  // Cycles (strongly connected components, iterative Tarjan) and entry points of what is shown.
  function analyse(nodes, links) {
    const out = new Map(nodes.map((n) => [n.id, []]));
    const incoming = new Set();
    for (const l of links) {
      if (l.kind === "defines") continue;
      out.get(idOf(l.source)).push(idOf(l.target));
      incoming.add(idOf(l.target));
    }
    state.entries = new Set(nodes.filter((n) => !BUCKET_KINDS.has(n.kind) && n.kind !== "noncode"
      && !incoming.has(n.id) && out.get(n.id).length > 0).map((n) => n.id));
    const index = new Map(), low = new Map(), onStack = new Set(), stack = [], comp = new Map();
    let counter = 0, compId = 0;
    for (const start of out.keys()) {
      if (index.has(start)) continue;
      const work = [[start, 0]];
      index.set(start, counter); low.set(start, counter); counter++; stack.push(start); onStack.add(start);
      while (work.length) {
        const frame = work[work.length - 1], v = frame[0], next = out.get(v);
        if (frame[1] < next.length) {
          const w = next[frame[1]++];
          if (!index.has(w)) {
            index.set(w, counter); low.set(w, counter); counter++; stack.push(w); onStack.add(w); work.push([w, 0]);
          } else if (onStack.has(w)) low.set(v, Math.min(low.get(v), index.get(w)));
        } else {
          work.pop();
          if (work.length) { const u = work[work.length - 1][0]; low.set(u, Math.min(low.get(u), low.get(v))); }
          if (low.get(v) === index.get(v)) {
            let w;
            do { w = stack.pop(); onStack.delete(w); comp.set(w, compId); } while (w !== v);
            compId++;
          }
        }
      }
    }
    const size = new Map();
    for (const c of comp.values()) size.set(c, (size.get(c) || 0) + 1);
    state.cycleNodes = new Set();
    state.cycleLinks = new Set();
    for (const l of links) {
      const a = idOf(l.source), b = idOf(l.target);
      if (l.kind === "defines") continue;
      if (a === b || (comp.get(a) === comp.get(b) && size.get(comp.get(a)) > 1)) {
        state.cycleLinks.add(linkKey(l)); state.cycleNodes.add(a); state.cycleNodes.add(b);
      }
    }
  }

  function groupOf(n) {
    if (state.groupBy === "language") return n.lang || "-";
    if (state.groupBy === "directory") return n.group || null;
    if (state.groupBy === "parent") {
      const id = n.id.split("(")[0];
      for (const sep of ["::", "."]) { const i = id.lastIndexOf(sep); if (i > id.indexOf(":")) return id.slice(0, i); }
      return n.group || null;
    }
    return null;
  }

  function groupColor(n) {
    const g = groupOf(n);
    if (g === null) return null;
    let h = 0;
    for (const c of String(g)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
    return GROUP_PALETTE[h % GROUP_PALETTE.length];
  }

  // Pulls the members of a group towards their centre (grouping by folder, language, module or class).
  function groupForce() {
    let nodes = [];
    function force(alpha) {
      if (!state.groupBy) return;
      const centres = new Map();
      for (const n of nodes) {
        const g = groupOf(n);
        if (g === null) continue;
        const c = centres.get(g) || { x: 0, y: 0, z: 0, k: 0 };
        c.x += n.x || 0; c.y += n.y || 0; c.z += n.z || 0; c.k += 1;
        centres.set(g, c);
      }
      for (const n of nodes) {
        const c = centres.get(groupOf(n));
        if (!c || c.k < 2) continue;
        const k = 0.12 * alpha;
        n.vx += (c.x / c.k - (n.x || 0)) * k;
        n.vy += (c.y / c.k - (n.y || 0)) * k;
        if (state.dims === 3) n.vz = (n.vz || 0) + (c.z / c.k - (n.z || 0)) * k;
      }
    }
    force.initialize = (ns) => { nodes = ns; };
    return force;
  }

  function checkboxes(id, title, values, hiddenSet) {
    const box = document.getElementById(id);
    box.innerHTML = values.length ? `<b>${title}</b> ` : "";
    for (const v of values) {
      const label = document.createElement("label");
      const input = document.createElement("input");
      input.type = "checkbox"; input.checked = !hiddenSet.has(v);
      input.onchange = () => { if (input.checked) hiddenSet.delete(v); else hiddenSet.add(v); redraw(); refreshStyle(); };
      label.appendChild(input); label.appendChild(document.createTextNode(" " + v));
      box.appendChild(label);
    }
  }

  function buildFilters() {
    const kinds = [...new Set([...state.links.values()].map((l) => l.kind))].sort();
    const langs = [...new Set([...state.nodes.values()].filter((n) => !BUCKET_KINDS.has(n.kind))
                                                         .map((n) => n.lang || "-"))].sort();
    const statuses = [...new Set([...state.links.values()].map((l) => l.status || "resolved"))].sort();
    checkboxes("kindfilter", "Links", kinds, state.hidden.kinds);
    checkboxes("langfilter", "Languages", langs, state.hidden.langs);
    checkboxes("statusfilter", "Status", statuses, state.hidden.statuses);
  }

  // ------------------------------------------------------------------ style
  function nodeColor(n) {
    if (n.is_root) return "#f2c94c";
    if (state.hover && !state.neighbours.has(n.id) && state.hover !== n.id) return "rgba(90,100,110,0.35)";
    if (document.getElementById("cycles").checked && state.cycleNodes.has(n.id)) return "#ff5555";
    if (document.getElementById("entries").checked && state.entries.has(n.id)) return "#3fb950";
    const byGroup = groupColor(n);
    if (byGroup) return byGroup;
    if (n.in_scope === false) return "#8957e5";
    if (n.kind === "file" && state.meta.mode !== "files") return "#c9d1d9";  // files mode: colour by language
    if (n.kind === "external") return "#484f58";
    if (n.kind === "noncode") return "#6b6b6b";
    if (n.kind === "isolated") return "#9e9e9e";
    if (n.kind === "more") return "#4a4a4a";
    if (n.kind === "entry_point") return "#ff7b72";
    return LANG_COLORS[n.lang] || "#8b949e";
  }

  function tooltip(n) {
    const where = n.file ? `${n.file}${n.line ? ":" + n.line : ""}` : "outside the repository";
    return `<b>${escapeHtml(n.label)}</b><br><span style="color:#9e9e9e">${escapeHtml(n.kind)} · ${escapeHtml(n.lang || "-")}</span>`
      + (BUCKET_KINDS.has(n.kind) ? `<br>${escapeHtml(n.note)}<br>click to open`
         : n.kind === "noncode" ? `<br>${escapeHtml(n.note)} · not analyzed code<br>${escapeHtml(n.file || "")}`
         : `<br>${escapeHtml(where)}<br>callers ${n.fan_in} · callees ${n.fan_out}`);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ------------------------------------------------------------------ graph (WebGL may be unavailable)
  let graph = null;
  try {
    graph = ForceGraph3D({ controlType: "orbit" })(document.getElementById("graph"))
      .backgroundColor("#181818")
      .nodeId("id")
      .nodeLabel(tooltip)
      .nodeColor(nodeColor)
      .nodeVal((n) => (BUCKET_KINDS.has(n.kind) ? Math.max(2, n.size)  // radius grows as the cube root of the size
                       : n.kind === "noncode" ? 1
                       : n.kind === "file" && state.meta.mode === "both" ? 7 : 1 + Math.log2(1 + n.fan_in)))
      .cooldownTime(6000)  // modest CPUs (C4): the layout settles within a few seconds
      .onEngineStop(() => fitIfVisible(true))
      .nodeOpacity(0.92)
      .linkColor((l) => (state.hoverLinks.size && !state.hoverLinks.has(linkKey(l)) ? "rgba(60,60,60,0.25)"
                                                                                       : linkColor(l)))
      .linkWidth((l) => (l.kind === "defines" ? 0.3 : Math.min(4, 0.5 + Math.log2(1 + l.count))))
      .linkDirectionalArrowLength((l) => (document.getElementById("arrows").checked && l.kind !== "defines" ? 3.5 : 0))
      .linkDirectionalArrowRelPos(1)
      .linkDirectionalParticles((l) => (document.getElementById("particles").checked
                                        && (l.kind === "bridges" || l.kind === "binds") ? 2 : 0))
      .linkDirectionalParticleWidth(1.6)
      .linkLabel((l) => `${l.kind} · ${l.count} occurrence(s) · ${l.status || "resolved"} · ${l.confidence}`
                        + " · click: evidence")
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
    graph.d3Force("group", groupForce());
  } catch (err) {
    graph = null;
    document.getElementById("graph").textContent = "";
    send({ event: "error", message: "3D rendering unavailable: " + err });
  }

  function linkColor(l) {
    if (document.getElementById("cycles").checked && state.cycleLinks.has(linkKey(l))) return "#ff5555";
    if (STATUS_COLORS[l.status]) return STATUS_COLORS[l.status];
    if (l.cross_dir && document.getElementById("crossdir").checked) return CROSS_DIR;
    return LINK_COLORS[l.kind] || "#6e7681";
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
      + (BUCKET_KINDS.has(n.kind) ? escapeHtml(n.note)
         : canExpand() ? "Right-click: expand its neighbours" : "Open in CodeGraph-Sci to expand");
    box.style.display = "block";
  }

  function updateInfo(truncated) {
    const nodes = state.nodes.size, links = state.links.size;
    const all = [...state.nodes.values()];
    const groups = all.filter((n) => n.kind === "group").length;
    const nonCode = all.filter((n) => n.kind === "noncode").reduce((s, n) => s + (n.size || 1), 0);
    const crossing = [...state.links.values()].filter((l) => l.cross_dir).length;
    const text = nodes === 0 ? "No graph yet."
      : (groups ? `${groups} group(s) shown as spheres · ` : "")
        + `${nodes} node(s), ${links} link(s) (${crossing} between folders)`
        + (nonCode ? ` · ${nonCode} non-code file(s) apart` : "")
        + ` · mode ${state.meta.mode}`
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
      `${langs}<div><i style="background:#c9d1d9"></i>file</div><div><i style="background:#f2c94c"></i>root</div>`
      + `<div><i style="background:#9e9e9e"></i>isolated</div><div><i style="background:#6b6b6b"></i>non-code (apart)</div>`
      + `<hr style="border-color:#3a3a3a">${kinds}`
      + `<div><b class="line" style="background:${CROSS_DIR}"></b>between folders</div>`;
  }

  document.getElementById("fit").onclick = () => { if (graph) graph.zoomToFit(600, 40); };
  function reset() {
    state.hidden = { kinds: new Set(), langs: new Set(), statuses: new Set() };
    state.path = ""; state.groupBy = ""; state.hover = null; state.neighbours = new Set(); state.hoverLinks = new Set();
    document.getElementById("pathfilter").value = ""; document.getElementById("groupby").value = "";
    document.getElementById("details").style.display = "none";
    buildFilters(); redraw(); refreshStyle();
    if (graph) graph.zoomToFit(600, 40);
  }
  function setDims(dims) {
    state.dims = dims;
    document.getElementById("dims").textContent = dims === 3 ? "2D" : "3D";
    if (graph) graph.numDimensions(dims);
  }
  function setGroupBy(value) {
    state.groupBy = value;
    document.getElementById("groupby").value = value;
    refreshStyle();
    if (graph) graph.d3ReheatSimulation();
  }
  document.getElementById("reset").onclick = reset;
  document.getElementById("dims").onclick = () => setDims(state.dims === 3 ? 2 : 3);
  document.getElementById("groupby").onchange = (e) => setGroupBy(e.target.value);
  document.getElementById("pathfilter").addEventListener("input", (e) => { state.path = e.target.value.trim(); redraw(); });
  for (const id of ["cycles", "entries"]) document.getElementById(id).onchange = () => refreshStyle();
  for (const id of ["files", "arrows", "particles", "crossdir", "noncode"]) {
    document.getElementById(id).onchange = () => { redraw(); refreshStyle(); };
  }
  document.getElementById("search").addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || !graph) return;
    const q = e.target.value.trim().toLowerCase();
    if (!q) return;
    const hit = [...state.nodes.values()].find((n) => n.label.toLowerCase() === q)
      || [...state.nodes.values()].find((n) => n.label.toLowerCase().includes(q) || n.id.toLowerCase().includes(q));
    if (hit) {
      const live = graph.graphData().nodes.find((n) => n.id === hit.id);
      if (live) { focus(live); showDetails(live); notifySelect(live.id); }  // the inspector follows (UI audit)
    }
  });

  window.cgs = {
    load,
    merge(data) { merge(data); redraw(); updateInfo(data.truncated); },
    shown,
    count() { return { nodes: state.nodes.size, links: state.links.size, webgl: graph !== null }; },
    // State of what is shown (tests and the host): filters, dimensions, grouping, cycles, entry points.
    stats() {
      const data = visibleData();
      const groups = new Set(data.nodes.map(groupOf).filter((g) => g !== null));
      return { nodes: data.nodes.length, links: data.links.length, dims: state.dims, groupBy: state.groupBy,
               groups: groups.size, cycleNodes: [...state.cycleNodes].sort(), entries: [...state.entries].sort(),
               level: state.meta.level, statuses: [...new Set(data.links.map((l) => l.status || "resolved"))].sort(),
               kinds: [...new Set(data.links.map((l) => l.kind))].sort() };
    },
    filter(options) {  // {kinds, langs, statuses}: hidden values; path: prefix
      for (const key of ["kinds", "langs", "statuses"]) if (options[key]) state.hidden[key] = new Set(options[key]);
      if (typeof options.path === "string") { state.path = options.path; document.getElementById("pathfilter").value = options.path; }
      buildFilters(); redraw(); refreshStyle();
    },
    setDims, setGroupBy, reset,
    // Pairs of panels that overlap (the details panel is measured as if shown); empty when the layout is sound.
    overlaps() {
      const details = document.getElementById("details");
      const shown = details.style.display;
      details.style.display = "block";
      if (!details.textContent) details.textContent = "x".repeat(400);
      const zones = ["side", "legend", "details", "info"].map((id) => [id, document.getElementById(id)])
        .filter(([, e]) => e && getComputedStyle(e).display !== "none")
        .map(([id, e]) => [id, e.getBoundingClientRect()]);
      details.style.display = shown;
      const out = [];
      for (let i = 0; i < zones.length; i++) {
        for (let j = i + 1; j < zones.length; j++) {
          const [a, ra] = zones[i], [b, rb] = zones[j];
          if (ra.left < rb.right && rb.left < ra.right && ra.top < rb.bottom && rb.top < ra.bottom) out.push([a, b]);
        }
      }
      return out;
    },
  };
  legend();
  load(JSON.parse(document.getElementById("graph-data").textContent));
  send({ event: "ready", webgl: graph !== null });
})();
