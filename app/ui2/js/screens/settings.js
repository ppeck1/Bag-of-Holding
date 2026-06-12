/* BOH new UI (Phase A) — Settings screen. Port of SettingsScreen (screens.jsx).
   Dark-only v1: no theme toggle. Preferences persist in localStorage. */

import { h } from "../dom.js";
import { Card, Segmented, Select, Toggle } from "../primitives.js";

export function SettingsScreen({ settings, onSet }) {
  const fields = [
    { key: "density", name: "Row density", desc: "Comfortable (40px) or Compact (32px) table rows.", live: "LIVE", impl: "EXISTING BACKEND",
      control: Segmented({ value: settings.density, onChange: (v) => onSet("density", v), options: [{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }] }) },
    { key: "mode", name: "Default mode", desc: "Simple hides diagnostic columns and advanced controls; Advanced shows everything.", live: "LIVE", impl: "EXISTING BACKEND",
      control: Segmented({ value: settings.mode, onChange: (v) => onSet("mode", v), options: [{ value: "simple", label: "Simple" }, { value: "advanced", label: "Advanced" }] }) },
    { key: "landing", name: "Default landing page", desc: "Which workspace screen opens on launch.", live: "NEXT RUN", impl: "NEEDS CONFIG API",
      control: Select({ value: settings.landing, onChange: (v) => onSet("landing", v), width: 200,
        options: [{ value: "current", label: "Current State" }, { value: "review", label: "Review Center" }, { value: "library", label: "Library" }, { value: "status", label: "Status" }] }) },
    { key: "diagnostics", name: "Diagnostic badge visibility", desc: "Show the DEV-OPEN security badge and other diagnostic chips in the top bar.", live: "LIVE", impl: "EXISTING BACKEND",
      control: Toggle({ checked: settings.diagnostics, onChange: (v) => onSet("diagnostics", v), label: "Diagnostic badges" }) },
  ];
  return h("div", { className: "content content-narrow" },
    h("div", { className: "page-head" },
      h("div", { className: "t-display" }, "Settings"),
      h("div", { className: "sub t-small" }, "General workspace preferences. Bag of Holding is dark-only for v1 — no theme selector.")),
    Card({ title: "General", children: fields.map((f) => h("div", { className: "setting-row" },
      h("div", { className: "s-main" },
        h("div", { className: "s-name" }, f.name),
        h("div", { className: "s-desc" }, f.desc),
        h("div", { className: "s-annos" },
          h("span", { className: `anno ${f.live === "RESTART REQUIRED" ? "restart" : ""}`.trim() }, f.live),
          h("span", { className: `anno ${f.impl === "NEW CAPABILITY" ? "newcap" : ""}`.trim() }, f.impl))),
      h("div", { className: "s-control" }, f.control))) }));
}

export function StatusCell({ s, partial }) {
  const TONE = { primary: "var(--text-primary)", current: "var(--state-current)", accent: "var(--accent)", muted: "var(--text-muted)", stale: "var(--state-stale)" };
  let val = s.value, tone = s.tone;
  if (partial && s.label === "Intake watcher") { val = "UNAVAILABLE"; tone = "stale"; }
  return h("div", { className: "status-cell" },
    h("span", { className: "lbl t-micro" }, s.label),
    h("span", { className: "val" },
      s.kind === "pulse" && h("span", { className: "pulse-dot" }),
      s.kind === "dot" && h("span", { className: "dot", style: { background: TONE[tone] } }),
      h("span", { style: { color: TONE[tone], fontWeight: 500 } }, val)));
}
