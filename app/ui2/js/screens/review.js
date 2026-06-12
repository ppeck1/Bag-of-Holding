/* BOH new UI — Review Center. Tabs: Conflicts · Proposed Changes · Approvals · Review Queue */
import { h } from "../dom.js";
import { api, escHtml, getToken, tokenHeaders } from "../api.js";
import { Badge, Button, Card, Skeleton, Tabs, EmptyState, AlertBanner } from "../primitives.js";

let _tab = "conflicts";

export function ReviewScreen({ onToast }) {
  let root;
  function rebuild() { const old = root; const n = build(); old.replaceWith(n); }
  function build() {
    root = h("div", { class: "content content-narrow" },
      h("div", { class: "page-head" },
        h("div", { class: "t-display" }, "Review Center"),
        h("div", { class: "sub t-small" }, "Conflicts, proposed changes, and admission decisions — all governed actions in one place.")),
      Tabs({ value: _tab, onChange: v => { _tab = v; rebuild(); }, tabs: [
        { value: "conflicts", label: "Conflicts" },
        { value: "proposed",  label: "Proposed Changes" },
        { value: "approvals", label: "Approvals" },
        { value: "queue",     label: "Review Queue" },
      ] }),
      _tab === "conflicts" ? ConflictsTab() :
      _tab === "proposed"  ? ProposedTab(onToast, rebuild) :
      _tab === "approvals" ? ApprovalsTab() :
                             QueueTab(onToast));
    return root;
  }
  return build();
}

