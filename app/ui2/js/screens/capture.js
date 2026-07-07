/* BOH new UI — Capture & Intake.
   Tabs: Recent · Add documents · Capture note · Capabilities · Quarantine · Duplicates */
import { h } from "../dom.js";
import { api, escHtml, getToken, tokenHeaders, tokenHeadersMultipart } from "../api.js";
import { Badge, Button, Card, Skeleton, Tabs, EmptyState, AlertBanner } from "../primitives.js";

let _tab = "recent";

// In-flight guards for the capture forms (one each; forms are singletons).
let _indexBusy = false, _uploadBusy = false, _noteBusy = false;

// Track in-flight disposition requests to prevent double-submission per capability.
const _inflight = new Set();

// Track in-flight duplicate decision requests to prevent double-submission.
const _inflightDuplicateDecision = new Set();

function doDisposition(capabilityId, action, reason, onToast, rebuild) {
  if (!capabilityId) {
    onToast && onToast("Cannot act: capability ID unavailable for this quarantine record.", "stale");
    return;
  }
  if (_inflight.has(capabilityId)) {
    onToast && onToast("Request already in progress for this item.", "stale");
    return;
  }
  const tok = getToken();
  if (!tok) {
    onToast && onToast("Operator token required — set in Settings → Security & Advanced.", "stale");
    return;
  }
  _inflight.add(capabilityId);
  api(`/api/intake/capabilities/${encodeURIComponent(capabilityId)}/operator-disposition`, {
    method: "PATCH",
    headers: tokenHeaders(),
    body: JSON.stringify({ action, reason }),
  }).then(d => {
    _inflight.delete(capabilityId);
    if (d && d.error) {
      onToast && onToast(`${action === "hold" ? "Hold" : "Approve for Retry"} failed: ${d.error}`, "conflict");
      return;
    }
    onToast && onToast(
      action === "hold" ? "Capability held for review." : "Capability approved for retry.",
      action === "hold" ? "stale" : "current",
    );
    rebuild();
  });
}

function doDuplicateDecision(docId, relatedDocId, decision, onToast, rebuild) {
  if (!docId || !relatedDocId) {
    onToast && onToast("Cannot act: document IDs unavailable for this duplicate.", "stale");
    return;
  }
  const key = `${docId}|${relatedDocId}|${decision}`;
  if (_inflightDuplicateDecision.has(key)) {
    onToast && onToast("Request already in progress for this decision.", "stale");
    return;
  }
  const tok = getToken();
  if (!tok) {
    onToast && onToast("Operator token required — set in Settings → Security & Advanced.", "stale");
    return;
  }
  _inflightDuplicateDecision.add(key);
  api("/api/duplicates/decision", {
    method: "POST",
    headers: tokenHeaders(),
    body: JSON.stringify({ doc_id: docId, related_doc_id: relatedDocId, decision, note: "" }),
  }).then(d => {
    _inflightDuplicateDecision.delete(key);
    if (d && d.error) {
      onToast && onToast(`Decision failed: ${d.error}`, "conflict");
      return;
    }
    const decisionLabels = {
      "canonical": "Marked as canonical",
      "duplicate": "Marked as duplicate",
      "ignored": "Marked as ignored",
      "quarantine": "Marked for quarantine"
    };
    onToast && onToast(decisionLabels[decision] || `Decision recorded: ${decision}`, "current");
    rebuild();
  }).catch(e => {
    _inflightDuplicateDecision.delete(key);
    onToast && onToast(`Decision error: ${e}`, "conflict");
  });
}

// Normalizer functions: convert API rows to inspector shape
function normalizeCapability(c) {
  return {
    id: c.intake_capability_id || c.id,
    intake_capability_id: c.intake_capability_id,
    title: c.source_ref || "Capability",
    subtitle: [c.lifecycle_state, c.safety_lane].filter(Boolean).join(" · "),
    lifecycle: c.lifecycle_state || "unknown",
    safety_lane: c.safety_lane || "—",
    markers: [c.lifecycle_state ? { type: "lifecycle", value: c.lifecycle_state } : null].filter(Boolean),
    preservable: c.preservable ? "Yes" : "No",
    queryable: c.queryable ? "Yes" : "No",
    failure_reason: c.failure_reason || null,
    source_ref: c.source_ref || null,
  };
}

