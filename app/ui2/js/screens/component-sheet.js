/* BOH new UI (Phase A) — Component Sheet: the foundry gallery / visual QA harness.
   Renders every primitive once so the design's Phase A acceptance checklist
   (boh_component_sheet_v0_2.md §12) can be verified at a glance. */

import { h } from "../dom.js";
import { NS } from "../ns.js";
import * as P from "../primitives.js";

function Section(title, ...children) {
  return h("section", { className: "section" },
    h("div", { className: "section-head" }, h("span", { className: "t-subheading" }, title)),
    h("div", { className: "flex gap-2 wrap items-center", style: { alignItems: "flex-start" } }, children));
}

export function ComponentSheet({ onToast, onConfirm }) {
  const btnVariants = ["primary", "secondary", "ghost", "governed", "containment", "danger"];
  return h("div", { className: "content content-narrow" },
    h("div", { className: "page-head" },
      h("div", { className: "t-display" }, "Component Sheet"),
      h("div", { className: "sub t-small" }, "The foundry — every primitive once. Visual acceptance for Phase A.")),

    Section("Buttons (6 variants)",
      ...btnVariants.map((v) => P.Button({ variant: v, onClick: () => onToast(`${v} button`), children: [v] }))),

    Section("Badges — all namespaces",
      ...Object.keys(NS).map((ns) => P.Badge({ ns }))),

    Section("Metric tiles",
      P.MetricTile({ ns: "current", count: 128, delta: "+4 since last index", dir: "up" }),
      P.MetricTile({ ns: "conflict", count: 3, delta: "+1 since last index", dir: "down" }),
      P.MetricTile({ ns: "unknown", count: 0, delta: "", dir: "flat" })),

    Section("Card",
      P.Card({ title: "A card", action: P.Button({ variant: "ghost", className: "sm", children: ["Action"] }),
        children: h("div", { className: "t-small muted" }, "Card body content.") })),

    Section("Inputs",
      P.Toggle({ checked: true, onChange: () => {}, label: "Toggle on" }),
      P.Toggle({ checked: false, onChange: () => {}, label: "Toggle off" }),
      P.Segmented({ value: "a", onChange: () => {}, options: [{ value: "a", label: "Comfortable" }, { value: "b", label: "Compact" }] }),
      P.Select({ value: "current", onChange: () => {}, options: [{ value: "current", label: "Current State" }, { value: "library", label: "Library" }] })),

    Section("Tabs",
      P.Tabs({ value: "overview", onChange: () => {}, tabs: [{ value: "overview", label: "Overview" }, { value: "fold", label: "Fold Workspace" }] })),

    h("section", { className: "section" },
      h("div", { className: "section-head" }, h("span", { className: "t-subheading" }, "Accordion")),
      P.Card({ children: P.Accordion({ items: [
        { id: "a", title: "Open by default", defaultOpen: true, body: h("div", { className: "t-small muted" }, "Tier-2 groups default open.") },
        { id: "b", title: "Collapsed by default", body: h("div", { className: "t-small muted" }, "Tier-3 groups default collapsed.") },
      ] }) })),

    h("section", { className: "section" },
      h("div", { className: "section-head" }, h("span", { className: "t-subheading" }, "Alert banner")),
      P.AlertBanner({ ns: "stale", children: ["Partial data — degraded state example."] })),

    h("section", { className: "section" },
      h("div", { className: "section-head" }, h("span", { className: "t-subheading" }, "Why current?")),
      P.Card({ children: P.WhyCurrent({ rows: [
        { dir: "pos", factor: "Source fresh", evi: "valid until 2026-09-01" },
        { dir: "pos", factor: "Authority confirmed", evi: "cert C_8821" },
        { dir: "weak", factor: "1 supporting source", evi: "stale" },
      ], onTrace: () => onToast("Routing to Trace & Gates (Phase B).", "review") }) })),

    h("section", { className: "section" },
      h("div", { className: "section-head" }, h("span", { className: "t-subheading" }, "Skeleton / Empty state")),
      P.Card({ children: h("div", { className: "col gap-3" },
        P.Skeleton({ w: "60%", h: 14 }), P.Skeleton({ w: "90%", h: 12 }),
        P.EmptyState({ glyph: "◈", title: "Nothing here yet", desc: "Empty-state panel reuses the Card primitive.",
          actions: P.Button({ variant: "primary", glyph: "+", children: ["Primary action"] }) })) })),

    Section("Modal",
      P.Button({ variant: "danger", onClick: () => onConfirm({ kind: "reset", title: "Reset workspace?",
        body: "Irreversibly removes local index data and layouts. Source files are not deleted.",
        confirmLabel: "Reset workspace", variant: "danger", danger: true }), children: ["Open danger modal"] })));
}
