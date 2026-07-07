/* BOH new UI (Phase A) — app shell: sidebar, top bar, scope tree, jobs, alerts,
   inspector, toasts. Vanilla port of components/shell.jsx (same DOM/classes).
   Uses a full-subtree re-render model: the app root re-renders on state change. */

import { h } from "./dom.js";
import { api, escHtml } from "./api.js";
import { NS, PLANES, nsMeta } from "./ns.js";
import * as FX from "./fixtures.js";
import { Icon, Badge, Button, Tooltip, Popover, Segmented, MarkerPip, WhyCurrent, Accordion, EmptyState, AlertBanner } from "./primitives.js";
import { AssociatedFilePreview } from "./file-preview.js";

const NAV_GROUPS = [
  { label: "Workspace", items: [
    { id: "current", glyph: "◈", label: "Current State" },
    { id: "intake",  glyph: "+", label: "Capture & Intake" },
    { id: "library", glyph: "▦", label: "Library" },
    { id: "review",  glyph: "✓", label: "Review Center", pip: 11 },
  ] },
  { label: "Governance", items: [
    { id: "authority", glyph: "⚖", label: "Authority & Audit", pip: 3 },
  ] },
  { label: "System", items: [
    { id: "status",   glyph: "●", label: "Status" },
    { id: "settings", glyph: "⚙", label: "Settings" },
  ] },
];
const ADV_ITEMS = [
  { id: "components",   glyph: "▤", label: "Component Sheet" },
  { id: "fold",         glyph: "◈", label: "Fold Workspace" },
  { id: "context-pack", glyph: "⊞", label: "Context Pack" },
  { id: "log",          glyph: "›_", label: "Activity Log" },
];

let _advOpen = false; // sidebar Advanced Tools expansion (UI-local)

export function Sidebar({ route, onNavigate }) {
  const advSub = _advOpen && h("div", { className: "adv-sub" },
    ADV_ITEMS.map((it) => it.href
      ? h("a", { className: "nav-item", href: it.href, style: { textDecoration: "none", color: "inherit" } },
          h("span", { className: "nav-glyph" }, it.glyph), it.label)
      : h("button", { className: `nav-item ${route === it.id ? "active" : ""}`.trim(), onClick: () => onNavigate(it.id) },
          h("span", { className: "nav-glyph" }, it.glyph), it.label)));
  return h("nav", { className: "sidebar" },
    NAV_GROUPS.map((g) => h("div", null,
      h("div", { className: "nav-group-label t-micro" }, g.label),
      g.items.map((it) => h("button", {
        className: `nav-item ${route === it.id ? "active" : ""}`.trim(), onClick: () => onNavigate(it.id),
      }, h("span", { className: "nav-glyph" }, it.glyph), it.label,
        it.pip != null && h("span", { className: "nav-pip" }, it.pip))))),
    h("div", { className: "spring" }),
    h("div", { className: "adv-tools" },
      h("button", { className: "nav-item", "aria-expanded": _advOpen ? "true" : "false", onClick: (e) => { _advOpen = !_advOpen; rerenderSidebar(e.currentTarget, route, onNavigate); } },
        h("span", { className: "nav-glyph" }, _advOpen ? "▾" : "▸"), "Advanced Tools"),
      advSub));
}
function rerenderSidebar(btn, route, onNavigate) {
  const nav = btn.closest(".sidebar");
  if (nav) nav.replaceWith(Sidebar({ route, onNavigate }));
}

function planesLabel(vp) {
  const total = Object.keys(PLANES).length;
  if (!vp || vp.length === total) return "All";
  if (vp.length === 0) return "None";
  return String(vp.length);
}

function libraryLabel(activeLibrary, libraries) {
  if (activeLibrary && activeLibrary.name) return activeLibrary.name;
  const first = (libraries || [])[0];
  return first && first.name ? first.name : "All libraries";
}