function normalizeQuarantine(q) {
  return {
    id: q.quarantine_record_id || q.id,
    quarantine_record_id: q.quarantine_record_id,
    title: q.quarantine_record_id || "Quarantine",
    subtitle: [q.quarantine_category, q.current_safety_lane].filter(Boolean).join(" · "),
    category: q.quarantine_category || "—",
    reason: q.quarantine_reason || "—",
    lane: q.current_safety_lane || "quarantine",
    markers: [q.current_safety_lane ? { type: "lane", value: q.current_safety_lane } : null].filter(Boolean),
    created_at: q.created_at || null,
    record_id: q.quarantine_record_id || null,
  };
}

function normalizeDuplicatePair(p) {
  const composite = `${p.doc_id}|${p.related_doc_id}`;
  return {
    id: composite,
    composite_id: composite,
    title: p.relationship ? p.relationship.replace(/_/g, " ") : "Duplicate pair",
    subtitle: `${(p.doc_path || "").slice(-40)} ↔ ${(p.related_path || "").slice(-40)}`,
    doc_id: p.doc_id || null,
    related_doc_id: p.related_doc_id || null,
    relationship: p.relationship || "duplicate_content",
    detected_ts: p.detected_ts || null,
    detected_at: p.detected_ts ? new Date(p.detected_ts * 1000).toLocaleDateString() : null,
    markers: [
      p.relationship ? { type: "relationship", value: p.relationship.replace(/_/g, " ") } : null,
    ].filter(Boolean),
  };
}

function normalizeAuditEvent(e) {
  const timestamp = e.event_ts ? new Date(e.event_ts * 1000).toLocaleString() : "—";
  return {
    id: e.id || e.event_id,
    event_id: e.id || e.event_id,
    title: e.event_type || "Event",
    subtitle: [e.actor_id || e.actor_type, timestamp].filter(Boolean).join(" · "),
    event_type: e.event_type || "unknown",
    actor_id: e.actor_id || e.actor_type || "—",
    timestamp: timestamp,
    detail: e.detail || e.doc_id || "—",
    markers: [
      e.event_type ? { type: "event_type", value: e.event_type } : null,
    ].filter(Boolean),
  };
}

// Normalize a recent event row into doc inspector shape (from /api/input/recent)
function normalizeRecentEvent(r) {
  return {
    id: r.doc_id || "recent",
    title: r.detail || r.doc_id || "Recent item",
    project: "—",
    authority: "—",
    currentness: "unknown",
    markers: [],
    lifecycle: "—",
    action: "",
    updated: r.event_ts ? new Date(r.event_ts * 1000).toLocaleDateString() : "—",
    why: [],
  };
}

export function CaptureScreen({ onToast, onSelectCapability, onSelectQuarantine, onSelectDuplicatePair, onSelectAuditEvent, onSelectDoc }) {
  let root;
  function rebuild() { const old = root; const n = build(); old.replaceWith(n); }
  function build() {
    root = h("div", { class: "content content-narrow" },
      h("div", { class: "page-head" },
        h("div", { class: "t-display" }, "Capture & Intake"),
        h("div", { class: "sub t-small" }, "Recent activity, intake capabilities, quarantine, and duplicate candidates.")),
      Tabs({ value: _tab, onChange: v => { _tab = v; rebuild(); }, tabs: [
        { value: "recent",       label: "Recent" },
        { value: "add",          label: "Add documents" },
        { value: "note",         label: "Capture note" },
        { value: "capabilities", label: "Capabilities" },
        { value: "quarantine",   label: "Quarantine" },
        { value: "duplicates",   label: "Duplicates" },
      ] }),
      _tab === "recent"       ? RecentTab(onSelectDoc) :
      _tab === "add"          ? AddDocumentsTab(onToast, goRecent) :
      _tab === "note"         ? CaptureNoteTab(onToast, goRecent) :
      _tab === "capabilities" ? CapabilitiesTab(onSelectCapability) :
      _tab === "quarantine"   ? QuarantineTab(onToast, onSelectQuarantine) :
                                DuplicatesTab(onToast, rebuild, onSelectDuplicatePair));
    return root;
  }
  function goRecent() { _tab = "recent"; rebuild(); }
  return build();
}

