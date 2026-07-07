/* BOH new UI — Context Pack Builder. Read-only assembly surface.
   Uses /api/search to find candidate documents, then POST /api/context-pack/assemble.
   No DB writes; canon_eligible is always false on all outputs. */
import { h } from "../dom.js";
import { api, escHtml } from "../api.js";
import { Button, Card, Badge, EmptyState, Skeleton, AlertBanner } from "../primitives.js";

function sectionFor(doc) {
  const auth = String(doc.authority_state || doc.status || "").toLowerCase();
  const layer = String(doc.canonical_layer || "").toLowerCase();
  if (layer === "canonical" || auth === "canonical") return "canon";
  if (/conflict/.test(layer) || /conflict/.test(auth)) return "conflict";
  if (/evidence/.test(layer)) return "evidence";
  return "evidence";
}

export function ContextPackScreen() {
  let _query = "", _results = [], _selected = new Set(), _assembled = null, _searching = false, _assembling = false;
  let root;
  function rebuild() { const old = root; const n = build(); old.replaceWith(n); }

  function doSearch() {
    if (!_query.trim()) return;
    _searching = true; _results = []; _selected.clear(); _assembled = null; rebuild();
    api(`/api/search?q=${encodeURIComponent(_query)}&limit=20`).then(d => {
      _searching = false;
      _results = (d && (d.results || d.items || d.docs)) || [];
      rebuild();
    });
  }

  function toggleSelect(id) {
    if (_selected.has(id)) _selected.delete(id); else _selected.add(id);
    rebuild();
  }

  function doAssemble() {
    if (!_selected.size) return;
    _assembling = true; _assembled = null; rebuild();
    const packs = _results
      .filter(r => _selected.has(r.doc_id || r.id))
      .map(r => ({
        doc_id: r.doc_id || r.id || "",
        content: r.summary || r.content || r.title || "",
        section: sectionFor(r),
        score: typeof r.score === "number" ? r.score : 0.5,
      }));
    api("/api/context-pack/assemble", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: _query, operation: "answer_context", actor: "local_operator", mode: "exploration", candidate_packs: packs }),
    }).then(d => {
      _assembling = false;
      _assembled = (d && !d.error) ? d : null;
      if (d && d.error) _assembled = { _error: d.error };
      rebuild();
    });
  }

  function build() {
    let _qInput;
    root = h("div", { class: "content content-narrow" },
      h("div", { class: "page-head" },
        h("div", { class: "t-display" }, "Context Pack Builder"),
        h("div", { class: "sub t-small" }, "Search the corpus, select candidate documents, and assemble a governed context pack. Read-only; no writes.")),

      // Search bar
      Card({ children: h("div", { class: "col gap-3" },
        h("div", { class: "flex gap-2" },
          (_qInput = h("input", {
            class: "s-input", placeholder: "Search query…", value: _query,
            style: { flex: "1", fontFamily: "var(--font-mono)", fontSize: "13px" },
            onInput: e => { _query = e.target.value; },
            onKeydown: e => { if (e.key === "Enter") doSearch(); },
          })),
          Button({ variant: "primary", className: "sm", onClick: doSearch,
            children: [_searching ? "Searching…" : "Search"] })),
        _query && !_searching && _results.length === 0 &&
          h("div", { class: "t-small muted" }, "No results.")) }),

      // Results
      _searching && h("div", { style: { marginTop: "12px" } }, Skeleton({ w: "100%", h: 120, r: 8 })),

      _results.length > 0 && Card({ title: `${_results.length} results — select candidates`, children:
        h("div", { class: "col gap-1", style: { maxHeight: "320px", overflowY: "auto" } },
          _results.map(r => {
            const id = r.doc_id || r.id || "";
            const sel = _selected.has(id);
            return h("label", {
              class: "flex gap-2 items-start",
              style: { padding: "6px 8px", borderRadius: "6px", cursor: "pointer",
                       background: sel ? "color-mix(in oklab, var(--accent) 10%, transparent)" : "transparent" },
            },
              h("input", { type: "checkbox", checked: sel, onChange: () => toggleSelect(id),
                style: { marginTop: "3px", flexShrink: "0" } }),
              h("div", { class: "col gap-0" },
                h("span", { class: "t-body", style: { fontWeight: sel ? "600" : "400" } },
                  escHtml(r.title || r.doc_id || id)),
                h("div", { class: "flex gap-2 items-center" },
                  Badge({ ns: r.authority_state === "canonical" ? "current" : r.authority_state === "draft" ? "stale" : "unknown",
                    label: r.authority_state || "—" }),
                  h("span", { class: "t-small muted" }, escHtml(sectionFor(r))),
                  r.score != null && h("span", { class: "t-mono t-small muted" }, r.score.toFixed(2)))));
          }),
          _selected.size > 0 && h("div", { class: "flex gap-2", style: { padding: "8px", borderTop: "1px solid var(--border-default)", marginTop: "4px" } },
            Button({ variant: "governed", className: "sm", onClick: doAssemble,
              children: [_assembling ? "Assembling…" : `Assemble pack (${_selected.size} selected)`] }),
            Button({ variant: "ghost", className: "sm", onClick: () => { _selected.clear(); _assembled = null; rebuild(); },
              children: ["Clear"] }))) }),

      // Assembled result
      _assembled && (_assembled._error
        ? h("div", { class: "t-small", style: { color: "var(--state-conflict)", marginTop: "12px" } },
            `Assembly error: ${escHtml(_assembled._error)}`)
        : Card({ title: "Assembled context pack", children: h("div", { class: "col gap-3" },
            AlertBanner({ ns: "advisory", children: ["This is a read-only governed assembly. canon_eligible is always false on all outputs."] }),
            h("div", { class: "kv" },
              kvRow("Posture", _assembled.posture || "—"),
              kvRow("Sections with content", Object.entries(_assembled.sections || {}).filter(([,v]) => v?.length > 0).map(([k]) => k).join(", ") || "none"),
              kvRow("Withheld packs", String((_assembled.withheld || []).length)),
              kvRow("Blocking reasons", (_assembled.blocking_reasons || []).join("; ") || "none"),
              kvRow("Pack ID", _assembled.assembled_pack_id || _assembled.context_pack_id || "—")),
            h("details", null,
              h("summary", { class: "t-small", style: { cursor: "pointer", color: "var(--text-secondary)" } }, "Raw JSON"),
              h("pre", { class: "t-mono", style: { fontSize: "11px", overflowX: "auto", marginTop: "8px", padding: "8px", background: "var(--bg-input)", borderRadius: "6px" } },
                JSON.stringify(_assembled, null, 2).slice(0, 8000)))) })));
    return root;
  }
  return build();
}

function kvRow(k, v) { return h("div", { class: "kv-row" }, h("span", { class: "k" }, k), h("span", { class: "v" }, String(v))); }
