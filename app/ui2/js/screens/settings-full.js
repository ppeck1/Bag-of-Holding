/* BOH new UI — Settings. 6 groups per boh_claude_design_anchor_brief_v0_1.md §17.
   General (localStorage), Library & Indexing, Intake Automation, AI & Analysis,
   Visualization, Security & Advanced — all display/read-only except General. */
import { h } from "../dom.js";
import { api, escHtml, getToken, tokenHeaders } from "../api.js";
import { Card, Tabs, Segmented, Select, Toggle, Button, AlertBanner, Badge } from "../primitives.js";

let _tab = "general";

export function SettingsFullScreen({ settings, onSet, onConfirm, onToast }) {
  let root;
  function rebuild() { const old = root; const n = build(); old.replaceWith(n); }
  function build() {
    root = h("div", { class: "content content-narrow" },
      h("div", { class: "page-head" },
        h("div", { class: "t-display" }, "Settings"),
        h("div", { class: "sub t-small" }, "Bag of Holding is dark-only for v1. No theme toggle.")),
      Tabs({ value: _tab, onChange: v => { _tab = v; rebuild(); }, tabs: [
        { value: "general",    label: "General" },
        { value: "library",    label: "Library & Indexing" },
        { value: "intake",     label: "Intake Automation" },
        { value: "ai",         label: "AI & Analysis" },
        { value: "viz",        label: "Visualization" },
        { value: "security",   label: "Security & Advanced" },
      ] }),
      _tab === "general"  ? GeneralTab({ settings, onSet }) :
      _tab === "library"  ? StatusDrivenTab("Library & Indexing", libraryFields) :
      _tab === "intake"   ? StatusDrivenTab("Intake Automation", intakeFields) :
      _tab === "ai"       ? AITab({ onToast }) :
      _tab === "viz"      ? StatusDrivenTab("Visualization", vizFields) :
                            SecurityTab({ onConfirm, onToast }));
    return root;
  }
  return build();
}

function GeneralTab({ settings, onSet }) {
  return h("div", { class: "col gap-0", style: { marginTop: "16px" } }, Card({ title: "General", children: [
    settingRow("Row density", "Comfortable (40px) or Compact (32px) table rows.", "LIVE", "EXISTING BACKEND",
      Segmented({ value: settings.density, onChange: v => onSet("density", v), options: [{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }] })),
    settingRow("Default mode", "Simple hides diagnostic columns; Advanced shows everything.", "LIVE", "EXISTING BACKEND",
      Segmented({ value: settings.mode, onChange: v => onSet("mode", v), options: [{ value: "simple", label: "Simple" }, { value: "advanced", label: "Advanced" }] })),
    settingRow("Default landing page", "Which workspace screen opens on launch.", "NEXT RUN", "NEEDS CONFIG API",
      Select({ value: settings.landing, onChange: v => onSet("landing", v), width: 200, options: [{ value: "current", label: "Current State" }, { value: "review", label: "Review Center" }, { value: "library", label: "Library" }, { value: "status", label: "Status" }] })),
    settingRow("Diagnostic badges", "Show the DEV-OPEN badge and diagnostic chips in the top bar.", "LIVE", "EXISTING BACKEND",
      Toggle({ checked: settings.diagnostics, onChange: v => onSet("diagnostics", v), label: "Diagnostic badges" })),
  ] }));
}

const libraryFields = [
  ["Library root", "BOH_LIBRARY", "Directory the server reads from.", "RESTART REQUIRED", "EXISTING BACKEND"],
  ["Auto-index on startup", "BOH_AUTO_INDEX", "Re-index on every server start.", "RESTART REQUIRED", "EXISTING BACKEND"],
  ["Max files per scan", "BOH_AUTO_INDEX_MAX_FILES", "Limits scope of each scan.", "NEXT RUN", "EXISTING BACKEND"],
  ["Deterministic review on index", "BOH_DETERMINISTIC_REVIEW_ON_INDEX", "Run algorithmic review on newly indexed docs.", "NEXT RUN", "EXISTING BACKEND"],
  ["LLM review on index", "BOH_LLM_REVIEW_ON_INDEX", "Enqueue Ollama review for new docs.", "NEXT RUN", "EXISTING BACKEND"],
];
const intakeFields = [
  ["Data root", "BOH_DATA_ROOT", "Root for preserved/normalized artifacts.", "RESTART REQUIRED", "EXISTING BACKEND"],
  ["Scheduler enabled", "BOH_INTAKE_SCHEDULER_ENABLED", "Enable background scan daemon (true/false).", "RESTART REQUIRED", "EXISTING BACKEND"],
  ["Watch paths", "BOH_WATCH_PATH", "Colon-separated paths to watch.", "RESTART REQUIRED", "EXISTING BACKEND"],
  ["Scan interval (s)", "BOH_INTAKE_SCAN_INTERVAL", "Seconds between scans.", "RESTART REQUIRED", "EXISTING BACKEND"],
  ["Backpressure max", "BOH_INTAKE_BACKPRESSURE_MAX", "Max concurrent intake runs.", "NEXT RUN", "EXISTING BACKEND"],
];
const vizFields = [
  ["Max rendered nodes", "—", "Limit the graph node budget.", "LIVE", "NEW CAPABILITY"],
  ["Default projection", "—", "Which Fold projection opens by default.", "LIVE", "NEW CAPABILITY"],
  ["Animate transitions", "—", "Smooth projection switches.", "LIVE", "NEW CAPABILITY"],
  ["Camera memory", "—", "Persist zoom/pan across sessions.", "LIVE", "EXISTING BACKEND"],
];