// ── Add documents: server-path index + file upload ──────────────────────────
function AddDocumentsTab(onToast, goRecent) {
  function requireToken() {
    if (getToken()) return true;
    onToast && onToast("Operator token required — set in Settings → Security & Advanced.", "stale");
    return false;
  }

  // --- server-path index form ---
  let _pathInput, _indexBtn, _indexOut;
  function doIndex() {
    if (_indexBusy) return;
    if (!requireToken()) return;
    const root = (_pathInput && _pathInput.value.trim()) || "";
    _indexBusy = true; _indexBtn.disabled = true; _indexBtn.textContent = "Indexing…";
    _indexOut.textContent = "";
    api("/api/index", {
      method: "POST",
      headers: tokenHeaders(),
      body: JSON.stringify(root ? { library_root: root } : {}),
    }).then(d => {
      _indexBusy = false; _indexBtn.disabled = false; _indexBtn.textContent = "Index path";
      if (d && d.error) { _indexOut.style.color = "var(--state-conflict)"; _indexOut.textContent = d.error; return; }
      const n = d.indexed ?? d.indexed_count ?? d.count ?? "?";
      const conf = d.conflicts_detected != null ? ` · ${d.conflicts_detected} conflicts` : "";
      _indexOut.style.color = "var(--state-current)";
      _indexOut.textContent = `Indexed ${n} document(s)${conf}.`;
      onToast && onToast("Library indexed.", "current");
    });
  }

  // --- file upload form ---
  let _fileInput, _folderInput, _uploadBtn, _uploadOut;
  function doUpload() {
    if (_uploadBusy) return;
    if (!requireToken()) return;
    const files = (_fileInput && _fileInput.files) || [];
    if (!files.length) { onToast && onToast("Choose at least one file to upload.", "stale"); return; }
    const fd = new FormData();
    for (const f of files) fd.append("files", f);
    const folder = (_folderInput && _folderInput.value.trim()) || "scratch";
    fd.append("target_folder", folder);
    fd.append("intake_mode", "scratch");
    _uploadBusy = true; _uploadBtn.disabled = true; _uploadBtn.textContent = "Uploading…";
    _uploadOut.textContent = "";
    fetch("/api/input/upload", { method: "POST", headers: tokenHeadersMultipart(), body: fd })
      .then(async res => {
        _uploadBusy = false; _uploadBtn.disabled = false; _uploadBtn.textContent = "Upload & index";
        let body; try { body = await res.json(); } catch (_) { body = null; }
        if (!res.ok) {
          _uploadOut.style.color = "var(--state-conflict)";
          _uploadOut.textContent = (body && body.detail) || `Upload failed (HTTP ${res.status}).`;
          return;
        }
        const saved = (body && body.saved) || [];
        const rejected = (body && body.rejected) || [];
        _uploadOut.style.color = rejected.length ? "var(--state-stale)" : "var(--state-current)";
        _uploadOut.textContent = `Saved ${saved.length}` + (rejected.length ? ` · rejected ${rejected.length}: ${rejected.map(r => `${r.filename} (${r.reason})`).join("; ").slice(0, 120)}` : ".");
        if (saved.length) onToast && onToast(`Uploaded ${saved.length} file(s).`, "current");
      })
      .catch(e => {
        _uploadBusy = false; _uploadBtn.disabled = false; _uploadBtn.textContent = "Upload & index";
        _uploadOut.style.color = "var(--state-conflict)";
        _uploadOut.textContent = String(e && e.message || e);
      });
  }

  return h("div", { class: "col gap-3", style: { marginTop: "16px" } },
    AlertBanner({ ns: "advisory", children: ["Both actions require the operator token and write into the managed library. Server-path indexing is constrained to BOH_LIBRARY; uploads are extension-checked and never overwrite."] }),
    Card({ title: "Index a server-side path", children: h("div", { class: "col gap-3" },
      h("div", { class: "t-small" }, "Re-index the library, or a sub-path of it. Leave blank to index the whole library root. Paths outside BOH_LIBRARY are rejected (403)."),
      h("div", { class: "flex gap-2 items-center" },
        (_pathInput = h("input", { placeholder: "sub-path under library (optional)", style: { flex: "1", fontFamily: "var(--font-mono)", fontSize: "12px", padding: "4px 8px", background: "var(--bg-input)", border: "1px solid var(--border-default)", borderRadius: "6px", color: "var(--text-primary)" } })),
        (_indexBtn = h("button", { class: "btn btn-secondary btn-sm", onClick: doIndex }, "Index path"))),
      (_indexOut = h("div", { class: "t-small" })))}),
    Card({ title: "Upload files", children: h("div", { class: "col gap-3" },
      h("div", { class: "t-small" }, "Allowed: markdown, text/config/markup, JSON/YAML/CSV, HTML, notebooks, and DOCX. Executables and archives are rejected."),
      (_fileInput = h("input", { type: "file", multiple: true, style: { fontSize: "12px" } })),
      h("div", { class: "flex gap-2 items-center" },
        (_folderInput = h("input", { placeholder: "target folder (default: scratch)", style: { flex: "1", fontFamily: "var(--font-mono)", fontSize: "12px", padding: "4px 8px", background: "var(--bg-input)", border: "1px solid var(--border-default)", borderRadius: "6px", color: "var(--text-primary)" } })),
        (_uploadBtn = h("button", { class: "btn btn-secondary btn-sm", onClick: doUpload }, "Upload & index"))),
      (_uploadOut = h("div", { class: "t-small" })))}));
}

