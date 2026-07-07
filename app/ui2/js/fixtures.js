/* BOH new UI (Phase A) — prototype fixture data.
   Ported from the design prototype (components/data.jsx). Used by the Component
   Sheet and by shell affordances (alerts / jobs / scope / attention) that do not
   yet have a clean backend endpoint in Phase A. Screens that DO have real data
   (Overview metrics/recent/corpus, Status runtime) use js/api.js instead.
   Anything sourced from here is prototype/demo data, not live state. */

export const why = {
  healthy: [
    { dir: "pos",  factor: "Source fresh",        evi: "valid until 2026-09-01" },
    { dir: "pos",  factor: "Authority confirmed",  evi: "cert C_8821" },
    { dir: "weak", factor: "1 supporting source",  evi: "stale" },
    { dir: "pos",  factor: "No open conflicts",    evi: "" },
  ],
  stale: [
    { dir: "weak", factor: "Source aging",         evi: "indexed 41 days ago" },
    { dir: "pos",  factor: "Authority confirmed",  evi: "cert C_7740" },
    { dir: "weak", factor: "Supersedes pending",   evi: "1 newer draft" },
    { dir: "neutral", factor: "No open conflicts", evi: "" },
  ],
  conflict: [
    { dir: "weak", factor: "Contradicts canon",    evi: "Planar Storage Doctrine" },
    { dir: "pos",  factor: "Source fresh",         evi: "valid until 2026-08-12" },
    { dir: "weak", factor: "Authority unconfirmed",evi: "no certificate" },
    { dir: "weak", factor: "1 open conflict",      evi: "unresolved" },
  ],
  unknown: [
    { dir: "neutral", factor: "Authority unmapped", evi: "placeholder" },
    { dir: "weak", factor: "LLM-origin",            evi: "advisory" },
    { dir: "neutral", factor: "No supporting source", evi: "" },
    { dir: "neutral", factor: "Not yet reviewed",   evi: "" },
  ],
  expired: [
    { dir: "weak", factor: "Validity window closed", evi: "expired 2026-05-18" },
    { dir: "pos",  factor: "Authority confirmed",    evi: "cert C_6021" },
    { dir: "neutral", factor: "No replacement indexed", evi: "" },
    { dir: "neutral", factor: "No open conflicts",   evi: "" },
  ],
};

export const metrics = [
  { key: "current",   ns: "current",    count: 128, delta: "+4 since last index", dir: "up" },
  { key: "stale",     ns: "stale",      count: 14,  delta: "+2 since last index", dir: "down" },
  { key: "expired",   ns: "expired",    count: 2,   delta: "+1 since last index", dir: "down" },
  { key: "conflict",  ns: "conflict",   count: 3,   delta: "+1 since last index", dir: "down" },
  { key: "unknown",   ns: "unknown",    count: 9,   delta: "−1 since last index", dir: "up" },
  { key: "review",    ns: "review",     count: 11,  delta: "4 new handoffs",      dir: "flat" },
  { key: "preserved", ns: "preserved",  count: 7,   delta: "no change",           dir: "flat" },
  { key: "quarantine",ns: "quarantine", count: 2,   delta: "+1 since last index", dir: "down" },
];

