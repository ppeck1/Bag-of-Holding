/* BOH new UI — Library screen. Tabs: Documents · Search · PlaneCards (read-only).
   Clicking a row selects it and populates the shared Inspector panel (right side).
   No mutation controls (patch / backfill / promotion) are exposed here. */
import { h } from "../dom.js";
import { api, escHtml } from "../api.js";
import { Badge, Button, Card, Tabs, EmptyState, Skeleton } from "../primitives.js";
import { normalizePlaneKey } from "../ns.js";

let _tab = "documents";
let _page = 1, _query = "", _queryResults = null;
let _autoRun = false;  // one-shot: run a query deep-linked from the global search bar
let _lastLibraryId = "all";
const PER = 20;

function statusNs(status) {
  const s = String(status || "").toLowerCase();
  if (/conflict/.test(s)) return "conflict";
  if (/stale|draft|working/.test(s)) return "stale";
  if (/canon|stable/.test(s)) return "current";
  if (/arch|superseded/.test(s)) return "expired";
  return "unknown";
}

function libraryParam(activeLibraryId) {
  const id = activeLibraryId || "all";
  return id === "all" ? "" : `&library_id=${encodeURIComponent(id)}`;
}

// Normalize a raw /api/docs row into the shape the Inspector's selection.type==="doc" branch expects.
function normalizeDoc(d) {
  return {
    id: d.doc_id || d.id,
    title: d.title || d.path || d.doc_id || d.id,
    project: d.project || "—",
    authority: d.authority_state || d.authority || d.status || "—",
    currentness: statusNs(d.status || d.authority_state || ""),
    markers: [],
    lifecycle: d.lifecycle || d.status || "—",
    action: "",
    updated: d.updated_ts ? new Date(d.updated_ts * 1000).toLocaleDateString() : d.updated || "—",
    why: [],
  };
}

export function LibraryScreen({ onNavigate, onToast, pendingSearch, onSelectDoc, selectedId, onSelectCard, selectedCardId, visiblePlanes, activeLibrary, activeLibraryId }) {
  let root;
  function rebuild() { const old = root; const n = build(); old.replaceWith(n); }

  function build() {
    if (pendingSearch && _query !== pendingSearch) { _query = pendingSearch; _tab = "search"; _autoRun = true; }
    const libId = activeLibraryId || "all";
    if (_lastLibraryId !== libId) {
      _lastLibraryId = libId;
      _page = 1;
      _queryResults = null;
    }
    const ctx = { onNavigate, rebuild, onSelectDoc, selectedId, onSelectCard, selectedCardId, visiblePlanes, activeLibrary, activeLibraryId: libId };
    root = h("div", { class: "content content-narrow" },
      h("div", { class: "page-head" },
        h("div", { class: "t-display" }, "Library"),
        h("div", { class: "sub t-small" },
          `Browse documents, search the corpus, and inspect PlaneCards. Scope: ${activeLibrary?.name || "All libraries"}.`)),
      Tabs({ value: _tab, onChange: v => { _tab = v; rebuild(); }, tabs: [
        { value: "documents", label: "Documents" },
        { value: "search",    label: "Search" },
        { value: "cards",     label: "PlaneCards" },
      ] }),
      _tab === "documents" ? DocumentsTab(ctx) :
      _tab === "search"    ? SearchTab(ctx) :
                             CardsTab(ctx));
    return root;
  }
  return build();
}

