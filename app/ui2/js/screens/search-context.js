/* BOH Search + Current Context screen.
   Keyword search uses /api/search. Current Context Brief uses the retrieval-token
   guarded /api/current-context-brief contract. Both paths are read-only. */
import { h } from "../dom.js";
import { api, getRetrievalToken, retrievalHeaders } from "../api.js";
import { AlertBanner, Badge, Button, Card, EmptyState, Segmented, Skeleton, Toggle } from "../primitives.js";

let _mode = "brief";
let _query = "";
let _keywordResults = null;
let _brief = null;
let _loading = false;
let _error = "";
let _includePromoted = false;

function libraryParam(activeLibraryId) {
  const id = activeLibraryId || "all";
  return id === "all" ? "" : `&library_id=${encodeURIComponent(id)}`;
}

function statusNs(status) {
  const s = String(status || "").toLowerCase();
  if (/conflict/.test(s)) return "conflict";
  if (/stale|draft|working/.test(s)) return "stale";
  if (/canon|stable|approved|trusted/.test(s)) return "current";
  if (/arch|superseded/.test(s)) return "expired";
  return "unknown";
}

function normalizeDoc(item) {
  return {
    id: item.doc_id || item.id,
    title: item.title || item.path || item.doc_id || item.id,
    path: item.path || null,
    project: item.project || "-",
    authority: item.authority_state || item.authority || item.status || "-",
    currentness: statusNs(item.status || item.authority_state || ""),
    markers: [],
    lifecycle: item.status || "-",
    action: "",
    updated: item.updated_ts ? new Date(item.updated_ts * 1000).toLocaleDateString() : item.updated || "-",
    why: [],
  };
}

export function SearchContextScreen({
  pendingSearch,
  onSelectDoc,
  selectedId,
  onNavigate,
  onToast,
  activeLibrary,
  activeLibraryId,
}) {
  let root;
  function rebuild() { const old = root; const n = build(); old.replaceWith(n); }

  function runKeyword() {
    const q = _query.trim();
    if (!q) return;
    _loading = true;
    _error = "";
    _keywordResults = null;
    _brief = null;
    rebuild();
    api(`/api/search?q=${encodeURIComponent(q)}&limit=30${libraryParam(activeLibraryId)}`).then((d) => {
      _loading = false;
      if (d && d.error) {
        _error = d.error;
        _keywordResults = null;
      } else {
        _keywordResults = d;
      }
      rebuild();
    });
  }

  function runBrief() {
    const q = _query.trim();
    if (!q) return;
    if (!getRetrievalToken()) {
      _error = "Retrieval token required. Set it in Settings -> Security & Advanced.";
      _brief = null;
      rebuild();
      onToast && onToast("Retrieval token required for Current Context Brief.", "stale");
      return;
    }
    _loading = true;
    _error = "";
    _keywordResults = null;
    _brief = null;
    rebuild();
    api("/api/current-context-brief", {
      method: "POST",
      headers: retrievalHeaders(),
      body: JSON.stringify({
        topic: q,
        mode: "exploration",
        limit: 8,
        include_promoted: _includePromoted,
      }),
    }).then((d) => {
      _loading = false;
      if (d && d.error) {
        _error = d.error;
        _brief = null;
      } else {
        _brief = d;
      }
      rebuild();
    });
  }

  function run() {
    if (_mode === "keyword") runKeyword();
    else runBrief();
  }

  function build() {
    if (pendingSearch && _query !== pendingSearch) {
      _query = pendingSearch;
      _mode = "brief";
      setTimeout(runBrief, 0);
    }
    let inputEl;
    const scopeName = activeLibrary?.name || "All libraries";
    root = h("div", { class: "content content-narrow", style: { minWidth: 0, maxWidth: "100%", overflowX: "hidden" } },
      h("div", { class: "page-head" },
        h("div", { class: "t-display" }, "Search"),
        h("div", { class: "sub t-small" },
          `Keyword search is scoped to ${scopeName}. Current Context Brief is retrieval-scoped.`)),
      Card({ children: h("div", { class: "col gap-3" },
        h("div", { class: "flex between items-center gap-3 wrap" },
          Segmented({ value: _mode, onChange: (v) => { _mode = v; _error = ""; _brief = null; _keywordResults = null; rebuild(); }, options: [
            { value: "brief", label: "Current Context" },
            { value: "keyword", label: "Keyword Search" },
          ] }),
          h("div", { class: "flex items-center gap-2" },
            h("span", { class: "t-small muted" }, "Promoted"),
            Toggle({ checked: _includePromoted, label: "Include promoted intake", onChange: (v) => { _includePromoted = v; rebuild(); } }))),
        h("div", { class: "flex gap-2" },
          (inputEl = h("input", {
            class: "s-input",
            placeholder: _mode === "brief" ? "Ask for current context on a topic..." : "Search titles, summaries, and chunks...",
            value: _query,
            style: { flex: "1", fontFamily: "var(--font-mono)", fontSize: "13px" },
            onInput: e => { _query = e.target.value; },
            onKeydown: e => { if (e.key === "Enter") { _query = inputEl.value; run(); } },
          })),
          Button({ variant: "primary", className: "sm", onClick: () => { _query = inputEl.value; run(); },
            children: [_loading ? "Working..." : (_mode === "brief" ? "Brief" : "Search")] })),
        _mode === "brief" && !getRetrievalToken() && AlertBanner({
          ns: "stale",
          children: ["Current Context Brief requires the read-only retrieval token."],
        }),
        _mode === "brief" && h("div", { class: "flex gap-2" },
          Button({ variant: "ghost", className: "sm", onClick: () => onNavigate && onNavigate("context-pack"), children: ["Open pack builder"] }),
          Button({ variant: "ghost", className: "sm", onClick: () => onNavigate && onNavigate("settings"), children: ["Settings"] }))) }),
      _error && h("div", { class: "t-small", style: { color: "var(--state-conflict)" } }, _error),
      _loading && h("div", null, Skeleton({ w: "100%", h: 160, r: 8 })),
      !_loading && _mode === "keyword" && _keywordResults && KeywordResults(_keywordResults, onSelectDoc, selectedId),
      !_loading && _mode === "brief" && _brief && BriefResults(_brief, onSelectDoc, selectedId),
      !_loading && !_keywordResults && !_brief && !_error && EmptyState({
        glyph: "Q",
        title: "No query yet",
        desc: "Run a keyword search or build a bounded current-context brief.",
      }));
    return root;
  }
  return build();
}

