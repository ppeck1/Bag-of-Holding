/* BOH new UI — Fold Workspace. Vanilla SVG graph per boh_claude_design_anchor_brief_v0_1.md.
   6 projections (Web, Risk Map, Authority Path, Currentness Map, Evidence State, Timeline).
   Full interaction depth: hover tooltip, semantic zoom + label/edge budget, keyboard nav,
   Escape/F/R, camera memory (sessionStorage), cluster expand/collapse.
   Real data from fetchFoldGraph(); node inspector from /api/fold/node. fold.css styles it. */

import { h, hs, mount } from "../dom.js";
import { nsMeta, PLANES, normalizePlaneKey } from "../ns.js";
import { Badge, Button, Icon, Segmented, Accordion, EmptyState, AlertBanner, MarkerPip, Tooltip, WhyCurrent } from "../primitives.js";
import { fetchFoldNode, fetchFoldCluster } from "../api.js";

const LW = 1000, LH = 680;
const PAD = { t: 56, r: 60, b: 64, l: 76 };
const STORE = "boh_fold_cam_v1";

const PROJECTIONS = [
  { id: "web",         name: "Web",            lead: "currentness" },
  { id: "risk",        name: "Risk Map",        lead: "risk · size" },
  { id: "authority",   name: "Authority Path",  lead: "tier · border" },
  { id: "currentness", name: "Currentness Map", lead: "X auth · Y fresh" },
  { id: "evidence",    name: "Evidence State",  lead: "plane · fill" },
  { id: "timeline",    name: "Timeline",        lead: "time · position" },
];
const TOPO_PROJS = new Set(["web", "risk", "authority", "evidence"]);
const WORST_ORDER = ["conflict", "expired", "stale", "unknown", "current"];
const LANE = { interface: 0.12, claim: 0.28, evidence: 0.5, source: 0.74, cluster: 0.9 };

// Authority tier bucket from authority_score (0-1) → 0-3
function authTier(nd) {
  const s = nd.authority_score_raw ?? nd.authP ?? 0;
  if (s >= 0.75) return 3;
  if (s >= 0.5)  return 2;
  if (s >= 0.25) return 1;
  return nd.authTier ?? 0;
}

// CSS-var → resolved color for SVG attributes
const _hc = {};
function hx(token) {
  if (token in _hc) return _hc[token];
  let v = "";
  try { v = getComputedStyle(document.documentElement).getPropertyValue(token).trim(); } catch (_) {}
  return (_hc[token] = v || "#8893a5");
}
function varToHex(s) { return (typeof s === "string" && s.startsWith("var(")) ? hx(s.slice(4, -1).trim()) : (s || "#8893a5"); }
function curColor(c) { return varToHex(nsMeta(c).color); }

function posFor(nd, proj) {
  if (proj === "currentness") return { x: PAD.l + nd.authP * (LW - PAD.l - PAD.r), y: PAD.t + (1 - nd.freshP) * (LH - PAD.t - PAD.b) };
  if (proj === "timeline") {
    const t = nd.time_norm ?? nd.time ?? 0.5;
    const lane = LANE[nd.evKind] ?? 0.5;
    return { x: PAD.l + t * (LW - PAD.l - PAD.r), y: PAD.t + lane * (LH - PAD.t - PAD.b) };
  }
  return { x: PAD.l + nd.bx * (LW - PAD.l - PAD.r), y: PAD.t + nd.by * (LH - PAD.t - PAD.b) };
}
function radiusFor(nd, proj) {
  if (nd.kind === "cluster") return 16;
  if (proj === "risk") return 7 + (nd.risk ?? 0.3) * 15;
  if (proj === "currentness") return 6 + (nd.canon ?? 0.4) * 14;
  return 11;
}
function fillFor(nd, proj) {
  if (proj === "evidence") {
    const pl = nd.plane ? PLANES[nd.plane] : null;
    return pl ? varToHex(pl.color) : hx("--plane-internal");
  }
  const base = curColor(nd.currentness);
  if (proj === "risk") {
    // desaturate low-risk nodes
    const risk = nd.risk ?? 0.3;
    if (risk < 0.3) return lerpHex(base, hx("--text-muted"), 0.55);
  }
  return base;
}
function strokeFor(nd, proj) {
  if (proj === "authority") {
    const tier = authTier(nd);
    const cert = nd.cert ?? false;
    return {
      color: cert ? hx("--accent") : hx("--text-secondary"),
      width: [1, 1.4, 2.2, 3.2][tier] ?? 1.4,
    };
  }
  return { color: hx("--border-strong"), width: 1 };
}

