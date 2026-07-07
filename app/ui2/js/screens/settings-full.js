/* BOH new UI — Settings. 6 groups per boh_claude_design_anchor_brief_v0_1.md §17.
   General (localStorage), Library & Indexing, Intake Automation, AI & Analysis,
   Visualization, Security & Advanced — all display/read-only except General. */
import { h } from "../dom.js";
import { api, escHtml, getToken, tokenHeaders } from "../api.js";
import { Card, Tabs, Segmented, Select, Toggle, Button, AlertBanner, Badge, Skeleton } from "../primitives.js";

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
      _tab === "intake"   ? IntakeAutomationTab() :
      _tab === "ai"       ? AITab({ onToast }) :
      _tab === "viz"      ? StatusDrivenTab("Visualization", vizFields) :
                            SecurityTab({ onConfirm, onToast }));
    return root;
  }
  return build();
}

function GeneralTab({ settings, onSet }) {
  return h("div", { class: "col gap-0", style: { marginTop: "16px" } }, Card({ title: "General", children: [
    settingRow("Row density", "Comfortable (40px) or Compact (32px) table rows.", "LIVE", "BROWSER LOCAL",
      Segmented({ value: settings.density, onChange: v => onSet("density", v), options: [{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }] })),
    settingRow("Default mode", "Simple hides diagnostic columns; Advanced shows everything.", "LIVE", "BROWSER LOCAL",
      Segmented({ value: settings.mode, onChange: v => onSet("mode", v), options: [{ value: "simple", label: "Simple" }, { value: "advanced", label: "Advanced" }] })),
    settingRow("Default landing page", "Which workspace screen opens on launch.", "NEXT RUN", "NEEDS SETTINGS API",
      Select({ value: settings.landing, onChange: v => onSet("landing", v), width: 200, options: [{ value: "current", label: "Current State" }, { value: "review", label: "Review Center" }, { value: "library", label: "Library" }, { value: "status", label: "Status" }] })),
    settingRow("Diagnostic badges", "Show the DEV-OPEN badge and diagnostic chips in the top bar.", "LIVE", "BROWSER LOCAL",
      Toggle({ checked: settings.diagnostics, onChange: v => onSet("diagnostics", v), label: "Diagnostic badges" })),
  ] }));
}

const libraryFields = [
  ["Library root", "BOH_LIBRARY", "Directory the server reads from.", "RESTART REQUIRED", "READ-ONLY ENV"],
  ["Auto-index on startup", "BOH_AUTO_INDEX", "Re-index on every server start.", "RESTART REQUIRED", "READ-ONLY ENV"],
  ["Max files per scan", "BOH_AUTO_INDEX_MAX_FILES", "Limits scope of each scan.", "NEXT RUN", "READ-ONLY ENV"],
  ["Deterministic review on index", "BOH_DETERMINISTIC_REVIEW_ON_INDEX", "Run algorithmic review on newly indexed docs.", "NEXT RUN", "READ-ONLY ENV"],
  ["LLM review on index", "BOH_LLM_REVIEW_ON_INDEX", "Enqueue Ollama review for new docs.", "NEXT RUN", "READ-ONLY ENV"],
];
const intakeFields = [
  ["Data root", "BOH_DATA_ROOT", "Root for preserved/normalized artifacts.", "RESTART REQUIRED", "READ-ONLY ENV"],
  ["Scheduler enabled", "BOH_INTAKE_SCHEDULER_ENABLED", "Enable background scan daemon (true/false).", "RESTART REQUIRED", "READ-ONLY ENV"],
  ["Watch paths", "BOH_WATCH_PATH", "Colon-separated paths to watch.", "RESTART REQUIRED", "READ-ONLY ENV"],
  ["Scan interval (s)", "BOH_INTAKE_SCAN_INTERVAL", "Seconds between scans.", "RESTART REQUIRED", "READ-ONLY ENV"],
  ["Backpressure max", "BOH_INTAKE_BACKPRESSURE_MAX", "Max concurrent intake runs.", "NEXT RUN", "READ-ONLY ENV"],
];
const vizFields = [
  ["Max rendered nodes", "—", "Limit the graph node budget.", "LIVE", "NEEDS SETTINGS API"],
  ["Default projection", "—", "Which Fold projection opens by default.", "LIVE", "NEEDS SETTINGS API"],
  ["Animate transitions", "—", "Smooth projection switches.", "LIVE", "NEEDS SETTINGS API"],
  ["Camera memory", "—", "Persist zoom/pan across sessions.", "LIVE", "BROWSER LOCAL"],
];

