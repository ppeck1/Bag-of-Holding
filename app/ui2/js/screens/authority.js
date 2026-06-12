/* BOH new UI — Authority & Audit. Tabs: Integrity · Authority Ledger · Trace & Gates · Residence */
import { h } from "../dom.js";
import { api, escHtml } from "../api.js";
import { Skeleton, Accordion, Badge, Button, Card, Tabs, EmptyState, AlertBanner } from "../primitives.js";

let _tab = "integrity";

export function AuthorityScreen({ onNavigate }) {
  let root;
  function rebuild() { const old = root; const n = build(); old.replaceWith(n); }
  function build() {
    root = h("div", { class: "content content-narrow" },
      h("div", { class: "page-head" },
        h("div", { class: "t-display" }, "Authority & Audit"),
        h("div", { class: "sub t-small" }, "Integrity state, authority ledger, gate decisions, and residence mapping — all read-only.")),
      Tabs({ value: _tab, onChange: v => { _tab = v; rebuild(); }, tabs: [
        { value: "integrity", label: "Integrity" },
        { value: "ledger",    label: "Authority Ledger" },
        { value: "trace",     label: "Trace & Gates" },
        { value: "residence", label: "Residence" },
      ] }),
      _tab === "integrity" ? IntegrityTab() :
      _tab === "ledger"    ? LedgerTab() :
      _tab === "trace"     ? TraceTab() :
                             ResidenceTab());
    return root;
  }
  return build();
}

function IntegrityTab() {
  const wrap = loading();
  api("/api/integrity/dashboard").then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const st = d.integrity_state || {};
    const risk = d.highest_drift_risk || [];
    const auths = d.authority_violations || [];
    const esc = d.active_escalations || [];
    const out = h("div", { class: "col gap-4", style: { marginTop: "16px" } },
      Card({ title: "Integrity state", children:
        h("div", { class: "flex gap-4 wrap" },
          kv("Label", st.label || "—"), kv("Score", st.score != null ? String(st.score) : "—"),
          kv("Violations", String(auths.length)), kv("Escalations", String(esc.length))) }));
    if (risk.length) out.appendChild(Card({ title: "Highest drift risk", bodyFlush: true, children:
      tbl(["Node","State","Drift","Valid until"], risk.map(r => [
        mono((r.node_id || "").slice(0, 28)), (r.visual_state || {}).state || "—",
        r.drift_risk || "—", dim(r.valid_until || "—")])) }));
    if (auths.length) out.appendChild(Card({ title: "Authority violations", bodyFlush: true, children:
      tbl(["Target","Required","Attempted by","Time"], auths.map(a => [
        mono((a.target_id || "").slice(0, 28)), escHtml(a.required_authority || "—"),
        escHtml(a.actor_id || "—"), dim(a.timestamp ? new Date(a.timestamp).toLocaleDateString() : "—")])) }));
    if (!risk.length && !auths.length) out.appendChild(EmptyState({ glyph: "▣", title: "No integrity issues" }));
    wrap.replaceWith(out);
  });
  return wrap;
}

function LedgerTab() {
  const wrap = loading();
  Promise.all([api("/api/authority/promotions?limit=50"), api("/api/authority/log?limit=50")]).then(([p, l]) => {
    const promos = p.promotions || [];
    const log = l.log || [];
    const out = h("div", { class: "col gap-4", style: { marginTop: "16px" } },
      Card({ title: `Promotion ledger (${promos.length})`, bodyFlush: true, children:
        promos.length ? tbl(["Target","From → To","Authority","Reason","When"], promos.map(p => [
          mono((p.target_id || "").slice(0, 24)),
          h("span", { class: "t-small" }, `${escHtml(p.old_authority || "—")} → ${escHtml(p.new_authority || "—")}`),
          (p.authority_state || "").includes("cert") ? Badge({ ns: "current", label: "cert" }) : Badge({ ns: "unknown", label: p.authority_state || "—", glyph: "" }),
          small((p.promotion_reason || "").slice(0, 50)),
          dim(p.promotion_timestamp ? new Date(p.promotion_timestamp).toLocaleDateString() : "—")]))
        : nodata("No promotions recorded.") }),
      Card({ title: `Resolution log (${log.length})`, bodyFlush: true, children:
        log.length ? tbl(["When","Actor","Target","Required","Result"], log.map(e => [
          dim(e.timestamp ? new Date(e.timestamp).toLocaleDateString() : "—"),
          small(e.actor_id || "—"), mono((e.target_id || "").slice(0, 22)),
          small(e.required_authority || "—"),
          e.authorization_result
            ? h("span", { style: { color: "var(--state-current)" } }, "✓ auth")
            : h("span", { style: { color: "var(--state-conflict)" } }, "⊘ denied")]))
        : nodata("No resolution log entries.") }));
    wrap.replaceWith(out);
  });
  return wrap;
}

