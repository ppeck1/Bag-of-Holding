/* BOH new UI (Phase A) — state namespace metadata.
   Single source of truth for state → color/glyph/label, ported verbatim from the
   design prototype (components/data.jsx) and aligned with boh_component_sheet_v0_2.md §2
   and the node-encoding legend. Four independent namespaces; only `currentness` drives
   node fill. Colors reference the design tokens in tokens.css. */

export const NS = {
  // currentness (Fold) — the only namespace that drives default node fill
  current:    { glyph: "✓", color: "var(--state-current)",    label: "Current" },
  stale:      { glyph: "⚠", color: "var(--state-stale)",      label: "Stale" },
  expired:    { glyph: "⧖", color: "var(--state-expired)",    label: "Expired" },
  conflict:   { glyph: "!", color: "var(--state-conflict)",   label: "Conflicted" },
  unknown:    { glyph: "?", color: "var(--state-unknown)",    label: "Unknown" },
  // workflow / gate / intake — secondary markers, never fill
  review:     { glyph: "↺", color: "var(--state-review)",     label: "Review required" },
  blocked:    { glyph: "⊘", color: "var(--state-blocked)",    label: "Blocked" },
  quarantine: { glyph: "⊗", color: "var(--state-quarantine)", label: "Quarantined" },
  preserved:  { glyph: "▢", color: "var(--state-preserved)",  label: "Preserved-only" },
  // authority marker
  advisory:   { glyph: "◐", color: "var(--state-advisory)",   label: "Advisory" },
};

/** Plane palette (Evidence State projection only — Phase B). */
export const PLANES = {
  informational: { glyph: "I", color: "var(--plane-informational)", label: "Informational" },
  subjective:    { glyph: "S", color: "var(--plane-subjective)",    label: "Subjective" },
  evidence:      { glyph: "E", color: "var(--plane-evidence)",      label: "Evidence" },
  internal:      { glyph: "N", color: "var(--plane-internal)",      label: "Internal" },
  review:        { glyph: "R", color: "var(--plane-review)",        label: "Review" },
  canonical:     { glyph: "K", color: "var(--plane-canonical)",     label: "Canonical" },
  conflict:      { glyph: "X", color: "var(--plane-conflict)",      label: "Conflict" },
  archive:       { glyph: "A", color: "var(--plane-archive)",       label: "Archive" },
};

export function normalizePlaneKey(p) {
  return String(p || "").toLowerCase().trim();
}

export function nsMeta(ns) {
  return NS[ns] || { glyph: "", color: "var(--text-muted)", label: ns || "" };
}
