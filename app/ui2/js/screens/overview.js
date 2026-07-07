/* BOH new UI (Phase A) — Current State / Overview. Port of OverviewScreen (screens.jsx).
   Currentness tiles, recent-changes table, and system-status cells come from the live
   adapter (js/api.js → data). "Needs attention" is a prototype affordance (fixtures)
   until conflict/review/intake summary endpoints are wired. */

import { h } from "../dom.js";
import { Button, Card, MetricTile, Badge, MarkerPip, Tooltip, AlertBanner, EmptyState, Skeleton, Tabs } from "../primitives.js";
import { nsMeta } from "../ns.js";
import * as FX from "../fixtures.js";
import { StatusCell } from "./settings.js";

const CURRENTNESS_KEYS = ["current", "stale", "expired", "conflict", "unknown"];
let _tab = "overview";

export function OverviewScreen(props) {
  const { protoState, selection, data, onSelectMetric, onSelectDoc, onToast, onConfirm, onNavigate } = props;
  const D = data || {};

  const head = h("div", { className: "page-head" },
    h("div", { className: "titlerow" },
      h("div", null,
        h("div", { className: "t-display" }, "Current State"),
        h("div", { className: "sub t-small" }, "What is healthy, what needs attention, and what changed — in Bag of Holding.")),
      h("div", { className: "flex gap-2 items-center" },
        Button({ variant: "ghost", glyph: "▦", onClick: () => onNavigate("library"), children: ["Open Library"] }),
        Button({ variant: "secondary", glyph: "+", onClick: () => onNavigate("intake"), children: ["Capture intake"] }))),
    Tabs({ value: _tab, onChange: (v) => { if (v === "fold") onNavigate("fold"); else { _tab = v; } }, tabs: [
      { value: "overview", label: "Overview" }, { value: "fold", label: "Fold Workspace" }] }));

  if (protoState === "loading") return h("div", { className: "content content-narrow" }, head, OverviewLoading());
  if (protoState === "empty")   return h("div", { className: "content content-narrow" }, head, OverviewEmpty({ onNavigate }));
  if (protoState === "error")   return h("div", { className: "content content-narrow" }, head, OverviewError({ onToast }));
  if (protoState === "denied")  return h("div", { className: "content content-narrow" }, head, OverviewDenied({ onNavigate }));

  const partial = protoState === "partial";
  const metrics = (D.metrics || FX.metrics).filter((m) => CURRENTNESS_KEYS.includes(m.key));
  const docs = D.recentDocs || FX.documents;
  const statusCells = D.statusCells || FX.systemStatus;
  const nodeCount = D.nodeCount != null ? D.nodeCount : FX.overviewCounts.nodes;

  return h("div", { className: "content content-narrow" },
    head,

    D.inferred && AlertBanner({ ns: "unknown", children: [
      h("strong", { style: { color: "var(--text-primary)" } }, "Inferred currentness. "),
      "These tiles map the backend coherence/conflict summary onto the design's currentness namespace; the mapping is provisional until a native currentness endpoint exists."] }),

    partial && AlertBanner({ ns: "stale",
      action: Button({ variant: "secondary", className: "sm", onClick: () => onToast("Retrying index scan — prototype action", "review"), children: ["Retry scan"] }),
      children: [h("strong", { style: { color: "var(--text-primary)" } }, "Partial data. "), "The last index scan was interrupted; counts may be incomplete until the scan completes."] }),

    // Currentness
    h("section", { className: "section" },
      h("div", { className: "section-head" },
        h("span", { className: "t-subheading" }, "Currentness"),
        h("span", { className: "count t-small" }, `${nodeCount} nodes`),
        h("span", { className: "spacer" }),
        h("span", { className: "t-small muted" }, "Fill = currentness · counts, not node fills")),
      h("div", { className: "metric-grid" },
        metrics.map((m) => MetricTile({
          ns: m.ns, count: m.count, delta: m.delta, dir: m.dir,
          selected: selection && selection.type === "metric" && selection.ns === m.ns,
          onClick: () => onSelectMetric(m),
        })))),

    // Needs attention (prototype affordance)
    h("section", { className: "section" },
      h("div", { className: "section-head" }, h("span", { className: "t-subheading" }, "Needs attention now"),
        h("span", { className: "spacer" }), h("span", { className: "t-small muted" }, "prototype summary")),
      Card({ bodyFlush: true, children: h("div", { className: "attn-list" },
        FX.attention.map((a) => { const meta = nsMeta(a.ns); return h("div", { className: "attn-row" },
          h("span", { className: "attn-glyph", style: { color: meta.color, background: `color-mix(in oklab, ${meta.color} 14%, transparent)` } }, meta.glyph),
          h("div", { className: "attn-text" }, h("div", { className: "lead" }, a.lead), h("div", { className: "sub" }, a.sub)),
          Button({ variant: a.action.variant, className: "sm",
            glyph: a.action.variant === "governed" ? "↺" : (a.action.variant === "containment" ? "⊗" : null),
            onClick: () => { if (a.action.variant === "governed") onToast("Opened a review item — a reviewer must act before anything changes.", "review"); else onNavigate(a.target); },
            children: [a.action.label] })); })) })),

    // Recent changes (real docs)
    h("section", { className: "section" },
      h("div", { className: "section-head" },
        h("span", { className: "t-subheading" }, "Recent changes"),
        h("span", { className: "count t-small" }, `${docs.length} documents`),
        h("span", { className: "spacer" }),
        Button({ variant: "ghost", className: "sm", onClick: () => onNavigate("library"), children: ["Browse Library →"] })),
      Card({ bodyFlush: true, children: h("div", { style: { overflowX: "auto" } },
        h("table", { className: "tbl" },
          h("thead", null, h("tr", null,
            h("th", { style: { width: "132px" } }, "State"),
            h("th", null, "Document"),
            h("th", { className: "adv-only", style: { width: "130px" } }, "Project"),
            h("th", { className: "adv-only", style: { width: "130px" } }, "Authority"),
            h("th", { style: { width: "110px" } }, "Lifecycle"),
            h("th", { style: { width: "160px" } }, "Required action"),
            h("th", { className: "num", style: { width: "90px" } }, "Updated"))),
          h("tbody", null, docs.map((d) => h("tr", {
            className: selection && selection.type === "doc" && selection.doc.id === d.id ? "selected" : "",
            tabindex: "0", onClick: () => onSelectDoc(d), onKeydown: (e) => { if (e.key === "Enter") onSelectDoc(d); },
          },
            h("td", null, Badge({ ns: d.currentness || "unknown" })),
            h("td", null, h("span", { className: "doc-title" }, d.title),
              (d.markers && d.markers.length) ? h("span", { className: "markers" }, d.markers.map((m) => MarkerPip({ ns: m }))) : null),
            h("td", { className: "adv-only" }, d.project || "—"),
            h("td", { className: "adv-only" }, d.authority || "—"),
            h("td", null, d.lifecycle || "—"),
            h("td", null, d.action ? h("span", { style: { color: "var(--state-review)" } }, d.action) : h("span", { className: "muted" }, "—")),
            h("td", { className: "num muted" }, d.updated || "—")))))) })),

    // System status (real cells)
    h("section", { className: "section" },
      h("div", { className: "section-head" }, h("span", { className: "t-subheading" }, "System status")),
      Card({ bodyFlush: true, children: [
        h("div", { className: "card-head", style: { borderBottom: "1px solid var(--border-default)" } },
          h("span", { className: "t-small muted" }, "Local runtime · Bag of Holding"), h("span", { className: "spacer" }),
          Button({ variant: "secondary", className: "sm", glyph: "↺", onClick: () => onConfirm({ kind: "rebuild", title: "Rebuild index?", body: "Discards derived index data and re-scans the managed library. Source files are untouched and the operation is recoverable by re-running.", confirmLabel: "Rebuild index", variant: "secondary" }), children: ["Rebuild index"] })),
        h("div", { className: "card-body" }, h("div", { className: "status-grid" }, statusCells.map((s) => StatusCell({ s, partial })))),
      ] })));
}