function TraceTab() {
  const wrap = loading();
  api("/api/trace/gate-results?limit=50").then(d => {
    if (d && d.error) { wrap.innerHTML = `<div class="t-small" style="color:var(--state-conflict)">${escHtml(d.error)}</div>`; return; }
    const rows = d.gate_results || [];
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Gate results"), h("span", { class: "count t-small" }, String(rows.length))));
    if (rows.length) {
      const fmtTs = (ts) => {
        const n = Number(ts);
        return Number.isFinite(n) && n > 0 ? new Date(n * 1000).toLocaleString() : "—";
      };
      const asList = (v) => Array.isArray(v) ? v : (v ? [v] : []);
      const traceItems = rows.map((t, i) => {
        const blocking = asList(t.blocking_reasons);
        const warning = asList(t.warning_reasons);
        const posture = t.posture || "—";
        return {
          id: String(t.gate_result_id || i),
          title: `${posture} — ${escHtml(t.operation || t.trace_event_type || "gate")}`,
          meta: dim(fmtTs(t.created_ts)),
          defaultOpen: false,
          body: h("div", { class: "kv" },
            kvRow("Actor", t.actor_id || "—"),
            kvRow("Query", (t.query || "—").slice(0, 80)),
            kvRow("Posture", posture),
            kvRow("Required route", t.required_route || "—"),
            kvRow("Blocking", blocking.length ? blocking.join("; ").slice(0, 120) : "none"),
            kvRow("Warnings", warning.length ? warning.join("; ").slice(0, 120) : "none")),
        };
      });
      out.appendChild(Card({ children: Accordion({ items: traceItems }) }));
    } else {
      out.appendChild(EmptyState({ glyph: "≣", title: "No gate results yet", desc: "Planar gate evaluations appear here once retrieval/context-pack assembly runs." }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

function ResidenceTab() {
  const wrap = loading();
  api("/api/residence/map?limit=100").then(d => {
    const rows = d.residences || [];
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Residence map"), h("span", { class: "count t-small" }, String(rows.length))));
    if (rows.length) {
      out.appendChild(Card({ bodyFlush: true, children:
        tbl(["Original","Current","Status","Reason"], rows.map(r => [
          mono((r.original_ref || "").slice(0, 24)), mono((r.current_ref || "").slice(0, 24)),
          escHtml(r.status || "—"), small((r.reason || "").slice(0, 50))])) }));
    } else {
      out.appendChild(EmptyState({ glyph: "⌖", title: "No residence records" }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

// ── helpers ──────────────────────────────────────────────────────────────────

function kvRow(k, v) { return h("div", { class: "kv-row" }, h("span", { class: "k" }, k), h("span", { class: "v" }, String(v || "—"))); }

function tbl(headers, rows) {
  const thead = h("thead", null, h("tr", null, ...headers.map(hd => h("th", null, hd))));
  const tbody = h("tbody", null, ...rows.map(cells => h("tr", null, ...cells.map(c => h("td", null, c)))));
  return h("div", { style: { overflowX: "auto" } }, h("table", { class: "tbl" }, thead, tbody));
}
function kv(k, v) { return h("div", { class: "kv-row" }, h("span", { class: "k" }, k), h("span", { class: "v" }, v)); }
function mono(s) { return h("code", { class: "t-mono" }, s); }
function small(s) { return h("span", { class: "t-small" }, escHtml(String(s))); }
function dim(s) { return h("span", { class: "t-small muted" }, String(s)); }
function nodata(msg) { return h("div", { class: "t-small muted", style: { padding: "12px" } }, msg); }
function loading() {
  const w = h("div", { style: { marginTop: "16px", display: "flex", flexDirection: "column", gap: "8px" } });
  w.appendChild(Skeleton({ w: "100%", h: 32, r: 6 }));
  w.appendChild(Skeleton({ w: "80%", h: 32, r: 6 }));
  return w;
}
function err(w, e) { w.innerHTML = `<div class="t-small" style="color:var(--state-conflict)">${escHtml(e)}</div>`; }
