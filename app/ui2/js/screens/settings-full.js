/* BOH new UI — Settings. 6 groups per boh_claude_design_anchor_brief_v0_1.md §17.
   General (localStorage), Library & Indexing, Intake Automation, AI & Analysis,
   Visualization, Security & Advanced — all display/read-only except General. */
import { h } from "../dom.js";
import { api, escHtml, getRetrievalToken, getToken, tokenHeaders } from "../api.js";
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

  async function render() {
    const [st, tokenStatus, connector] = await Promise.all([
      api("/api/status"),
      api("/api/security/tokens"),
      api("/api/security/mcp-connector", { headers: tokenHeaders() }),
    ]);
    if (tokenStatus.error) {
      wrap.replaceChildren(AlertBanner({ ns: "conflict", children: [`Security status unavailable: ${tokenStatus.error}`] }));
      return;
    }
    const operator = tokenStatus.operator || {};
    const retrieval = tokenStatus.retrieval || {};
    wrap.replaceChildren(Card({ title: "Security & Advanced", children: [
      AlertBanner({ ns: "advisory", children: ["BOH stores only salted verifiers. Plaintext stays in this browser tab. These BOH tokens do not authenticate ChatGPT MCP. Settings manages the OAuth gateway path; the no-auth stdio tunnel path is script-started."] }),
      settingRow("Default actor", "BOH_DEFAULT_ACTOR - actor used for unauthenticated local requests.", "RESTART REQUIRED", "READ-ONLY ENV", h("span", { class: "t-small muted" }, st.default_actor || "dev_operator")),
      h("div", { class: "security-token-section" }, "Server credentials"),
      ServerTokenRow({ kind: "operator", serverState: operator, operatorState: operator, onToast, onRefresh: render, onConfirm }),
      SessionTokenRow({ onToast }),
      ServerTokenRow({ kind: "retrieval", serverState: retrieval, operatorState: operator, onToast, onRefresh: render, onConfirm }),
      RetrievalSessionTokenRow({ onToast }),
      ...McpConnectorRows({ connector, onToast, onRefresh: render }),
      h("div", { class: "setting-row" },
        h("div", { class: "s-main" },
          h("div", { class: "s-name" }, "Maintenance actions"),
          h("div", { class: "s-desc" }, "Index maintenance remains governed by operator authorization.")),
        h("div", { class: "s-control col gap-2", style: { alignItems: "flex-start" } },
          Button({ variant: "secondary", className: "sm", onClick: () => onConfirm({ kind: "rebuild", title: "Rebuild index?", body: "Discards derived index data and re-scans. Source files are untouched.", confirmLabel: "Rebuild index", variant: "secondary" }), children: ["Rebuild index"] }),
          Button({ variant: "danger", className: "sm", onClick: () => onConfirm({ kind: "reset", title: "Reset workspace?", body: "Irreversibly removes all local index data and layouts.", confirmLabel: "Reset workspace", variant: "danger", danger: true }), children: ["Reset workspace"] }))),
    ] }));
  }

  render();
  wrap.innerHTML = `<div class="t-small muted" style="margin-top:16px">Loading...</div>`;
  return wrap;
}

function tokenRoleDescription(kind, environmentOwned) {
  if (kind === "operator") {
    return environmentOwned
      ? "Mutation access is managed by BOH_OPERATOR_TOKEN. Load the matching value into this tab to use governed controls."
      : "Create or replace the server verifier for mutation access. Use 16-256 letters, digits, or symbols without spaces.";
  }
  return environmentOwned
    ? "Read-only retrieval access is managed by BOH_RETRIEVAL_TOKEN. Load the matching value into this tab for Search and Current Context."
    : "Optional protection for Search and Current Context. With no retrieval verifier, local BOH search is open and needs no token.";
}

