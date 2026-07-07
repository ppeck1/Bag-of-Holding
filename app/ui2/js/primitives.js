/* BOH new UI (Phase A) — reusable primitives (the foundry).
   Vanilla port of components/primitives.jsx; same DOM/classnames so app.css applies.
   Spec: boh_component_sheet_v0_2.md. */

import { h } from "./dom.js";
import { nsMeta } from "./ns.js";

/* ---------- Icon (UI chrome only; state uses text glyphs) ---------- */
const ICON_PATHS = {
  search:   '<circle cx="7" cy="7" r="5"/><path d="M11 11l4 4"/>',
  bell:     '<path d="M8 2a4 4 0 0 0-4 4c0 4-1.5 5-1.5 5h11S12 10 12 6a4 4 0 0 0-4-4z"/><path d="M6.5 13.5a1.6 1.6 0 0 0 3 0"/>',
  jobs:     '<rect x="2.5" y="4.5" width="11" height="8" rx="1.5"/><path d="M6 4.5V3.5a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v1"/>',
  close:    '<path d="M4 4l8 8M12 4l-8 8"/>',
  chevDown: '<path d="M4 6l4 4 4-4"/>',
  chevRight:'<path d="M6 4l4 4-4 4"/>',
  gear:     '<circle cx="8" cy="8" r="2.2"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4"/>',
  plus:     '<path d="M8 3v10M3 8h10"/>',
  refresh:  '<path d="M13 8a5 5 0 1 1-1.5-3.5"/><path d="M13 2.5V5h-2.5"/>',
  external: '<path d="M6 3H3.5v9.5h9.5V10"/><path d="M9 3h4v4M13 3L7.5 8.5"/>',
  copy:     '<rect x="5" y="5" width="8" height="8" rx="1.2"/><path d="M3 11V3.5A.5.5 0 0 1 3.5 3H11"/>',
  info:     '<circle cx="8" cy="8" r="6"/><path d="M8 7.2v3.6M8 5.2v.2"/>',
  shield:   '<path d="M8 1.8l5 1.8v3.8c0 3.2-2.2 5.2-5 6.2-2.8-1-5-3-5-6.2V3.6z"/>',
  check:    '<path d="M3.5 8.5l3 3 6-7"/>',
  filter:   '<path d="M2.5 4h11M5 8h6M7 12h2"/>',
  list:     '<path d="M3 4h10M3 8h10M3 12h10"/>',
};

export function Icon({ name, size = 16, stroke = 1.6, className, style }) {
  const tmpl = document.createElement("template");
  tmpl.innerHTML =
    `<svg width="${size}" height="${size}" viewBox="0 0 16 16" fill="none" stroke="currentColor"` +
    ` stroke-width="${stroke}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">` +
    `${ICON_PATHS[name] || ""}</svg>`;
  const el = tmpl.content.firstChild;
  if (className) el.setAttribute("class", className);
  if (style) Object.assign(el.style, style);
  return el;
}

/* ---------- Badge ---------- */
export function Badge({ ns, label, glyph, color, className = "" }) {
  const meta = ns ? nsMeta(ns) : {};
  const c = color || meta.color || "var(--text-muted)";
  const g = glyph || meta.glyph;
  const text = label || meta.label || "";
  return h("span", {
    className: "badge " + className,
    style: {
      color: c,
      background: `color-mix(in oklab, ${c} 14%, transparent)`,
      border: `1px solid color-mix(in oklab, ${c} 30%, transparent)`,
    },
  }, g && h("span", { className: "b-glyph" }, g), text);
}

/* secondary marker pip */
export function MarkerPip({ ns }) {
  const meta = nsMeta(ns);
  return Tooltip({ text: meta.label, children: [h("span", { className: "marker-pip", style: { color: meta.color } }, meta.glyph)] });
}

/* ---------- Button ---------- */
export function Button({ variant = "secondary", glyph, children, className = "", ...rest }) {
  return h("button", { className: `btn btn-${variant} ${className}`.trim(), ...rest },
    glyph && h("span", { className: "b-glyph" }, glyph), children);
}

