/* BOH new UI (Phase A) — application root.
   Vanilla port of the prototype app.jsx. Full-subtree re-render on state change.
   Coexists at /v2; reads live data from existing read-only endpoints. */

import { h, mount } from "./dom.js";
import { Sidebar, TopBar, AlertsDrawer, Inspector, ToastHost } from "./shell.js";
import { Button, Icon, Segmented, Select, Toggle, Modal } from "./primitives.js";
import { OverviewScreen, PlaceholderScreen } from "./screens/overview.js";
import { SettingsScreen } from "./screens/settings.js";
import { StatusScreen } from "./screens/status.js";
import { ComponentSheet } from "./screens/component-sheet.js";
import { FoldWorkspace } from "./screens/fold.js";
import { LibraryScreen } from "./screens/library.js";
import { SearchContextScreen } from "./screens/search-context.js";
import { ReviewScreen } from "./screens/review.js";
import { AuthorityScreen } from "./screens/authority.js";
import { CaptureScreen } from "./screens/capture.js";
import { SettingsFullScreen } from "./screens/settings-full.js";
import { ActivityScreen } from "./screens/activity.js";
import { ContextPackScreen } from "./screens/context-pack.js";
import { api, fetchOverview, fetchStatus, fetchFoldGraph, getToken, tokenHeaders } from "./api.js";
import { PLANES, normalizePlaneKey } from "./ns.js";

const STORE_KEY = "boh_v2_phase_a";
const PLANE_KEYS = Object.keys(PLANES); // stable reference to all 8 plane keys

const PROTO_STATES = [
  { value: "auto", label: "Auto (live)" },
  { value: "populated", label: "Populated" },
  { value: "empty", label: "Empty corpus" },
  { value: "loading", label: "Loading" },
  { value: "partial", label: "Partial data" },
  { value: "error", label: "Error" },
  { value: "denied", label: "Permission denied" },
];

function loadSettings() {
  const def = { density: "comfortable", mode: "advanced", landing: "current", diagnostics: true, activeLibraryId: "all" };
  try { return { ...def, ...JSON.parse(localStorage.getItem(STORE_KEY) || "{}") }; } catch (_) { return def; }
}

