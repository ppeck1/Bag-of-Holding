/* BOH new UI — Activity Log. Read-only audit stream from /api/audit. */
import { h } from "../dom.js";
import { api, escHtml } from "../api.js";
import { Card, Button, Tabs, EmptyState, Skeleton } from "../primitives.js";

let _tab = "activity", _limit = 50;

export function ActivityScreen() {
  let root;
  function rebuild() { const old = root; const n = build(); old.replaceWith(n); }
  function build() {
    root = h("div", { class: "content content-narrow" },
      h("div", { class: "page-head" },
        h("div", { class: "t-display" }, "Activity Log"),
        h("div", { class: "sub t-small" }, "The deterministic local audit stream — every material event, actor, and document reference, preserved in order.")),
      Tabs({ value: _tab, onChange: v => { _tab = v; rebuild(); }, tabs: [
        { value: "activity", label: "Audit events" },
        { value: "export",   label: "Export" },
      ] }),
      _tab === "activity" ? ActivityTab({ rebuild }) : ExportTab());
    return root;
  }
  return build();
}

function ActivityTab({ rebuild }) {
  const wrap = loading();
  api(`/api/audit?limit=${_limit}`).then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const events = d.events || [];
    const total = d.count ?? events.length;
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      h("div", { class: "flex between items-center" },
        h("span", { class: "t-small muted" }, `${events.length} of ${total} events`),
        h("div", { class: "flex gap-2" },
          _limit < total && Button({ variant: "ghost", className: "sm", onClick: () => { _limit += 100; rebuild(); }, children: ["Load more"] }),
          Button({ variant: "ghost", className: "sm", onClick: () => { _limit = 50; rebuild(); }, children: ["↺ Refresh"] }))));
    if (events.length) {
      out.appendChild(Card({ bodyFlush: true, children:
        tbl(["Time","Type","Actor","Document","Detail"],
          events.map(e => [
            e.event_ts ? h("div", null,
              h("span", { class: "t-small" }, new Date(e.event_ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })),
              h("div", { class: "t-small muted" }, new Date(e.event_ts * 1000).toLocaleDateString())) : dim("—"),
            h("span", { class: "t-small", style: { color: typeColor(e.event_type) } }, escHtml(e.event_type || "—")),
            dim(e.actor_id || e.actor_type || "—"),
            mono((e.doc_id || "").slice(0, 24)),
            h("span", { class: "t-small muted" }, escHtml((e.detail || "").slice(0, 70)))])) }));
    } else {
      out.appendChild(EmptyState({ glyph: "›_", title: "No audit events yet", desc: "Material events are recorded here as documents are indexed, admitted, and governed." }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

function ExportTab() {
  function dateStamp() {
    return new Date().toISOString().slice(0, 10);
  }
  function triggerDownload(filename, content) {
    const blob = new Blob([content], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = h("a", { href: url, download: filename, style: { display: "none" } });
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 1000);
  }

  function exportCorpus(btn) {
    btn.disabled = true; btn.textContent = "Exporting…";
    // Fetch up to 2000 docs in one pass; a future paginated export can extend this.
    api("/api/docs?per_page=2000").then(d => {
      btn.disabled = false; btn.textContent = "Export document corpus";
      if (!d || d.error) { btn.closest(".col").querySelector(".exp-err").textContent = d?.error || "Fetch failed."; return; }
      const docs = d.docs || d.items || [];
      const payload = {
        export_type: "boh_corpus_snapshot",
        exported_at: new Date().toISOString(),
        doc_count: docs.length,
        governance_note: "This export is a read-only snapshot. canon_eligible values are advisory only.",
        docs,
      };
      triggerDownload(`boh-corpus-${dateStamp()}.json`, JSON.stringify(payload, null, 2));
    });
  }

  function exportAudit(btn) {
    btn.disabled = true; btn.textContent = "Exporting…";
    api("/api/audit?limit=5000").then(d => {
      btn.disabled = false; btn.textContent = "Export audit log";
      if (!d || d.error) { btn.closest(".col").querySelector(".exp-err").textContent = d?.error || "Fetch failed."; return; }
      const events = d.events || [];
      const payload = {
        export_type: "boh_audit_snapshot",
        exported_at: new Date().toISOString(),
        event_count: events.length,
        events,
      };
      triggerDownload(`boh-audit-${dateStamp()}.json`, JSON.stringify(payload, null, 2));
    });
  }

  function exportICS(btn) {
    btn.disabled = true; btn.textContent = "Exporting…";
    fetch("/api/events/export.ics")
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.text();
      })
      .then(content => {
        btn.disabled = false; btn.textContent = "Export ICS calendar";
        const blob = new Blob([content], { type: "text/calendar" });
        const url = URL.createObjectURL(blob);
        const a = h("a", { href: url, download: `boh-events-${dateStamp()}.ics`, style: { display: "none" } });
        document.body.appendChild(a);
        a.click();
        setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 1000);
      })
      .catch(err => {
        btn.disabled = false; btn.textContent = "Export ICS calendar";
        btn.closest(".col").querySelector(".exp-err").textContent = err.message || "Export failed.";
      });
  }

  let corpusBtn, auditBtn, icsBtn;
  const corpusCard = Card({ title: "Document corpus", children: h("div", { class: "col gap-3" },
    h("div", { class: "t-small" }, "Downloads all indexed documents (title, path, authority state, status, metadata) as a JSON snapshot. Read-only; does not include file content."),
    h("div", { class: "flex gap-2 items-center" },
      (corpusBtn = h("button", { class: "btn btn-secondary btn-sm", onClick: () => exportCorpus(corpusBtn) }, "Export document corpus")),
      h("span", { class: "t-small muted" }, "boh-corpus-YYYY-MM-DD.json")),
    h("div", { class: "exp-err t-small", style: { color: "var(--state-conflict)" } })) });
  const auditCard = Card({ title: "Audit log", children: h("div", { class: "col gap-3" },
    h("div", { class: "t-small" }, "Downloads up to 5 000 most recent audit events (event type, actor, document reference, timestamp) as a JSON snapshot."),
    h("div", { class: "flex gap-2 items-center" },
      (auditBtn = h("button", { class: "btn btn-secondary btn-sm", onClick: () => exportAudit(auditBtn) }, "Export audit log")),
      h("span", { class: "t-small muted" }, "boh-audit-YYYY-MM-DD.json")),
    h("div", { class: "exp-err t-small", style: { color: "var(--state-conflict)" } })) });
  const icsCard = Card({ title: "ICS calendar", children: h("div", { class: "col gap-3" },
    h("div", { class: "t-small" }, "Downloads all indexed events as an RFC 5545 ICS calendar file. Includes event timestamps and document references for external calendar clients."),
    h("div", { class: "flex gap-2 items-center" },
      (icsBtn = h("button", { class: "btn btn-secondary btn-sm", onClick: () => exportICS(icsBtn) }, "Export ICS calendar")),
      h("span", { class: "t-small muted" }, "boh-events-YYYY-MM-DD.ics")),
    h("div", { class: "exp-err t-small", style: { color: "var(--state-conflict)" } })) });
  return h("div", { class: "col gap-3", style: { marginTop: "16px" } }, corpusCard, auditCard, icsCard);
}