function LibraryPopover({ libraries, activeLibraryId, onSelectLibrary, onManageLibraries }) {
  const items = libraries && libraries.length ? libraries : [{ id: "all", name: "All libraries", count: 0 }];
  return h("div", null,
    h("div", { className: "popover-title t-micro" }, "Logical libraries"),
    h("div", { className: "t-small muted", style: { padding: "0 10px 6px", fontSize: "11px" } },
      "Browsing filter for Library and Fold Workspace."),
    items.map((lib) => h("button", {
      className: `menu-item ${lib.id === activeLibraryId ? "selected" : ""}`.trim(),
      onClick: () => onSelectLibrary && onSelectLibrary(lib.id),
    },
      h("span", null, escHtml(lib.name || lib.id)),
      h("span", { className: "spacer" }),
      h("span", { className: "t-mono" }, String(lib.count ?? 0)),
      lib.id === activeLibraryId && Icon({ name: "check", size: 14, className: "check" }))),
    h("div", { style: { borderTop: "1px solid var(--border-default)", margin: "4px 0 0", padding: "4px 6px 2px" } },
      h("button", { className: "menu-item", onClick: () => onManageLibraries && onManageLibraries() },
        Icon({ name: "gear", size: 14 }),
        "Manage libraries")));
}

function PlanesPopover({ visiblePlanes, onToggle, onShowAll }) {
  const allOn = !visiblePlanes || visiblePlanes.length === Object.keys(PLANES).length;
  return h("div", null,
    h("div", { className: "popover-title t-micro" }, "Visible planes"),
    h("div", { className: "t-small muted", style: { padding: "0 10px 6px", fontSize: "11px" } },
      "Browsing visibility only. Retrieval and authority are unchanged."),
    Object.entries(PLANES).map(([key, meta]) => {
      const on = !visiblePlanes || visiblePlanes.includes(key);
      return h("button", { className: "plane-row", role: "button",
        "aria-pressed": on ? "true" : "false",
        "aria-label": `${meta.label} plane, ${on ? "visible" : "hidden"}`,
        onClick: () => onToggle(key) },
        h("span", { className: "plane-glyph", style: { color: meta.color } }, meta.glyph),
        h("span", null, meta.label),
        on && h("span", { className: "plane-check", "aria-hidden": "true" }, "✓"));
    }),
    h("div", { style: { borderTop: "1px solid var(--border-default)", margin: "4px 0 0", padding: "4px 6px 2px" } },
      h("button", { className: "menu-item", onClick: onShowAll, disabled: allOn },
        allOn ? "All planes visible" : "Show all planes")));
}