function DocumentsTab({ onNavigate, rebuild, onSelectDoc, selectedId, activeLibraryId }) {
  const wrap = loading();
  api(`/api/docs?page=${_page}&per_page=${PER}${libraryParam(activeLibraryId)}`).then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const docs = d.docs || [];
    const total = d.total || 0;
    const pages = Math.max(1, Math.ceil(total / PER));
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } },
      h("div", { class: "flex between items-center" },
        h("span", { class: "t-small muted" }, `${total} documents`),
        h("div", { class: "flex gap-2" },
          Button({ variant: "ghost", className: "sm", disabled: _page <= 1, onClick: () => { _page--; rebuild(); }, children: ["← Prev"] }),
          h("span", { class: "t-small muted", style: { padding: "0 8px" } }, `${_page} / ${pages}`),
          Button({ variant: "ghost", className: "sm", disabled: _page >= pages, onClick: () => { _page++; rebuild(); }, children: ["Next →"] }))));
    if (docs.length) {
      out.appendChild(Card({ bodyFlush: true, children:
        tbl(["Title / Path", "Status", "Authority", "Updated"], docs.map(d => ({
          key: d.doc_id,
          selected: selectedId === d.doc_id,
          onClick: () => onSelectDoc && onSelectDoc(normalizeDoc(d)),
          onKeydown: e => { if (e.key === "Enter") onSelectDoc && onSelectDoc(normalizeDoc(d)); },
          cells: [
            h("span", { class: "doc-title" }, d.title || d.path || d.doc_id),
            Badge({ ns: statusNs(d.status), label: d.status || "—" }),
            dim(d.authority || d.status || "—"),
            dim(d.updated_ts ? new Date(d.updated_ts * 1000).toLocaleDateString() : "—")],
        })))}));
    } else {
      out.appendChild(EmptyState({ glyph: "▦", title: "No documents indexed yet",
        desc: "Use Capture & Intake to add documents.",
        actions: Button({ variant: "secondary", glyph: "+", onClick: () => onNavigate && onNavigate("intake"), children: ["Capture intake"] }) }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

function SearchTab({ rebuild, onSelectDoc, selectedId, activeLibraryId }) {
  let inputEl;
  const resultsWrap = h("div", { style: { marginTop: "16px" } });
  if (_queryResults) renderResults(resultsWrap, _queryResults, onSelectDoc, selectedId);
  const searchBar = h("div", { class: "flex gap-2 items-center", style: { marginTop: "16px" } },
    (inputEl = h("input", { type: "text", placeholder: "Search corpus, titles, summaries…", value: _query, "aria-label": "Search query",
      style: { flex: "1", background: "var(--bg-input)", border: "1px solid var(--border-default)", borderRadius: "8px", padding: "8px 12px", color: "var(--text-primary)", fontSize: "13px" },
      onKeydown: e => { if (e.key === "Enter") doSearch(e.target.value, rebuild, activeLibraryId); },
      onInput: e => { _query = e.target.value; } })),
    Button({ variant: "secondary", className: "sm", onClick: () => doSearch(inputEl.value, rebuild, activeLibraryId), children: ["Search"] }));
  if (_autoRun && _query && !_queryResults) { _autoRun = false; doSearch(_query, rebuild, activeLibraryId); }
  return h("div", null, searchBar, resultsWrap);
}

function doSearch(q, rebuild, activeLibraryId) {
  _query = q.trim();
  if (!_query) return;
  _queryResults = null;
  api(`/api/search?q=${encodeURIComponent(_query)}&limit=30${libraryParam(activeLibraryId)}`).then(d => { _queryResults = d; rebuild(); });
}

function renderResults(wrap, d, onSelectDoc, selectedId) {
  if (d.error) { err(wrap, d.error); return; }
  const res = d.results || [];
  const out = h("div", { class: "col gap-3" },
    h("div", { class: "t-small muted" }, `${res.length} results for "${escHtml(_query)}" — ${escHtml(d.score_formula || "FTS")}`));
  if (res.length) {
    out.appendChild(Card({ bodyFlush: true, children:
      tbl(["Title", "Status", "Plane", "Score"], res.map(r => ({
        key: r.doc_id,
        selected: selectedId === r.doc_id,
        onClick: () => onSelectDoc && onSelectDoc(normalizeDoc(r)),
        onKeydown: e => { if (e.key === "Enter") onSelectDoc && onSelectDoc(normalizeDoc(r)); },
        cells: [
          h("span", null,
            h("span", { class: "doc-title" }, r.title || r.path || r.doc_id),
            r.has_conflict && h("span", { class: "badge", style: { marginLeft: "6px", color: "var(--state-conflict)", background: "color-mix(in oklab, var(--state-conflict) 14%, transparent)", border: "1px solid color-mix(in oklab, var(--state-conflict) 30%, transparent)" } }, "! conflict")),
          Badge({ ns: statusNs(r.status) }),
          dim(r.plane || r.canonical_layer || "—"),
          dim(r.final_score != null ? r.final_score.toFixed(2) : "—")],
      })))}));
  } else {
    out.appendChild(EmptyState({ glyph: "⌕", title: `No results for "${escHtml(_query)}"` }));
  }
  wrap.replaceChildren(out);
}

/* PlaneCards: governed, document-level projections. Read-only here — backfill (wrapping indexed
   documents into cards) is operator-gated and intentionally NOT exposed as a mutation from /v2.
   NOTE: this is the PlaneCard list (GET /api/planes/cards), distinct from the plane SUMMARY
   endpoint (GET /api/planes). The separate Domains subject-taxonomy axis stays diagnostic-only
   (doc->domain linkage is not implemented), so there is no Domains tab. */
function CardsTab({ onSelectCard, selectedCardId, visiblePlanes, activeLibraryId }) {
  const wrap = loading();
  api(`/api/planes/cards?limit=200${libraryParam(activeLibraryId)}`).then(d => {
    if (d.error) { err(wrap, d.error); return; }
    const cards = d.cards || [];
    const total = cards.length;
    const filtered = visiblePlanes
      ? cards.filter(c => { const key = normalizePlaneKey(c.plane); return !key || visiblePlanes.includes(key); })
      : cards;
    const out = h("div", { class: "col gap-3", style: { marginTop: "16px" } });
    if (total > 0) {
      out.appendChild(h("div", { class: "flex between items-center" },
        h("span", { class: "t-small muted" },
          filtered.length === total ? `${total} PlaneCards` : `Showing ${filtered.length} of ${total} PlaneCards`)));
    }
    if (filtered.length > 0) {
      out.appendChild(Card({ bodyFlush: true, children:
        tbl(["Card ID", "Plane", "Type", "Topic", "b", "d", "m", "Valid until", "Doc"],
          filtered.map(c => ({
            key: c.id,
            selected: selectedCardId === c.id,
            onClick: () => onSelectCard && onSelectCard(c),
            onKeydown: e => { if (e.key === "Enter") onSelectCard && onSelectCard(c); },
            cells: [
              mono((c.id || "").slice(0, 24)),
              c.plane || "—",
              c.card_type || "—",
              dim((c.topic || "—").slice(0, 48)),
              c.b != null ? String(c.b) : "—",
              c.d != null ? String(c.d) : "—",
              c.m != null ? String(c.m) : "—",
              dim(c.valid_until || "—"),
              dim((c.doc_id || "—").slice(0, 36))],
          })))}));
    } else if (total > 0) {
      out.appendChild(EmptyState({
        glyph: "◈",
        title: "No PlaneCards in the visible planes",
        desc: "Adjust the Planes filter in the top bar to show cards on other planes.",
      }));
    } else {
      out.appendChild(EmptyState({
        glyph: "⊟",
        title: "No PlaneCards yet",
        desc: "PlaneCards are created when indexed documents are wrapped. Existing indexed "
            + "documents may require an operator-gated backfill.",
      }));
    }
    wrap.replaceWith(out);
  });
  return wrap;
}

/* Table helper. A row may be a plain cell array (non-interactive) OR a row-meta object
   { key, selected, onClick, onKeydown, cells } — interactive rows get tabindex/role/aria-selected. */
function tbl(headers, rows) {
  const thead = h("thead", null, h("tr", null, ...headers.map(hd => h("th", null, hd))));
  const tbody = h("tbody", null, ...rows.map(row => {
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
  const w = h("div", { style: { marginTop: "16px", display: "flex", flexDirection: "column", gap: "8px" } });
  w.appendChild(Skeleton({ w: "100%", h: 32, r: 6 }));
  w.appendChild(Skeleton({ w: "80%", h: 32, r: 6 }));
  w.appendChild(Skeleton({ w: "90%", h: 32, r: 6 }));
  return w;
}
function err(w, e) { w.innerHTML = `<div class="t-small" style="color:var(--state-conflict)">${escHtml(e)}</div>`; }
