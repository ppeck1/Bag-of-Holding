/* BOH new UI (Phase A) — data layer + adapter.
   Read-only fetches to existing endpoints, normalized into the shape the screens
   consume. The currentness namespace is INFERRED from the backend coherence/conflict
   summary (no native currentness endpoint yet) — callers surface this via `inferred`. */

export async function api(path, opts) {
  try {
    const res = await fetch(path, opts);
    const ct = res.headers.get("content-type") || "";
    const body = ct.includes("application/json") ? await res.json() : await res.text();
    if (!res.ok) return { error: (body && body.detail) || `HTTP ${res.status}` };
    return body;
  } catch (e) {
    return { error: String(e && e.message || e) };
  }
}

export function escHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Read the session operator token (tab-local, never sent to a server unencrypted). */
export function getToken() {
  return sessionStorage.getItem("boh_operator_token") || "";
}

/** Build request headers including the operator token when set. */
export function tokenHeaders(extra = {}) {
  const tok = getToken();
  return {
    "Content-Type": "application/json",
    ...(tok ? { "X-BOH-Operator-Token": tok } : {}),
    ...extra,
  };
}

/** Operator-token header ONLY — for multipart/FormData uploads where the browser
 *  must set Content-Type (including the multipart boundary) itself. */
export function tokenHeadersMultipart(extra = {}) {
  const tok = getToken();
  return {
    ...(tok ? { "X-BOH-Operator-Token": tok } : {}),
    ...extra,
  };
}

/* status value (canonical/draft/conflict/…) → currentness namespace. Best-effort. */
function currentnessOf(status) {
  const s = String(status || "").toLowerCase();
  if (/conflict/.test(s)) return "conflict";
  if (/(archiv|superseded|expired|legacy)/.test(s)) return "expired";
  if (/(draft|working|review|scratch|proposed)/.test(s)) return "stale";
  if (/(canon|derived|reference|stable|current)/.test(s)) return "current";
  return "unknown";
}

function statusCellsFrom(st) {
  if (!st || st.error) return null;
  const ol = st.ollama || {};
  const ollamaVal = ol.enabled ? (ol.available ? "AVAILABLE" : "ENABLED / DOWN") : "OPTIONAL / OFF";
  const errs = st.index_errors || 0;
  return [
    { label: "Server",        value: (st.server || "—").toUpperCase(), tone: st.server === "ok" ? "current" : "stale", kind: "dot" },
    { label: "Last indexed",  value: st.last_indexed_at ? String(st.last_indexed_at) : "never", tone: "primary", kind: "text" },
    { label: "Indexed docs",  value: String(st.indexed_docs ?? "—"), tone: "primary", kind: "text" },
    { label: "Graph edges",   value: String(st.graph_edges ?? "—"), tone: "muted", kind: "text" },
    { label: "Review queue",  value: String((st.review_queue && st.review_queue.pending) ?? 0), tone: "muted", kind: "text" },
    { label: "Index errors",  value: String(errs), tone: errs > 0 ? "stale" : "current", kind: "dot" },
    { label: "Ollama",        value: ollamaVal, tone: ol.available ? "current" : "muted", kind: "dot" },
  ];
}

/** Status screen data. */
export async function fetchStatus() {
  const st = await api("/api/status");
  return { statusCells: statusCellsFrom(st) || [], raw: st };
}