function typeColor(t) {
  const s = String(t || "").toLowerCase();
  if (/error|fail|reject/.test(s)) return "var(--state-conflict)";
  if (/warn|stale/.test(s)) return "var(--state-stale)";
  if (/admit|index|canon/.test(s)) return "var(--state-current)";
  if (/review|queue|proposal/.test(s)) return "var(--state-review)";
  return "var(--text-secondary)";
}
function kvRow(k, v) { return h("div", { class: "kv-row" }, h("span", { class: "k" }, k), h("span", { class: "v" }, v)); }
function tbl(headers, rows) {
  const thead = h("thead", null, h("tr", null, ...headers.map(hd => h("th", null, hd))));
  const tbody = h("tbody", null, ...rows.map(cells => h("tr", null, ...cells.map(c => h("td", null, c)))));
  return h("div", { style: { overflowX: "auto" } }, h("table", { class: "tbl" }, thead, tbody));
}
function mono(s) { return h("code", { class: "t-mono" }, s); }
function dim(s) { return h("span", { class: "t-small muted" }, String(s)); }
function loading() {
  const w = h("div", { style: { marginTop: "16px", display: "flex", flexDirection: "column", gap: "8px" } });
  w.appendChild(Skeleton({ w: "100%", h: 32, r: 6 }));
  w.appendChild(Skeleton({ w: "80%", h: 32, r: 6 }));
  w.appendChild(Skeleton({ w: "90%", h: 32, r: 6 }));
  return w;
}
function err(w, e) { w.innerHTML = `<div class="t-small" style="color:var(--state-conflict)">${escHtml(e)}</div>`; }