function OverviewLoading() {
  return h("div", null,
    h("section", { className: "section" }, Skeleton({ w: 120, h: 14 }),
      h("div", { className: "metric-grid" }, [0,1,2,3,4].map(() => h("div", { className: "metric-tile", style: { cursor: "default" } },
        Skeleton({ w: 84, h: 20, r: 999 }), Skeleton({ w: 48, h: 28, style: { marginTop: "6px" } }), Skeleton({ w: 90, h: 12 }))))),
    h("section", { className: "section" }, Skeleton({ w: 150, h: 14 }),
      h("div", { className: "card" }, h("div", { className: "card-body col gap-3" }, [0,1,2,3].map(() =>
        h("div", { className: "flex gap-3 items-center" }, Skeleton({ w: 22, h: 22, r: 6 }),
          h("div", { className: "col gap-1", style: { flex: 1 } }, Skeleton({ w: "40%", h: 12 }), Skeleton({ w: "70%", h: 10 })),
          Skeleton({ w: 120, h: 26, r: 8 })))))),
    h("section", { className: "section" }, Skeleton({ w: 150, h: 14 }),
      h("div", { className: "card" }, h("div", { className: "card-body col gap-3" }, [0,1,2,3,4].map(() => Skeleton({ w: "100%", h: 20 }))))));
}

function OverviewEmpty({ onNavigate }) {
  return Card({ children: EmptyState({ glyph: "◈", title: "Empty corpus — nothing indexed yet",
    desc: "No documents have been admitted to the index for this library. Capture material through Intake, then index the library to populate Current State.",
    actions: [Button({ variant: "primary", glyph: "+", onClick: () => onNavigate("intake"), children: ["Capture intake"] }),
      Button({ variant: "secondary", glyph: "▦", onClick: () => onNavigate("library"), children: ["Index library"] })] }) });
}

function OverviewError({ onToast }) {
  return Card({ children: EmptyState({ glyph: "!", title: "Could not load Current State",
    desc: "The resolver did not respond. No data has been changed. Retry, or open the activity log to see what failed.",
    actions: [Button({ variant: "primary", glyph: "↺", onClick: () => onToast("Retrying — prototype action", "review"), children: ["Retry"] }),
      Button({ variant: "ghost", children: ["Open activity log"] })] }) });
}

function OverviewDenied({ onNavigate }) {
  return Card({ children: EmptyState({ glyph: "⊘", title: "Permission denied",
    desc: "Current State requires a configured local operator token. Go to Settings → Security & Advanced to enter your session token.",
    actions: Button({ variant: "secondary", onClick: () => onNavigate && onNavigate("settings"), children: ["Open Settings"] }) }) });
}

export function PlaceholderScreen({ title, glyph, desc, onNavigate }) {
  return h("div", { className: "content content-narrow" },
    h("div", { className: "page-head" }, h("div", { className: "t-display" }, title)),
    Card({ children: EmptyState({ glyph, title: `${title} arrives in a later phase`, desc,
      actions: Button({ variant: "ghost", glyph: "◈", onClick: () => onNavigate("current"), children: ["Back to Current State"] }) }) }));
}