function ConflictsTab() {
  const wrap = loading();
  api("/api/conflicts?limit=100").then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const items = d.conflicts || [];
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Conflicts"), h("span", { class: "count t-small" }, String(items.length))));
    if (items.length) {
      out.appendChild(Card({ bodyFlush: true, children:
        tbl(["Type","Term / Path","Acked","Detected"], items.map(c => [
          h("span", { class: "badge", style: { color: "var(--state-conflict)", background: "color-mix(in oklab, var(--state-conflict) 14%, transparent)", border: "1px solid color-mix(in oklab, var(--state-conflict) 30%, transparent)" } }, "! " + (c.conflict_type || "conflict")),
          h("code", { class: "t-mono", style: { fontSize: "11px" } }, escHtml((c.term || c.plane_path || "").slice(0, 60))),
          c.acknowledged ? h("span", { style: { color: "var(--state-current)" } }, "✓") : dim("—"),
          dim(c.detected_ts ? new Date(c.detected_ts * 1000).toLocaleDateString() : "—")])) }));
    } else {
      out.appendChild(EmptyState({ glyph: "⚔", title: "No conflicts", desc: "Canon collisions appear here when detected during indexing." }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

function ProposedTab(onToast, rebuild) {
  const wrap = loading();
  api("/api/llm/queue?status=pending&limit=50").then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const items = d.items || [];
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      AlertBanner({ ns: "review", children: ["LLM proposals never apply automatically. Each requires an explicit operator admission decision."] }),
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Pending proposals"), h("span", { class: "count t-small" }, String(items.length))));
    if (items.length) {
      out.appendChild(Card({ bodyFlush: true, children:
        tbl(["Document","Summary","Created","Actions"], items.map(i => [
          mono((i.doc_id || "").slice(0, 24)),
          h("span", { class: "t-small" }, escHtml(((i.summary || i.content || (i.proposed && i.proposed.summary) || i.note) || "").slice(0, 80))),
          dim(i.created_ts ? new Date(i.created_ts * 1000).toLocaleDateString() : "—"),
          h("div", { class: "flex gap-1" },
            Button({ variant: "governed", glyph: "↺", className: "sm", onClick: () => {
              const tok = getToken();
              if (!tok) { onToast && onToast("Operator token required — set in Settings → Security & Advanced.", "stale"); return; }
              api(`/api/llm/queue/${encodeURIComponent(i.queue_id || i.id)}/approve`, {
                method: "POST", headers: tokenHeaders(), body: JSON.stringify({ actor_id: "local_operator", note: "Admitted as draft from Review Center." })
              }).then(d => {
                if (d && d.error) { onToast && onToast(`Admit failed: ${d.error}`, "conflict"); return; }
                onToast && onToast("Proposal admitted as draft.", "current");
                rebuild();
              });
            }, children: ["Admit as Draft"] }),
            Button({ variant: "ghost", className: "sm", onClick: () => {
              const tok = getToken();
              if (!tok) { onToast && onToast("Operator token required — set in Settings → Security & Advanced.", "stale"); return; }
              api(`/api/llm/queue/${encodeURIComponent(i.queue_id || i.id)}/reject`, {
                method: "POST", headers: tokenHeaders(), body: JSON.stringify({ actor_id: "local_operator", note: "Rejected from Review Center." })
              }).then(d => {
                if (d && d.error) { onToast && onToast(`Reject failed: ${d.error}`, "conflict"); return; }
                onToast && onToast("Proposal rejected.", "stale");
                rebuild();
              });
            }, children: ["Reject"] }))])) }));
    } else {
      out.appendChild(EmptyState({ glyph: "◈", title: "No pending proposals", desc: "LLM-proposed changes will appear here when Ollama is active." }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

function ApprovalsTab() {
  const wrap = loading();
  api("/api/governance/approve/pending").then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const items = d.pending || [];
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Pending approvals"), h("span", { class: "count t-small" }, String(items.length))));
    if (items.length) {
      out.appendChild(Card({ bodyFlush: true, children:
        tbl(["Document","Action","Required authority","Queued"], items.map(i => [
          mono((i.doc_id || i.target_id || "").slice(0, 24)),
          escHtml(i.action_type || i.action || "—"),
          h("span", { style: { color: "var(--state-review)" } }, escHtml(i.required_authority || "—")),
          dim(i.created_at ? new Date(i.created_at).toLocaleDateString() : "—")])) }));
    } else {
      out.appendChild(EmptyState({ glyph: "↺", title: "No pending approvals" }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

function QueueTab(onToast) {
  const wrap = loading();
  api("/api/review-queue/proposals?limit=50").then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const items = d.proposals || d.items || [];
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Review queue"), h("span", { class: "count t-small" }, String(items.length))));
    if (items.length) {
      out.appendChild(Card({ bodyFlush: true, children:
        tbl(["Document","Reason","Status","Created","Action"], items.map(i => [
          mono((i.doc_id || i.target_id || "").slice(0, 24)),
          h("span", { class: "t-small" }, escHtml((i.reason || "").slice(0, 60))),
          escHtml(i.status || "—"),
          dim(i.created_at ? new Date(i.created_at).toLocaleDateString() : "—"),
          Button({ variant: "governed", glyph: "↺", className: "sm", onClick: () => {
            const tok = getToken();
            if (!tok) { onToast && onToast("Operator token required — set in Settings → Security & Advanced.", "stale"); return; }
            onToast && onToast("Open the item in Authority & Audit → Trace & Gates to act.", "review");
          }, children: ["Review"] })])) }));
    } else {
      out.appendChild(EmptyState({ glyph: "✓", title: "Review queue empty" }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

function tbl(headers, rows) {
  const thead = h("thead", null, h("tr", null, ...headers.map(hd => h("th", null, hd))));
  const tbody = h("tbody", null, ...rows.map(cells => h("tr", null, ...cells.map(c => h("td", null, c)))));
  return h("div", { style: { overflowX: "auto" } }, h("table", { class: "tbl" }, thead, tbody));
}
function mono(s) { return h("code", { class: "t-mono" }, s); }
function dim(s) { return h("span", { class: "t-small muted" }, String(s)); }
function loading() {
  const w = h("div", { style: { marginTop: "16px" } });
  w.appendChild(Skeleton({ w: "100%", h: 120, r: 8 }));
  return w;
}
function err(w, e) { w.innerHTML = `<div class="t-small" style="color:var(--state-conflict)">${escHtml(e)}</div>`; }