// ── Capture note: create a Markdown note ────────────────────────────────────
function CaptureNoteTab(onToast, goRecent) {
  let _titleInput, _bodyInput, _topicsInput, _saveBtn, _out;
  function update() {
    const blank = !(_bodyInput && _bodyInput.value.trim());
    if (_saveBtn) _saveBtn.disabled = blank || _noteBusy;
  }
  function doSave() {
    if (_noteBusy) return;
    if (!getToken()) { onToast && onToast("Operator token required — set in Settings → Security & Advanced.", "stale"); return; }
    const body = (_bodyInput && _bodyInput.value.trim()) || "";
    if (!body) { onToast && onToast("Note body is empty.", "stale"); return; }
    const title = (_titleInput && _titleInput.value.trim()) || "Untitled note";
    const topics = ((_topicsInput && _topicsInput.value) || "").split(",").map(t => t.trim()).filter(Boolean);
    _noteBusy = true; _saveBtn.disabled = true; _saveBtn.textContent = "Saving…";
    _out.textContent = "";
    api("/api/input/markdown", {
      method: "POST",
      headers: tokenHeaders(),
      body: JSON.stringify({ title, body, topics, target_folder: "notes" }),
    }).then(d => {
      _noteBusy = false; _saveBtn.textContent = "Capture note"; update();
      if (d && d.error) { _out.style.color = "var(--state-conflict)"; _out.textContent = d.error; return; }
      onToast && onToast("Note captured.", "current");
      goRecent();
    });
  }

  const tab = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
    AlertBanner({ ns: "advisory", children: ["Notes are saved as draft Markdown in the managed library (never canonical). Requires the operator token."] }),
    Card({ title: "New note", children: h("div", { class: "col gap-3" },
      (_titleInput = h("input", { placeholder: "Title (optional)", style: { fontSize: "13px", padding: "6px 8px", background: "var(--bg-input)", border: "1px solid var(--border-default)", borderRadius: "6px", color: "var(--text-primary)" } })),
      (_bodyInput = h("textarea", { placeholder: "Note body (Markdown)…", rows: "8", oninput: update, style: { fontFamily: "var(--font-mono)", fontSize: "12px", padding: "8px", background: "var(--bg-input)", border: "1px solid var(--border-default)", borderRadius: "6px", color: "var(--text-primary)", resize: "vertical" } })),
      (_topicsInput = h("input", { placeholder: "topics, comma, separated (optional)", style: { fontSize: "12px", padding: "6px 8px", background: "var(--bg-input)", border: "1px solid var(--border-default)", borderRadius: "6px", color: "var(--text-primary)" } })),
      h("div", { class: "flex gap-2 items-center" },
        (_saveBtn = h("button", { class: "btn btn-governed btn-sm", disabled: true, onClick: doSave }, "Capture note")),
        h("span", { class: "t-small muted" }, "blank notes are rejected")),
      (_out = h("div", { class: "t-small" })))}));
  update();
  return tab;
}