function StatusDrivenTab(title, fields) {
  const wrap = h("div", { style: { marginTop: "16px" } });
  api("/api/status").then(st => {
    wrap.replaceWith(Card({ title, children: [
      AlertBanner({ ns: "unknown", children: ["These settings map to environment variables or planned config APIs. They are displayed for reference; editing requires a restart or is not yet wired."] }),
      ...fields.map(([name, ref, desc, live, impl]) => {
        let value = ref === "—" ? "planned" : ref;
        let badge = null;

        // Map ref to actual status values
        if (title === "Library & Indexing") {
          if (ref === "BOH_LIBRARY") {
            value = st.library_root || "—";
            badge = "requires env change";
          } else if (ref === "BOH_AUTO_INDEX") {
            value = st.autoindex?.enabled ? "enabled" : "disabled";
            badge = "requires env change";
          } else if (ref === "BOH_AUTO_INDEX_MAX_FILES") {
            value = "—";
            badge = "requires env change";
          } else if (ref === "BOH_DETERMINISTIC_REVIEW_ON_INDEX") {
            value = "—";
            badge = "requires env change";
          } else if (ref === "BOH_LLM_REVIEW_ON_INDEX") {
            value = "—";
            badge = "requires env change";
          }
        } else if (title === "Intake Automation") {
          if (ref === "BOH_DATA_ROOT") {
            value = "—";
            badge = "requires env change";
          } else if (ref === "BOH_INTAKE_SCHEDULER_ENABLED") {
            value = st.intake_scheduler?.enabled ? "enabled" : "disabled";
            badge = "requires env change";
          } else if (ref === "BOH_WATCH_PATH") {
            value = st.intake_scheduler?.watch_path || "not configured";
            badge = "requires env change";
          } else if (ref === "BOH_INTAKE_SCAN_INTERVAL") {
            value = st.intake_scheduler?.scan_interval || "—";
            badge = "requires env change";
          } else if (ref === "BOH_INTAKE_BACKPRESSURE_MAX") {
            value = st.intake_scheduler?.max || "—";
            badge = "requires env change";
          }
        } else if (title === "Visualization") {
          value = ref === "—" ? "planned" : ref;
          badge = null;
        }

        const control = h("div", { class: "flex items-center gap-2" },
          h("span", { class: "t-small muted" }, value),
          badge ? h("span", { class: "badge", style: { fontSize: "10px", padding: "2px 8px", borderRadius: "999px", color: "var(--text-muted)", background: "var(--bg-secondary)", border: "1px solid var(--border-muted)" } }, badge) : null);

        return settingRow(name, desc, live, impl, control);
      }),
    ] }));
  });
  wrap.innerHTML = `<div class="t-small muted" style="margin-top:16px">Loading…</div>`;
  return wrap;
}

function IntakeAutomationTab() {
  const wrap = h("div", { class: "col gap-3", style: { marginTop: "16px" } });
  wrap.appendChild(Skeleton({ w: "100%", h: 180, r: 8 }));
  Promise.all([api("/api/status"), api("/api/intake/adapters")]).then(([st, adapters]) => {
    if ((st && st.error) && (adapters && adapters.error)) {
      wrap.replaceChildren(AlertBanner({ ns: "conflict", children: ["Intake status and adapter coverage are unavailable."] }));
      return;
    }

    const statusCard = buildIntakeStatusCard(st || {});
    const coverageCard = buildAdapterCoverageCard(adapters || {});
    wrap.replaceChildren(statusCard, coverageCard);
  });
  return wrap;
}

function buildIntakeStatusCard(st) {
  const fields = intakeFields;
  const rows = fields.map(([name, ref, desc, live, impl]) => {
    const s = st.intake_scheduler || {};
    let value = ref;
    let badge = "requires env change";
    if (ref === "BOH_DATA_ROOT") {
      value = s.data_root_configured ? "configured" : "not configured";
    } else if (ref === "BOH_INTAKE_SCHEDULER_ENABLED") {
      value = s.enabled ? "enabled" : "disabled";
    } else if (ref === "BOH_WATCH_PATH") {
      value = s.watch_path || "not configured";
    } else if (ref === "BOH_INTAKE_SCAN_INTERVAL") {
      value = s.scan_interval || "—";
    } else if (ref === "BOH_INTAKE_BACKPRESSURE_MAX") {
      value = s.max || "—";
    }
    const control = h("div", { class: "flex items-center gap-2" },
      h("span", { class: "t-small muted" }, value),
      h("span", { class: "badge", style: { fontSize: "10px", padding: "2px 8px", borderRadius: "999px", color: "var(--text-muted)", background: "var(--bg-secondary)", border: "1px solid var(--border-muted)" } }, badge));
    return settingRow(name, desc, live, impl, control);
  });
  return Card({ title: "Intake Automation", children: [
    AlertBanner({ ns: "unknown", children: ["These settings are read-only runtime facts. The scheduler remains disabled unless BOH_INTAKE_SCHEDULER_ENABLED=true is configured before startup."] }),
    ...rows,
  ] });
}

