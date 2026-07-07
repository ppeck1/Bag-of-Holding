/* BOH new UI (Phase A) — Status screen. Port of StatusScreen (screens.jsx).
   Runtime cells come from the live /api/status adapter (statusCells); jobs are
   fetched from /api/autoindex/status with polling while running. */

import { h } from "../dom.js";
import { api, escHtml, getToken, tokenHeaders } from "../api.js";
import { Card, Button, AlertBanner, Badge, Skeleton } from "../primitives.js";
import { StatusCell } from "./settings.js";

function kvRow(k, v) { return h("div", { class: "kv-row" }, h("span", { class: "k" }, k), h("span", { class: "v" }, String(v ?? "—"))); }
function fmt(v) { return (v === null || v === undefined || v === "") ? "—" : String(v); }

function AutoindexStatus() {
  const wrap = h("div", { style: { width: "100%" } });
  let pollInterval = null;
  let rebuilding = false;
  let rebuildBtn = null;
  let contentDiv = null;

  function loadStatus() {
    api("/api/autoindex/status").then(status => {
      if (!status || status.error) {
        if (contentDiv) contentDiv.innerHTML = `<div class="t-small muted" style="padding:12px">Not available.</div>`;
        return;
      }

      const lastRun = status.last_run_ts
        ? new Date(status.last_run_ts * 1000).toLocaleString()
        : "Never";

      const rows = [
        kvRow("Last run", lastRun),
        kvRow("Scanned", fmt(status.last_scanned)),
        kvRow("Indexed", fmt(status.last_indexed)),
        kvRow("Skipped", fmt(status.last_skipped)),
        status.last_failed > 0
          ? h("div", { class: "kv-row" }, h("span", { class: "k" }, "Failed"), h("span", { class: "v", style: { color: "var(--state-conflict)" } }, String(status.last_failed)))
          : kvRow("Failed", "0"),
        status.elapsed_ms ? kvRow("Elapsed", `${status.elapsed_ms}ms`) : null,
        status.running || rebuilding ? h("div", { class: "kv-row" }, h("span", { class: "k" }, "Status"), h("span", { class: "pulse-dot", style: { display: "inline-block", marginRight: "6px" } }), "Running…") : null,
      ].filter(Boolean);

      const rebuildHandler = () => {
        if (rebuilding) return;
        const tok = getToken();
        if (!tok) {
          if (contentDiv) contentDiv.innerHTML = `<div class="t-small" style="color:var(--state-conflict);padding:8px">Operator token required. Set in Settings → Security & Advanced.</div>`;
          return;
        }
        rebuilding = true;
        if (rebuildBtn) rebuildBtn.disabled = true;
        if (rebuildBtn) rebuildBtn.textContent = "Rebuilding…";
        api("/api/autoindex/run", {
          method: "POST",
          headers: tokenHeaders(),
          body: JSON.stringify({ library_root: "", max_files: 5000, changed_only: true, include_scratch: false })
        }).then(result => {
          rebuilding = false;
          if (rebuildBtn) rebuildBtn.disabled = false;
          if (rebuildBtn) rebuildBtn.textContent = "Rebuild index";
          if (result && result.error) {
            if (contentDiv) contentDiv.innerHTML = `<div class="t-small" style="color:var(--state-conflict);padding:8px">Rebuild failed: ${escHtml(result.error)}</div>`;
            setTimeout(loadStatus, 2000);
          } else if (result) {
            const summary = `Scanned ${result.scanned || 0} · Indexed ${result.indexed || 0} · Skipped ${result.skipped || 0} · Failed ${result.failed || 0}`;
            if (contentDiv) contentDiv.innerHTML = `<div class="t-small" style="color:var(--state-current);padding:8px">✓ Rebuild complete: ${summary}</div>`;
            setTimeout(loadStatus, 2000);
          }
        });
      };

      const card = Card({
        children: (contentDiv = h("div", null,
          h("div", { class: "kv" }, rows),
          h("div", { style: { marginTop: "12px" } },
            (rebuildBtn = Button({
              variant: "secondary",
              disabled: rebuilding,
              onClick: rebuildHandler,
              children: ["Rebuild index"]
            }))
          )))
      });
      wrap.replaceChildren(card);

      if (status.running) {
        if (!pollInterval) pollInterval = setInterval(loadStatus, 1000);
      } else {
        if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
      }
    });
  }

  const initialBody = h("div");
  initialBody.appendChild(Skeleton({ w: "100%", h: 120, r: 8 }));
  wrap.appendChild(initialBody);

  loadStatus();
  return wrap;
}