function KeywordResults(payload, onSelectDoc, selectedId) {
  const rows = payload.results || [];
  return Card({ title: `${rows.length} keyword result${rows.length === 1 ? "" : "s"}`, bodyFlush: true,
    children: rows.length ? table(["Title", "Status", "Plane", "Score"], rows.map((r) => ({
      key: r.doc_id,
      selected: selectedId === r.doc_id,
      onClick: () => onSelectDoc && onSelectDoc(normalizeDoc(r)),
      cells: [
        h("span", { class: "doc-title" }, r.title || r.path || r.doc_id),
        Badge({ ns: statusNs(r.status), label: r.status || "-" }),
        dim(r.plane || r.canonical_layer || "-"),
        dim(r.final_score != null ? r.final_score.toFixed(2) : "-"),
      ],
    }))) : EmptyState({ glyph: "0", title: "No keyword results" }) });
}

function BriefResults(brief, onSelectDoc, selectedId) {
  const best = brief.best_evidence || [];
  const newest = brief.newest_evidence || [];
  const conflicts = brief.superseded_or_conflicted || [];
  const instructions = brief.llm_instructions || {};
  const promoted = brief.promoted_visibility || {};
  const contractCard = Card({
    title: "CurrentContextBrief v0.1",
    children: h("div", { class: "col gap-3" },
      h("div", { class: "flex gap-2 wrap items-center" },
        Badge({ ns: brief.answerable_now ? "current" : "stale", label: brief.answerable_now ? "answerable" : "not answerable" }),
        Badge({ ns: promoted.visible ? "review" : "unknown",
          label: promoted.visible ? "promoted visible" : "promoted hidden" })),
      h("div", { class: "t-body", style: { overflowWrap: "anywhere" } }, brief.current_context_summary || ""),
      brief.warnings?.length ? AlertBanner({
        ns: "advisory",
        children: [h("span", { style: { overflowWrap: "anywhere" } }, brief.warnings.slice(0, 4).join(" / "))],
      }) : null,
      h("div", { class: "kv" },
        kvRow("Treat as", instructions.treat_as || "-"),
        kvRow("Do not infer", (instructions.do_not_infer || []).join(", ") || "-"),
        kvRow("Unknowns", String((brief.unknowns || []).length)),
        kvRow("Withheld", String((brief.withheld || []).length)),
        kvRow("Conflicts", String(conflicts.length))))
  });
  const conflictsCard = conflicts.length ? Card({
    title: "Conflicts / Supersession",
    children: h("div", { class: "col gap-2" }, conflicts.slice(0, 8).map((c) =>
      h("div", { class: "t-small" },
        h("span", { class: "t-mono" }, c.source || c.conflict_type || "conflict"),
        " ",
        c.term || c.reason || c.doc_id || JSON.stringify(c).slice(0, 120))))
  }) : null;
  const rawCard = Card({
    title: "Raw Contract",
    children: h("details", null,
      h("summary", { class: "t-small", style: { cursor: "pointer", color: "var(--text-secondary)" } }, "JSON"),
      h("pre", { class: "t-mono", style: { fontSize: "11px", maxWidth: "100%", overflowX: "auto", marginTop: "8px", padding: "8px", background: "var(--bg-input)", borderRadius: "6px" } },
        JSON.stringify(brief, null, 2).slice(0, 12000)))
  });
  return h("div", { class: "col gap-3" },
    contractCard,
    EvidenceCard("Best Evidence", best, onSelectDoc, selectedId),
    EvidenceCard("Newest Evidence", newest, onSelectDoc, selectedId),
    conflictsCard,
    rawCard);
}

