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

export function CaptureScreen({ onToast }) {
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
      _tab === "recent"       ? RecentTab() :
      _tab === "add"          ? AddDocumentsTab(onToast, goRecent) :
      _tab === "note"         ? CaptureNoteTab(onToast, goRecent) :
      _tab === "capabilities" ? CapabilitiesTab() :
      _tab === "quarantine"   ? QuarantineTab(onToast) :
                                DuplicatesTab());
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
      h("div", { class: "t-small" }, "Allowed: .md .markdown .txt .rst .csv .json .yaml .yml .html .htm. Executables and other types are rejected."),
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

function RecentTab() {
  const wrap = loading();
  api("/api/input/recent?limit=20").then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const items = d.items || [];
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      AlertBanner({ ns: "stale", children: ["Recent items are capture-surface activity. Admission to the index requires an explicit operator action."] }),
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Recent activity"), h("span", { class: "count t-small" }, String(items.length))));
    if (items.length) {
      out.appendChild(Card({ bodyFlush: true, children:
        tbl(["Document","Actor","Detail","Time"], items.map(i => [
          mono((i.doc_id || "").slice(0, 24)),
          dim(i.actor_id || "—"),
          h("span", { class: "t-small" }, escHtml((i.detail || "").slice(0, 60))),
          dim(i.event_ts ? new Date(i.event_ts * 1000).toLocaleTimeString() : "—")])) }));
    } else {
      out.appendChild(EmptyState({ glyph: "＋", title: "No recent items", desc: "Documents added to the capture surface will appear here." }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

function CapabilitiesTab() {
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
        return [
          h("td", { title: c.source_ref || "" }, mono((c.source_ref || "").slice(-36))),
          h("td", null, Badge({ ns, label: c.lifecycle_state || "—" })),
          h("td", null, dim(c.safety_lane || "—")),
          h("td", { class: "num" }, c.preservable ? "✓" : "·"),
          h("td", { class: "num" }, c.queryable ? "✓" : "·"),
          h("td", null, dim((c.failure_reason || "").slice(0, 40))),
        ];
      });
      out.appendChild(Card({ bodyFlush: true, children:
        h("div", { style: { overflowX: "auto" } },
          h("table", { class: "tbl" },
            h("thead", null, h("tr", null, h("th", null, "Source"), h("th", { style: { width: "110px" } }, "Lifecycle"), h("th", { style: { width: "90px" } }, "Lane"), h("th", { style: { width: "60px" } }, "Preserve"), h("th", { style: { width: "60px" } }, "Query"), h("th", null, "Failure"))),
            h("tbody", null, ...rows.map(cells => h("tr", null, ...cells))))) }));
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


function QuarantineTab(onToast) {
  let _rebuild;
  const wrap = loading();
  function load() {
    api("/api/intake/quarantine?limit=100").then(d => {
      if (d.error) { err(wrap, d.error); return; }
      const items = d.items || [];
      const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
        AlertBanner({ ns: "quarantine", children: ["Quarantined files are metadata-only (never copied to RAW) and preserved as records. Hold places an item under review; Replay reprocesses held/failed items via /api/intake/replay (blocked content such as executables is not replay-eligible). Nothing is deleted."] }),
        h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Active quarantine"), h("span", { class: "count t-small" }, String(items.length))));
      if (items.length) {
        out.appendChild(Card({ bodyFlush: true, children:
          tbl(["Record","Lane","Category","Reason","Created","Actions"], items.map(q => [
            mono((q.quarantine_record_id || "").slice(0, 20)),
            h("span", { class: "badge", style: { color: q.current_safety_lane === "hold" ? "var(--state-stale)" : "var(--state-conflict)" } }, q.current_safety_lane || "quarantine"),
            h("span", { style: { color: "var(--state-conflict)" } }, escHtml(q.quarantine_category || "—")),
            h("span", { class: "t-small" }, (q.quarantine_reason || "").slice(0, 60)),
            dim(q.created_at ? new Date(q.created_at).toLocaleDateString() : "—"),
            h("div", { class: "flex gap-1" },
              Button({ variant: "containment", glyph: "⊗", className: "sm",
                onClick: () => doDisposition(q.intake_capability_id, "hold",
                  "Held for operator review via Capture & Intake.", onToast, () => load()),
                children: ["Hold"] }),
              Button({ variant: "secondary", className: "sm",
                onClick: () => doReplay(q.intake_capability_id, onToast, () => load()),
                children: ["Replay"] }))])) }));
      } else {
        out.appendChild(EmptyState({ glyph: "⚠", title: "No active quarantine items", desc: "Released items are removed from this view. Check capabilities list for history." }));
      }
      wrap.replaceWith(out);
    });
  }
  load();
  return wrap;
}

function DuplicatesTab() {
  const wrap = loading();
  api("/api/duplicates?limit=50").then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const groups = d.duplicates || [];
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      AlertBanner({ ns: "stale", children: ["Files are never deleted here. Use Copy Path or Open Location, then remove files manually outside Bag of Holding."] }),
      h("div", { class: "section-head" }, h("span", { class: "t-subheading" }, "Duplicate candidates"), h("span", { class: "count t-small" }, `${groups.length} groups`)));
    if (groups.length) {
      groups.forEach(g => {
        const docs = g.docs || g.doc_ids || [];
        out.appendChild(Card({ title: (g.term || g.reason || "similar content").slice(0, 50), children:
          h("div", { class: "col gap-2" },
            h("div", { class: "t-small muted" }, `${docs.length} candidates · ${g.conflict_type || "content-similar"}`),
            ...docs.map(doc => h("div", { class: "flex gap-2" }, mono((doc.doc_id || doc || "").slice(0, 40)), dim((doc.path || "").slice(-40))))) }));
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
  const tbody = h("tbody", null, ...rows.map(cells => h("tr", null, ...cells.map(c => h("td", null, c)))));
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