export function ServerTokenRow({ kind, serverState, operatorState, onToast, onRefresh, onConfirm }) {
  let input;
  const storageKey = kind === "operator" ? "boh_operator_token" : "boh_retrieval_token";
  const label = kind === "operator" ? "Operator" : "Retrieval";
  const environmentOwned = serverState.source === "environment";
  const operatorConfigured = operatorState && operatorState.configured && operatorState.record_valid !== false;

  function serverMutationBlocker() {
    if (environmentOwned) {
      return `${label} verifier is managed by the server environment.`;
    }
    if (kind === "operator" && serverState.configured && !getToken()) {
      return "Load the current operator token into this tab before rotating or removing the operator verifier.";
    }
    if (kind === "retrieval" && !operatorConfigured) {
      return "Configure a valid operator verifier before managing retrieval access.";
    }
    if (kind === "retrieval" && !getToken()) {
      return "Load the operator token into this tab before changing the retrieval verifier.";
    }
    return "";
  }

  async function saveToServer() {
    const value = input && input.value ? input.value : "";
    if (!value.trim()) {
      onToast && onToast(`Enter a ${kind} token before saving.`, "stale");
      return;
    }
    const blocked = serverMutationBlocker();
    if (blocked) {
      onToast && onToast(blocked, "stale");
      return;
    }
    if (kind === "retrieval" && value === getToken()) {
      onToast && onToast("Retrieval and operator credentials must be different.", "stale");
      return;
    }
    const result = await api(`/api/security/tokens/${kind}`, {
      method: "POST",
      headers: tokenHeaders(),
      body: JSON.stringify({ token: value }),
    });
    if (result.error) {
      onToast && onToast(result.error, "conflict");
      return;
    }
    sessionStorage.setItem(storageKey, value);
    input.value = "";
    onToast && onToast(`${label} verifier saved; credential loaded into this tab.`, "current");
    onRefresh && onRefresh();
  }

  async function clearServerNow() {
    const blocked = serverMutationBlocker();
    if (blocked) {
      onToast && onToast(blocked, "stale");
      return;
    }
    const result = await api(`/api/security/tokens/${kind}`, {
      method: "DELETE",
      headers: tokenHeaders(),
    });
    if (result.error) {
      onToast && onToast(result.error, "conflict");
      return;
    }
    sessionStorage.removeItem(storageKey);
    onToast && onToast(`${label} UI verifier removed.`, "stale");
    onRefresh && onRefresh();
  }

  function requestClearServer() {
    if (!onConfirm) return;
    const devOpenWarning = kind === "operator" && serverState.source === "ui"
      ? " Removing it will immediately return operator-protected BOH routes to DEV-OPEN."
      : "";
    onConfirm({
      kind: "clear-security-token",
      title: `Remove ${kind} UI verifier?`,
      body: `This removes only the salted Settings verifier. Plaintext cannot be recovered.${devOpenWarning}`,
      confirmLabel: `Remove ${label} verifier`,
      danger: true,
      variant: "danger",
      execute: clearServerNow,
    });
  }

  const liveLabel = serverState.restart_required ? "RESTART REQUIRED" : "LIVE";
  const implLabel = environmentOwned ? "READ-ONLY ENV" : "SETTINGS API";
  const blocker = serverMutationBlocker();
  const actionHelp = environmentOwned
    ? "Server value is environment-owned; use tab-only load for browser requests."
    : blocker || "Server save stores only a salted verifier and loads the same value into this tab.";
  const serverStateLabel = serverState.record_valid === false
    ? "Configuration error"
    : serverState.source === "environment"
      ? "Managed by environment"
      : serverState.configured
        ? "Configured in Settings"
        : kind === "operator" ? "DEV-OPEN (not configured)" : "Open locally (no token required)";

  return h("div", { class: "setting-row security-token-row" },
    h("div", { class: "s-main" },
      h("div", { class: "s-name" }, `${label} server credential`),
      h("div", { class: "s-desc" }, tokenRoleDescription(kind, environmentOwned)),
      h("div", { class: "s-annos" },
        h("span", { class: "anno", style: { color: liveLabel === "RESTART REQUIRED" ? "var(--state-stale)" : "var(--text-muted)" } }, liveLabel),
        h("span", { class: "anno", style: { color: implLabel === "READ-ONLY ENV" ? "var(--text-muted)" : "var(--state-current)" } }, implLabel),
        h("span", { class: "anno", style: { color: "var(--state-advisory)" } }, "PLAINTEXT TAB-LOCAL"))),
    h("div", { class: "s-control token-control" },
      h("div", { class: "token-server-state", style: { color: serverState.record_valid === false ? "var(--state-conflict)" : serverState.configured ? "var(--state-current)" : "var(--text-muted)" } }, serverStateLabel),
      h("div", { class: "token-entry" },
        (input = h("input", { class: "input token-input", type: "password", placeholder: `Enter ${kind} token`, autocomplete: "off",
          onKeydown: e => { if (e.key === "Enter") saveToServer(); } })),
        h("div", { class: "token-actions" },
          Button({ variant: "secondary", className: "sm", disabled: environmentOwned, onClick: saveToServer, children: [serverState.configured ? `Replace + load ${label.toLowerCase()}` : `Save + load ${label.toLowerCase()}`] }),
          Button({ variant: "danger", className: "sm", disabled: serverState.source !== "ui" && !serverState.ui_verifier_present, onClick: requestClearServer, children: [environmentOwned ? "Remove dormant UI verifier" : "Remove UI verifier"] }))),
      h("div", { class: "token-help" }, actionHelp)));
}