/** Overview data: currentness tiles (inferred), node count, recent docs, status cells. */
export async function fetchOverview() {
  const [dash, coh, st, docsResp] = await Promise.all([
    api("/api/dashboard"),
    api("/api/coherence/summary"),
    api("/api/status"),
    api("/api/docs?per_page=8"),
  ]);
  if (dash && dash.error && coh && coh.error) {
    return { error: dash.error };
  }

  const c = (coh && coh.counts) || {};
  const conflicts = (dash && (dash.conflicts ?? dash.open_conflicts ?? dash.conflict_docs)) ?? 0;
  const expired = (dash && dash.epistemic_expired) ?? ((c.stale || 0) + (c.critical_decay || 0));
  const unknown = (dash && dash.epistemic_no_state) ?? 0;

  const metrics = [
    { key: "current",  ns: "current",  count: c.fresh || 0,  delta: "from coherence", dir: "flat" },
    { key: "stale",    ns: "stale",    count: c.aging || 0,  delta: "from coherence", dir: "flat" },
    { key: "expired",  ns: "expired",  count: expired || 0,  delta: "inferred",       dir: "flat" },
    { key: "conflict", ns: "conflict", count: conflicts || 0,delta: "open conflicts", dir: "flat" },
    { key: "unknown",  ns: "unknown",  count: unknown || 0,  delta: "no epistemic state", dir: "flat" },
  ];

  const items = (docsResp && (docsResp.docs || docsResp.items)) || [];
  const recentDocs = items.map((d, i) => ({
    id: d.id || d.doc_id || `doc-${i}`,
    title: d.title || d.name || "(untitled)",
    path: d.path || null,
    project: d.project || "—",
    authority: d.authority || d.status || "—",
    currentness: currentnessOf(d.status || d.authority),
    markers: [],
    lifecycle: d.lifecycle || d.status || "—",
    action: "",
    updated: d.updated || d.updated_at || d.indexed_at || "—",
  }));

  const nodeCount = (dash && dash.total_docs) ?? recentDocs.length;

  return {
    inferred: true,
    metrics,
    nodeCount,
    recentDocs,
    statusCells: statusCellsFrom(st) || [],
  };
}

/* ---- Fold Workspace (Phase B) ---- */

const clamp01 = (v) => Math.max(0, Math.min(1, Number(v) || 0));

function withLibrary(path, activeLibraryId) {
  const id = activeLibraryId || "all";
  if (id === "all") return path;
  const joiner = path.includes("?") ? "&" : "?";
  return `${path}${joiner}library_id=${encodeURIComponent(id)}`;
}

/** Backend currentness label set (9) → the design's 5 fill values. Documented reduction;
 *  quarantined/held also surface as secondary markers so nothing is hidden. */
export function foldCurrentness(label) {
  const s = String(label || "").toLowerCase();
  if (s === "conflicted" || s === "current_but_contested") return "conflict";
  if (s === "stale") return "stale";
  if (s === "superseded" || s === "expired") return "expired";
  if (s === "current" || s === "draft_current") return "current";
  return "unknown"; // unknown, quarantined, held
}
function foldMarkers(label) {
  const s = String(label || "").toLowerCase();
  if (s === "quarantined") return ["quarantine"];
  if (s === "held") return ["preserved"];
  return [];
}
/** Backend edge relationship → the prototype edgeStyle keys. */
function normEdge(t) {
  const s = String(t || "").toLowerCase();
  if (/(contradict|conflict)/.test(s)) return "contradicts";
  if (/supersede/.test(s)) return "supersedes";
  if (/support/.test(s)) return "supports";
  if (/(deriv|lineage)/.test(s)) return "derived_from";
  if (/(review|governed)/.test(s)) return "governed_by";
  return "references";
}
/** Build a min→max normalizer to 0..1; null if not enough spread. */
function normalizer(vals) {
  const nums = vals.filter((v) => typeof v === "number" && isFinite(v));
  if (nums.length < 2) return null;
  const lo = Math.min(...nums), hi = Math.max(...nums);
  if (hi - lo < 1e-9) return null;
  return (v) => (v - lo) / (hi - lo);
}
// deterministic golden-angle scatter fallback when backend gives no coords
function fbx(i, n) { return 0.5 + 0.42 * Math.sqrt((i + 0.5) / n) * Math.cos(i * 2.399963); }
function fby(i, n) { return 0.5 + 0.42 * Math.sqrt((i + 0.5) / n) * Math.sin(i * 2.399963); }