function StatusDrivenTab(title, fields) {
  return h("div", { class: "col gap-0", style: { marginTop: "16px" } }, Card({ title, children: [
    AlertBanner({ ns: "unknown", children: ["These settings map to environment variables or planned config APIs. They are displayed for reference; editing requires a restart or is not yet wired."] }),
    ...fields.map(([name, ref, desc, live, impl]) => settingRow(name, `${desc} Env: ${ref}`, live, impl, h("span", { class: "t-small muted" }, ref === "—" ? "planned" : ref))),
  ] }));
}

function AITab({ onToast }) {
  const wrap = h("div", { style: { marginTop: "16px" } });
  api("/api/status").then(st => {
    const ol = (st && st.ollama) || {};
    wrap.replaceWith(Card({ title: "AI & Analysis", children: [
      settingRow("Ollama URL", "BOH_OLLAMA_URL", "Where the Ollama server listens.", "RESTART REQUIRED", "EXISTING BACKEND", h("span", { class: "t-small muted" }, ol.url || "not configured")),
      settingRow("Default model", "BOH_OLLAMA_MODEL", "Model to use for LLM review.", "RESTART REQUIRED", "EXISTING BACKEND", h("span", { class: "t-small muted" }, ol.model || "not set")),
      settingRow("Ollama available", "—", "Live status from /api/status.", "LIVE", "EXISTING BACKEND",
        h("span", { style: { color: ol.available ? "var(--state-current)" : "var(--text-muted)" } }, ol.available ? "✓ available" : (ol.enabled ? "enabled / unavailable" : "not enabled"))),
      h("div", { class: "setting-row" }, h("div", { class: "s-main" },
        h("div", { class: "s-name" }, "Governance locks"),
        h("div", { class: "s-desc" }, "These rules are hard-coded and cannot be changed in Settings.")),
        h("div", { class: "s-control col gap-1", style: { alignItems: "flex-start" } },
          lockRow("LLM proposal queue only", "LOCKED ON"),
          lockRow("LLM canon promotion", "LOCKED OFF"),
          lockRow("Trace LLM output", "LOCKED ON"))),
    ] }));
  });
  wrap.innerHTML = `<div class="t-small muted" style="margin-top:16px">Loading…</div>`;
  return wrap;
}
function lockRow(label, state) {
  const color = state === "LOCKED ON" ? "var(--state-current)" : "var(--state-conflict)";
  return h("div", { class: "flex gap-2 items-center" }, h("span", { class: "badge", style: { color, background: `color-mix(in oklab, ${color} 14%, transparent)`, border: `1px solid color-mix(in oklab, ${color} 30%, transparent)`, padding: "2px 8px", borderRadius: "999px", fontSize: "10px" } }, state), h("span", { class: "t-small muted" }, label));
}