const state = {
  settings: loadSettings(),
  route: (location.hash.replace(/^#/, "") || loadSettings().landing),
  forcedState: "auto",
  selection: null,
  alertsOpen: false,
  protoOpen: false,
  toasts: [],
  confirm: null,
  overview: { status: "idle", data: null }, // idle|loading|ready|error
  statusData: { status: "idle", data: null },
  fold: { status: "idle", data: null, libraryId: loadSettings().activeLibraryId || "all" },
  libraries: { status: "idle", items: [{ id: "all", name: "All libraries", count: 0 }] },
  libraryManagerOpen: false,
  libraryManager: { status: "idle", items: [] },
  activeLibraryId: loadSettings().activeLibraryId || "all",
  pendingSearch: null,
  inspectorOpen: true,   // inspector panel visible
  inspectorWidth: 320,   // px — user-resizable
  visiblePlanes: PLANE_KEYS, // all 8 planes visible by default; in-memory only
};

const root = () => document.getElementById("root");
function setState(patch) { Object.assign(state, patch); render(); }

// Drag-to-resize the inspector panel. Updates the .main grid template directly during
// drag (no full re-render) for smooth performance; syncs state on mouseup.
function startResize(e) {
  e.preventDefault();
  const startX = e.clientX, startW = state.inspectorWidth;
  const handle = e.currentTarget;
  handle.classList.add("dragging");
  function onMove(ev) {
    const w = Math.max(240, Math.min(700, startW + (startX - ev.clientX)));
    state.inspectorWidth = w;
    const main = document.querySelector(".main");
    if (main) main.style.gridTemplateColumns = `1fr 5px ${w}px`;
  }
  function onUp() {
    handle.classList.remove("dragging");
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    render(); // sync inline style with settled state
  }
  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}

function togglePlane(plane) {
  const now = state.visiblePlanes.includes(plane)
    ? state.visiblePlanes.filter(p => p !== plane)
    : [...state.visiblePlanes, plane];
  // Clear a selected PlaneCard if its plane is now hidden.
  const cardHidden = state.selection?.type === "card" &&
    normalizePlaneKey(state.selection.card.plane ?? "") &&
    !now.includes(normalizePlaneKey(state.selection.card.plane ?? ""));
  setState({ visiblePlanes: now, ...(cardHidden ? { selection: null } : {}) });
}

function showAllPlanes() { setState({ visiblePlanes: PLANE_KEYS }); }

function setSetting(k, v) {
  state.settings = { ...state.settings, [k]: v };
  try { localStorage.setItem(STORE_KEY, JSON.stringify(state.settings)); } catch (_) {}
  render();
}
function setActiveLibrary(id) {
  const nextId = id || "all";
  const changed = state.activeLibraryId !== nextId;
  state.activeLibraryId = nextId;
  state.settings = { ...state.settings, activeLibraryId: nextId };
  state.selection = null;
  if (changed) state.fold = { status: "idle", data: null, libraryId: nextId };
  try { localStorage.setItem(STORE_KEY, JSON.stringify(state.settings)); } catch (_) {}
  if (changed && state.route === "fold") { ensureFold(true); return; }
  render();
}
function pushToast(msg, ns = "current") {
  const id = Date.now() + Math.random();
  state.toasts = [...state.toasts, { id, msg, ns }];
  render();
  setTimeout(() => { state.toasts = state.toasts.filter((t) => t.id !== id); render(); }, 5000);
}
function navigate(r) {
  state.route = r; state.selection = null; location.hash = r;
  if (r === "current") ensureOverview();
  if (r === "status") ensureStatus();
  if (r === "fold") ensureFold();
  render();
}

function ensureOverview(force) {
  if (!force && state.overview.status !== "idle") return;
  state.overview = { status: "loading", data: null }; render();
  fetchOverview().then((d) => {
    state.overview = d && d.error ? { status: "error", data: null } : { status: "ready", data: d };
    render();
  });
}
function ensureStatus(force) {
  if (!force && state.statusData.status !== "idle") return;
  state.statusData = { status: "loading", data: null }; render();
  fetchStatus().then((d) => { state.statusData = { status: "ready", data: d }; render(); });
}
function ensureFold(force) {
  const libraryId = state.activeLibraryId || "all";
  if (!force && state.fold.status !== "idle" && state.fold.libraryId === libraryId) return;
  state.fold = { status: "loading", data: null, libraryId }; render();
  fetchFoldGraph(libraryId).then((d) => {
    if ((state.activeLibraryId || "all") !== libraryId) return;
    state.fold = d && d.error
      ? { status: "error", data: null, libraryId }
      : { status: "ready", data: d, libraryId };
    render();
  });
}
function ensureLibraries(force) {
  if (!force && state.libraries.status !== "idle") return;
  state.libraries = { ...state.libraries, status: "loading" }; render();
  api("/api/libraries").then((d) => {
    const items = d && !d.error && Array.isArray(d.libraries)
      ? d.libraries
      : [{ id: "all", name: "All libraries", count: 0 }];
    const activeExists = items.some(l => l.id === state.activeLibraryId);
    state.libraries = { status: d && d.error ? "error" : "ready", items };
    if (!activeExists) {
      state.activeLibraryId = "all";
      state.settings = { ...state.settings, activeLibraryId: "all" };
      state.fold = { status: "idle", data: null, libraryId: "all" };
      try { localStorage.setItem(STORE_KEY, JSON.stringify(state.settings)); } catch (_) {}
    }
    render();
  });
}
function loadLibraryManager() {
  state.libraryManager = { status: "loading", items: state.libraryManager.items || [] };
  render();
  api("/api/libraries?include_hidden=true").then((d) => {
    const items = d && !d.error && Array.isArray(d.libraries) ? d.libraries : [];
    state.libraryManager = { status: d && d.error ? "error" : "ready", items, error: d && d.error };
    render();
  });
}
function openLibraryManager() {
  state.libraryManagerOpen = true;
  loadLibraryManager();
}
function refreshLibrarySurfaces() {
  ensureLibraries(true);
  if (state.libraryManagerOpen) loadLibraryManager();
}
function saveLibraryOverride(lib, patch) {
  api(`/api/libraries/${encodeURIComponent(lib.id)}`, {
    method: "PATCH",
    headers: tokenHeaders(),
    body: JSON.stringify(patch),
  }).then((d) => {
    if (d && d.error) {
      pushToast(`Library update failed: ${d.error}`, "conflict");
      return;
    }
    pushToast("Library updated.", "current");
    refreshLibrarySurfaces();
  });
}
function resetLibraryOverride(lib) {
  api(`/api/libraries/${encodeURIComponent(lib.id)}/override`, {
    method: "DELETE",
    headers: tokenHeaders(),
  }).then((d) => {
    if (d && d.error) {
      pushToast(`Library reset failed: ${d.error}`, "conflict");
      return;
    }
    pushToast("Library reset.", "current");
    refreshLibrarySurfaces();
  });
}
function reorderLibrary(lib, delta) {
  const items = state.libraryManager.items || [];
  const from = items.findIndex((item) => item.id === lib.id);
  const to = from + delta;
  if (from < 0 || to < 0 || to >= items.length || !items[from].orderable || !items[to].orderable) return;
  const ids = items.map((item) => item.id);
  const tmp = ids[from];
  ids[from] = ids[to];
  ids[to] = tmp;
  api("/api/libraries/order", {
    method: "PATCH",
    headers: tokenHeaders(),
    body: JSON.stringify({ ids }),
  }).then((d) => {
    if (d && d.error) {
      pushToast(`Library reorder failed: ${d.error}`, "conflict");
      return;
    }
    pushToast("Library order updated.", "current");
    refreshLibrarySurfaces();
  });
}

function overviewProtoState() {
  if (state.forcedState !== "auto") return state.forcedState;
  if (state.overview.status === "loading") return "loading";
  if (state.overview.status === "error") return "error";
  if (state.overview.data && (!state.overview.data.recentDocs || state.overview.data.recentDocs.length === 0)) return "empty";
  return "populated";
}

function currentScreen() {
  const r = state.route;
  if (r === "current") {
    return OverviewScreen({
      protoState: overviewProtoState(), mode: state.settings.mode,
      selection: state.selection, data: state.overview.data,
      onSelectMetric: (m) => setState({ selection: (state.selection && state.selection.type === "metric" && state.selection.ns === m.ns) ? null : { type: "metric", ns: m.ns, count: m.count, delta: m.delta }, inspectorOpen: true }),
      onSelectDoc: (d) => setState({ selection: (state.selection && state.selection.type === "doc" && state.selection.doc.id === d.id) ? null : { type: "doc", doc: d }, inspectorOpen: true }),
      onToast: pushToast, onConfirm: (c) => setState({ confirm: c }), onNavigate: navigate,
    });
  }
  if (r === "settings") return SettingsFullScreen({ settings: state.settings, onSet: setSetting, onConfirm: (c) => setState({ confirm: c }), onToast: pushToast });
  if (r === "status") return StatusScreen({ statusCells: (state.statusData.data && state.statusData.data.statusCells) || [], onConfirm: (c) => setState({ confirm: c }), onToast: pushToast });
  if (r === "components") return ComponentSheet({ onToast: pushToast, onConfirm: (c) => setState({ confirm: c }) });
  if (r === "fold") {
    if (state.fold.status === "loading" || state.fold.status === "idle")
      return PlaceholderScreen({ title: "Fold Workspace", glyph: "◈", desc: "Loading fold state…", onNavigate: navigate });
    if (state.fold.status === "error")
      return PlaceholderScreen({ title: "Fold Workspace", glyph: "!", desc: "Could not load fold data (/api/fold/library or /api/graph/projection). No data was changed.", onNavigate: navigate });
    return FoldWorkspace({
      visiblePlanes: state.visiblePlanes,
      data: state.fold.data,
      onToast: pushToast,
      activeLibrary: state.libraries.items.find(l => l.id === state.activeLibraryId) || state.libraries.items[0],
      activeLibraryId: state.activeLibraryId,
    });
  }
  if (r === "intake") {
    const curSelId  = state.selection && state.selection.type === "doc"  ? state.selection.doc.id  : null;
    const curCapId  = state.selection && state.selection.type === "intake_capability" ? state.selection.cap.id : null;
    const curQrId   = state.selection && state.selection.type === "quarantine_record" ? state.selection.qr.id : null;
    const curDupId  = state.selection && state.selection.type === "duplicate_pair" ? state.selection.pair.id : null;

    // Reuse doc selection pattern from Library
    const onSelectDoc = (doc) => {
      if (curSelId === doc.id) { setState({ selection: null }); return; }
      setState({ selection: { type: "doc", doc: { ...doc, _loading: true } }, inspectorOpen: true });
      api(`/api/docs/${encodeURIComponent(doc.id)}`).then(payload => {
        if (!payload || payload.error || !payload.doc) return;
        if (!(state.selection && state.selection.type === "doc" && state.selection.doc.id === doc.id)) return;
        const full = payload.doc;
        setState({ selection: { type: "doc", doc: {
          ...state.selection.doc,
          _loading: false,
          path: full.path || null,
          summary: full.summary || null,
          definitionCount: (payload.definitions || []).length,
          eventCount: (payload.events || []).length,
          authority: full.authority_state || full.authority || state.selection.doc.authority,
          lifecycle: full.lifecycle || full.status || state.selection.doc.lifecycle,
        }}});
      });
    };

    // Capability selection
    const onSelectCapability = (cap) => {
      if (curCapId === cap.id) { setState({ selection: null }); return; }
      setState({ selection: { type: "intake_capability", cap, _loading: false }, inspectorOpen: true });
    };

    // Quarantine selection
    const onSelectQuarantine = (qr) => {
      if (curQrId === qr.id) { setState({ selection: null }); return; }
      setState({ selection: { type: "quarantine_record", qr, _loading: false }, inspectorOpen: true });
    };

    // Duplicate pair selection
    const onSelectDuplicatePair = (pair) => {
      if (curDupId === pair.id) { setState({ selection: null }); return; }
      setState({ selection: { type: "duplicate_pair", pair, _loading: false }, inspectorOpen: true });
    };

    // Audit event selection
    const onSelectAuditEvent = (event) => {
      const eventId = event.id || event.event_id;
      if (state.selection && state.selection.type === "audit_event" && state.selection.event.id === eventId) {
        setState({ selection: null }); return;
      }
      setState({ selection: { type: "audit_event", event, _loading: false }, inspectorOpen: true });
    };

    return CaptureScreen({
      onToast: pushToast,
      onSelectDoc, onSelectCapability, onSelectQuarantine, onSelectDuplicatePair, onSelectAuditEvent
    });
  }
  if (r === "library") {
    const ps = state.pendingSearch; state.pendingSearch = null;
    const curSelId  = state.selection && state.selection.type === "doc"  ? state.selection.doc.id  : null;
    const curCardId = state.selection && state.selection.type === "card" ? state.selection.card.id : null;

    const onSelectDoc = (doc) => {
      if (curSelId === doc.id) { setState({ selection: null }); return; }
      // Show normalized row data immediately; flag as enriching so Inspector can indicate loading.
      setState({ selection: { type: "doc", doc: { ...doc, _loading: true } }, inspectorOpen: true });
      // Lazy enrich from GET /api/docs/{id}. Stale-guard: only merge if same doc still selected.
      api(`/api/docs/${encodeURIComponent(doc.id)}`).then(payload => {
        if (!payload || payload.error || !payload.doc) return;
        if (!(state.selection && state.selection.type === "doc" && state.selection.doc.id === doc.id)) return;
        const full = payload.doc;
        setState({ selection: { type: "doc", doc: {
          ...state.selection.doc,
          _loading: false,
          path: full.path || null,
          summary: full.summary || null,
          definitionCount: (payload.definitions || []).length,
          eventCount: (payload.events || []).length,
          authority: full.authority_state || full.authority || state.selection.doc.authority,
          lifecycle: full.lifecycle || full.status || state.selection.doc.lifecycle,
        }}});
      });
    };

    return LibraryScreen({
      onNavigate: navigate, onToast: pushToast, pendingSearch: ps,
      selectedId: curSelId,
      selectedCardId: curCardId,
      visiblePlanes: state.visiblePlanes,
      activeLibrary: state.libraries.items.find(l => l.id === state.activeLibraryId) || state.libraries.items[0],
      activeLibraryId: state.activeLibraryId,
      onSelectDoc,
      onSelectCard: (card) => setState({
        selection: curCardId === card.id ? null : { type: "card", card },
        inspectorOpen: true,
      }),
    });
  }
  if (r === "search") {
    const ps = state.pendingSearch; state.pendingSearch = null;
    const curSelId = state.selection && state.selection.type === "doc" ? state.selection.doc.id : null;
    const onSelectDoc = (doc) => {
      if (curSelId === doc.id) { setState({ selection: null }); return; }
      setState({ selection: { type: "doc", doc: { ...doc, _loading: true } }, inspectorOpen: true });
      api(`/api/docs/${encodeURIComponent(doc.id)}`).then(payload => {
        if (!payload || payload.error || !payload.doc) return;
        if (!(state.selection && state.selection.type === "doc" && state.selection.doc.id === doc.id)) return;
        const full = payload.doc;
        setState({ selection: { type: "doc", doc: {
          ...state.selection.doc,
          _loading: false,
          path: full.path || null,
          summary: full.summary || null,
          definitionCount: (payload.definitions || []).length,
          eventCount: (payload.events || []).length,
          authority: full.authority_state || full.authority || state.selection.doc.authority,
          lifecycle: full.lifecycle || full.status || state.selection.doc.lifecycle,
        } } });
      });
    };
    return SearchContextScreen({
      pendingSearch: ps,
      onNavigate: navigate,
      onToast: pushToast,
      selectedId: curSelId,
      activeLibrary: state.libraries.items.find(l => l.id === state.activeLibraryId) || state.libraries.items[0],
      activeLibraryId: state.activeLibraryId,
      onSelectDoc,
    });
  }
  if (r === "review") {
    const curConflictId = state.selection && state.selection.type === "review_conflict" ? state.selection.conflict.conflict_id : null;
    const curProposalId = state.selection && state.selection.type === "review_proposal" ? state.selection.proposal.queue_id : null;
    const curApprovalId = state.selection && state.selection.type === "review_approval" ? state.selection.approval.id : null;
    const curQueueId = state.selection && state.selection.type === "review_queue" ? state.selection.queueItem.id : null;

    const onSelectConflict = (conflict) => {
      if (curConflictId === conflict.conflict_id) { setState({ selection: null }); return; }
      setState({ selection: { type: "review_conflict", conflict }, inspectorOpen: true });
    };

    const onSelectProposal = (proposal) => {
      if (curProposalId === proposal.queue_id) { setState({ selection: null }); return; }
      setState({ selection: { type: "review_proposal", proposal }, inspectorOpen: true });
    };

    const onSelectApproval = (approval) => {
      if (curApprovalId === approval.id) { setState({ selection: null }); return; }
      setState({ selection: { type: "review_approval", approval }, inspectorOpen: true });
    };

    const onSelectQueueItem = (queueItem) => {
      if (curQueueId === queueItem.id) { setState({ selection: null }); return; }
      setState({ selection: { type: "review_queue", queueItem }, inspectorOpen: true });
    };

    return ReviewScreen({
      onToast: pushToast,
      onSelectConflict, onSelectProposal, onSelectApproval, onSelectQueueItem
    });
  }
  if (r === "authority") {
    const curIntegrityId = state.selection && state.selection.type === "authority_integrity" ? state.selection.integrityItem.id : null;
    const curLedgerId = state.selection && state.selection.type === "authority_ledger" ? state.selection.ledgerEvent.id : null;
    const curGateId = state.selection && state.selection.type === "authority_gate" ? state.selection.gateResult.id : null;
    const curResidenceId = state.selection && state.selection.type === "authority_residence" ? state.selection.residence.id : null;

    const onSelectIntegrityItem = (item) => {
      if (curIntegrityId === item.id) { setState({ selection: null }); return; }
      setState({ selection: { type: "authority_integrity", integrityItem: item }, inspectorOpen: true });
    };

    const onSelectLedgerEvent = (event) => {
      if (curLedgerId === event.id) { setState({ selection: null }); return; }
      setState({ selection: { type: "authority_ledger", ledgerEvent: event }, inspectorOpen: true });
    };

    const onSelectGateResult = (result) => {
      if (curGateId === result.id) { setState({ selection: null }); return; }
      setState({ selection: { type: "authority_gate", gateResult: result }, inspectorOpen: true });
    };

    const onSelectResidence = (residence) => {
      if (curResidenceId === residence.id) { setState({ selection: null }); return; }
      setState({ selection: { type: "authority_residence", residence }, inspectorOpen: true });
    };

    return AuthorityScreen({
      onNavigate: navigate,
      onSelectIntegrityItem, onSelectLedgerEvent, onSelectGateResult, onSelectResidence
    });
  }
  if (r === "log") return ActivityScreen();
  if (r === "context-pack") return ContextPackScreen();
  const meta = {
    export: { title: "Export", glyph: "⤓", desc: "Structured corpus export and ICS handoff. Planned for a later phase." },
  }[r] || { title: "Screen", glyph: "▢", desc: "" };
  return PlaceholderScreen({ ...meta, onNavigate: navigate });
}

function ProtoControls() {
  if (!state.protoOpen) {
    return h("button", { className: "proto-fab", onClick: () => setState({ protoOpen: true }) },
      h("span", { className: "glyph" }, Icon({ name: "gear", size: 15 })), "Prototype");
  }
  return h("div", { className: "proto-panel" },
    h("div", { className: "pp-head" }, h("span", { className: "t-subheading" }, "Prototype controls"),
      h("span", { className: "spacer" }), h("button", { className: "icon-btn", onClick: () => setState({ protoOpen: false }), "aria-label": "Close" }, Icon({ name: "close", size: 14 }))),
    h("div", { className: "pp-body" },
      h("div", { className: "pp-group" }, h("span", { className: "pp-label t-micro" }, "Overview screen state"),
        h("div", { className: "state-radios" }, PROTO_STATES.map((s) => h("button", {
          className: `state-radio ${state.forcedState === s.value ? "active" : ""}`.trim(),
          onClick: () => { state.forcedState = s.value; if (state.route !== "current") navigate("current"); else render(); },
        }, h("span", { className: "sr-dot" }), s.label)))),
      h("div", { className: "pp-group" }, h("span", { className: "pp-label t-micro" }, "Density"),
        Segmented({ value: state.settings.density, onChange: (v) => setSetting("density", v), options: [{ value: "comfortable", label: "Comfortable" }, { value: "compact", label: "Compact" }] })),
      h("div", { className: "pp-group" }, h("span", { className: "pp-label t-micro" }, "Mode"),
        Segmented({ value: state.settings.mode, onChange: (v) => setSetting("mode", v), options: [{ value: "simple", label: "Simple" }, { value: "advanced", label: "Advanced" }] })),
      Button({ variant: "secondary", className: "sm", glyph: "▤", onClick: () => { navigate("components"); setState({ protoOpen: false }); }, children: ["Open Component Sheet"] }),
      h("div", { className: "pp-note" }, "Prototype-only controls — fixture toggles, no backend writes.")));
}

function LibraryManagerModal() {
  const manager = state.libraryManager || { status: "idle", items: [] };
  const rows = manager.items || [];
  const body = manager.status === "loading"
    ? h("div", { className: "t-small muted", style: { padding: "8px 0" } }, "Loading libraries...")
    : manager.status === "error"
      ? h("div", { className: "t-small", style: { color: "var(--state-conflict)", padding: "8px 0" } }, manager.error || "Could not load libraries.")
      : h("div", { className: "col gap-2" }, rows.map((lib) => {
          const label = lib.derived_name || lib.name || lib.id;
          const input = h("input", {
            className: "input",
            value: lib.name || lib.id,
            disabled: lib.editable === false,
            style: { gridColumn: "1 / 4" },
            "aria-label": `Display name for ${label}`,
            onKeydown: (e) => { if (e.key === "Enter") saveLibraryOverride(lib, { display_name: input.value }); },
          });
          return h("div", {
            className: "library-manager-row",
            style: {
              display: "grid",
              gridTemplateColumns: "1fr auto auto auto",
              alignItems: "center",
              gap: "8px",
              padding: "8px 0",
              borderBottom: "1px solid var(--border-default)",
            },
          },
            h("div", { style: { minWidth: 0 } },
              h("div", { className: "t-body", style: { whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" } }, label),
              h("div", { className: "t-mono muted" }, `${lib.count ?? 0} docs`)),
            lib.hideable
              ? Toggle({
                  checked: !lib.hidden,
                  label: `${label} visible`,
                  onChange: (visible) => saveLibraryOverride(lib, { hidden: !visible }),
                })
              : h("span", { className: "t-small muted" }, "Pinned"),
            h("div", { className: "flex gap-1" },
              h("button", {
                className: "icon-btn",
                disabled: !lib.orderable,
                "aria-label": `Move ${label} up`,
                onClick: () => reorderLibrary(lib, -1),
              }, h("span", { style: { transform: "rotate(180deg)", display: "inline-flex" } }, Icon({ name: "chevDown", size: 14 }))),
              h("button", {
                className: "icon-btn",
                disabled: !lib.orderable,
                "aria-label": `Move ${label} down`,
                onClick: () => reorderLibrary(lib, 1),
              }, Icon({ name: "chevDown", size: 14 }))),
            h("button", {
              className: "icon-btn",
              disabled: !lib.overridden,
              "aria-label": `Reset ${label}`,
              onClick: () => resetLibraryOverride(lib),
            }, Icon({ name: "refresh", size: 14 })),
            input,
            h("button", {
              className: "icon-btn",
              disabled: lib.editable === false,
              "aria-label": `Save ${label}`,
              onClick: () => saveLibraryOverride(lib, { display_name: input.value }),
            }, Icon({ name: "check", size: 14 })));
        }));
  return Modal({
    title: "Manage libraries",
    onClose: () => setState({ libraryManagerOpen: false }),
    footer: h("div", { className: "flex gap-2" },
      Button({ variant: "secondary", onClick: () => setState({ libraryManagerOpen: false }), children: ["Done"] })),
    children: [
      body,
    ],
  });
}

function render() {
  const showInspector = state.inspectorOpen && (
    (state.route === "current" && ["populated", "partial"].includes(overviewProtoState())) ||
    state.route === "library" ||
    state.route === "search" ||
    (state.route === "intake" && state.selection) ||
    (state.route === "review" && state.selection) ||
    (state.route === "authority" && state.selection)
  );

  // Derive live counts from already-loaded state — no extra fetches.
  const conflictMetric = (state.overview.data && state.overview.data.metrics || []).find(m => m.key === "conflict");
  const unresolvedAlerts = conflictMetric ? (conflictMetric.count || 0) : 0;
  const runningJobs = 0; // no jobs endpoint; chip hidden when 0
  const lastIndexedCell = state.statusData.data && state.statusData.data.statusCells &&
    state.statusData.data.statusCells.find(c => c.label === "Last indexed");
  const lastIndexed = lastIndexedCell ? lastIndexedCell.value : null;

  const tree = h("div", { className: "app", "data-density": state.settings.density, "data-mode": state.settings.mode },
    h("div", { className: "brandcell" }, h("span", { className: "brand-dot" }), h("span", { className: "brand-mark" }, "BOH")),
    TopBar({ mode: state.settings.mode, onMode: (v) => setSetting("mode", v),
      visiblePlanes: state.visiblePlanes, onTogglePlane: togglePlane, onShowAllPlanes: showAllPlanes,
      libraries: state.libraries.items, activeLibraryId: state.activeLibraryId, onSelectLibrary: setActiveLibrary,
      onManageLibraries: openLibraryManager,
      onOpenAlerts: () => setState({ alertsOpen: true }), alertCount: unresolvedAlerts, jobCount: runningJobs,
      lastIndexed, diagnostics: state.settings.diagnostics,
      onSearch: (q) => { state.pendingSearch = q; navigate("search"); } }),
    Sidebar({ route: state.route, onNavigate: navigate }),
    h("div", {
      className: `main ${showInspector ? "with-inspector" : ""}`.trim(),
      style: { gridTemplateColumns: showInspector ? `1fr 5px ${state.inspectorWidth}px` : "1fr" } },
      currentScreen(),
      showInspector && h("div", { className: "inspector-resize", onMousedown: startResize }),
      showInspector && Inspector({ selection: state.selection,
        onClose: () => setState({ selection: null }),
        onCollapse: () => setState({ inspectorOpen: false, selection: null }),
        onTrace: () => pushToast("Routing to Authority & Audit → Trace & Gates (Phase B).", "review") })),
    state.alertsOpen && AlertsDrawer({ onClose: () => setState({ alertsOpen: false }), onToast: pushToast }),
    state.libraryManagerOpen && LibraryManagerModal(),
    state.confirm && Modal({ title: state.confirm.title, onClose: () => setState({ confirm: null }),
      footer: h("div", { className: "flex gap-2" },
        Button({ variant: "secondary", onClick: () => setState({ confirm: null }), children: ["Cancel"] }),
        Button({ variant: state.confirm.variant === "danger" ? "danger" : (state.confirm.variant || "secondary"),
          onClick: () => {
            const kind = state.confirm.kind;
            // Rebuild Index
            if (kind === "rebuild") {
              const tok = getToken();
              if (!tok) {
                pushToast("Operator token required — set in Settings → Security & Advanced.", "stale");
                setState({ confirm: null });
                return;
              }
              setState({ confirm: null });
              api("/api/autoindex/run", {
                method: "POST",
                headers: tokenHeaders(),
                body: JSON.stringify({ library_root: null, max_files: 5000, changed_only: false, include_scratch: false }),
              }).then(d => {
                if (d && d.error) {
                  pushToast(`Rebuild failed: ${d.error}`, "conflict");
                  return;
                }
                pushToast("Rebuild started. Check status below.", "current");
                setTimeout(() => ensureStatus(true), 1000);
              });
            }
            // Reset Workspace
            else if (kind === "reset") {
              const tok = getToken();
              if (!tok) {
                pushToast("Operator token required — set in Settings → Security & Advanced.", "stale");
                setState({ confirm: null });
                return;
              }
              setState({ confirm: null });
              api("/api/workspace/reset", {
                method: "POST",
                headers: tokenHeaders(),
                body: JSON.stringify({ confirm: "RESET" }),
              }).then(d => {
                if (d && d.error) {
                  pushToast(`Reset failed: ${d.error}`, "conflict");
                  return;
                }
                pushToast("Workspace reset complete. Reload page to see changes.", "current");
                setTimeout(() => { ensureStatus(true); ensureOverview(true); }, 1000);
              });
            }
            // Clear Caches (not implemented)
            else if (kind === "caches") {
              pushToast("Clear caches is not yet implemented.", "stale");
              setState({ confirm: null });
            }
            // Fallback for unknown actions
            else {
              pushToast(`${state.confirm.confirmLabel} — prototype action, no backend change.`, state.confirm.danger ? "conflict" : "current");
              setState({ confirm: null });
            }
          }, children: [state.confirm.confirmLabel] })),
      children: [
        h("p", { style: { margin: 0 } }, state.confirm.body),
        h("div", { className: "scope-preview" },
          h("div", { className: "sp-row" }, h("span", { className: "k" }, "Library"), h("span", null, "Bag of Holding")),
          h("div", { className: "sp-row" }, h("span", { className: "k" }, "Source files"), h("span", { style: { color: "var(--state-current)" } }, "untouched"))),
        state.confirm.danger && h("div", { className: "t-small", style: { color: "var(--state-conflict)" } }, "This action is irreversible. Review the scope preview before confirming."),
      ] }),
    ToastHost({ toasts: state.toasts }),
    ProtoControls());

  mount(root(), tree);
}

window.addEventListener("hashchange", () => {
  const r = location.hash.replace(/^#/, "");
  if (r && r !== state.route) navigate(r);
});

// boot
ensureLibraries();
if (state.route === "current") ensureOverview();
if (state.route === "status") ensureStatus();
if (state.route === "fold") ensureFold();
render();