function EvidenceCard(title, items, onSelectDoc, selectedId) {
  return Card({ title, bodyFlush: true, children: items.length
    ? table(["Title", "Authority", "Freshness", "Citation"], items.map((item) => ({
      key: `${item.doc_id}:${item.chunk_id || ""}`,
      selected: selectedId === item.doc_id,
      onClick: () => onSelectDoc && onSelectDoc(normalizeDoc(item)),
      cells: [
        h("span", null,
          h("span", { class: "doc-title" }, item.title || item.path || item.doc_id),
          item.warnings?.length ? h("span", { class: "badge", style: { marginLeft: "6px", color: "var(--state-advisory)", background: "color-mix(in oklab, var(--state-advisory) 14%, transparent)", border: "1px solid color-mix(in oklab, var(--state-advisory) 30%, transparent)" } }, item.warnings[0]) : null),
        Badge({ ns: statusNs(item.authority_state || item.status), label: item.authority_state || item.status || "-" }),
        dim(item.freshness?.age_days != null ? `${item.freshness.age_days}d` : "unknown"),
        mono(item.citation_uri || "-"),
      ],
    }))) : EmptyState({ glyph: "0", title: `No ${title.toLowerCase()}` }) });
}

function table(headers, rows) {
  const thead = h("thead", null, h("tr", null, ...headers.map((hd) => h("th", null, hd))));
  const tbody = h("tbody", null, ...rows.map((row) => {
    const props = { class: row.selected ? "selected" : "", tabindex: "0", role: "button",
      "aria-selected": row.selected ? "true" : "false" };
    if (row.onClick) props.onClick = row.onClick;
    return h("tr", props, ...row.cells.map((cell) => h("td", null, cell)));
  }));
  return h("div", { style: { maxWidth: "100%", minWidth: 0, overflowX: "auto" } },
    h("table", { class: "tbl", style: { minWidth: "720px" } }, thead, tbody));
}

function kvRow(k, v) {
  return h("div", { class: "kv-row", style: { alignItems: "flex-start" } },
    h("span", { class: "k" }, k),
    h("span", { class: "v", style: { minWidth: 0, overflowWrap: "anywhere", whiteSpace: "normal" } }, String(v)));
}

function mono(s) { return h("code", { class: "t-mono", style: { overflowWrap: "anywhere" } }, String(s)); }
function dim(s) { return h("span", { class: "t-small muted" }, String(s)); }