function McpConnectorRows({ connector, onToast, onRefresh }) {
  if (connector.error) {
    return [h("div", { class: "setting-row" },
      h("div", { class: "s-main" },
        h("div", { class: "s-name" }, "ChatGPT MCP connector"),
        h("div", { class: "s-desc" }, "Load the current operator credential into this tab to view or change local MCP startup settings.")),
      h("div", { class: "s-control" }, h("span", { style: { color: "var(--state-stale)" } }, connector.error)))];
  }

  const config = connector.config || {};
  const state = connector.status || {};
  let tunnelIdInput;
  let issuerInput;
  let portInput;
  let enabledInput;
  let runtimeKeyInput;
  const inputStyle = { fontFamily: "var(--font-mono)", fontSize: "12px", padding: "4px 8px", background: "var(--bg-input)", border: "1px solid var(--border-default)", borderRadius: "6px", color: "var(--text-primary)", width: "250px" };

  async function saveConfig() {
    const result = await api("/api/security/mcp-connector/config", {
      method: "POST",
      headers: tokenHeaders(),
      body: JSON.stringify({
        enabled: Boolean(enabledInput.checked),
        tunnel_id: tunnelIdInput.value.trim(),
        oauth_issuer: issuerInput.value.trim(),
        auth_mode: "oauth_gateway",
        scope: "boh.read",
        port: Number(portInput.value),
      }),
    });
    if (result.error) {
      onToast && onToast(result.error, "conflict");
      return;
    }
    onToast && onToast("MCP connector saved. It will be applied on the next BOH launch.", "current");
    onRefresh && onRefresh();
  }

  async function disableConfig() {
    const result = await api("/api/security/mcp-connector/config", {
      method: "DELETE",
      headers: tokenHeaders(),
    });
    if (result.error) {
      onToast && onToast(result.error, "conflict");
      return;
    }
    onToast && onToast("MCP connector autostart disabled for the next launch.", "stale");
    onRefresh && onRefresh();
  }

  async function saveRuntimeKey() {
    const value = runtimeKeyInput && runtimeKeyInput.value ? runtimeKeyInput.value : "";
    if (!value.trim()) {
      onToast && onToast("Enter the OpenAI tunnel runtime key.", "stale");
      return;
    }
    const result = await api("/api/security/mcp-connector/runtime-key", {
      method: "POST",
      headers: tokenHeaders(),
      body: JSON.stringify({ runtime_key: value }),
    });
    runtimeKeyInput.value = "";
    if (result.error) {
      onToast && onToast(result.error, "conflict");
      return;
    }
    onToast && onToast("Tunnel runtime key written locally. Its value was not returned.", "current");
    onRefresh && onRefresh();
  }

  const stdioNoAuth = state.auth_mode === "stdio_no_auth";
  const readiness = state.remote_ready
    ? (stdioNoAuth ? "stdio tunnel ready" : "gateway + tunnel ready")
    : state.gateway_ready
      ? "gateway ready; tunnel not ready"
      : state.enabled
        ? (stdioNoAuth ? "stdio no-auth enabled; tunnel not ready" : "enabled; not currently ready")
        : state.configured
          ? "configured; autostart disabled"
          : "not configured";
  const readinessColor = state.remote_ready ? "var(--state-current)" : state.enabled ? "var(--state-stale)" : "var(--text-muted)";

  return [
    settingRow(
      "ChatGPT MCP connector",
      "Opt-in read-only MCP and OpenAI tunnel. Settings manages the OAuth gateway path; the no-auth stdio path uses tools/start_boh_mcp_connector.ps1 -AuthMode stdio_no_auth.",
      "NEXT START",
      "SETTINGS API",
      h("div", { class: "col gap-1", style: { alignItems: "flex-start" } },
        h("span", { style: { color: readinessColor } }, readiness),
        h("span", { class: "t-small muted" }, state.dependencies_ready ? (stdioNoAuth ? "MCP stdio dependency ready" : "JWKS dependencies ready") : (stdioNoAuth ? "MCP dependency missing" : "JWKS dependencies missing")))),
    h("div", { class: "setting-row" },
      h("div", { class: "s-main" },
        h("div", { class: "s-name" }, "MCP startup configuration"),
        h("div", { class: "s-desc" }, "OAuth gateway startup uses a tunnel ID and canonical OAuth issuer. No-auth stdio startup is configured by the script, not this form."),
        h("div", { class: "s-annos" }, h("span", { class: "anno" }, "READ-ONLY 8-TOOL PROFILE"))),
      h("div", { class: "s-control col gap-2", style: { alignItems: "flex-start" } },
        h("label", { class: "flex items-center gap-2 t-small" },
          (enabledInput = h("input", { type: "checkbox", checked: config.enabled !== false })),
          "Start MCP with BOH"),
        (tunnelIdInput = h("input", { value: config.tunnel_id || "", placeholder: "OpenAI tunnel ID", style: inputStyle })),
        (issuerInput = h("input", { value: config.oauth_issuer || "", placeholder: "https://your-tenant.auth0.com/", style: inputStyle })),
        (portInput = h("input", { type: "number", min: "1024", max: "65535", value: String(config.port || 4884), style: { ...inputStyle, width: "110px" } })),
        h("div", { class: "flex gap-2" },
          Button({ variant: "secondary", className: "sm", onClick: saveConfig, children: ["Save for next launch"] }),
          Button({ variant: "ghost", className: "sm", disabled: !state.configured, onClick: disableConfig, children: ["Disable autostart"] })))),
    h("div", { class: "setting-row" },
      h("div", { class: "s-main" },
        h("div", { class: "s-name" }, "OpenAI tunnel runtime key"),
        h("div", { class: "s-desc" }, "Write-only local key for the tunnel client. BOH never reads it back through the API or displays it."),
        h("div", { class: "s-annos" }, h("span", { class: "anno", style: { color: "var(--state-advisory)" } }, "LOCAL SECRET"))),
      h("div", { class: "s-control col gap-2", style: { alignItems: "flex-start" } },
        h("span", { style: { color: state.runtime_key_configured ? "var(--state-current)" : "var(--text-muted)" } }, state.runtime_key_configured ? "configured" : "not configured"),
        h("div", { class: "flex gap-2" },
          (runtimeKeyInput = h("input", { type: "password", autocomplete: "off", placeholder: "Paste tunnel runtime key", style: inputStyle })),
          Button({ variant: "secondary", className: "sm", onClick: saveRuntimeKey, children: ["Write key"] })))),
  ];
}