/** canonical_layer string → plane key matching the PLANES dict in ns.js. */
function layerToPlane(layer) {
  const s = String(layer || "").toLowerCase();
  if (/canon/.test(s)) return "canonical";
  if (/inform/.test(s)) return "informational";
  if (/subject/.test(s)) return "subjective";
  if (/evid/.test(s)) return "evidence";
  if (/intern/.test(s)) return "internal";
  if (/review/.test(s)) return "review";
  if (/conflict/.test(s)) return "conflict";
  if (/arch/.test(s)) return "archive";
  return "internal";
}
/** evKind from corpusClass / document_class string */
function evKindOf(cls) {
  const s = String(cls || "").toLowerCase();
  if (/interface|cert/.test(s)) return "interface";
  if (/evidence|proof/.test(s)) return "evidence";
  if (/source|artifact/.test(s)) return "source";
  return "claim";
}
/** Normalize time from epistemic_valid_until (ISO string or null) → 0-1. */
function timeNorm(val, allVals) {
  if (!val) return null;
  try {
    const t = new Date(val).getTime();
    if (!isFinite(t)) return null;
    const nums = allVals.filter(Boolean).map(v => { try { return new Date(v).getTime(); } catch (_) { return null; } }).filter(v => v != null && isFinite(v));
    if (nums.length < 2) return 0.5;
    const lo = Math.min(...nums), hi = Math.max(...nums);
    return hi === lo ? 0.5 : (t - lo) / (hi - lo);
  } catch (_) { return null; }
}
function scopeValue(scopeId, axis) {
  const prefix = `${axis}:`;
  const s = String(scopeId || "");
  return s.startsWith(prefix) ? s.slice(prefix.length) : "";
}
function displayValue(value) {
  return String(value || "").replace(/\b\w/g, (m) => m.toUpperCase());
}
function addClusterMembership(nd, axis, clusterId) {
  nd.clusters = nd.clusters || {};
  const current = nd.clusters[axis];
  const next = Array.isArray(current) ? current : (current ? [current] : []);
  if (!next.includes(clusterId)) next.push(clusterId);
  nd.clusters[axis] = next;
  if (axis === "project") {
    nd.cluster = clusterId;
    nd.hidden = true;
  }
}

/** Joined Fold graph: /api/fold/library (currentness + scalar pressures) merged with
 *  /api/graph/projection web (topology + edges + constraint fields) by doc id.
 *  All 6 projection axes are populated: authP/freshP/canon (Currentness Map),
 *  bx/by (topology: Web/Risk/Authority/Evidence), risk/drift_risk (Risk Map),
 *  authority_score_raw/cert (Authority Path), plane/evKind (Evidence State),
 *  time_norm (Timeline). */