export function TopBar({ mode, onMode, visiblePlanes, onTogglePlane, onShowAllPlanes,
                         libraries, activeLibraryId, onSelectLibrary, onManageLibraries,
                         onOpenAlerts, alertCount, jobCount, lastIndexed, diagnostics, onSearch }) {
  let _searchInput;
  function doSearch() {
    const q = _searchInput && _searchInput.value.trim();
    if (q && onSearch) onSearch(q);
  }
  const indexed = lastIndexed && lastIndexed !== "never" ? lastIndexed : null;
  const indexedTooltip = indexed ? `Last indexed: ${indexed}` : "Not yet indexed";
  const indexedChip = h("span", { className: "chip is-static" },
    h("span", { className: "glyph", style: { color: indexed ? "var(--state-current)" : "var(--text-muted)" } }, indexed ? "✓" : "○"),
    indexed ? "Indexed" : "Not indexed");
  const activeLibrary = (libraries || []).find(l => l.id === activeLibraryId) || (libraries || [])[0];
  return h("header", { className: "topbar" },
    Popover({ align: "left", width: 260,
      trigger: ({ toggle }) => h("button", { className: "chip", onClick: toggle,
        "aria-label": `Library: ${libraryLabel(activeLibrary, libraries)}`, "aria-haspopup": "true" },
        h("span", { className: "glyph", style: { color: "var(--accent)" } }, "â–¦"),
        `Library: ${libraryLabel(activeLibrary, libraries)}`,
        Icon({ name: "chevDown", size: 13 })),
      children: ({ close }) => LibraryPopover({
        libraries, activeLibraryId,
        onSelectLibrary: (id) => { onSelectLibrary && onSelectLibrary(id); close(); },
        onManageLibraries: () => { onManageLibraries && onManageLibraries(); close(); },
      }) }),
    null && Tooltip({ text: "Single private memory library. Additional library mounts are deferred.",
      below: true, children: [
        h("span", { className: "chip is-static", "aria-label": "Library: Bag of Holding" },
          h("span", { className: "glyph", style: { color: "var(--accent)" } }, "▦"),
          "Library: Bag of Holding")] }),
    Popover({ align: "left", width: 220,
      trigger: ({ toggle }) => h("button", { className: "chip", onClick: toggle,
        "aria-label": `Planes: ${planesLabel(visiblePlanes)}`, "aria-haspopup": "true" },
        h("span", { className: "glyph", style: { color: "var(--accent)" } }, "◈"),
        `Planes: ${planesLabel(visiblePlanes)}`,
        Icon({ name: "chevDown", size: 13 })),
      children: () => PlanesPopover({ visiblePlanes, onToggle: onTogglePlane, onShowAll: onShowAllPlanes }) }),
    h("div", { className: "search" },
      h("span", { className: "lead" }, Icon({ name: "search", size: 15 })),
      (_searchInput = h("input", { placeholder: "Search corpus, planes, certificates…", "aria-label": "Global search",
        onKeydown: (e) => { if (e.key === "Enter") doSearch(); } }))),
    h("span", { className: "grow" }),
    jobCount > 0
      ? Popover({ align: "right", width: 320,
          trigger: ({ toggle }) => h("button", { className: "chip", onClick: toggle, "aria-label": "Jobs" },
            Icon({ name: "jobs", size: 14 }), "Jobs", h("span", { className: "count-pip" }, jobCount)),
          children: () => JobsPopover() })
      : null,
    alertCount > 0
      ? h("button", { className: "chip sev-conflict", onClick: onOpenAlerts, "aria-label": "Alerts" },
          Icon({ name: "bell", size: 14 }), "Alerts", h("span", { className: "count-pip" }, alertCount))
      : h("button", { className: "chip", onClick: onOpenAlerts, "aria-label": "Alerts" },
          Icon({ name: "bell", size: 14 }), "Activity"),
    Tooltip({ text: indexedTooltip, below: true, children: [indexedChip] }),
    diagnostics && Tooltip({ text: "Security state: DEV-OPEN. Protected local controls are unlocked in this prototype.", below: true, children: [
      h("span", { className: "chip dev-open" }, h("span", { className: "glyph" }, "⚠"), "DEV-OPEN")] }),
    Segmented({ sm: true, value: mode, onChange: onMode, options: [{ value: "simple", label: "Simple" }, { value: "advanced", label: "Advanced" }] }));
}

export function JobsPopover() {
  const TONE = { running: "var(--accent)", queued: "var(--text-muted)", done: "var(--state-current)" };
  return h("div", { style: { width: "100%" } },
    h("div", { className: "popover-title t-micro" }, "Active jobs"),
    h("div", { className: "col gap-1", style: { padding: "0 4px 4px" } },
      FX.jobs.map((j) => h("div", { className: "col gap-1", style: { padding: "8px 8px", borderRadius: "7px", background: "var(--bg-panel)" } },
        h("div", { className: "flex items-center between" },
          h("span", { className: "t-body", style: { color: "var(--text-primary)", fontWeight: 500 } },
            j.state === "running" && h("span", { className: "pulse-dot", style: { display: "inline-block", marginRight: "8px" } }), j.name),
          h("span", { className: "t-micro", style: { color: TONE[j.state] } }, j.state)),
        h("span", { className: "t-small muted" }, j.detail),
        j.state !== "done" && h("div", { style: { height: "4px", borderRadius: "999px", background: "var(--bg-input)", overflow: "hidden", marginTop: "2px" } },
          h("div", { style: { width: `${j.pct}%`, height: "100%", background: TONE[j.state] } }))))));
}