function SecurityTab({ onConfirm, onToast }) {
  const wrap = h("div", { style: { marginTop: "16px" } });
  api("/api/status").then(st => {
    wrap.replaceWith(Card({ title: "Security & Advanced", children: [
      AlertBanner({ ns: "advisory", children: ["Secret values are never displayed. Token states show configured/not-configured only."] }),
      settingRow("Default actor", "BOH_DEFAULT_ACTOR", "Actor used for unauthenticated local requests.", "RESTART REQUIRED", "EXISTING BACKEND", h("span", { class: "t-small muted" }, st.default_actor || "dev_operator")),
      settingRow("Operator token", "BOH_OPERATOR_TOKEN", "Governs all mutation routes.", "RESTART REQUIRED", "EXISTING BACKEND",
        h("span", { style: { color: st.operator_token_set ? "var(--state-current)" : "var(--state-stale)" } }, st.operator_token_set ? "✓ configured" : "⚠ DEV-OPEN (not set)")),
      SessionTokenRow({ onToast }),
      settingRow("Retrieval token", "BOH_RETRIEVAL_TOKEN", "Governs /api/retrieve read access.", "RESTART REQUIRED", "EXISTING BACKEND",
        h("span", { style: { color: st.retrieval_token_set ? "var(--state-current)" : "var(--text-muted)" } }, st.retrieval_token_set ? "✓ configured" : "not set")),
      h("div", { class: "setting-row" }, h("div", { class: "s-main" }, h("div", { class: "s-name" }, "Maintenance actions")),
        h("div", { class: "s-control col gap-2", style: { alignItems: "flex-start" } },
          Button({ variant: "secondary", className: "sm", glyph: "↺", onClick: () => onConfirm({ kind: "rebuild", title: "Rebuild index?", body: "Discards derived index data and re-scans. Source files are untouched.", confirmLabel: "Rebuild index", variant: "secondary" }), children: ["Rebuild index"] }),
          Button({ variant: "danger", className: "sm", onClick: () => onConfirm({ kind: "reset", title: "Reset workspace?", body: "Irreversibly removes all local index data and layouts.", confirmLabel: "Reset workspace", variant: "danger", danger: true }), children: ["Reset workspace"] }))),
    ] }));
  });
  wrap.innerHTML = `<div class="t-small muted" style="margin-top:16px">Loading…</div>`;
  return wrap;
}

function SessionTokenRow({ onToast }) {
  let _input;
  function sessionState() {
    return getToken() ? "✓ set for this session" : "○ not set for this session";
  }
  function sessionColor() {
    return getToken() ? "var(--state-current)" : "var(--text-muted)";
  }
  const stateSpan = h("span", { style: { color: sessionColor() } }, sessionState());

  function save() {
    const val = (_input && _input.value) ? _input.value.trim() : "";
    if (!val) { onToast && onToast("Enter a token value before saving.", "stale"); return; }
    sessionStorage.setItem("boh_operator_token", val);
    if (_input) _input.value = "";
    stateSpan.textContent = sessionState();
    stateSpan.style.color = sessionColor();
    onToast && onToast("Operator token saved for this session.", "current");
  }
  function clear() {
    sessionStorage.removeItem("boh_operator_token");
    if (_input) _input.value = "";
    stateSpan.textContent = sessionState();
    stateSpan.style.color = sessionColor();
    onToast && onToast("Session token cleared.", "stale");
  }

  return h("div", { class: "setting-row" },
    h("div", { class: "s-main" },
      h("div", { class: "s-name" }, "Session token entry"),
      h("div", { class: "s-desc" }, "Enter the operator token for this browser tab. Cleared when the tab closes. Not the same as setting BOH_OPERATOR_TOKEN in the server environment."),
      h("div", { class: "s-annos" },
        h("span", { class: "anno", style: { color: "var(--state-advisory)" } }, "TAB-LOCAL ONLY"))),
    h("div", { class: "s-control col gap-2", style: { alignItems: "flex-start" } },
      h("div", { class: "flex gap-2" },
        (_input = h("input", { type: "password", placeholder: "Enter operator token…",
          style: { fontFamily: "var(--font-mono)", fontSize: "12px", padding: "4px 8px",
                   background: "var(--bg-input)", border: "1px solid var(--border-default)",
                   borderRadius: "6px", color: "var(--text-primary)", width: "200px" },
          onKeydown: e => { if (e.key === "Enter") save(); } })),
        Button({ variant: "secondary", className: "sm", onClick: save, children: ["Save for session"] }),
        Button({ variant: "ghost", className: "sm", onClick: clear, children: ["Clear"] })),
      stateSpan));
}

function settingRow(name, desc, live, impl, control) {
  const liveColor = live === "RESTART REQUIRED" ? "var(--state-stale)" : "var(--text-muted)";
  const implColor = impl === "NEW CAPABILITY" ? "var(--state-advisory)" : "var(--text-muted)";
  return h("div", { class: "setting-row" },
    h("div", { class: "s-main" },
      h("div", { class: "s-name" }, name),
      h("div", { class: "s-desc" }, desc),
      h("div", { class: "s-annos" },
        h("span", { class: "anno", style: { color: liveColor } }, live),
        h("span", { class: "anno", style: { color: implColor } }, impl))),
    h("div", { class: "s-control" }, control));
}