export async function fetchFoldGraph(activeLibraryId) {
  const [lib, web, domainCorpus] = await Promise.all([
    api(withLibrary("/api/fold/library", activeLibraryId)),
    api(withLibrary("/api/graph/projection?mode=web&max_nodes=300", activeLibraryId)),
    api(withLibrary("/api/fold/corpus/domain", activeLibraryId)),
  ]);
  if ((lib && lib.error) && (web && web.error)) return { error: lib.error };

  const byId = {};
  for (const d of (lib && lib.docs) || []) {
    const cv = d.canon_variables ?? {};
    const driftRate = cv.drift_rate   ?? null;
    const gamma     = cv.gamma        ?? null;
    const authP     = clamp01(d.authority_score);
    // Risk Map: drift_rate supplements the composite; falls back to conflict_pressure
    const risk = clamp01(Math.max(driftRate ?? d.conflict_pressure ?? 0, d.conflict_pressure ?? 0));
    byId[d.doc_id] = {
      id: d.doc_id, label: d.title || d.doc_id, path: d.path || null, kind: "document", evKind: "claim",
      currentness: foldCurrentness(d.currentness_label), rawLabel: d.currentness_label,
      markers: foldMarkers(d.currentness_label),
      authP,
      freshP: clamp01(d.freshness_score),
      canon: clamp01(d.canon_readiness),
      risk,
      authority_score_raw: d.authority_score,
      // Derived CANON policy variables (omega/mismatch are null in batch; the
      // node inspector fetches the full packet for exact values).
      driftRate,
      entropy:      cv.entropy           ?? null,
      deltaCStar:   cv.delta_c_star      ?? null,
      gamma,
      omegaViability:   cv.omega_viability   ?? null,
      mismatchGradient: cv.mismatch_gradient ?? null,
      effectiveAuthP: gamma ?? authP,
      plane: null, cert: false, clusters: {},
      bx: null, by: null, time_norm: null,
      epistemicD: null, epistemicQ: null, epistemicC: null,
      constraintZone: null, custodianLane: null, authorityState: null,
    };
  }

  const wnodes = (web && web.nodes) || [];
  const nx = normalizer(wnodes.map(n => n.x));
  const ny = normalizer(wnodes.map(n => n.y));
  const allDates = wnodes.map(n => n.epistemic_valid_until);

  wnodes.forEach((n, i) => {
    const id = n.id;
    const nd = byId[id] || (byId[id] = {
      id, label: n.label || n.title || id, path: n.path || null, kind: "document", evKind: "claim",
      currentness: foldCurrentness(n.currentness_label || n.status), markers: [],
      authP: 0.5, freshP: 0.5, canon: 0.4, risk: 0.3, authority_score_raw: null,
      plane: null, cert: false, clusters: {}, bx: null, by: null, time_norm: null,
      epistemicD: null, epistemicQ: null, epistemicC: null,
      constraintZone: null, custodianLane: null, authorityState: null,
    });
    nd.bx = (typeof n.x === "number" && nx) ? nx(n.x) : fbx(i, Math.max(1, wnodes.length));
    nd.by = (typeof n.y === "number" && ny) ? ny(n.y) : fby(i, Math.max(1, wnodes.length));
    nd.path = n.path || nd.path || null;
    nd.corpusClass = n.corpusClass; nd.status = n.status; nd.project = n.project || null;
    nd.epistemicD = n.epistemic_d ?? n.epistemicD ?? nd.epistemicD ?? null;
    nd.epistemicQ = n.epistemic_q ?? n.epistemicQ ?? nd.epistemicQ ?? null;
    nd.epistemicC = n.epistemic_c ?? n.epistemicC ?? nd.epistemicC ?? null;
    nd.constraintZone = n.constraint_zone ?? n.constraintZone ?? nd.constraintZone ?? null;
    nd.custodianLane = n.custodian_lane ?? n.custodianLane ?? nd.custodianLane ?? null;
    nd.authorityState = n.authority_state ?? n.authorityState ?? nd.authorityState ?? null;
    // Risk Map: preserve composite; drift_rate (from canon_variables) supplements drift_risk
    const cm = n.constraint_metrics || {};
    if (cm.drift_risk != null || cm.conflict_pressure != null) {
      nd.risk = clamp01(Math.max(nd.driftRate ?? cm.drift_risk ?? 0, cm.conflict_pressure ?? 0, cm.projection_loss ?? 0));
    }
    // Authority Path: cert inferred from authority_state
    nd.authority_score_raw = nd.authority_score_raw ?? (n.canonScore != null ? n.canonScore : null);
    nd.cert = /cert|verified|authorit/.test(String(n.authority_state || "").toLowerCase());
    // Evidence State: plane from canonical_layer
    nd.plane = layerToPlane(n.canonical_layer || n.canonicalLayer);
    nd.evKind = evKindOf(n.corpusClass || n.document_class);
    // Timeline: normalized date
    nd.time_norm = timeNorm(n.epistemic_valid_until, allDates);
  });

  const all = Object.values(byId);
  // fill fallback bx/by and time_norm for library-only nodes
  all.forEach((nd, i) => {
    if (nd.bx == null) { nd.bx = fbx(i, all.length); nd.by = fby(i, all.length); }
    if (nd.plane == null) nd.plane = "informational";
    if (nd.time_norm == null) nd.time_norm = (nd.authP + nd.freshP) / 2;
  });

  // Build project cluster nodes (≥2 members per project).
  const WORST_ORDER = ["conflict", "expired", "stale", "unknown", "current"];
  const projectGroups = {};
  all.forEach(nd => { if (nd.project) (projectGroups[nd.project] = projectGroups[nd.project] || []).push(nd); });
  const clusterNodes = [];
  Object.entries(projectGroups).forEach(([project, members]) => {
    if (members.length < 2) return;
    const cid = `cluster:project:${project}`;
    members.forEach(nd => addClusterMembership(nd, "project", cid));
    const bx = members.reduce((s, n) => s + (n.bx ?? 0.5), 0) / members.length;
    const by = members.reduce((s, n) => s + (n.by ?? 0.5), 0) / members.length;
    let worst = "current";
    members.forEach(n => { if (WORST_ORDER.indexOf(n.currentness) < WORST_ORDER.indexOf(worst)) worst = n.currentness; });
    clusterNodes.push({
      id: cid, kind: "cluster", label: project, axis: "project", value: project,
      count: members.length, currentness: worst, markers: [],
      authP: members.reduce((s, n) => s + n.authP, 0) / members.length,
      freshP: members.reduce((s, n) => s + n.freshP, 0) / members.length,
      canon: members.reduce((s, n) => s + n.canon, 0) / members.length,
      risk: Math.max(...members.map(n => n.risk ?? 0)),
      driftRate: null, entropy: null, deltaCStar: null, gamma: null, effectiveAuthP: null,
      bx, by, time_norm: null, cert: false, plane: null,
      epistemicD: null, epistemicQ: null, epistemicC: null,
      constraintZone: null, custodianLane: null, authorityState: null,
    });
  });

  // Build domain cluster nodes from the resolved backend domain corpus. The
  // corpus lists registered domains; each cluster packet tells us whether it
  // has actual linked document contributors, so empty domains are not visualized.
  const domainValues = [...new Set(((domainCorpus && !domainCorpus.error && domainCorpus.contributors) || [])
    .map(c => scopeValue(c.scope_id, "domain"))
    .filter(Boolean))];
  if (domainValues.length) {
    const domainPackets = await Promise.all(domainValues.map(async value => ({
      value,
      packet: await fetchFoldCluster("domain", value, activeLibraryId),
    })));
    domainPackets.forEach(({ value, packet }) => {
      if (!packet || packet.error) return;
      const memberIds = ((packet.contributors || []).map(c => c.scope_id).filter(id => byId[id]));
      if (!memberIds.length) return;
      const members = memberIds.map(id => byId[id]);
      const cid = `cluster:domain:${value}`;
      members.forEach(nd => addClusterMembership(nd, "domain", cid));
      const bx = members.reduce((s, n) => s + (n.bx ?? 0.5), 0) / members.length;
      const by = members.reduce((s, n) => s + (n.by ?? 0.5), 0) / members.length;
      const ss = packet.scalar_state || {};
      clusterNodes.push({
        id: cid, kind: "cluster", label: displayValue(value), axis: "domain", value,
        count: members.length,
        currentness: foldCurrentness(packet.symbolic_state && packet.symbolic_state.currentness_label),
        rawLabel: packet.symbolic_state && packet.symbolic_state.currentness_label,
        markers: [],
        authP: clamp01(ss.authority_score ?? (members.reduce((s, n) => s + n.authP, 0) / members.length)),
        freshP: clamp01(ss.freshness_score ?? (members.reduce((s, n) => s + n.freshP, 0) / members.length)),
        canon: clamp01(ss.canon_readiness ?? (members.reduce((s, n) => s + n.canon, 0) / members.length)),
        risk: clamp01(ss.drift_risk ?? Math.max(...members.map(n => n.risk ?? 0))),
        driftRate: null, entropy: null, deltaCStar: null, gamma: null, effectiveAuthP: null,
        bx, by, time_norm: null, cert: false, plane: null,
        epistemicD: null, epistemicQ: null, epistemicC: null,
        constraintZone: null, custodianLane: null, authorityState: null,
      });
    });
  }

  const rawEdges = ((web && web.edges) || [])
    .map(e => ({ from: e.source, to: e.target, type: normEdge(e.relationship || e.type) }))
    .filter(e => byId[e.from] && byId[e.to]);

  return { nodes: [...all, ...clusterNodes], edges: rawEdges, inferred: true };
}

/** Aggregate fold packet for one cluster (inspector detail). */
export async function fetchFoldCluster(axis, value, activeLibraryId) {
  return api(withLibrary(
    `/api/fold/cluster/${encodeURIComponent(axis)}/${encodeURIComponent(value)}`,
    activeLibraryId,
  ));
}

/** Aggregate fold packet for one axis corpus. */
export async function fetchFoldCorpus(axis, activeLibraryId) {
  return api(withLibrary(`/api/fold/corpus/${encodeURIComponent(axis)}`, activeLibraryId));
}

/** Full fold packet for one document (inspector detail). */
export async function fetchFoldNode(docId, activeLibraryId) {
  return api(withLibrary(`/api/fold/node/${encodeURIComponent(docId)}`, activeLibraryId));
}