export function AlertsDrawer({ onClose, onToast }) {
  function eventNs(type) {
    const t = String(type || "").toLowerCase();
    if (/error|fail|conflict/.test(t)) return "conflict";
    if (/warn|stale/.test(t)) return "stale";
    if (/review|queue/.test(t)) return "review";
    return "unknown";
  }
  const body = h("div", { className: "drawer-body" });
  body.innerHTML = `<div class="t-small muted" style="padding:16px">Loading…</div>`;
  api("/api/audit?limit=50").then(d => {
    const events = (d && d.events) || [];
    if (d && d.error) {
      body.innerHTML = `<div class="t-small" style="padding:16px;color:var(--state-conflict)">${escHtml(d.error)}</div>`;
      return;
    }
    if (!events.length) {
      body.innerHTML = `<div class="t-small muted" style="padding:16px">No audit events yet.</div>`;
      return;
    }
    body.replaceChildren(...events.map(e => {
      const ns = eventNs(e.event_type);
      const meta = nsMeta(ns);
      const time = e.event_ts ? new Date(e.event_ts * 1000).toLocaleString() : "—";
      return h("div", { className: "alert-row" },
        h("span", { className: "ar-glyph", style: { color: meta.color } }, meta.glyph),
        h("div", null,
          h("div", { className: "ar-title" }, escHtml(e.event_type || "event")),
          h("div", { className: "ar-meta" },
            h("span", null, escHtml(e.actor_id || e.actor_type || "—")),
            h("span", null, "·"),
            h("span", null, time)),
          h("div", { className: "ar-expl" }, escHtml((e.detail || e.doc_id || "").slice(0, 120))),
          h("div", { className: "ar-foot" },
            h("span", { className: "resolved-dot", style: { background: "var(--state-current)" } }),
            h("span", { className: "t-small muted" }, "audit event"))));
    }));
  });
  const unresolved = events => events.filter(e => /error|fail|conflict/.test(String(e.event_type || "").toLowerCase())).length;
  return h("div", null,
    h("div", { className: "scrim", onClick: onClose }),
    h("aside", { className: "drawer wide", role: "dialog", "aria-label": "Alert center" },
      h("div", { className: "drawer-head" },
        h("span", { className: "t-heading" }, "Activity"),
        h("span", { className: "spacer" }),
        h("button", { className: "icon-btn", onClick: onClose, "aria-label": "Close" }, Icon({ name: "close" }))),
      body));
}

function namespaceOf(ns) {
  if (["current", "stale", "expired", "conflict", "unknown"].includes(ns)) return "Currentness";
  if (ns === "review") return "Workflow";
  if (ns === "blocked") return "Gate";
  return "Intake";
}