function buildAdapterCoverageCard(adapters) {
  if (adapters.error) {
    return Card({ title: "Supported File Types", children:
      AlertBanner({ ns: "conflict", children: [`Adapter coverage unavailable: ${adapters.error}`] }) });
  }
  const report = adapters.coverage_report || {};
  const rows = Array.isArray(report.rows) ? report.rows : [];
  const groups = groupAdapterRows(rows);
  const summary = [
    `${report.adapter_count ?? 0} adapters`,
    `${report.extension_count ?? rows.length} extensions`,
  ].join(" · ");

  return Card({ title: "Supported File Types", children: [
    h("div", { class: "t-small muted", style: { marginBottom: "10px" } }, summary),
    AlertBanner({ ns: "advisory", children: ["Queryable types can enter normalized search material. Held and quarantined types are recognized but are not searchable from intake by default. Unknown extensions are held pending an adapter."] }),
    h("div", { class: "col gap-2", style: { marginTop: "12px" } },
      adapterGroup("Accepted · queryable", "current", groups.acceptQueryable),
      adapterGroup("Held · queryable after review", "draft", groups.holdQueryable),
      adapterGroup("Held · preserved only", "stale", groups.holdOnly),
      adapterGroup("Quarantined / blocked", "conflict", groups.quarantine),
      adapterGroup("Unsupported fallback", "unknown", ["unknown extensions -> adapter pending"])),
  ] });
}

function groupAdapterRows(rows) {
  const groups = { acceptQueryable: [], holdQueryable: [], holdOnly: [], quarantine: [] };
  for (const row of rows) {
    const ext = row.extension || "";
    if (!ext) continue;
    if (row.default_safety_lane === "quarantine") {
      groups.quarantine.push(ext);
    } else if (row.default_safety_lane === "hold" && row.can_make_queryable) {
      groups.holdQueryable.push(ext);
    } else if (row.default_safety_lane === "hold") {
      groups.holdOnly.push(ext);
    } else if (row.can_make_queryable) {
      groups.acceptQueryable.push(ext);
    }
  }
  for (const key of Object.keys(groups)) groups[key].sort();
  return groups;
}

function adapterGroup(title, ns, extensions) {
  const list = extensions && extensions.length ? extensions.join(" ") : "None reported";
  return h("div", { class: "setting-row" },
    h("div", { class: "s-main" },
      h("div", { class: "s-name" }, title),
      h("div", { class: "s-desc t-mono" }, list)),
    h("div", { class: "s-control" }, Badge({ ns, label: String(extensions ? extensions.length : 0) })));
}