export const documents = [
  { id: "d1", title: "Planar Storage Doctrine",    project: "Project Atlas", authority: "Canon · cert", currentness: "current", markers: [],                     lifecycle: "Stable",  action: "",                   updated: "4m ago",  why: why.healthy },
  { id: "d2", title: "Authority Ledger Whitepage", project: "Project Atlas", authority: "Reference",    currentness: "current", markers: ["review"],            lifecycle: "Review",  action: "Awaiting admission", updated: "22m ago", why: why.healthy },
  { id: "d3", title: "BOH Fold Workspace Spec",    project: "Project Atlas", authority: "Draft",        currentness: "stale",   markers: [],                     lifecycle: "Draft",   action: "Re-validate source", updated: "1h ago",  why: why.stale },
  { id: "d4", title: "Intake Capability Map",      project: "Intake",        authority: "Reference",    currentness: "current", markers: ["preserved"],         lifecycle: "Stable",  action: "",                   updated: "2h ago",  why: why.healthy },
  { id: "d5", title: "Overlay Schema Proposal",    project: "Overlays",      authority: "Unmapped",     currentness: "unknown", markers: ["advisory","review"], lifecycle: "Proposed",action: "Reviewer must act",  updated: "3h ago",  why: why.unknown },
  { id: "d6", title: "Metis Retrieval Contract",   project: "Retrieval",     authority: "Reference",    currentness: "conflict",markers: ["blocked"],           lifecycle: "Blocked", action: "Resolve conflict",   updated: "5h ago",  why: why.conflict },
  { id: "d7", title: "Current State Snapshot",     project: "Project Atlas", authority: "Derived",      currentness: "current", markers: [],                     lifecycle: "Stable",  action: "",                   updated: "6h ago",  why: why.healthy },
  { id: "d8", title: "Watcher Configuration",      project: "System",        authority: "Reference",    currentness: "expired", markers: ["quarantine"],        lifecycle: "Archive", action: "Renew validity",     updated: "1d ago",  why: why.expired },
];

export const attention = [
  { id: "a1", ns: "conflict",   lead: "3 conflicts unresolved",  sub: "Canon collisions awaiting an explicit decision.",       action: { label: "Review conflicts", variant: "governed", sub: "review" }, target: "review" },
  { id: "a2", ns: "review",     lead: "11 awaiting admission",   sub: "Handoffs queued for an audited admission decision.",     action: { label: "Open Review Center", variant: "secondary" }, target: "review" },
  { id: "a3", ns: "expired",    lead: "2 expired sources",       sub: "Validity windows have closed; no replacement indexed.",  action: { label: "View expired", variant: "secondary" }, target: "library" },
  { id: "a4", ns: "quarantine", lead: "2 quarantined artifacts", sub: "Isolated during intake; preserved and releasable.",      action: { label: "Open Exceptions", variant: "containment" }, target: "intake" },
  { id: "a5", ns: "preserved",  lead: "7 preserved-only items",  sub: "Captured but not admitted to the index.",                action: { label: "Review intake", variant: "secondary" }, target: "intake" },
];

export const alerts = [
  { id: "al1", ns: "stale",    title: "Watch path unavailable",       source: "Intake watcher",   time: "2m ago",  expl: "The configured watch folder did not respond on the last scan. Captured items are buffered.", action: "Retry watch path", resolved: false },
  { id: "al2", ns: "review",   title: "4 handoffs awaiting admission", source: "Review Center",    time: "18m ago", expl: "New handoffs require an audited admission decision before indexing.", action: "Open Review Center", resolved: false },
  { id: "al3", ns: "conflict", title: "Authority conflict detected",   source: "Authority & Audit",time: "32m ago", expl: "Two references claim canon for the same topic. No auto-resolution will occur.", action: "Open conflict", resolved: false },
  { id: "al4", ns: "current",  title: "Index completed",               source: "Index scan",       time: "4m ago",  expl: "Index scan finished with 128 updated nodes.", action: "", resolved: true },
];

export const jobs = [
  { id: "j1", name: "Index scan",          state: "running", detail: "scanning · 128 nodes",        pct: 62 },
  { id: "j2", name: "Autoindex (library)", state: "queued",  detail: "queued behind index scan",    pct: 0 },
  { id: "j3", name: "Last admission run",  state: "done",    detail: "completed 12m ago",           pct: 100 },
];

export const systemStatus = [
  { label: "Last indexed",   value: "4 minutes ago", tone: "primary", kind: "text" },
  { label: "Intake watcher", value: "HEALTHY",       tone: "current", kind: "dot" },
  { label: "Index scan",     value: "RUNNING",       tone: "accent",  kind: "pulse" },
  { label: "Ollama",         value: "OPTIONAL / OFF",tone: "muted",   kind: "dot" },
  { label: "Security state", value: "DEV-OPEN",      tone: "stale",   kind: "dot" },
];

export const overviewCounts = { nodes: 163 };