export function Inspector({ selection, onClose, onCollapse, onTrace }) {
  let body;
  if (!selection) {
    body = h("div", { className: "inspector-body" },
      EmptyState({ glyph: "◈", title: "Nothing selected", desc: "Select a metric tile, document row, or PlaneCard to inspect it." }));
  } else if (selection.type === "metric") {
    const meta = nsMeta(selection.ns);
    body = h("div", { className: "inspector-body" },
      h("div", { className: "flex items-center gap-2" }, Badge({ ns: selection.ns }), h("span", { className: "t-mono" }, `${selection.count} nodes`)),
      h("div", { className: "kv" },
        kvRow("Namespace", namespaceOf(selection.ns)),
        kvRow("Lead channel", "fill = currentness"),
        kvRow("Delta", selection.delta)),
      AlertBanner({ ns: selection.ns, children: [`${meta.label} is a ${namespaceOf(selection.ns).toLowerCase()} signal. Opening the filtered view is a Phase B affordance.`] }),
      Button({ variant: "governed", glyph: "↺", onClick: () => onTrace && onTrace(), children: ["Open filtered view"] }));
  } else if (selection.type === "doc") {
    const d = selection.doc;
    const subtitle = [d.project !== "—" && d.project, d.updated !== "—" && d.updated].filter(Boolean).join(" · ");
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading", style: { color: "var(--text-primary)" } }, d.title),
        subtitle && h("div", { className: "t-small muted" }, subtitle)),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: d.currentness }), (d.markers || []).map((m) => Badge({ ns: m }))),
      d._loading && h("div", { className: "t-small muted", style: { fontStyle: "italic", marginTop: "4px" } }, "Loading full detail…"),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Project", d.project),
        d.path && kvRow("Path", d.path, null, true),
        kvRow("Status", d.lifecycle),
        kvRow("Authority", d.authority),
        d.summary && kvRow("Summary", d.summary),
        d.definitionCount != null && kvRow("Definitions", String(d.definitionCount)),
        d.eventCount != null && kvRow("Events", String(d.eventCount)),
        kvRow("Updated", d.updated),
        d.action && kvRow("Required action", d.action, "var(--state-review)")),
      d.id && AssociatedFilePreview({ docId: d.id, path: d.path, title: d.title || d.path || "Document" }),
      (d.why && d.why.length > 0) && Accordion({ items: [
        { id: "why", title: "Why current?", defaultOpen: true, body: WhyCurrent({ rows: d.why, onTrace }) },
      ] }));
  } else if (selection.type === "card") {
    const c = selection.card;
    const topic = c.topic ? String(c.topic).slice(0, 80) : `Card ${(c.id || "").slice(0, 20)}`;
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading", style: { color: "var(--text-primary)" } }, topic),
        h("div", { className: "t-small muted" }, c.plane ? `PlaneCard · ${c.plane}` : "PlaneCard")),
      Badge({ ns: "unknown" }),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Card ID", c.id),
        kvRow("Plane", c.plane),
        kvRow("Card type", c.card_type),
        kvRow("Topic", c.topic),
        c.b != null && kvRow("b", String(c.b)),
        c.d != null && kvRow("d", String(c.d)),
        c.m != null && kvRow("m", String(c.m)),
        kvRow("Valid until", c.valid_until),
        kvRow("Backing doc", c.doc_id)));
  } else if (selection.type === "intake_capability") {
    const cap = selection.cap;
    const subtitle = [cap.lifecycle, cap.safety_lane].filter(Boolean).join(" · ");
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading" }, cap.source_ref || "Capability"),
        subtitle && h("div", { className: "t-small muted" }, subtitle)),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: cap.safety_lane === "accept" ? "current" : cap.safety_lane === "hold" ? "stale" : "quarantine" })),
      cap._loading && h("div", { className: "t-small muted", style: { fontStyle: "italic", marginTop: "4px" } }, "Loading…"),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Source", cap.source_ref, null, true),
        kvRow("Lifecycle", cap.lifecycle),
        kvRow("Safety lane", cap.safety_lane),
        kvRow("Preservable", cap.preservable),
        kvRow("Queryable", cap.queryable),
        cap.failure_reason && kvRow("Failure", cap.failure_reason)));
  } else if (selection.type === "quarantine_record") {
    const qr = selection.qr;
    const subtitle = [qr.category, qr.lane].filter(Boolean).join(" · ");
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading" }, `Quarantine`),
        subtitle && h("div", { className: "t-small muted" }, subtitle)),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: "quarantine" })),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Record ID", qr.record_id || qr.id, null, true),
        kvRow("Capability ID", qr.intake_capability_id, null, true),
        kvRow("Category", qr.category),
        kvRow("Lane", qr.lane),
        kvRow("Reason", qr.reason),
        qr.created_at && kvRow("Created", qr.created_at)));
  } else if (selection.type === "duplicate_pair") {
    const p = selection.pair;
    const subtitle = [p.doc_id, "↔", p.related_doc_id].filter(Boolean).slice(0, 3).join(" ");
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading" }, "Duplicate pair"),
        subtitle && h("div", { className: "t-small muted" }, subtitle)),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: "stale" })),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Doc ID", p.doc_id, null, true),
        kvRow("Doc path", p.doc_path),
        kvRow("Related ID", p.related_doc_id, null, true),
        kvRow("Related path", p.related_path),
        kvRow("Relationship", p.relationship),
        p.detected_at && kvRow("Detected", p.detected_at),
        p.detected_ts && !p.detected_at && kvRow("Detected", new Date(p.detected_ts * 1000).toLocaleDateString())));
  } else if (selection.type === "audit_event") {
    const e = selection.event;
    const subtitle = [e.actor_id || e.actor_type, e.timestamp].filter(Boolean).join(" · ");
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading" }, e.event_type || "Event"),
        subtitle && h("div", { className: "t-small muted" }, subtitle)),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: "unknown" })),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Event ID", e.id, null, true),
        kvRow("Type", e.event_type),
        kvRow("Actor", e.actor_id || e.actor_type),
        e.doc_id && kvRow("Document", e.doc_id, null, true),
        kvRow("Timestamp", e.timestamp),
        e.detail && kvRow("Detail", e.detail)));
  } else if (selection.type === "review_conflict") {
    const c = selection.conflict;
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading" }, c.conflict_type || "Conflict"),
        h("div", { className: "t-small muted" }, c.term || c.plane_path || "—")),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: "conflict", label: "conflict" })),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Conflict ID", c.conflict_id, null, true),
        kvRow("Type", c.conflict_type),
        kvRow("Term", c.term || c.plane_path),
        kvRow("Acknowledged", c.acknowledged ? "Yes" : "No"),
        c.detected_ts && kvRow("Detected", new Date(c.detected_ts * 1000).toLocaleDateString())));
  } else if (selection.type === "review_proposal") {
    const p = selection.proposal;
    const summary = p.summary || p.content || (p.proposed && p.proposed.summary) || p.note || "—";
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading" }, "LLM Proposal"),
        h("div", { className: "t-small muted" }, p.doc_id || "—")),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: "review", label: "proposal" })),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Queue ID", p.queue_id || p.id, null, true),
        kvRow("Document", p.doc_id, null, true),
        kvRow("Summary", summary.slice(0, 100)),
        p.created_ts && kvRow("Created", new Date(p.created_ts * 1000).toLocaleDateString())));
  } else if (selection.type === "review_approval") {
    const a = selection.approval;
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading" }, a.action_type || "Approval"),
        h("div", { className: "t-small muted" }, a.doc_id || a.target_id || "—")),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: "review", label: "approval" })),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Approval ID", a.id || a.approval_id, null, true),
        kvRow("Document", a.doc_id || a.target_id, null, true),
        kvRow("Action", a.action_type || a.action),
        kvRow("Required Authority", a.required_authority),
        a.created_at && kvRow("Created", new Date(a.created_at).toLocaleDateString())));
  } else if (selection.type === "review_queue") {
    const q = selection.queueItem;
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading" }, q.status || "Queue Item"),
        h("div", { className: "t-small muted" }, q.doc_id || q.target_id || "—")),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: "review", label: "queued" })),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Queue ID", q.id || q.queue_id, null, true),
        kvRow("Document", q.doc_id || q.target_id, null, true),
        kvRow("Reason", q.reason),
        kvRow("Status", q.status),
        q.created_at && kvRow("Created", new Date(q.created_at).toLocaleDateString())));
  } else if (selection.type === "authority_integrity") {
    const i = selection.integrityItem;
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading" }, i.type === "violation" ? "Authority Violation" : "Drift Risk"),
        h("div", { className: "t-small muted" }, i.target_id || i.node_id || "—")),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: i.type === "violation" ? "conflict" : "stale", label: i.type || "item" })),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Item ID", i.target_id || i.node_id, null, true),
        ...(i.type === "violation" ? [
          kvRow("Required", i.required_authority),
          kvRow("Actor", i.actor_id)
        ] : [
          kvRow("State", (i.visual_state || {}).state || "—"),
          kvRow("Drift", i.drift_risk),
          kvRow("Valid until", i.valid_until)
        ]),
        ...(i.timestamp ? [kvRow("Time", new Date(i.timestamp).toLocaleDateString())] : [])));
  } else if (selection.type === "authority_ledger") {
    const l = selection.ledgerEvent;
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading" }, l.new_authority ? "Promotion" : "Resolution"),
        h("div", { className: "t-small muted" }, l.target_id || "—")),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: l.authorization_result ? "current" : "conflict", label: l.authorization_result ? "auth" : "denied" })),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Target", l.target_id, null, true),
        ...(l.new_authority ? [
          kvRow("From", l.old_authority),
          kvRow("To", l.new_authority),
          kvRow("Reason", l.promotion_reason),
          ...(l.promotion_timestamp ? [kvRow("When", new Date(l.promotion_timestamp).toLocaleDateString())] : [])
        ] : [
          kvRow("Actor", l.actor_id),
          kvRow("Required", l.required_authority),
          kvRow("Result", l.authorization_result ? "authorized" : "denied"),
          ...(l.timestamp ? [kvRow("When", new Date(l.timestamp).toLocaleDateString())] : [])
        ])));
  } else if (selection.type === "authority_gate") {
    const g = selection.gateResult;
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading" }, g.operation || g.trace_event_type || "Gate Result"),
        h("div", { className: "t-small muted" }, g.actor_id || "—")),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: g.posture === "blocking" ? "conflict" : g.posture === "warning" ? "stale" : "current", label: g.posture || "gate" })),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Gate ID", g.gate_result_id, null, true),
        kvRow("Operation", g.operation || g.trace_event_type),
        kvRow("Posture", g.posture),
        kvRow("Query", (g.query || "—").slice(0, 60)),
        g.created_ts && kvRow("Created", new Date(g.created_ts * 1000).toLocaleDateString())));
  } else if (selection.type === "authority_residence") {
    const r = selection.residence;
    body = h("div", { className: "inspector-body" },
      h("div", null,
        h("div", { className: "t-subheading" }, "Residence"),
        h("div", { className: "t-small muted" }, r.plane || r.resource || "—")),
      h("div", { className: "flex gap-2 wrap items-center" },
        Badge({ ns: "unknown", label: "residence" })),
      h("div", { className: "kv", style: { marginTop: "8px" } },
        kvRow("Residence ID", r.id || r.residence_id, null, true),
        kvRow("Plane", r.plane),
        kvRow("Resource", r.resource),
        kvRow("Type", r.residence_type || "—")));
  }
  return h("aside", { className: "inspector" },
    h("div", { className: "inspector-head" },
      h("span", { className: "t-micro" }, "Inspector"),
      h("span", { className: "spacer" }),
      selection && h("button", { className: "icon-btn", onClick: onClose, "aria-label": "Clear selection" }, Icon({ name: "close", size: 14 })),
      h("button", { className: "icon-btn", onClick: onCollapse, "aria-label": "Collapse inspector", title: "Close inspector panel" }, "‹")),
    body);
}
function kvRow(k, v, color, mono) {
  const display = (v == null || v === "") ? "—" : v;
  return h("div", { className: "kv-row" }, h("span", { className: "k" }, k),
    h("span", { className: "v" + (mono ? " t-mono" : ""), style: color ? { color } : null }, String(display)));
}

export function ToastHost({ toasts }) {
  return h("div", { className: "toast-host" },
    toasts.map((t) => { const meta = NS[t.ns || "current"]; return h("div", { className: "toast" },
      h("span", { className: "t-glyph", style: { color: meta.color } }, meta.glyph),
      h("span", { className: "t-msg" }, t.msg),
      t.undo && Button({ variant: "ghost", className: "sm", onClick: t.undo, children: ["Undo"] })); }));
}