/* ---------- Card ---------- */
export function Card({ title, action, children, raised = false, className = "", bodyFlush = false }) {
  return h("div", { className: `card ${raised ? "raised" : ""} ${className}`.trim() },
    (title || action) && h("div", { className: "card-head" },
      h("span", { className: "t-subheading" }, title),
      h("span", { className: "spacer" }),
      action),
    h("div", { className: `card-body ${bodyFlush ? "flush" : ""}`.trim() }, children));
}

/* ---------- Metric tile ---------- */
export function MetricTile({ ns, count, delta, dir = "flat", selected, onClick }) {
  return h("button", {
    className: `metric-tile ${count === 0 ? "zero" : ""} ${selected ? "selected" : ""}`.trim(),
    onClick, "aria-pressed": selected ? "true" : "false",
  },
    Badge({ ns }),
    h("span", { className: "count" }, count),
    (delta && count !== 0) && h("span", { className: `delta ${dir}` }, delta));
}

/* ---------- Tooltip (hover + focus) ---------- */
export function Tooltip({ text, below = false, children }) {
  if (!text) return h("span", null, children);
  const tip = h("span", { className: `tooltip ${below ? "below" : ""}`.trim(), role: "tooltip", style: { display: "none" } }, text);
  const show = () => { tip.style.display = ""; };
  const hide = () => { tip.style.display = "none"; };
  return h("span", { className: "tt-wrap", onMouseenter: show, onMouseleave: hide, onFocusin: show, onFocusout: hide }, children, tip);
}