function RecentTab(onSelectDoc) {
  const wrap = loading();
  api("/api/input/recent?limit=20").then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const items = d.items || [];
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      AlertBanner({ ns: "stale", children: ["Recent items are capture-surface activity. Admission to the index requires an explicit operator action."] }),
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Recent activity"), h("span", { class: "count t-small" }, String(items.length))));
    if (items.length) {
      out.appendChild(Card({ bodyFlush: true, children:
        tbl(["Document","Actor","Detail","Time"], items.map(i => ({
          key: i.doc_id || i.event_ts,
          onClick: () => onSelectDoc && onSelectDoc(normalizeRecentEvent(i)),
          onKeydown: e => { if (e.key === "Enter") onSelectDoc && onSelectDoc(normalizeRecentEvent(i)); },
          cells: [
            mono((i.doc_id || "").slice(0, 24)),
            dim(i.actor_id || "—"),
            h("span", { class: "t-small" }, escHtml((i.detail || "").slice(0, 60))),
            dim(i.event_ts ? new Date(i.event_ts * 1000).toLocaleTimeString() : "—")],
        }))) }));
    } else {
      out.appendChild(EmptyState({ glyph: "＋", title: "No recent items", desc: "Documents added to the capture surface will appear here." }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

function CapabilitiesTab(onSelectCapability) {
  const wrap = loading();
  api("/api/intake/capabilities?limit=100").then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const items = d.items || [];
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      h("div", { class: "section-head" },
        h("span", { class: "t-subheading" }, "Intake capabilities"),
        h("span", { class: "count t-small" }, `${items.length} / ${d.total ?? items.length}`)));
    if (items.length) {
      const rows = items.map(c => {
        const ns = c.lifecycle_state === "quarantined" ? "quarantine" : c.lifecycle_state === "held" ? "preserved" : "current";
        return {
          key: c.intake_capability_id || c.source_ref,
          onClick: () => onSelectCapability && onSelectCapability(normalizeCapability(c)),
          onKeydown: e => { if (e.key === "Enter") onSelectCapability && onSelectCapability(normalizeCapability(c)); },
          cells: [
            h("td", { title: c.source_ref || "" }, mono((c.source_ref || "").slice(-36))),
            h("td", null, Badge({ ns, label: c.lifecycle_state || "—" })),
            h("td", null, dim(c.safety_lane || "—")),
            h("td", { class: "num" }, c.preservable ? "✓" : "·"),
            h("td", { class: "num" }, c.queryable ? "✓" : "·"),
            h("td", null, dim((c.failure_reason || "").slice(0, 40))),
          ],
        };
      });
      out.appendChild(Card({ bodyFlush: true, children:
        h("div", { style: { overflowX: "auto" } },
          h("table", { class: "tbl" },
            h("thead", null, h("tr", null, h("th", null, "Source"), h("th", { style: { width: "110px" } }, "Lifecycle"), h("th", { style: { width: "90px" } }, "Lane"), h("th", { style: { width: "60px" } }, "Preserve"), h("th", { style: { width: "60px" } }, "Query"), h("th", null, "Failure"))),
            h("tbody", null, ...rows.map(row => {
              const props = { tabindex: "0", role: "button", "aria-selected": "false" };
              if (row.onClick) props.onClick = row.onClick;
              if (row.onKeydown) props.onKeydown = row.onKeydown;
              return h("tr", props, ...row.cells);
            })))) }));
    } else {
      out.appendChild(EmptyState({ glyph: "⬇", title: "No intake capabilities" }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

function doReplay(capabilityId, onToast, rebuild) {
  // Explicit governed retry. `/api/intake/run` is idempotent (a re-POST is a no-op), so reprocessing
  // goes through the dedicated replay endpoint. Held/failed items reprocess; quarantined (blocked)
  // content is refused server-side.
  if (!capabilityId) {
    onToast && onToast("Cannot replay: capability ID unavailable for this record.", "stale");
    return;
  }
  if (_inflight.has(capabilityId)) {
    onToast && onToast("Request already in progress for this item.", "stale");
    return;
  }
  const tok = getToken();
  if (!tok) {
    onToast && onToast("Operator token required — set in Settings → Security & Advanced.", "stale");
    return;
  }
  _inflight.add(capabilityId);
  api("/api/intake/replay", {
    method: "POST",
    headers: tokenHeaders(),
    body: JSON.stringify({ intake_capability_id: capabilityId }),
  }).then(d => {
    _inflight.delete(capabilityId);
    if (d && d.error) { onToast && onToast(`Replay failed: ${d.error}`, "conflict"); return; }
    if (d && d.success) {
      onToast && onToast("Replay complete.", "current");
    } else {
      onToast && onToast(
        `Not reprocessed${d && d.stage_reached ? " (" + d.stage_reached + ")" : ""} — blocked content is not replay-eligible.`,
        "stale");
    }
    rebuild && rebuild();
  }).catch(e => {
    _inflight.delete(capabilityId);
    onToast && onToast("Replay error: " + e, "conflict");
  });
}

function doQuarantineRelease(capabilityId, force, onToast, rebuild) {
  // Release a quarantined item: PATCH /api/intake/capabilities/{id}/operator-disposition
  // with { action: "release", force: force }. Permits release of complete/held items without force;
  // failed items require force=true (optional hint on 422 validation error suggests retry with force).
  // Success: toast showing "Released" + capability status + rebuild table.
  // In-flight guard: prevents duplicate submissions per capability_id.
  if (!capabilityId) {
    onToast && onToast("Cannot release: capability ID unavailable for this quarantine record.", "stale");
    return;
  }
  if (_inflight.has(capabilityId)) {
    onToast && onToast("Request already in progress for this item.", "stale");
    return;
  }
  const tok = getToken();
  if (!tok) {
    onToast && onToast("Operator token required — set in Settings → Security & Advanced.", "stale");
    return;
  }
  _inflight.add(capabilityId);
  api(`/api/intake/capabilities/${encodeURIComponent(capabilityId)}/operator-disposition`, {
    method: "PATCH",
    headers: tokenHeaders(),
    body: JSON.stringify({ action: "release", force: force || false }),
  }).then(d => {
    _inflight.delete(capabilityId);
    if (d && d.error) {
      let errorMsg = `Release failed: ${d.error}`;
      // Check for 422 validation error (force param hint)
      if (d.error && d.error.includes("force")) {
        errorMsg += " · Consider Retry with force if this is a failed attempt.";
      }
      onToast && onToast(errorMsg, "conflict");
      return;
    }
    onToast && onToast(
      `Released: capability ${(d && d.capability_id || capabilityId).slice(0, 16)}… is now eligible for manual retry.`,
      "current");
    rebuild();
  }).catch(e => {
    _inflight.delete(capabilityId);
    onToast && onToast("Release error: " + e, "conflict");
  });
}


function QuarantineTab(onToast, onSelectQuarantine) {
  let _rebuild;
  const wrap = loading();
  function load() {
    api("/api/intake/quarantine?limit=100").then(d => {
      if (d.error) { err(wrap, d.error); return; }
      const items = d.items || [];
      const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
        AlertBanner({ ns: "quarantine", children: ["Quarantined files are metadata-only (never copied to RAW) and preserved as records. Hold places an item under review; Release marks it eligible for manual retry; Replay reprocesses held/failed items via /api/intake/replay (blocked content such as executables is not replay-eligible). Nothing is deleted."] }),
        h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Active quarantine"), h("span", { class: "count t-small" }, String(items.length))));
      if (items.length) {
        out.appendChild(Card({ bodyFlush: true, children:
          tbl(["Record","Lane","Category","Reason","Created","Actions"], items.map(q => ({
            key: q.quarantine_record_id || q.intake_capability_id,
            onClick: () => onSelectQuarantine && onSelectQuarantine(normalizeQuarantine(q)),
            onKeydown: e => { if (e.key === "Enter") onSelectQuarantine && onSelectQuarantine(normalizeQuarantine(q)); },
            cells: [
              mono((q.quarantine_record_id || "").slice(0, 20)),
              h("span", { class: "badge", style: { color: q.current_safety_lane === "hold" ? "var(--state-stale)" : "var(--state-conflict)" } }, q.current_safety_lane || "quarantine"),
              h("span", { style: { color: "var(--state-conflict)" } }, escHtml(q.quarantine_category || "—")),
              h("span", { class: "t-small" }, (q.quarantine_reason || "").slice(0, 60)),
              dim(q.created_at ? new Date(q.created_at).toLocaleDateString() : "—"),
              h("div", { class: "flex gap-1" },
                Button({ variant: "containment", glyph: "⊗", className: "sm",
                  onClick: (e) => { e.stopPropagation(); doDisposition(q.intake_capability_id, "hold",
                    "Held for operator review via Capture & Intake.", onToast, () => load()); },
                  children: ["Hold"] }),
                Button({ variant: "secondary", className: "sm",
                  onClick: (e) => { e.stopPropagation(); doQuarantineRelease(q.intake_capability_id, q.lifecycle_state === "failed", onToast, () => load()); },
                  children: ["Release"] }),
                Button({ variant: "secondary", className: "sm",
                  onClick: (e) => { e.stopPropagation(); doReplay(q.intake_capability_id, onToast, () => load()); },
                  children: ["Replay"] }))]
          }))) }));
      } else {
        out.appendChild(EmptyState({ glyph: "⚠", title: "No active quarantine items", desc: "Released items are removed from this view. Check capabilities list for history." }));
      }
      wrap.replaceWith(out);
    });
  }
  load();
  return wrap;
}

function DuplicatesTab(onToast, rebuild, onSelectDuplicatePair) {
  const wrap = loading();
  api("/api/duplicates?limit=50").then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const duplicates = d.duplicates || [];
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      AlertBanner({ ns: "stale", children: ["Files are never deleted here. Use Copy Path or Open Location, then remove files manually outside Bag of Holding."] }),
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Duplicate pairs"), h("span", { class: "count t-small" }, `${duplicates.length} pairs`)));
    if (duplicates.length) {
      duplicates.forEach(row => {
        const cardTitle = (row.relationship || "duplicate_content").replace(/_/g, " ").slice(0, 50);
        const docRows = [];
        const selectProps = {
          class: "flex gap-2 items-center",
          style: { cursor: onSelectDuplicatePair ? "pointer" : "default" },
          onClick: () => onSelectDuplicatePair && onSelectDuplicatePair(normalizeDuplicatePair(row)),
          onKeydown: e => { if (e.key === "Enter") onSelectDuplicatePair && onSelectDuplicatePair(normalizeDuplicatePair(row)); },
          tabindex: 0,
          role: "button",
          "aria-selected": "false"
        };
        docRows.push(
          h("div", selectProps,
            h("div", { class: "flex gap-2", style: { flex: "1" } },
              mono((row.doc_id || "").slice(0, 40)),
              dim((row.doc_path || "").slice(-40))),
            h("div", { class: "flex gap-1" },
              Button({ variant: "secondary", className: "xs",
                onClick: e => { e.stopPropagation(); doDuplicateDecision(row.doc_id, row.related_doc_id, "canonical", onToast, rebuild); },
                children: ["Canonical"] }),
              Button({ variant: "secondary", className: "xs",
                onClick: e => { e.stopPropagation(); doDuplicateDecision(row.doc_id, row.related_doc_id, "duplicate", onToast, rebuild); },
                children: ["Duplicate"] }),
              Button({ variant: "ghost", className: "xs",
                onClick: e => { e.stopPropagation(); doDuplicateDecision(row.doc_id, row.related_doc_id, "ignored", onToast, rebuild); },
                children: ["Ignore"] }),
              Button({ variant: "containment", className: "xs",
                onClick: e => { e.stopPropagation(); doDuplicateDecision(row.doc_id, row.related_doc_id, "quarantine", onToast, rebuild); },
                children: ["Quarantine"] }))));
        docRows.push(
          h("div", selectProps,
            h("div", { class: "flex gap-2", style: { flex: "1" } },
              mono((row.related_doc_id || "").slice(0, 40)),
              dim((row.related_path || "").slice(-40))),
            h("div", { class: "flex gap-1" },
              Button({ variant: "secondary", className: "xs",
                onClick: e => { e.stopPropagation(); doDuplicateDecision(row.related_doc_id, row.doc_id, "canonical", onToast, rebuild); },
                children: ["Canonical"] }),
              Button({ variant: "secondary", className: "xs",
                onClick: e => { e.stopPropagation(); doDuplicateDecision(row.related_doc_id, row.doc_id, "duplicate", onToast, rebuild); },
                children: ["Duplicate"] }),
              Button({ variant: "ghost", className: "xs",
                onClick: e => { e.stopPropagation(); doDuplicateDecision(row.related_doc_id, row.doc_id, "ignored", onToast, rebuild); },
                children: ["Ignore"] }),
              Button({ variant: "containment", className: "xs",
                onClick: e => { e.stopPropagation(); doDuplicateDecision(row.related_doc_id, row.doc_id, "quarantine", onToast, rebuild); },
                children: ["Quarantine"] }))));
        out.appendChild(Card({ title: cardTitle, children:
          h("div", { class: "col gap-2" },
            h("div", { class: "t-small muted" }, `Detected: ${new Date(row.detected_ts * 1000).toLocaleDateString()}`),
            ...docRows) }));
      });
    } else {
      out.appendChild(EmptyState({ glyph: "≋", title: "No duplicates detected" }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

function tbl(headers, rows) {
  const thead = h("thead", null, h("tr", null, ...headers.map(hd => h("th", null, hd))));
  const tbody = h("tbody", null, ...rows.map(row => {
    // Support both plain cell arrays (non-interactive) and row-meta objects (interactive)
    if (Array.isArray(row)) return h("tr", null, ...row.map(c => h("td", null, c)));
    const props = { class: row.selected ? "selected" : "", tabindex: "0", role: "button",
      "aria-selected": row.selected ? "true" : "false" };
    if (row.onClick) props.onClick = row.onClick;
    if (row.onKeydown) props.onKeydown = row.onKeydown;
    return h("tr", props, ...row.cells.map(c => h("td", null, c)));
  }));
  return h("div", { style: { overflowX: "auto" } }, h("table", { class: "tbl" }, thead, tbody));
}
function mono(s) { return h("code", { class: "t-mono" }, s); }
function dim(s) { return h("span", { class: "t-small muted" }, String(s)); }
function loading() {
  const w = h("div", { style: { marginTop: "16px" } });
  w.appendChild(Skeleton({ w: "100%", h: 120, r: 8 }));
  return w;
}
function err(w, e) { w.innerHTML = `<div class="t-small" style="color:var(--state-conflict)">${escHtml(e)}</div>`; }