function AITab({ onToast }) {
  const wrap = h("div", { style: { marginTop: "16px" } });
  api("/api/status").then(st => {
    const ol = (st && st.ollama) || {};
    const ollamaControl = h("div", { class: "flex items-center gap-2" },
      h("span", { class: "t-small muted" }, ol.url || "not configured"),
      h("span", { class: "badge", style: { fontSize: "10px", padding: "2px 8px", borderRadius: "999px", color: "var(--text-muted)", background: "var(--bg-secondary)", border: "1px solid var(--border-muted)" } }, "requires env change"));
    const modelControl = h("div", { class: "flex items-center gap-2" },
      h("span", { class: "t-small muted" }, ol.model || "not set"),
      h("span", { class: "badge", style: { fontSize: "10px", padding: "2px 8px", borderRadius: "999px", color: "var(--text-muted)", background: "var(--bg-secondary)", border: "1px solid var(--border-muted)" } }, "requires env change"));
    wrap.replaceWith(Card({ title: "AI & Analysis", children: [
      settingRow("Ollama URL", "BOH_OLLAMA_URL", "Where the Ollama server listens.", "RESTART REQUIRED", "READ-ONLY ENV", ollamaControl),
      settingRow("Default model", "BOH_OLLAMA_MODEL", "Model to use for LLM review.", "RESTART REQUIRED", "READ-ONLY ENV", modelControl),
      settingRow("Ollama available", "—", "Live status from /api/status.", "LIVE", "READ-ONLY ENV",
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
    const opTokenControl = h("div", { class: "flex items-center gap-2" },
      h("span", { style: { color: st.operator_token_set ? "var(--state-current)" : "var(--state-stale)" } }, st.operator_token_set ? "✓ configured" : "⚠ DEV-OPEN (not set)"),
      h("span", { class: "badge", style: { fontSize: "10px", padding: "2px 8px", borderRadius: "999px", color: "var(--text-muted)", background: "var(--bg-secondary)", border: "1px solid var(--border-muted)" } }, "requires env change"));
    const retrievalTokenControl = h("div", { class: "flex items-center gap-2" },
      h("span", { style: { color: st.retrieval_token_set ? "var(--state-current)" : "var(--text-muted)" } }, st.retrieval_token_set ? "✓ configured" : "not set"),
      h("span", { class: "badge", style: { fontSize: "10px", padding: "2px 8px", borderRadius: "999px", color: "var(--text-muted)", background: "var(--bg-secondary)", border: "1px solid var(--border-muted)" } }, "requires env change"));
    wrap.replaceWith(Card({ title: "Security & Advanced", children: [
      AlertBanner({ ns: "advisory", children: ["Secret values are never displayed. Token states show configured/not-configured only."] }),
      settingRow("Default actor", "BOH_DEFAULT_ACTOR", "Actor used for unauthenticated local requests.", "RESTART REQUIRED", "READ-ONLY ENV", h("span", { class: "t-small muted" }, st.default_actor || "dev_operator")),
      settingRow("Operator token", "BOH_OPERATOR_TOKEN", "Governs all mutation routes.", "RESTART REQUIRED", "SESSION LOCAL", opTokenControl),
      SessionTokenRow({ onToast }),
      settingRow("Retrieval token", "BOH_RETRIEVAL_TOKEN", "Governs /api/retrieve read access.", "RESTART REQUIRED", "SESSION LOCAL", retrievalTokenControl),
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
      h("div", { class: "flex items-center gap-2" },
        stateSpan,
        h("span", { class: "badge", style: { fontSize: "10px", padding: "2px 8px", borderRadius: "999px", color: "var(--state-advisory)", background: "color-mix(in oklab, var(--state-advisory) 14%, transparent)", border: "1px solid color-mix(in oklab, var(--state-advisory) 30%, transparent)" } }, "session-only (cleared on tab close)"))));
}

function settingRow(name, desc, live, impl, control) {
  const liveColor = live === "RESTART REQUIRED" ? "var(--state-stale)" : "var(--text-muted)";

  // Color code implementation status for clarity
  let implColor = "var(--text-muted)";
  let implBg = "transparent";
  if (impl === "BROWSER LOCAL") {
    implColor = "var(--state-current)";
    implBg = "color-mix(in oklab, var(--state-current) 14%, transparent)";
  } else if (impl === "SESSION LOCAL") {
    implColor = "var(--accent)";
    implBg = "color-mix(in oklab, var(--accent) 14%, transparent)";
  } else if (impl === "READ-ONLY ENV") {
    implColor = "var(--text-muted)";
    implBg = "color-mix(in oklab, var(--text-muted) 10%, transparent)";
  } else if (impl === "NEEDS SETTINGS API") {
    implColor = "var(--state-advisory)";
    implBg = "color-mix(in oklab, var(--state-advisory) 14%, transparent)";
  } else if (impl === "NEW CAPABILITY") {
    implColor = "var(--state-advisory)";
    implBg = "color-mix(in oklab, var(--state-advisory) 14%, transparent)";
  }

  return h("div", { class: "setting-row", style: { opacity: (impl === "READ-ONLY ENV" || impl === "NEEDS SETTINGS API") ? "0.75" : "1" } },
    h("div", { class: "s-main" },
      h("div", { class: "s-name" }, name),
      h("div", { class: "s-desc" }, desc),
      h("div", { class: "s-annos" },
        h("span", { class: "anno", style: { color: liveColor } }, live),
        h("span", { class: "anno", style: { color: implColor, background: implBg, padding: "2px 8px", borderRadius: "4px", fontSize: "11px" } }, impl))),
    h("div", { class: "s-control", style: { opacity: (impl === "READ-ONLY ENV" || impl === "NEEDS SETTINGS API") ? "0.5" : "1", pointerEvents: (impl === "READ-ONLY ENV") ? "none" : "auto" } }, control));
}