function hexRGB(h) {
  h = (h || "").trim();
  if (h.startsWith("rgb")) { const m = h.match(/\d+/g); return [+m[0], +m[1], +m[2]]; }
  h = h.replace("#", ""); if (h.length === 3) h = h.split("").map(x => x + x).join("");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function lerpHex(a, b, t) {
  const pa = hexRGB(a), pb = hexRGB(b);
  return `rgb(${Math.round(pa[0] + (pb[0] - pa[0]) * t)},${Math.round(pa[1] + (pb[1] - pa[1]) * t)},${Math.round(pa[2] + (pb[2] - pa[2]) * t)})`;
}

const EDGE_STYLE = {
  contradicts:     { stroke: "var(--state-conflict)", dash: "5 4", width: 1.5, arrow: true },
  supersedes:      { stroke: "var(--text-muted)",     dash: "",    width: 2.4, arrow: true, dbl: true },
  supports:        { stroke: "var(--border-strong)",  dash: "",    width: 1.4, arrow: true },
  derived_from:    { stroke: "var(--text-muted)",     dash: "",    width: 1,   arrow: true },
  references:      { stroke: "var(--text-muted)",     dash: "2 4", width: 1,   arrow: false },
  wrapped_as:      { stroke: "var(--border-default)", dash: "",    width: 1,   arrow: false },
  indexed_from:    { stroke: "var(--border-default)", dash: "",    width: 1,   arrow: false },
  governed_by:     { stroke: "var(--state-review)",   dash: "",    width: 1.4, arrow: true },
  requires_review: { stroke: "var(--state-review)",   dash: "",    width: 1.4, arrow: true },
};

// ── persistent interaction state ──────────────────────────────────────────────
const st = {
  proj: "web", view: "canvas",
  sel: null, hover: null,
  expanded: new Set(),
  legendOpen: true,
  cam: loadCam(),
  packet: null, packetFor: null, packetLoading: false,
};
function loadCam() {
  try { return JSON.parse(sessionStorage.getItem(STORE) || "null") || { z: 1, x: 0, y: 0 }; } catch (_) { return { z: 1, x: 0, y: 0 }; }
}
function saveCam() {
  try { sessionStorage.setItem(STORE, JSON.stringify(st.cam)); } catch (_) {}
}

// ── module-level element refs (survive re-renders) ────────────────────────────
const R = {};

// ── exported component ────────────────────────────────────────────────────────
export function FoldWorkspace({ visiblePlanes, data, onToast }) {
  const D = (data && Array.isArray(data.nodes)) ? data : { nodes: [], edges: [] };
  const nodeById = {}; D.nodes.forEach(n => (nodeById[n.id] = n));

  // which nodes are visible (plane filter + cluster logic + hidden/expanded)
  function visNodes() {
    return D.nodes.filter(n => {
      if (n.kind === "cluster") {
        // cluster visible iff at least one member's plane passes the filter
        return D.nodes.some(m => {
          if (m.cluster !== n.id) return false;
          const key = normalizePlaneKey(m.plane);
          return !key || !visiblePlanes || visiblePlanes.includes(key);
        });
      }
      const key = normalizePlaneKey(n.plane);
      if (key && visiblePlanes && !visiblePlanes.includes(key)) return false;
      return !n.hidden || st.expanded.has(n.cluster);
    });
  }

  // Reconcile interaction state against the current plane filter on every render.
  // (st is module-level; must be reconciled here, not from app.js.)
  if (st.sel && !visNodes().some(n => n.id === st.sel)) {
    st.sel = null; st.packet = null; st.packetFor = null;
  }
  if (st.hover && !visNodes().some(n => n.id === st.hover)) { st.hover = null; }

  function visEdges() {
    const vis = new Set(visNodes().map(n => n.id));
    return D.edges.filter(e => vis.has(e.from) && vis.has(e.to));
  }

  // neighborhood of a node (for edge/label budget)
  function hoodOf(id) {
    if (!id) return null;
    const s = new Set([id]);
    visEdges().forEach(e => { if (e.from === id) s.add(e.to); if (e.to === id) s.add(e.from); });
    return s;
  }

  // label budget: show label for selected, hovered, neighbors, high-risk/authority
  function showLabel(nd) {
    if (st.cam.z < 0.65) return false; // far zoom: no labels
    const hood = hoodOf(st.sel || st.hover);
    if (hood && hood.has(nd.id)) return true;
    if (nd.id === st.sel || nd.id === st.hover) return true;
    if (st.cam.z >= 1.2) return true; // near zoom: show all
    // medium zoom: show high-risk/authority/conflict only
    return (nd.risk ?? 0) > 0.7 || (nd.authP ?? 0) > 0.75 || nd.currentness === "conflict" || nd.currentness === "expired";
  }

  // edge budget: only selected-neighborhood edges (unless far zoom shows none, wide shows all)
  function showEdge(e) {
    if (!st.sel && !st.hover) return st.cam.z < 1.6; // default: show if not overloaded
    const active = st.sel || st.hover;
    return e.from === active || e.to === active;
  }

  // ── selection / packet ───────────────────────────────────────────────────
  function select(id) {
    st.sel = st.sel === id ? null : id;
    if (st.sel) loadPacket(st.sel);
    else { st.packet = null; st.packetFor = null; }
    repaintAll();
  }
  function loadPacket(id) {
    if (st.packetFor === id && st.packet) { repaintInspector(); return; }
    st.packet = null; st.packetFor = id; st.packetLoading = true; repaintInspector();
    const nd = nodeById[id];
    const fetcher = (nd && nd.kind === "cluster")
      ? fetchFoldCluster(nd.axis, nd.value)
      : fetchFoldNode(id);
    fetcher.then(pk => {
      if (st.packetFor !== id) return;
      st.packet = (pk && !pk.error) ? pk : null; st.packetLoading = false; repaintInspector();
    });
  }

  // ── camera ────────────────────────────────────────────────────────────────
  let panRef = null;
  function applyCam() {
    if (R.gT) R.gT.setAttribute("transform", `translate(${st.cam.x} ${st.cam.y}) scale(${st.cam.z})`);
    if (R.zoomPct) R.zoomPct.textContent = `${Math.round(st.cam.z * 100)}%`;
    saveCam();
  }
  function zoom(f, cx = LW / 2, cy = LH / 2) {
    const nz = Math.min(3, Math.max(0.4, st.cam.z * f));
    st.cam.x = cx - (cx - st.cam.x) * (nz / st.cam.z);
    st.cam.y = cy - (cy - st.cam.y) * (nz / st.cam.z);
    st.cam.z = nz; applyCam(); repaintEdges(); repaintNodes(); repaintLegend();
  }
  function resetCam() { st.cam = { z: 1, x: 0, y: 0 }; applyCam(); saveCam(); repaintEdges(); repaintNodes(); }
  function fitSel() {
    if (!st.sel) { resetCam(); return; }
    const hood = hoodOf(st.sel);
    const pts = visNodes().filter(n => hood.has(n.id)).map(n => posFor(n, st.proj));
    if (!pts.length) return;
    const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
    const mx = (Math.min(...xs) + Math.max(...xs)) / 2, my = (Math.min(...ys) + Math.max(...ys)) / 2;
    st.cam.x = LW / 2 - mx; st.cam.y = LH / 2 - my; st.cam.z = 1; applyCam(); saveCam();
  }

  const onWheel = e => { e.preventDefault(); const r = R.svgWrap.getBoundingClientRect(); zoom(e.deltaY < 0 ? 1.12 : 0.89, e.clientX - r.left, e.clientY - r.top); };
  const onDown = e => { if (e.target.closest(".fnode")) return; panRef = { sx: e.clientX, sy: e.clientY, ox: st.cam.x, oy: st.cam.y }; };
  const onMove = e => { if (!panRef) return; st.cam.x = panRef.ox + (e.clientX - panRef.sx); st.cam.y = panRef.oy + (e.clientY - panRef.sy); applyCam(); };
  const onUp = () => { if (panRef) { saveCam(); panRef = null; } };
  // Click handling via delegation on the <svg> — robust across SVG event quirks.
  function _nodeIdFromEvent(e) {
    if (!e) return null;
    // 1) prefer target.closest(".fnode"); also try each composedPath() entry's closest.
    const cands = [];
    if (e.target) cands.push(e.target);
    if (typeof e.composedPath === "function") { try { cands.push(...e.composedPath()); } catch (_) { /* ignore */ } }
    for (const t of cands) {
      const g = t && typeof t.closest === "function" ? t.closest(".fnode") : null;
      if (g && typeof g.getAttribute === "function") return g.getAttribute("data-node-id");
    }
    // 2) fall back to walking parent nodes (SVG event-target quirks).
    let n = e.target;
    while (n) {
      const cls = (n.getAttribute && n.getAttribute("class")) || n.className || "";
      if (String(cls).split(" ").includes("fnode")) return n.getAttribute ? n.getAttribute("data-node-id") : null;
      n = n.parentNode || n._parent || null;
    }
    return null;
  }
  const onStageClick = e => { const id = _nodeIdFromEvent(e); if (id) select(id); };
  const onStageDblclick = e => {
    const id = _nodeIdFromEvent(e); if (!id) return;
    const nd = nodeById[id];
    if (nd && nd.kind === "cluster") { st.expanded.has(id) ? st.expanded.delete(id) : st.expanded.add(id); repaintAll(); }
    else { select(id); fitSel(); }
  };
  const onKey = e => {
    const nd = st.sel ? nodeById[st.sel] : null;
    if (e.key === "Escape") { st.sel = null; st.hover = null; repaintAll(); return; }
    if (e.key === "f" || e.key === "F") { fitSel(); return; }
    if (e.key === "r" || e.key === "R") { resetCam(); return; }
    if (!nd || !["ArrowUp","ArrowDown","ArrowLeft","ArrowRight"].includes(e.key)) return;
    e.preventDefault();
    // move selection to closest neighbor in key direction
    const cur = posFor(nd, st.proj);
    const hood = hoodOf(st.sel); hood.delete(st.sel);
    const candidates = [...hood].map(id => ({ id, nd: nodeById[id] })).filter(c => c.nd);
    if (!candidates.length) return;
    const dx = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    const dy = e.key === "ArrowDown" ? 1 : e.key === "ArrowUp" ? -1 : 0;
    let best = null, bestScore = -Infinity;
    candidates.forEach(({ id, nd: c }) => {
      const p = posFor(c, st.proj);
      const score = dx * (p.x - cur.x) + dy * (p.y - cur.y);
      if (score > bestScore) { bestScore = score; best = id; }
    });
    if (best) select(best);
  };

  // ── SVG building ──────────────────────────────────────────────────────────
  function buildDefs() {
    return hs("defs", {},
      ...[["ar-muted","var(--text-muted)"],["ar-conflict","var(--state-conflict)"],
          ["ar-review","var(--state-review)"],["ar-strong","var(--border-strong)"]].map(([id, c]) =>
        hs("marker", { id, viewBox: "0 0 10 10", refX: "9", refY: "5", markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse" },
          hs("path", { d: "M0 0L10 5L0 10z", fill: varToHex(c) }))));
  }

  function buildEdge(e) {
    if (!showEdge(e)) return null;
    const a = nodeById[e.from] ? posFor(nodeById[e.from], st.proj) : null;
    const b = nodeById[e.to]   ? posFor(nodeById[e.to], st.proj) : null;
    if (!a || !b) return null;
    const active = st.sel || st.hover;
    const incident = active && (e.from === active || e.to === active);
    const faded = active && !incident;
    const es = EDGE_STYLE[e.type] || EDGE_STYLE.references;
    const authFade = st.proj === "authority" && !["governed_by","requires_review","supersedes"].includes(e.type);
    const g = hs("g", { class: `fedge ${(faded || (!active && authFade)) ? "faded" : ""}`.trim() });
    const arrowId = es.stroke.includes("conflict") ? "ar-conflict" : es.stroke.includes("review") ? "ar-review" : es.stroke.includes("strong") ? "ar-strong" : "ar-muted";
    const w = (es.width ?? 1) * (st.proj === "authority" && !authFade ? 1.4 : 1);
    if (es.dbl) g.appendChild(hs("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: hx("--bg-app"), "stroke-width": w + 2 }));
    g.appendChild(hs("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, stroke: varToHex(es.stroke), "stroke-width": w, "stroke-dasharray": es.dash || null, "marker-end": es.arrow ? `url(#${arrowId})` : null, "stroke-linecap": "round" }));
    return g;
  }

  function buildNode(nd) {
    const pos = posFor(nd, st.proj);
    const r = radiusFor(nd, st.proj);
    const fill = fillFor(nd, st.proj);
    const { color: strokeColor, width: strokeW } = strokeFor(nd, st.proj);
    const isEv = st.proj === "evidence";
    const hood = hoodOf(st.sel || st.hover);
    const faded = hood && !hood.has(nd.id);
    const selected = st.sel === nd.id, hovered = st.hover === nd.id;

    // Click/double-click are handled by delegation on the <svg> (onStageClick/Dblclick),
    // keyed off this data-node-id. Per-node mouseenter/leave/keydown stay local.
    const g = hs("g", { class: `fnode ${faded ? "faded" : ""}`.trim(), transform: `translate(${pos.x} ${pos.y})`,
      tabindex: "0", role: "button", "aria-label": nd.label, "data-node-id": nd.id,
      // Hover must NOT call repaintNodes(): that replaceChildren()s the node layer and detaches
      // the very element under the pointer mid-hover. Update fade non-destructively + repaint the
      // (separate) edge layer, and let CSS :hover handle node scale/highlight.
      onMouseenter: () => { st.hover = nd.id; applyNodeFade(); repaintEdges(); showTooltip(nd, pos); },
      onMouseleave: () => { st.hover = null; applyNodeFade(); repaintEdges(); hideTooltip(); },
      onKeydown: e => { if (e.key === "Enter") select(nd.id); },
    });

    // shape — class="nshape" enables CSS hover scale + transitions
    const sp = { class: "nshape", fill, stroke: strokeColor, "stroke-width": strokeW };
    if (nd.kind === "cluster") {
      const s = r * 1.25; g.appendChild(hs("rect", { x: -s, y: -s, width: s * 2, height: s * 2, rx: 5, ...sp }));
    } else if (nd.kind === "interface") {
      g.appendChild(hs("polygon", { points: `0,${-r} ${r},0 0,${r} ${-r},0`, ...sp }));
    } else if (isEv && nd.evKind === "source") {
      g.appendChild(hs("rect", { x: -r, y: -r, width: r * 2, height: r * 2, rx: 2, ...sp }));
    } else if (isEv && nd.evKind === "evidence") {
      g.appendChild(hs("polygon", { points: `0,${-r} ${r * 0.92},${r * 0.62} ${-r * 0.92},${r * 0.62}`, ...sp }));
    } else {
      g.appendChild(hs("circle", { r, ...sp }));
    }

    // inner glyph (near zoom or always for clusters)
    const showGlyph = nd.kind === "cluster" || st.cam.z > 1.5;
    if (showGlyph) {
      const glyph = isEv ? (PLANES[nd.plane]?.glyph ?? "?") : nd.kind === "cluster" ? String(nd.count ?? "") : nsMeta(nd.currentness).glyph;
      g.appendChild(hs("text", { "text-anchor": "middle", dy: "0.34em", fill: hx("--bg-app"), style: { fontSize: "9px", fontFamily: "var(--font-mono)", fontWeight: "600", pointerEvents: "none" } }, glyph));
    }

    // evidence projection: currentness corner badge
    if (isEv) g.appendChild(hs("circle", { cx: r * 0.85, cy: -r * 0.85, r: 3.5, fill: curColor(nd.currentness), stroke: hx("--bg-app"), "stroke-width": 1 }));

    // secondary markers
    (nd.markers || []).forEach((m, i) => {
      const mm = nsMeta(m); const ang = -0.6 + i * 0.55; const mr = r + 7;
      const mg = hs("g", { transform: `translate(${Math.cos(ang) * mr} ${Math.sin(ang) * mr})` });
      mg.appendChild(hs("circle", { r: 6, fill: hx("--bg-app"), stroke: varToHex(mm.color), "stroke-width": 1 }));
      mg.appendChild(hs("text", { "text-anchor": "middle", dy: "0.34em", fill: varToHex(mm.color), style: { fontSize: "8px", fontFamily: "var(--font-mono)", pointerEvents: "none" } }, mm.glyph));
      g.appendChild(mg);
    });

    if (selected) g.appendChild(hs("circle", { class: "sel-ring", r: r + 6 }));
    if (hovered && !selected) g.appendChild(hs("circle", { class: "hover-glow", r: r + 4 }));
    // keyboard focus ring (dashed, outside sel-ring) — always in DOM, shown by CSS :focus-visible
    g.appendChild(hs("circle", { class: "focus-ring", r: r + (selected ? 10 : 6) }));

    // label budget
    if (showLabel(nd)) {
      if (nd.kind === "cluster") {
        const visCount = D.nodes.filter(m => {
          if (m.cluster !== nd.id) return false;
          const key = normalizePlaneKey(m.plane);
          return !key || !visiblePlanes || visiblePlanes.includes(key);
        }).length;
        const clusterLabel = visCount === nd.count ? `${nd.label} · ${nd.count}` : `${nd.label} · ${visCount}/${nd.count}`;
        g.appendChild(hs("text", { class: "nlabel", x: 0, y: r * 1.25 + 16, "text-anchor": "middle" }, clusterLabel));
      } else {
        g.appendChild(hs("text", { class: "nlabel", x: r + 9, y: 4 }, nd.label.length > 26 ? nd.label.slice(0, 24) + "…" : nd.label));
      }
    }
    return g;
  }

  // ── canvas overlays ───────────────────────────────────────────────────────
  function buildAxes() {
    const x0 = PAD.l, x1 = LW - PAD.r, y0 = PAD.t, y1 = LH - PAD.b;
    if (st.proj === "currentness") return hs("g", {},
      hs("line", { class: "axis-line", x1: x0, y1: y1, x2: x1, y2: y1 }),
      hs("line", { class: "axis-line", x1: x0, y1: y0, x2: x0, y2: y1 }),
      hs("text", { class: "axis-label", x: x1, y: y1 + 22, "text-anchor": "end" }, "authority pressure →"),
      hs("text", { class: "axis-label", x: x0 - 10, y: y0 - 8, "text-anchor": "start" }, "↑ freshness pressure"),
      hs("text", { class: "quad-label", x: x1 - 12, y: y0 + 16, "text-anchor": "end" }, "high auth · high fresh"),
      hs("text", { class: "quad-label", x: x0 + 8, y: y1 - 10 }, "low auth · low fresh"));
    if (st.proj === "timeline") return hs("g", {},
      hs("line", { class: "axis-line", x1: x0, y1: y1, x2: x1, y2: y1 }),
      hs("text", { class: "axis-label", x: x1, y: y1 + 22, "text-anchor": "end" }, "validity / time →"),
      hs("text", { class: "axis-label", x: x0, y: y1 + 22 }, "older"),
      ...(Object.entries(LANE).map(([k, v]) => hs("text", { class: "quad-label", x: x0 - 8, y: PAD.t + v * (LH - PAD.t - PAD.b) + 4, "text-anchor": "end" }, k))));
    return null;
  }

  // ── tooltip (hover, not React state — direct DOM) ─────────────────────────
  function showTooltip(nd, svgPos) {
    if (!R.tooltip) return;
    const cur = nsMeta(nd.currentness);
    const tier = authTier(nd);
    R.tooltip.innerHTML = `<div class="tt-title">${escHtml(nd.label)}</div>` +
      `<div class="tt-row"><span class="k">State</span><span style="color:${cur.color}">${cur.glyph} ${cur.label}</span></div>` +
      `<div class="tt-row"><span class="k">Authority</span><span>tier ${tier}${nd.cert ? " · cert" : ""}</span></div>` +
      (nd.rawLabel ? `<div class="tt-row"><span class="k">Label</span><span>${escHtml(nd.rawLabel)}</span></div>` : "") +
      (nd.updated ? `<div class="tt-row"><span class="k">Updated</span><span>${escHtml(nd.updated)}</span></div>` : "");
    R.tooltip.style.display = "";
    // position below cursor, inside the stage
    const sr = R.stageWrap ? R.stageWrap.getBoundingClientRect() : { left: 0, top: 0 };
    // convert SVG pos to screen
    const sx = (svgPos.x * st.cam.z + st.cam.x); const sy = (svgPos.y * st.cam.z + st.cam.y);
    const x = Math.min(sx + 16, LW - 200), y = Math.min(sy + 16, LH - 100);
    R.tooltip.style.left = x + "px"; R.tooltip.style.top = y + "px";
  }
  function hideTooltip() { if (R.tooltip) R.tooltip.style.display = "none"; }
  function escHtml(s) { return String(s || "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c])); }

  // ── repaints ──────────────────────────────────────────────────────────────
  // Lightweight (hover / zoom): only touch the SVG node/edge layers + legend.
  function repaintEdges() {
    if (!R.edgeG) return;
    R.edgeG.replaceChildren();
    visEdges().forEach(e => { const el = buildEdge(e); if (el) R.edgeG.appendChild(el); });
  }
  function repaintNodes() {
    if (!R.nodeG) return;
    R.nodeG.replaceChildren();
    visNodes().forEach(nd => R.nodeG.appendChild(buildNode(nd)));
  }
  // Non-destructive neighborhood fade: re-derive each existing node's faded state and update its
  // class attribute in place. Used during hover so the pointer's target node is never recreated.
  function applyNodeFade() {
    if (!R.nodeG) return;
    const hood = hoodOf(st.sel || st.hover);
    (R.nodeG.children || []).forEach(g => {
      if (!g || typeof g.getAttribute !== "function") return;
      const id = g.getAttribute("data-node-id");
      if (!id) return;
      const faded = hood && !hood.has(id);
      g.setAttribute("class", `fnode ${faded ? "faded" : ""}`.trim());
    });
  }
  function repaintLegend() { if (R.legendWrap) mount(R.legendWrap, buildLegend()); }
  // Chrome repaint — rebuild .fold's THREE direct grid children (bar / crumbs / stage)
  // in place. No wrapper divs: the CSS grid (.fold rows auto/auto/1fr, .fold-wrap cols)
  // requires bar/crumbs/stage and .fold/.inspector to be DIRECT children, or the stage
  // collapses to zero height.
  function repaintChrome() {
    if (R.foldCol) mount(R.foldCol, [buildBar(), buildCrumbs(), st.view === "list" ? buildList() : buildStage()]);
  }
  // Inspector-only repaint (e.g. async packet load): replace just the .inspector aside,
  // keeping the existing .fold column (and its live SVG/camera) untouched.
  function repaintInspector() {
    if (R.wrap) R.wrap.replaceChildren(R.foldCol, buildInspectorAside());
  }
  // Full repaint on discrete user actions (select / projection / view / reset).
  function repaintAll() { repaintChrome(); repaintInspector(); }

  // ── build SVG stage ───────────────────────────────────────────────────────
  function buildStage() {
    R.edgeG = hs("g", {}); R.nodeG = hs("g", {});
    R.gT = hs("g", {}, buildAxes(), R.edgeG, R.nodeG);
    visEdges().forEach(e => { const el = buildEdge(e); if (el) R.edgeG.appendChild(el); });
    visNodes().forEach(nd => R.nodeG.appendChild(buildNode(nd)));
    applyCam();

    R.tooltip = h("div", { class: "fold-tooltip", style: { display: "none", position: "absolute", pointerEvents: "none", zIndex: "20" } });
    R.tooltip.innerHTML = "";

    const svg = hs("svg", { class: "fold-svg", viewBox: `0 0 ${LW} ${LH}`, preserveAspectRatio: "xMidYMid meet",
      onWheel, onMousedown: onDown, onMousemove: onMove, onMouseup: onUp, onMouseleave: onUp,
      onClick: onStageClick, onDblclick: onStageDblclick, tabindex: "0",
      onKeydown: onKey },
      buildDefs(), R.gT);
    R.svgWrap = svg;

    R.zoomPct = h("span", { class: "chip is-static" }, `${Math.round(st.cam.z * 100)}%`);
    const meta = h("div", { class: "fold-meta" },
      h("span", { class: "chip is-static" }, (() => {
        const docCount = visNodes().filter(n => n.kind !== "cluster").length;
        const edgeCount = visEdges().filter(e => !e.member).length;
        const allPlaneCount = Object.keys(PLANES).length;
        const planesInfo = (!visiblePlanes || visiblePlanes.length === allPlaneCount) ? "" : ` · Planes: ${visiblePlanes.length}/${allPlaneCount}`;
        return `${docCount} nodes · ${edgeCount} edges${planesInfo}`;
      })()),
      R.zoomPct);
    // NOTE: named zoomControls (not `zoom`) so it does not shadow the outer zoom() function;
    // otherwise the button onClicks would try to invoke this DOM element as a function.
    const zoomControls = h("div", { class: "fold-zoom" },
      h("button", { class: "icon-btn", "aria-label": "Zoom in",  onClick: () => zoom(1.15) }, Icon({ name: "plus" })),
      h("button", { class: "icon-btn", "aria-label": "Zoom out", onClick: () => zoom(0.87) }, h("span", { style: { fontSize: "16px", lineHeight: "1" } }, "−")),
      h("button", { class: "icon-btn", "aria-label": "Reset",    onClick: () => { resetCam(); select(null); } }, Icon({ name: "refresh" })));

    R.legendWrap = h("div", {}, buildLegend());
    R.stageWrap = h("div", { class: "fold-stage", style: { position: "relative" } }, svg, R.legendWrap, meta, zoomControls, R.tooltip);
    return R.stageWrap;
  }

  // ── legend ────────────────────────────────────────────────────────────────
  function buildLegend() {
    const projDef = PROJECTIONS.find(p => p.id === st.proj);
    const states = [["current","✓"],["stale","⚠"],["expired","⧖"],["conflict","!"],["unknown","?"]];
    const markers = [["review","↺"],["blocked","⊘"],["preserved","▢"],["quarantine","⊗"],["advisory","◐"]];
    const head = h("div", { class: "fl-head", onClick: () => { st.legendOpen = !st.legendOpen; repaintLegend(); } },
      h("span", { class: "fl-lead" }, projDef.name.toUpperCase()),
      h("span", { class: "fl-chan" }, `lead: ${projDef.lead}`),
      h("span", { class: "spacer" }), Icon({ name: st.legendOpen ? "chevDown" : "chevRight", size: 13 }));
    if (!st.legendOpen) return h("div", { class: "fold-legend" }, head);
    const stateRow = st.proj === "evidence"
      ? h("div", { class: "fl-row" }, h("span", { class: "fl-key" }, "fill = plane"),
          ...Object.entries(PLANES).map(([k, v]) => h("span", { class: "fl-chip" }, h("span", { class: "g", style: { color: v.color, fontFamily: "var(--font-mono)" } }, v.glyph), v.label)))
      : h("div", { class: "fl-row" }, h("span", { class: "fl-key" }, "fill = current"),
          ...states.map(([k, g]) => h("span", { class: "fl-chip" }, h("span", { class: "g", style: { color: nsMeta(k).color } }, g), nsMeta(k).label)));
    const keys = h("div", { class: "fl-row" }, h("span", { class: "fl-key" }, "kbd"),
      h("span", { class: "fl-chip" }, "↑↓←→ neighbors"), h("span", { class: "fl-chip" }, "F fit"), h("span", { class: "fl-chip" }, "R reset"), h("span", { class: "fl-chip" }, "Esc clear"));
    return h("div", { class: "fold-legend" }, head,
      h("div", { class: "fl-body" }, stateRow,
        h("div", { class: "fl-row" }, h("span", { class: "fl-key" }, "markers"),
          ...markers.map(([k, g]) => h("span", { class: "fl-chip" }, h("span", { class: "g", style: { color: nsMeta(k).color } }, g), nsMeta(k).label))),
        h("div", { class: "fl-row" }, h("span", { class: "fl-key" }, "edges"),
          h("span", { class: "fl-chip", style: { color: "var(--state-conflict)" } }, "⊘ contradicts"),
          h("span", { class: "fl-chip" }, "→ supersedes"),
          h("span", { class: "fl-chip", style: { color: "var(--state-review)" } }, "governed")),
        keys));
  }

  // ── inspector ────────────────────────────────────────────────────────────

  // Cluster member distribution: counts per currentness + weighted summary (0–1).
  // Precedence weights: current=1, unknown=0.6, stale=0.4, expired=0.2, conflict=0.
  const DIST_WEIGHTS = { current: 1, unknown: 0.6, stale: 0.4, expired: 0.2, conflict: 0 };
  function clusterDist(clusterId) {
    const members = D.nodes.filter(n => (n.cluster === clusterId || n.id === clusterId) && n.kind !== "cluster");
    const dist = { current: 0, stale: 0, expired: 0, conflict: 0, unknown: 0 };
    members.forEach(n => { if (n.currentness in dist) dist[n.currentness]++; });
    const total = members.length || 1;
    const weighted = Object.entries(dist).reduce((sum, [k, v]) => sum + v * (DIST_WEIGHTS[k] ?? 0), 0) / total;
    return { dist, total: members.length, weighted };
  }

  function buildInspector() {
    const nd = st.sel ? nodeById[st.sel] : null;
    if (!nd) return h("div", { class: "inspector-body" }, EmptyState({ glyph: "◈", title: "Nothing selected", desc: "Click a node · arrow keys to traverse · Escape to clear" }));

    // Cluster inspector: local distribution + aggregate packet from /api/fold/cluster
    if (nd.kind === "cluster") {
      const { dist, total, weighted } = clusterDist(nd.id);
      const ORDER = ["conflict", "expired", "stale", "unknown", "current"];
      const pk = (st.packetFor === nd.id) ? st.packet : null;
      const loading = st.packetLoading && st.packetFor === nd.id;

      // Aggregate scalar pressures (from backend packet)
      const agg = pk ? (pk.scalar_state || {}) : null;
      const PRESSURE_KEYS = ["authority_score","freshness_score","conflict_pressure","canon_readiness","drift_risk","resolution_confidence"];
      const PRESSURE_LABELS = { authority_score: "Authority", freshness_score: "Freshness", conflict_pressure: "Conflict", canon_readiness: "Canon readiness", drift_risk: "Drift risk", resolution_confidence: "Confidence" };
      const aggSymbolic = pk ? (pk.symbolic_state || {}) : null;
      const aggUnknowns = pk ? (pk.unknowns || []) : [];
      const aggMemberCount = pk && pk.aggregation ? (pk.aggregation.member_count ?? total) : total;

      const distCard = h("div", { class: "card" }, h("div", { class: "card-body col gap-3" },
        h("span", { class: "t-micro muted" }, "Local state distribution"),
        ...ORDER.map(k => dist[k] > 0 && h("div", { class: "col gap-1" },
          h("div", { class: "flex between" },
            h("span", { class: "flex gap-1 items-center" },
              h("span", { style: { color: nsMeta(k).color } }, nsMeta(k).glyph),
              h("span", { class: "t-small" }, nsMeta(k).label)),
            h("span", { class: "t-mono t-small" }, dist[k])),
          h("div", { style: { height: "4px", borderRadius: "999px", background: "var(--bg-input)", overflow: "hidden" } },
            h("div", { style: { width: `${(dist[k] / total) * 100}%`, height: "100%", background: nsMeta(k).color } })))),
        h("div", { class: "flex between", style: { marginTop: "4px", borderTop: "1px solid var(--border-default)", paddingTop: "8px" } },
          h("span", { class: "t-small muted" }, "Weighted currentness"),
          h("span", { class: "t-mono t-small" }, weighted.toFixed(2)))));

      const aggCard = loading
        ? h("div", { class: "card" }, h("div", { class: "card-body t-small muted" }, "Loading aggregate…"))
        : agg
          ? h("div", { class: "card" }, h("div", { class: "card-body col gap-3" },
              h("div", { class: "flex between" },
                h("span", { class: "t-micro muted" }, "Aggregate pressures"),
                aggSymbolic && Badge({ ns: aggSymbolic.currentness_label || "unknown" })),
              ...PRESSURE_KEYS.map(k => {
                const v = agg[k];
                if (v == null) return null;
                const pct = Math.round(v * 100);
                return h("div", { class: "col gap-1" },
                  h("div", { class: "flex between" },
                    h("span", { class: "t-small" }, PRESSURE_LABELS[k] || k),
                    h("span", { class: "t-mono t-small" }, pct + "%")),
                  h("div", { style: { height: "4px", borderRadius: "999px", background: "var(--bg-input)", overflow: "hidden" } },
                    h("div", { style: { width: `${pct}%`, height: "100%", background: "var(--accent)" } })));
              }),
              aggUnknowns.length > 0 && h("div", { class: "t-small", style: { color: "var(--state-stale)", marginTop: "4px" } },
                `${aggUnknowns.length} unknown${aggUnknowns.length > 1 ? "s" : ""}: ${aggUnknowns.map(u => u.field).join(", ")}`)))
          : null;

      return h("div", { class: "inspector-body" },
        h("div", null,
          h("div", { class: "t-subheading", style: { color: "var(--text-primary)" } }, nd.label),
          h("div", { class: "t-small muted" }, `Project cluster · ${aggMemberCount} members`)),
        Badge({ ns: nd.currentness }),
        distCard,
        aggCard,
        h("p", { class: "t-small muted", style: { margin: "8px 0 0" } }, "Double-click to expand members."));
    }

    const pk = (st.packetFor === nd.id) ? st.packet : null;
    const ss = (pk && pk.scalar_state) || {};
    const authP = ss.authority_score ?? nd.authP ?? 0;
    const freshP = ss.freshness_score ?? nd.freshP ?? 0;
    const canon  = ss.canon_readiness  ?? nd.canon  ?? 0;
    const unknowns = (pk && pk.unknowns) || [];
    const traceN = (pk && pk.resolver_trace_summary && pk.resolver_trace_summary.length) || 0;
    const plane = nd.plane ? PLANES[nd.plane] : null;

    return h("div", { class: "inspector-body" },
      h("div", null,
        h("div", { class: "t-subheading", style: { color: "var(--text-primary)" } }, nd.label),
        h("div", { class: "t-small muted" }, (st.packetLoading && st.packetFor === nd.id) ? "loading…" : (nd.rawLabel ? `label: ${nd.rawLabel}` : nd.id))),
      h("div", { class: "flex gap-2 wrap items-center" },
        Badge({ ns: nd.currentness }),
        plane && h("span", { class: "t-small", style: { color: plane.color, fontFamily: "var(--font-mono)" } }, `${plane.glyph} ${plane.label}`),
        ...(nd.markers || []).map(m => Badge({ ns: m }))),
      h("div", { class: "card" }, h("div", { class: "card-body col gap-3" },
        h("span", { class: "t-micro muted" }, "Dimensional pressures"),
        presBar("Authority", authP, "var(--accent)"),
        presBar("Freshness", freshP, "var(--state-current)"),
        presBar("Canon readiness", canon, "var(--plane-canonical)"),
        h("span", { class: "t-small muted" }, "Pressures, not truth values."))),
      Accordion({ items: [
        // FOLD-24: Why-current factor rows — prefer the backend's provenance-tagged
        // rows (direct/computed/inferred/unknown) from the live packet; fall back to
        // client-side synthesis only when the packet has not loaded yet.
        { id: "why", title: "Why current?", defaultOpen: true,
          body: WhyCurrent({ rows: (pk && Array.isArray(pk.why_current) && pk.why_current.length) ? pk.why_current : whyRows(nd, ss), onTrace: () => onToast && onToast("Routing to Authority & Audit → Trace & Gates.", "review") }) },
        // FOLD-25: authority facets
        { id: "auth", title: "Authority", defaultOpen: true, body: h("div", { class: "kv" },
          kvRow("Tier", authTier(nd) > 0 ? `${authTier(nd)}` : "unmapped (placeholder)"),
          kvRow("Certificate", nd.cert ? "✓ confirmed" : "none"),
          kvRow("Authority pressure", authP.toFixed(2)),
          nd.cert && nd.rawLabel && kvRow("Cert ref", nd.rawLabel, null, true)) },
        // FOLD-21: Fold Snapshot (renamed from "Symbolic state")
        { id: "snap", title: "Fold Snapshot", defaultOpen: false, body: pk && pk.symbolic_state
          ? h("div", { class: "kv" }, ...Object.entries(pk.symbolic_state).filter(([k]) => k.endsWith("_label")).map(([k, v]) =>
              h("div", { class: "kv-row" }, h("span", { class: "k" }, k.replace("_label", "")), h("span", { class: "v" }, String(v)))))
          : h("span", { class: "t-small muted" }, "—") },
        { id: "unk", title: "Unknowns", meta: Badge({ ns: "unknown", label: String(unknowns.length), glyph: "", className: "solidless" }),
          body: unknowns.length
            ? h("ul", { style: { margin: 0, paddingLeft: "16px", color: "var(--text-secondary)" } }, unknowns.map(u => h("li", { class: "t-small" }, u.meaning || u.field || String(u))))
            : h("span", { class: "t-small muted" }, "None.") },
        { id: "trace", title: "Resolver trace", meta: Badge({ ns: "review", label: String(traceN), glyph: "", className: "solidless" }),
          body: h("div", { class: "flex gap-2 items-center" },
            h("span", { class: "t-small muted" }, `${traceN} events`),
            Button({ variant: "governed", glyph: "↺", className: "sm", onClick: () => onToast && onToast("Routing to Authority & Audit → Trace & Gates.", "review"), children: ["View full trace"] })) },
      ] }));
  }
  function kvRow(k, v, color, mono) {
    return h("div", { class: "kv-row" }, h("span", { class: "k" }, k),
      h("span", { class: "v" + (mono ? " t-mono" : ""), style: color ? { color } : null }, v));
  }

  // Synthesize Why-current rows (FOLD-24) from scalar packet + node fields.
  // Uses live packet values when available; falls back to node fields.
  function whyRows(nd, ss) {
    const authP  = Number(ss.authority_score ?? nd.authP ?? 0);
    const freshP = Number(ss.freshness_score ?? nd.freshP ?? 0);
    const hasCert   = !!(nd.cert);
    const isConflict = nd.currentness === "conflict";
    const isBlocked  = (nd.markers || []).includes("blocked");
    const needsReview = (nd.markers || []).includes("review");
    const tier = authTier(nd);
    return [
      { dir: freshP >= 0.6 ? "pos" : "weak",
        factor: "Source freshness",
        evi: freshP >= 0.6 ? `pressure ${freshP.toFixed(2)}` : `aging — pressure ${freshP.toFixed(2)}` },
      { dir: hasCert ? "pos" : (authP >= 0.5 ? "pos" : "weak"),
        factor: "Authority",
        evi: hasCert ? `cert confirmed · tier ${tier}` : (tier > 0 ? `tier ${tier} · no certificate` : "authority tier: unmapped (placeholder)") },
      { dir: isConflict ? "weak" : "pos",
        factor: "Open conflicts",
        evi: isConflict ? "1 open conflict" : "none" },
      ...(isBlocked  ? [{ dir: "weak",    factor: "Gate",           evi: "blocked" }] : []),
      ...(needsReview ? [{ dir: "weak",   factor: "Review required", evi: "awaiting reviewer" }] : []),
    ];
  }

  function presBar(label, v, tone) {
    v = Math.max(0, Math.min(1, Number(v) || 0));
    return h("div", { class: "col gap-1" },
      h("div", { class: "flex between" }, h("span", { class: "t-small muted" }, label), h("span", { class: "t-mono" }, v.toFixed(2))),
      h("div", { style: { height: "5px", borderRadius: "999px", background: "var(--bg-input)", overflow: "hidden" } },
        h("div", { style: { width: `${v * 100}%`, height: "100%", background: tone } })));
  }

  // ── list view ────────────────────────────────────────────────────────────
  function buildList() {
    const ns = visNodes().filter(n => n.kind !== "cluster");
    return h("div", { class: "fold-list" }, h("div", { class: "card", style: { overflow: "hidden" } },
      h("div", { style: { overflowX: "auto" } }, h("table", { class: "tbl" },
        h("thead", null, h("tr", null,
          h("th", { style: { width: "130px" } }, "State"), h("th", null, "Document"),
          h("th", { style: { width: "120px" } }, "Authority"), h("th", { style: { width: "130px" } }, "Markers"),
          h("th", { class: "num", style: { width: "80px" } }, "Risk"))),
        h("tbody", null, ns.map(nd => h("tr", { class: st.sel === nd.id ? "selected" : "", tabindex: "0",
          onClick: () => select(nd.id), onKeydown: e => { if (e.key === "Enter") select(nd.id); } },
          h("td", null, Badge({ ns: nd.currentness })),
          h("td", null, h("span", { class: "doc-title" }, nd.label)),
          h("td", null, nd.rawLabel || "—"),
          h("td", null, (nd.markers || []).length ? h("span", { class: "flex gap-1" }, nd.markers.map(m => MarkerPip({ ns: m }))) : h("span", { class: "muted" }, "—")),
          h("td", { class: "num muted" }, (nd.risk ?? 0).toFixed(2)))))))));
  }

  // ── assemble ──────────────────────────────────────────────────────────────
  if (!D.nodes.length) {
    return h("div", { class: "fold-wrap" },
      h("div", { class: "fold" }, h("div", { class: "content content-narrow" },
        EmptyState({ glyph: "◈", title: "No fold data", desc: "Index documents to populate the Fold Workspace." }))),
      h("aside", { class: "inspector" }, h("div", { class: "inspector-head" }, h("span", { class: "t-micro" }, "Inspector")),
        h("div", { class: "inspector-body" }, EmptyState({ glyph: "◈", title: "Nothing selected", desc: "No documents to inspect." }))));
  }

  // Builders — each reads current `st`, so a repaint reflects the latest selection/projection.
  function buildBar() {
    return h("div", { class: "fold-bar" },
      h("div", { class: "proj-switch", role: "group", "aria-label": "Projection" },
        PROJECTIONS.map(p => h("button", { class: `proj-seg ${st.proj === p.id ? "active" : ""}`.trim(), onClick: () => { if (st.proj !== p.id) { st.proj = p.id; repaintAll(); } } },
          h("span", { class: "ps-name" }, p.name), h("span", { class: "ps-lead" }, p.lead)))),
      // FOLD-04: reserved overlay selector — v1 always None; populated when overlay atlas is wired
      Tooltip({ text: "Perceptual overlays reserved for a future phase. No overlay is active.", children: [
        h("span", { class: "overlay-none" },
          h("span", { class: "bar-label t-small" }, "Overlay"),
          h("span", { class: "chip is-static" }, "None")) ] }),
      h("span", { class: "spacer" }),
      Segmented({ sm: true, value: st.view, onChange: v => { if (st.view !== v) { st.view = v; repaintAll(); } }, options: [{ value: "canvas", label: "Canvas" }, { value: "list", label: "List" }] }),
      Button({ variant: "secondary", className: "sm", glyph: "⤢", onClick: fitSel, children: ["Fit"] }));
  }

  function buildCrumbs() {
    const sel = st.sel ? nodeById[st.sel] : null;
    return h("div", { class: "fold-crumbs" },
      h("span", { class: sel ? "crumb" : "crumb last", onClick: () => select(null) }, "Bag of Holding"),
      ...(sel ? [h("span", { class: "sep" }, "›"), h("span", { class: "crumb last" }, sel.label)] : []));
  }

  function buildInspectorAside() {
    // .inspector is a flex column: head + body (buildInspector returns .inspector-body).
    return h("aside", { class: "inspector" },
      h("div", { class: "inspector-head" }, h("span", { class: "t-micro" }, "Inspector"),
        h("span", { class: "spacer" }),
        st.sel && h("button", { class: "icon-btn", "aria-label": "Clear", onClick: () => select(null) }, Icon({ name: "close", size: 14 }))),
      buildInspector());
  }

  // Stable refs to the two grid containers; repaints replace their DIRECT children
  // in place so the CSS grid contract (and the stage's 1fr height) is preserved.
  R.foldCol = h("div", { class: "fold" }, buildBar(), buildCrumbs(), st.view === "list" ? buildList() : buildStage());
  R.wrap    = h("div", { class: "fold-wrap" }, R.foldCol, buildInspectorAside());
  return R.wrap;
}