function LegacySecurityTab({ onConfirm, onToast }) {
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
      settingRow("Retrieval token", "BOH_RETRIEVAL_TOKEN", "Governs /api/retrieve and context brief read access.", "RESTART REQUIRED", "READ-ONLY ENV", retrievalTokenControl),
      RetrievalSessionTokenRow({ onToast }),
      h("div", { class: "setting-row" }, h("div", { class: "s-main" }, h("div", { class: "s-name" }, "Maintenance actions")),
        h("div", { class: "s-control col gap-2", style: { alignItems: "flex-start" } },
          Button({ variant: "secondary", className: "sm", glyph: "↺", onClick: () => onConfirm({ kind: "rebuild", title: "Rebuild index?", body: "Discards derived index data and re-scans. Source files are untouched.", confirmLabel: "Rebuild index", variant: "secondary" }), children: ["Rebuild index"] }),
          Button({ variant: "danger", className: "sm", onClick: () => onConfirm({ kind: "reset", title: "Reset workspace?", body: "Irreversibly removes all local index data and layouts.", confirmLabel: "Reset workspace", variant: "danger", danger: true }), children: ["Reset workspace"] }))),
    ] }));
  });
  wrap.innerHTML = `<div class="t-small muted" style="margin-top:16px">Loading…</div>`;
  return wrap;
}