/* ---------- Popover (click; outside-click + Esc to close) ---------- */
export function Popover({ trigger, children, align = "left", width }) {
  const wrap = h("span", { style: { position: "relative", display: "inline-flex" } });
  let panel = null;
  const close = () => {
    if (!panel) return;
    panel.remove(); panel = null;
    document.removeEventListener("mousedown", onDoc);
    document.removeEventListener("keydown", onKey);
  };
  const onDoc = (e) => { if (!wrap.contains(e.target)) close(); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const open = () => {
    if (panel) return;
    const body = typeof children === "function" ? children({ close }) : children;
    panel = h("div", { className: "popover", style: { top: "calc(100% + 8px)", [align]: 0, width } }, body);
    wrap.appendChild(panel);
    setTimeout(() => { document.addEventListener("mousedown", onDoc); document.addEventListener("keydown", onKey); }, 0);
  };
  const toggle = () => (panel ? close() : open());
  wrap.appendChild(trigger({ toggle, close }));
  return wrap;
}

/* ---------- Toggle ---------- */
export function Toggle({ checked, onChange, label }) {
  return h("button", {
    className: "toggle", role: "switch", "aria-checked": checked ? "true" : "false", "aria-label": label,
    onClick: () => onChange(!checked),
  }, h("span", { className: "knob" }));
}

/* ---------- Segmented ---------- */
export function Segmented({ value, onChange, options, sm = false }) {
  return h("div", { className: `segmented ${sm ? "sm" : ""}`.trim(), role: "group" },
    options.map((o) => h("button", {
      key: o.value, "aria-pressed": value === o.value ? "true" : "false",
      onClick: () => onChange(o.value),
    }, o.label)));
}

/* ---------- Select (dropdown) ---------- */
export function Select({ value, onChange, options, width = 180 }) {
  return Popover({
    width,
    trigger: ({ toggle }) => h("button", { className: "select-trigger", style: { width: typeof width === "number" ? width + "px" : width }, onClick: toggle },
      h("span", null, (options.find((o) => o.value === value) || {}).label || value),
      Icon({ name: "chevDown", size: 14, className: "caret" })),
    children: ({ close }) => options.map((o) => h("button", {
      key: o.value, className: `menu-item ${o.value === value ? "selected" : ""}`.trim(),
      onClick: () => { onChange(o.value); close(); },
    }, o.label, o.value === value && Icon({ name: "check", size: 14, className: "check" }))),
  });
}

/* ---------- Tab strip ---------- */
export function Tabs({ value, onChange, tabs }) {
  return h("div", { className: "tabstrip", role: "tablist" },
    tabs.map((t) => h("button", {
      key: t.value, role: "tab", className: "tab",
      "aria-selected": value === t.value ? "true" : "false",
      disabled: t.disabled, onClick: () => !t.disabled && onChange(t.value),
    }, t.label, t.badge && h("span", { className: "tab-badge" }, t.badge))));
}

/* ---------- Accordion ---------- */
export function Accordion({ items }) {
  return h("div", null, items.map((it) => {
    const body = h("div", { className: "acc-body", style: { display: it.defaultOpen ? "" : "none" } }, it.body);
    const item = h("div", { className: `acc-item ${it.defaultOpen ? "open" : ""}`.trim() },
      h("button", {
        className: "acc-head t-micro", "aria-expanded": it.defaultOpen ? "true" : "false",
        onClick: () => {
          const open = item.classList.toggle("open");
          body.style.display = open ? "" : "none";
          item.firstChild.setAttribute("aria-expanded", open ? "true" : "false");
        },
      }, Icon({ name: "chevRight", size: 12, className: "chev" }), it.title, h("span", { className: "spacer" }), it.meta),
      body);
    return item;
  }));
}

/* ---------- Alert banner ---------- */
export function AlertBanner({ ns, children, action }) {
  const meta = nsMeta(ns);
  return h("div", { className: "alert-banner", style: { color: meta.color, background: `color-mix(in oklab, ${meta.color} 10%, transparent)` } },
    h("span", { className: "ab-glyph" }, meta.glyph),
    h("div", { className: "ab-body", style: { color: "var(--text-secondary)" } }, children),
    action);
}

/* ---------- Empty state ---------- */
export function EmptyState({ glyph = "▢", title, desc, actions }) {
  return h("div", { className: "empty" },
    h("div", { className: "e-glyph" }, glyph),
    h("div", { className: "e-title t-subheading" }, title),
    desc && h("div", { className: "e-desc t-small" }, desc),
    actions && h("div", { className: "e-actions" }, actions));
}

/* ---------- Skeleton ---------- */
export function Skeleton({ w = "100%", h: hh = 12, r = 6, pulse = true, style = {} }) {
  return h("div", { className: `sk ${pulse ? "pulse" : ""}`.trim(), style: { width: typeof w === "number" ? w + "px" : w, height: typeof hh === "number" ? hh + "px" : hh, borderRadius: typeof r === "number" ? r + "px" : r, ...style } });
}

/* ---------- Why-current factor rows ---------- */
export function WhyCurrent({ rows, onTrace }) {
  const DIR = { pos: "✓", weak: "⚠", neutral: "·" };
  return h("div", { className: "why" },
    rows.map((r) => h("div", { className: "why-row" },
      h("span", { className: `dir ${r.dir}` }, DIR[r.dir]),
      h("span", { className: "factor t-body" }, r.factor),
      h("span", { className: "evi" }, r.evi))),
    h("button", { className: "trace-link", onClick: onTrace }, "→ View full trace"));
}

/* ---------- Confirmation modal ---------- */
export function Modal({ title, children, footer, onClose }) {
  const onKey = (e) => { if (e.key === "Escape" && onClose) onClose(); };
  document.addEventListener("keydown", onKey);
  const wrap = h("div", { className: "modal-wrap" },
    h("div", { className: "scrim", onClick: onClose }),
    h("div", { className: "modal", role: "dialog", "aria-modal": "true", "aria-label": title },
      h("div", { className: "modal-head" }, h("span", { className: "t-heading" }, title)),
      h("div", { className: "modal-body" }, children),
      footer && h("div", { className: "modal-foot" }, footer)));
  // best-effort listener cleanup when removed
  wrap.__cleanup = () => document.removeEventListener("keydown", onKey);
  return wrap;
}