/* Distinct rendering for each scheduler state (Phase B item 3). */
const SCHED_STATE_NS = {
  running: "current", disabled: "stale", stopped: "stale",
  draining: "draft", undrained: "conflict", error: "conflict",
};

function SchedulerSection() {
  const wrap = h("div", { class: "section" },
    h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Intake Scheduler")));
  const body = h("div", { style: { marginTop: "8px" } });
  body.appendChild(Skeleton({ w: "100%", h: 120, r: 8 }));
  wrap.appendChild(body);
  api("/api/status").then(d => {
    if (!d || d.error) { body.innerHTML = `<div class="t-small muted">Not available.</div>`; return; }
    const s = d.intake_scheduler || {};
    const state = String(s.state || "disabled");
    const rows = [
      h("div", { class: "kv-row" }, h("span", { class: "k" }, "Scheduler"),
        s.enabled ? Badge({ ns: "current", label: "enabled" }) : Badge({ ns: "stale", label: "disabled" })),
      h("div", { class: "kv-row" }, h("span", { class: "k" }, "State"),
        Badge({ ns: SCHED_STATE_NS[state] || "stale", label: state })),
      kvRow("Running", s.running ? "yes" : "no"),
      kvRow("Generation", fmt(s.generation)),
      h("div", { class: "kv-row" }, h("span", { class: "k" }, "Watch path"),
        h("span", { class: "v t-mono" }, escHtml(fmt(s.watch_path)))),
      kvRow("Data root configured", s.data_root_configured ? "yes" : "no"),
      kvRow("Queued or running", fmt(s.queued_or_running)),
      kvRow("Active workers", fmt(s.active_workers)),
      kvRow("Drained", s.drained ? "yes" : "no"),
      kvRow("Last scan", fmt(s.last_scan_ts)),
      kvRow("Last error", fmt(s.last_error)),
      kvRow("Restart refusal", fmt(s.restart_refusal_reason)),
    ];
    body.replaceWith(Card({ children: h("div", { class: "kv" }, rows) }));
  });
  return wrap;
}

export function StatusScreen({ statusCells, onConfirm }) {
  const cells = statusCells && statusCells.length ? statusCells : [];
  return h("div", { class: "content content-narrow" },
    h("div", { class: "page-head" },
      h("div", { class: "t-display" }, "Status"),
      h("div", { class: "sub t-small" }, "Local runtime, jobs, and watcher health for Bag of Holding.")),
    h("section", { class: "section" },
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Runtime")),
      Card({ children: h("div", { class: "status-grid" }, cells.map((s) => StatusCell({ s }))) })),
    h("section", { class: "section" },
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Auto-Index")),
      Card({ children: AutoindexStatus() })),
    h("section", { class: "section" },
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Maintenance")),
      Card({ children: h("div", { class: "flex gap-2 wrap" },
        Button({ variant: "secondary", glyph: "↺", onClick: () => onConfirm({ kind: "rebuild", title: "Rebuild index?", body: "Discards derived index data and re-scans the managed library. Source files are untouched; recoverable by re-running.", confirmLabel: "Rebuild index", variant: "secondary" }), children: ["Rebuild index"] }),
        Button({ variant: "secondary", onClick: () => onConfirm({ kind: "caches", title: "Clear caches?", body: "Clears derived caches and saved layouts. Operational only — no corpus data is affected.", confirmLabel: "Clear caches", variant: "secondary" }), children: ["Clear caches"] }),
        Button({ variant: "danger", onClick: () => onConfirm({ kind: "reset", title: "Reset workspace?", body: "Irreversibly removes all local index data, layouts, and review queue state for this workspace. Source files in the managed library are not deleted.", confirmLabel: "Reset workspace", variant: "danger", danger: true }), children: ["Reset workspace"] })) })),
    SchedulerSection());
}