export function SessionTokenRow({ onToast }) {
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
    onToast && onToast("Operator credential loaded into this tab.", "current");
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
      h("div", { class: "s-name" }, "Operator session token"),
      h("div", { class: "s-desc" }, "Use an operator credential already configured above. This changes only this browser tab, not the BOH server."),
      h("div", { class: "s-annos" },
        h("span", { class: "anno", style: { color: "var(--state-advisory)" } }, "TAB-LOCAL ONLY"))),
    h("div", { class: "s-control col gap-2", style: { alignItems: "flex-start" } },
      h("div", { class: "flex gap-2" },
        (_input = h("input", { type: "password", placeholder: "Enter operator token…",
          style: { fontFamily: "var(--font-mono)", fontSize: "12px", padding: "4px 8px",
                   background: "var(--bg-input)", border: "1px solid var(--border-default)",
                   borderRadius: "6px", color: "var(--text-primary)", width: "200px" },
          onKeydown: e => { if (e.key === "Enter") save(); } })),
        Button({ variant: "secondary", className: "sm", onClick: save, children: ["Load into this tab"] }),
        Button({ variant: "ghost", className: "sm", onClick: clear, children: ["Clear"] })),
      h("div", { class: "flex items-center gap-2" },
        stateSpan,
        h("span", { class: "badge", style: { fontSize: "10px", padding: "2px 8px", borderRadius: "999px", color: "var(--state-advisory)", background: "color-mix(in oklab, var(--state-advisory) 14%, transparent)", border: "1px solid color-mix(in oklab, var(--state-advisory) 30%, transparent)" } }, "session-only (cleared on tab close)"))));
}

export function RetrievalSessionTokenRow({ onToast }) {
  let _input;
  function sessionState() {
    return getRetrievalToken() ? "loaded in this tab" : "not loaded in this tab";
  }
  function sessionColor() {
    return getRetrievalToken() ? "var(--state-current)" : "var(--text-muted)";
  }
  const stateSpan = h("span", { style: { color: sessionColor() } }, sessionState());

  function save() {
    const val = (_input && _input.value) ? _input.value.trim() : "";
    if (!val) { onToast && onToast("Enter a retrieval token value before saving.", "stale"); return; }
    sessionStorage.setItem("boh_retrieval_token", val);
    if (_input) _input.value = "";
    stateSpan.textContent = sessionState();
    stateSpan.style.color = sessionColor();
    onToast && onToast("Retrieval credential loaded into this tab.", "current");
  }
  function clear() {
    sessionStorage.removeItem("boh_retrieval_token");
    if (_input) _input.value = "";
    stateSpan.textContent = sessionState();
    stateSpan.style.color = sessionColor();
    onToast && onToast("Retrieval token cleared.", "stale");
  }

  return h("div", { class: "setting-row" },
    h("div", { class: "s-main" },
      h("div", { class: "s-name" }, "Retrieval session token"),
      h("div", { class: "s-desc" }, "Use the retrieval credential already configured above. Search and Current Context send it only as the retrieval credential."),
      h("div", { class: "s-annos" },
        h("span", { class: "anno", style: { color: "var(--state-advisory)" } }, "TAB-LOCAL ONLY"))),
    h("div", { class: "s-control token-session-control" },
      h("div", { class: "flex gap-2" },
        (_input = h("input", { type: "password", placeholder: "Enter retrieval token...",
          style: { fontFamily: "var(--font-mono)", fontSize: "12px", padding: "4px 8px",
                   background: "var(--bg-input)", border: "1px solid var(--border-default)",
                   borderRadius: "6px", color: "var(--text-primary)", width: "200px" },
          onKeydown: e => { if (e.key === "Enter") save(); } })),
        Button({ variant: "secondary", className: "sm", onClick: save, children: ["Load into this tab"] }),
        Button({ variant: "ghost", className: "sm", onClick: clear, children: ["Clear"] })),
      h("div", { class: "flex items-center gap-2" },
        stateSpan,
        h("span", { class: "badge", style: { fontSize: "10px", padding: "2px 8px", borderRadius: "999px", color: "var(--state-advisory)", background: "color-mix(in oklab, var(--state-advisory) 14%, transparent)", border: "1px solid color-mix(in oklab, var(--state-advisory) 30%, transparent)" } }, "read-only"))));
}

function settingRow(name, desc, live, impl, control, legacyControl) {
  // Older call sites supplied an environment-variable label as a separate
  // second description argument. Preserve that information without shifting
  // the actual control out of the row.
  if (legacyControl !== undefined) {
    desc = `${desc} - ${live}`;
    live = impl;
    impl = control;
    control = legacyControl;
  }
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
  } else if (impl === "SETTINGS API") {
    implColor = "var(--state-current)";
    implBg = "color-mix(in oklab, var(--state-current) 14%, transparent)";
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
