/* ═══════════════════════════════════════════════════════════════
   Bag of Holding v2 — SPA Application Logic
   Phase 7: Atlas visualization, document reader, KaTeX math
   All API calls target /api/* endpoints.
   State: module-level JS variables only (no localStorage).
   Routing: window.location.hash
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BOH_VERSION = 'v2-phase12';
console.info(`%c📦 Bag of Holding ${BOH_VERSION}`, 'color:#10b981;font-weight:bold;font-size:14px');
console.info('Phase 12: Lifecycle undo/backward · Auto-index · Ingestion CTA · LLM Queue · Atlas controls · Mutation safety');

// ── Global state ──────────────────────────────────────────────
let _conflicts = [];
let _libPage = 1;
const LIB_PER_PAGE = 50;

// ── Phase 8: Drawer reader state ──────────────────────────────
let _drawerDocId   = null;
let _drawerRawText = '';
let _drawerMode    = 'rendered'; // 'rendered' | 'raw'
let _activeLibraryRoot = './library';

// ── Phase 8: Shared reader helpers ────────────────────────────

function setActiveLibraryRoot(root) {
  const normalized = (root || './library').trim() || './library';
  _activeLibraryRoot = normalized;
  try { sessionStorage.setItem('boh_active_library_root', normalized); } catch (_) {}
  const input = el('index-root');
  if (input) input.value = normalized;
  return normalized;
}

function getActiveLibraryRoot() {
  const inputVal = el('index-root')?.value?.trim();
  if (inputVal) return inputVal;
  if (_activeLibraryRoot) return _activeLibraryRoot;
  try {
    return sessionStorage.getItem('boh_active_library_root') || './library';
  } catch (_) {
    return './library';
  }
}

function withLibraryRoot(path) {
  const root = getActiveLibraryRoot();
  const sep = path.includes('?') ? '&' : '?';
  return `${path}${sep}library_root=${encodeURIComponent(root)}`;
}


/**
 * Render coordinate badges from a summary string or coord array.
 * Summary format: "dim=STATE(qX/cY mode)" from Python backend.
 */
function renderCoordBadges(coords) {
  if (!coords || !coords.length) return '';
  return coords.map(c => {
    const stateClass = c.state === 1 ? 'state-pos' : c.state === -1 ? 'state-neg' : 'state-zero';
    const staleClass = c.stale ? ' stale' : '';
    const stateStr   = c.state === 1 ? '+1' : String(c.state);
    const q = c.quality    != null ? `q${c.quality.toFixed(2)}` : '';
    const conf = c.confidence != null ? `c${c.confidence.toFixed(2)}` : '';
    const mode = c.mode || '';
    const inner = [q, conf, mode].filter(Boolean).join('/');
    return `<span class="coord-badge ${stateClass}${staleClass}" title="${escHtml(c.dimension)}">
      ${escHtml(c.dimension)}=${stateStr}${inner ? `(${inner})` : ''}
    </span>`;
  }).join('');
}

/**
 * Load markdown content + related docs for a docId.
 * Returns { rawText, related } or { error }.
 */
async function loadDocPayload(docId) {
  const [contentRes, relatedRes] = await Promise.all([
    fetch(withLibraryRoot(`/api/docs/${encodeURIComponent(docId)}/content`)),
    fetch(`/api/docs/${encodeURIComponent(docId)}/related?limit=6`),
  ]);
  const rawText = contentRes.ok ? await contentRes.text() : null;
  const relData = relatedRes.ok ? await relatedRes.json() : {};
  return { rawText, related: relData.related || [] };
}

/**
 * Render markdown content into a container element.
 * mode: 'rendered' | 'raw'
 */
function renderDocBodyInto(containerId, rawText, mode) {
  const el_ = el(containerId);
  if (!el_) return;
  if (!rawText) {
    el_.innerHTML = `<div class="text-faint font-sm" style="padding:12px">File not available on disk.</div>`;
    return;
  }
  if (mode === 'raw') {
    el_.innerHTML = `<div class="raw-view">${escHtml(rawText)}</div>`;
  } else {
    el_.innerHTML = `<div class="md-body">${renderMarkdown(rawText)}</div>`;
  }
}

/**
 * Render related doc chips into a container element.
 * clickHandler(docId) — called when a chip is clicked.
 */
function renderRelatedInto(containerId, relatedDocs, clickHandler) {
  const el_ = el(containerId);
  if (!el_ || !relatedDocs.length) return;
  el_.innerHTML = relatedDocs.map(r => {
    const fname = (r.path || '').split('/').pop().replace('.md', '');
    return `<span class="related-chip" onclick="${clickHandler}('${escHtml(r.doc_id)}')" title="${escHtml(r.path)}">
      ${escHtml(fname)} <span class="score">${r.score.toFixed(2)}</span>
    </span>`;
  }).join('');
}

// ── Utility ───────────────────────────────────────────────────
async function api(path, opts = {}) {
  try {
    const r = await fetch(path, opts);
    return r.json();
  } catch (e) {
    return { error: String(e) };
  }
}

function el(id) { return document.getElementById(id); }

function statusBadge(s) {
  const map = { canonical:'badge-canonical', draft:'badge-draft',
                working:'badge-working', archived:'badge-archived' };
  return `<span class="badge ${map[s]||'badge-draft'}">${s||'—'}</span>`;
}
function typeBadge(t) {
  return t ? `<span class="badge badge-type">${t}</span>` : '—';
}
function stateBadge(s) {
  return s ? `<span class="badge badge-state">${s}</span>` : '—';
}
function corpusBadge(c) {
  if (!c) return '';
  const map = {
    'CORPUS_CLASS:CANON':    ['badge-canonical',  'CANON'],
    'CORPUS_CLASS:DRAFT':    ['badge-draft',      'DRAFT'],
    'CORPUS_CLASS:DERIVED':  ['badge-state',      'DERIVED'],
    'CORPUS_CLASS:ARCHIVE':  ['badge-archived',   'ARCHIVE'],
    'CORPUS_CLASS:EVIDENCE': ['badge-type',       'EVIDENCE'],
  };
  const [cls, label] = map[c] || ['badge-draft', c.replace('CORPUS_CLASS:', '')];
  return `<span class="badge ${cls}" title="${escHtml(c)}">${label}</span>`;
}

function conflictBadge() {
  return `<span class="badge badge-conflict">conflict</span>`;
}

// ── Phase 9: Title + signal helpers ───────────────────────────

/** Return the best available display title for a doc object. */
function docTitle(doc) {
  if (doc.title && doc.title.trim()) return doc.title.trim();
  if (doc.path) return doc.path.split('/').pop().replace(/\.md$/, '');
  return (doc.doc_id || '').slice(0, 20);
}

/** Compact signal badges for library / card views. */
function signalBadges(doc, conflictDocIds) {
  const parts = [];
  if (conflictDocIds && conflictDocIds.has(doc.doc_id))
    parts.push(`<span class="sig-badge sig-conflict" title="Has open conflict">⚡</span>`);
  if (doc._stale)
    parts.push(`<span class="sig-badge sig-stale" title="Stale coordinates">⏱</span>`);
  if (doc._uncertain)
    parts.push(`<span class="sig-badge sig-uncertain" title="Uncertain coordinates">?</span>`);
  if (doc._highconf)
    parts.push(`<span class="sig-badge sig-highconf" title="High confidence">✓</span>`);
  return parts.join('');
}

/** Deterministic "why this matched" phrase from score breakdown. */
function matchReason(r) {
  const sb = r.score_breakdown || {};
  if (r.has_conflict) return 'Conflict-bearing result';
  if (sb.daenary_adjustment < -0.02) return 'Stale knowledge candidate';
  const uncertain = sb.daenary_adjustment > 0 && sb.canon_score_normalized < 0.3;
  if (uncertain) return 'Uncertain but high-quality document';
  if (sb.text_score > 0.7 && sb.canon_score_normalized > 0.4) return 'Strong text match · canon-aligned';
  if (sb.text_score > 0.7) return 'Strong text match';
  if (sb.canon_score_normalized > 0.5) return 'Canon-aligned';
  return '';
}

function scoreBar(val, label = '') {
  const pct = Math.round(Math.max(0, Math.min(1, val)) * 100);
  const cls = pct >= 60 ? 'good' : pct >= 30 ? '' : 'warn';
  return `
    <div class="score-bar-wrap">
      <div class="score-bar"><div class="score-bar-fill ${cls}" style="width:${pct}%"></div></div>
      <div class="score-num">${label || val.toFixed(3)}</div>
    </div>`;
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function toggleAccordion(head) {
  head.classList.toggle('open');
  const body = head.nextElementSibling;
  body.classList.toggle('open');
}

function ts(epoch) {
  if (!epoch) return '—';
  return new Date(epoch * 1000).toLocaleString();
}

function shortPath(p, max = 48) {
  if (!p) return '—';
  return p.length > max ? '…' + p.slice(-(max - 1)) : p;
}

// ── Navigation ────────────────────────────────────────────────
function nav(panelId) {
  // Deactivate all
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  // Activate target
  const panel = el(`panel-${panelId}`);
  if (panel) panel.classList.add('active');
  const navItem = document.querySelector(`[data-panel="${panelId}"]`);
  if (navItem) navItem.classList.add('active');

  window.location.hash = panelId;

  // Lazy load panel data
  if (panelId === 'dashboard')        loadDashboard();
  if (panelId === 'library')          loadLibrary();
  if (panelId === 'canon-conflicts') {
    loadConflicts();
    loadLineage();
  }
  if (panelId === 'governance')        { checkOllama(); loadPolicies(); }
  if (panelId === 'atlas' && !_graph) {
    setTimeout(initAtlas, 50); // allow CSS .active display to take effect first
  }
  if (panelId === 'status')    loadStatus();
  if (panelId === 'llm-queue') loadLlmQueue();
}

// Handle keyboard nav on nav items
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      item.click();
    }
  });
});

// ══════════════════════════════════════════════════════════════
// Panel 1: Dashboard
// ══════════════════════════════════════════════════════════════
async function loadDashboard() {
  const data = await api('/api/dashboard');
  if (data.error) return;

  el('stat-total').textContent      = data.total_docs ?? '—';
  el('stat-canonical').textContent  = data.canonical_docs ?? '—';
  el('stat-draft').textContent      = `${data.draft_docs??0} / ${data.working_docs??0}`;
  el('stat-archived').textContent   = data.archived_docs ?? '—';
  el('stat-conflicts').textContent  = data.open_conflicts ?? '—';
  el('stat-events').textContent     = data.total_events ?? '—';
  el('stat-planes').textContent     = data.indexed_planes ?? '—';
  if (el('stat-lineage')) el('stat-lineage').textContent = data.lineage_records ?? '—';
  if (el('stat-duplicates')) el('stat-duplicates').textContent = data.duplicate_links ?? '—';

  const oc = data.open_conflicts ?? 0;
  const conflictCard = el('stat-conflict-card');
  const dashAlert = el('dash-conflict-alert');
  const badge = el('conflict-badge');
  const navBadge = el('nav-conflict-badge');
  const dbStatus = el('db-status');

  conflictCard.classList.toggle('alert', oc > 0);
  dashAlert.classList.toggle('hidden', oc === 0);
  badge.classList.toggle('visible', oc > 0);
  navBadge.classList.toggle('hidden', oc === 0);
  el('conflict-badge-count').textContent = oc;
  navBadge.textContent = oc;

  dbStatus.textContent = '⬤ connected';
  dbStatus.className = 'ok';

  // Phase 12: library / auto-index status card
  const libStatus = el('dash-library-status');
  if (libStatus) {
    api('/api/autoindex/status').then(ai => {
      if (ai.error) { libStatus.textContent = 'Library status unavailable.'; return; }
      const root = ai.library_root || './library';
      const lastRun = ai.last_run_ts
        ? `Last indexed: ${new Date(ai.last_run_ts * 1000).toLocaleString()}`
        : 'Not yet indexed this session.';
      const stats = ai.last_run_ts
        ? ` · ${ai.last_indexed ?? 0} indexed, ${ai.last_skipped ?? 0} skipped`
        : '';
      libStatus.innerHTML = `<span class="text-muted">Library:</span> <code>${escHtml(root)}</code> &nbsp;·&nbsp; ${escHtml(lastRun)}${escHtml(stats)}`;
    });
    // LLM queue badge
    api('/api/llm/queue/count').then(q => {
      const pending = q.pending ?? 0;
      const badge = el('nav-llm-badge');
      if (badge) { badge.textContent = pending; badge.classList.toggle('hidden', pending === 0); }
      const hint = el('dash-unreviewed-hint');
      if (hint) hint.classList.toggle('hidden', pending === 0);
    });
  }

  // Corpus class distribution table
  const corpusDist = data.corpus_class_distribution || {};
  const corpusTotal = Object.values(corpusDist).reduce((a,b) => a+b, 0);
  el('corpus-count').textContent = `${corpusTotal} docs`;
  const corpusOrder = ['CORPUS_CLASS:CANON','CORPUS_CLASS:DRAFT','CORPUS_CLASS:DERIVED','CORPUS_CLASS:ARCHIVE','CORPUS_CLASS:EVIDENCE'];
  el('corpus-body').innerHTML = corpusOrder.map(cls => {
    const count = corpusDist[cls] || 0;
    const pct = corpusTotal ? Math.round(count / corpusTotal * 100) : 0;
    return `<tr>
      <td>${corpusBadge(cls)}</td>
      <td class="text-bright font-bold">${count}</td>
      <td>${scoreBar(pct/100)}</td>
    </tr>`;
  }).join('');

  // Recent docs
  const docs = await api('/api/docs?per_page=8');
  const tbody = el('recent-body');
  if (!docs.docs || docs.docs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty">No documents indexed yet. <button class="btn btn-ghost btn-sm" onclick="nav('import-ingest')">Index Library →</button></td></tr>`;
    return;
  }
  el('recent-count').textContent = `${docs.total} total`;
  tbody.innerHTML = docs.docs.map(d => `
    <tr class="clickable" onclick="openDrawer('${escHtml(d.doc_id)}')">
      <td class="path" title="${escHtml(d.path)}">${escHtml(shortPath(d.path))}</td>
      <td>${statusBadge(d.status)}</td>
      <td>${typeBadge(d.type)}</td>
      <td>${stateBadge(d.operator_state)}</td>
    </tr>`).join('');
}

// ══════════════════════════════════════════════════════════════
// Panel 2: Library
// ══════════════════════════════════════════════════════════════
async function loadLibrary() {
  const status = el('lib-status').value;
  const type   = el('lib-type').value;
  const state  = el('lib-state').value;

  let url = `/api/docs?page=${_libPage}&per_page=${LIB_PER_PAGE}`;
  if (status) url += `&status=${encodeURIComponent(status)}`;
  if (type)   url += `&type=${encodeURIComponent(type)}`;
  if (state)  url += `&operator_state=${encodeURIComponent(state)}`;

  el('lib-body').innerHTML = `<tr><td colspan="6" style="padding:20px;text-align:center;color:var(--text-faint)">
    <span class="spinner"></span> Loading…</td></tr>`;

  const data = await api(url);
  if (data.error) {
    el('lib-body').innerHTML = `<tr><td colspan="6" class="text-red">Error: ${escHtml(data.error)}</td></tr>`;
    return;
  }

  el('lib-count').textContent = `${data.total} total`;
  el('lib-subtitle').textContent = `${data.total} documents`;

  // Pagination controls
  const totalPages = Math.ceil(data.total / LIB_PER_PAGE) || 1;
  el('lib-page-info').textContent = `Page ${_libPage} of ${totalPages}`;
  el('lib-prev').disabled = _libPage <= 1;
  el('lib-next').disabled = _libPage >= totalPages;

  // Get conflict doc IDs for indicator
  const conflictDocIds = new Set(
    _conflicts.flatMap(c => (c.doc_ids || '').split(',').map(s => s.trim()))
  );

  if (!data.docs || data.docs.length === 0) {
    el('lib-body').innerHTML = `<tr><td colspan="6"><div class="empty">
      <div class="icon">⊞</div>No documents match the current filters.</div></td></tr>`;
    return;
  }

  el('lib-body').innerHTML = data.docs.map(d => {
    const hasConflict = conflictDocIds.has(d.doc_id);
    const title = docTitle(d);
    const summary = d.summary ? `<div class="lib-summary text-faint font-sm">${escHtml(d.summary.slice(0,100))}${d.summary.length>100?'…':''}</div>` : '';
    return `
    <tr class="clickable${hasConflict?' selected':''}" onclick="openDrawer('${escHtml(d.doc_id)}')">
      <td>
        <div class="lib-title">${escHtml(title)}</div>
        ${summary}
        <div class="lib-path text-faint font-sm" style="font-size:10px">${escHtml(shortPath(d.path, 52))}</div>
      </td>
      <td>${statusBadge(d.status)} ${hasConflict ? conflictBadge() : ''}</td>
      <td>${corpusBadge(d.corpus_class)}</td>
      <td>${typeBadge(d.type)}</td>
      <td>${stateBadge(d.operator_state)}</td>
      <td class="text-faint font-sm">${escHtml(d.version||'')}</td>
      <td><button class="btn btn-ghost btn-sm" onclick="event.stopPropagation();openDrawer('${escHtml(d.doc_id)}')">Detail →</button></td>
    </tr>`;
  }).join('');
}

function libPage(delta) {
  _libPage = Math.max(1, _libPage + delta);
  loadLibrary();
}

function clearLibFilters() {
  el('lib-status').value = '';
  el('lib-type').value = '';
  el('lib-state').value = '';
  _libPage = 1;
  loadLibrary();
}

// ── Doc drawer ────────────────────────────────────────────────
async function openDrawer(docId) {
  initDrawerResize();
  const drawer = el('doc-drawer');
  el('doc-drawer-content').innerHTML = `<div style="padding:20px;color:var(--text-faint)"><span class="spinner"></span> Loading…</div>`;
  drawer.classList.add('open');

  const data = await api(`/api/docs/${encodeURIComponent(docId)}`);
  if (data.error) {
    el('doc-drawer-content').innerHTML = `<p class="text-red">${escHtml(data.error)}</p>`;
    return;
  }

  const doc = data.doc;
  const defs = data.definitions || [];
  const evts = data.events || [];

  // Allowed next states for transition control
  const transitionMap = {
    observe:['vessel'], vessel:['constraint'], constraint:['integrate'],
    integrate:['release'], release:['constraint']
  };
  const allowed = transitionMap[doc.operator_state] || [];
  const intentOpts = ['capture','triage','define','extract','reconcile','refactor','canonize','archive']
    .map(i => `<option value="${i}">${i}</option>`).join('');

  const displayTitle = docTitle(doc);
  el('doc-drawer-content').innerHTML = `
    <div style="margin-bottom:16px">
      <div class="text-faint font-sm" style="margin-bottom:4px">Document Detail</div>
      <div class="text-bright font-bold" style="font-size:15px;margin-bottom:6px;line-height:1.3">${escHtml(displayTitle)}</div>
      ${doc.summary ? `<div class="text-muted font-sm" style="margin-bottom:8px;line-height:1.5">${escHtml(doc.summary)}</div>` : ''}
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        ${statusBadge(doc.status)} ${typeBadge(doc.type)} ${stateBadge(doc.operator_state)} ${corpusBadge(doc.corpus_class)}
      </div>
    </div>

    <div class="kv-grid" style="margin-bottom:16px">
      <div class="kv-key">Updated</div><div class="kv-val font-sm">${ts(doc.updated_ts)}</div>
      <div class="kv-key">Version</div><div class="kv-val">${escHtml(doc.version||'—')}</div>
      <div class="kv-key">Source</div><div class="kv-val">${escHtml(doc.source_type||'—')}</div>
      <div class="kv-key">Intent</div><div class="kv-val">${escHtml(doc.operator_intent||'—')}</div>
      <div class="kv-key">Topics</div><div class="kv-val font-sm">${escHtml(doc.topics_tokens||'—')}</div>
      <div class="kv-key">Plane scope</div><div class="kv-val font-sm">${escHtml(doc.plane_scope_json||'[]')}</div>
      <div class="kv-key" style="color:var(--text-faint)">Path</div>
      <div class="kv-val font-sm" style="display:flex;gap:6px;align-items:center">
        <span style="color:var(--text-faint)">${escHtml(doc.path)}</span>
        <button class="btn btn-ghost btn-sm" style="padding:1px 6px;font-size:10px" onclick="copyToClip('${escHtml(doc.path)}', this)">copy</button>
      </div>
      <div class="kv-key" style="color:var(--text-faint)">doc_id</div>
      <div class="kv-val font-sm" style="display:flex;gap:6px;align-items:center">
        <span style="color:var(--text-faint)">${escHtml(doc.doc_id)}</span>
        <button class="btn btn-ghost btn-sm" style="padding:1px 6px;font-size:10px" onclick="copyToClip('${escHtml(doc.doc_id)}', this)">copy</button>
      </div>
    </div>

    <!-- ── Phase 8: Document Viewer ── -->
    <div id="drawer-viewer-section" class="section" style="margin-bottom:12px">
      <div class="section-head">Document Viewer</div>
      <div class="section-body" style="padding:10px">
        <div id="drawer-reader-toggle">
          <button id="drawer-btn-rendered" class="active" onclick="setDrawerMode('rendered')">Rendered</button>
          <button id="drawer-btn-raw"                    onclick="setDrawerMode('raw')">Raw</button>
        </div>
        <div id="drawer-reader-related" style="margin-bottom:6px"></div>
        <div id="drawer-reader-content"><div style="color:var(--text-faint);font-size:12px"><span class="spinner"></span> Loading content…</div></div>
      </div>
    </div>

    <!-- Lineage (loaded async) -->
    <div class="accordion" style="margin-bottom:12px">
      <div class="accordion-head" onclick="loadDocLineage('${escHtml(doc.doc_id)}', this)">
        ⊞ Lineage <span class="text-faint font-sm">(click to load)</span>
        <span class="chevron">▶</span>
      </div>
      <div class="accordion-body" id="lineage-drawer-${escHtml(doc.doc_id)}">
        <span class="text-faint font-sm">Click header to load lineage.</span>
      </div>
    </div>

    <!-- Workflow transition -->
    <div class="section" style="margin-bottom:12px">
      <div class="section-head">Rubrix Lifecycle</div>
      <div class="section-body">
        <div class="state-flow" style="margin-bottom:10px">
          ${['observe','vessel','constraint','integrate','release'].map(s => {
            const isCurrent = s === doc.operator_state;
            const isAllowed = allowed.includes(s);
            return `<div class="state-node${isCurrent?' current':isAllowed?' allowed':''}"
              ${isAllowed ? `onclick="transitionDoc('${docId}','${s}')"` : ''}
              title="${isAllowed?'Click to transition':''}">
              ${s}</div>${s!=='release'?'<span class="state-arrow">→</span>':''}`;
          }).join('')}
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <span class="form-label">Transition to:</span>
          <select id="drawer-new-state" style="font-size:11px">
            ${allowed.length ? allowed.map(s=>`<option value="${s}">${s}</option>`).join('') : '<option value="">No transition available</option>'}
          </select>
          <select id="drawer-new-intent" style="font-size:11px">${intentOpts}</select>
          <button class="btn btn-amber btn-sm" onclick="submitTransition('${escHtml(docId)}')"
            ${!allowed.length?'disabled':''}>Apply →</button>
        </div>
        <div id="transition-msg-${escHtml(docId)}" class="font-sm mt-8"></div>

        <!-- Phase 12: backward / undo / history -->
        <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border-dim);display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <button class="btn btn-ghost btn-sm" onclick="showMoveBackwardModal('${escHtml(docId)}')">← Move backward</button>
          <button class="btn btn-ghost btn-sm" onclick="submitUndoLifecycle('${escHtml(docId)}')">↺ Undo last</button>
          <button class="btn btn-ghost btn-sm" onclick="toggleLifecycleHistory('${escHtml(docId)}')">⊞ History</button>
        </div>
        <div id="lifecycle-backward-form-${escHtml(docId)}" style="display:none;margin-top:8px">
          <div class="form-row" style="gap:6px">
            <input class="input" id="lc-reason-${escHtml(docId)}" placeholder="Reason for backward move (optional)" style="flex:1;font-size:11px">
            <button class="btn btn-amber btn-sm" onclick="submitMoveBackward('${escHtml(docId)}')">Confirm ←</button>
            <button class="btn btn-ghost btn-sm" onclick="el('lifecycle-backward-form-${escHtml(docId)}').style.display='none'">Cancel</button>
          </div>
        </div>
        <div id="lifecycle-history-${escHtml(docId)}" style="display:none;margin-top:8px"></div>
        <div id="lifecycle-action-msg-${escHtml(docId)}" class="font-sm" style="margin-top:4px"></div>
      </div>
    </div>

    <!-- LLM Review -->
    <div class="accordion" style="margin-bottom:12px">
      <div class="accordion-head" onclick="toggleAccordion(this)">
        ◈ Review Artifact <span class="text-faint font-sm">(non-authoritative)</span>
        <span class="chevron">▶</span>
      </div>
      <div class="accordion-body">
        <div class="alert alert-amber font-sm" style="margin-bottom:8px">
          Non-authoritative. Applying any suggestion requires explicit user action.
        </div>
        <div style="display:flex;gap:8px;margin-bottom:10px">
          <button class="btn btn-ghost btn-sm" onclick="loadReview('${escHtml(doc.path)}', '${escHtml(docId)}', false)">Load Review</button>
          <button class="btn btn-ghost btn-sm" onclick="loadReview('${escHtml(doc.path)}', '${escHtml(docId)}', true)">↻ Regenerate</button>
        </div>
        <div id="review-panel-${escHtml(docId)}"></div>
      </div>
    </div>

    <!-- Definitions -->
    ${defs.length ? `
    <div class="accordion" style="margin-bottom:12px">
      <div class="accordion-head" onclick="toggleAccordion(this)">
        Definitions (${defs.length}) <span class="chevron">▶</span>
      </div>
      <div class="accordion-body">
        ${defs.map(d => `<div style="margin-bottom:8px">
          <div class="text-bright font-sm font-bold">${escHtml(d.term)}</div>
          <div class="text-faint font-sm">${escHtml(d.block_text||'')}</div>
        </div>`).join('')}
      </div>
    </div>` : ''}

    <!-- Events -->
    ${evts.length ? `
    <div class="accordion" style="margin-bottom:12px">
      <div class="accordion-head" onclick="toggleAccordion(this)">
        Events (${evts.length}) <span class="chevron">▶</span>
      </div>
      <div class="accordion-body">
        ${evts.map(e => `<div style="margin-bottom:6px" class="font-sm">
          <span class="text-bright">${ts(e.start_ts)}</span>
          ${e.end_ts ? ` → ${ts(e.end_ts)}` : ''}
          <span class="badge badge-state" style="margin-left:6px">${escHtml(e.status||'')}</span>
        </div>`).join('')}
      </div>
    </div>` : ''}
  `;

  // Phase 8: Load document body + related docs into drawer viewer
  _drawerDocId = docId;
  // Preserve rendered/raw mode across documents for the current session
  _drawerMode  = (() => { try { return sessionStorage.getItem('boh_drawer_mode') || _drawerMode || 'rendered'; } catch(_) { return _drawerMode || 'rendered'; } })();
  loadDocPayload(docId).then(({ rawText, related }) => {
    _drawerRawText = rawText || '';
    renderDocBodyInto('drawer-reader-content', rawText, _drawerMode);
    renderRelatedInto('drawer-reader-related', related, 'openDrawer');
  });
}

function closeDrawer() {
  el('doc-drawer').classList.remove('open');
}

// ── Drawer resize ──────────────────────────────────────────────
function initDrawerResize() {
  const drawer = el('doc-drawer');
  const grip   = el('doc-drawer-resizer');
  if (!drawer || !grip || grip.dataset.bound) return;
  grip.dataset.bound = '1';

  // Restore saved width
  try {
    const saved = localStorage.getItem('boh_drawer_width');
    if (saved) drawer.style.width = saved;
  } catch (_) {}

  let dragging = false;
  grip.addEventListener('mousedown', (ev) => {
    dragging = true;
    ev.preventDefault();
    document.body.classList.add('resizing-drawer');
  });
  window.addEventListener('mousemove', (ev) => {
    if (!dragging) return;
    const w = Math.max(360, Math.min(window.innerWidth * .96, window.innerWidth - ev.clientX));
    drawer.style.width = `${Math.round(w)}px`;
    drawer.classList.remove('full');
  });
  window.addEventListener('mouseup', () => {
    if (!dragging) return;
    dragging = false;
    document.body.classList.remove('resizing-drawer');
    try { localStorage.setItem('boh_drawer_width', drawer.style.width); } catch (_) {}
  });

  // Keyboard shortcuts
  document.addEventListener('keydown', (ev) => {
    if (!drawer.classList.contains('open')) return;
    if (ev.target.tagName === 'INPUT' || ev.target.tagName === 'TEXTAREA') return;
    if (ev.key === 'Escape') closeDrawer();
    if (ev.key === ']') setDrawerWidthMode('wide');
    if (ev.key === '[') setDrawerWidthMode('narrow');
  });
}

function setDrawerWidthMode(mode) {
  const drawer = el('doc-drawer');
  if (!drawer) return;
  drawer.classList.remove('full');
  const widths = { narrow: '420px', wide: '760px', full: 'min(1100px, 96vw)' };
  const w = widths[mode] || '520px';
  if (mode === 'full') drawer.classList.add('full');
  drawer.style.width = w;
  try { localStorage.setItem('boh_drawer_width', w); } catch (_) {}
}
function setDrawerMode(mode) {
  _drawerMode = mode;
  try { sessionStorage.setItem('boh_drawer_mode', mode); } catch(_) {}
  const btnR = el('drawer-btn-rendered');
  const btnRaw = el('drawer-btn-raw');
  if (btnR) btnR.classList.toggle('active', mode === 'rendered');
  if (btnRaw) btnRaw.classList.toggle('active', mode === 'raw');
  renderDocBodyInto('drawer-reader-content', _drawerRawText, mode);
}

async function submitTransition(docId) {
  const newState  = el('drawer-new-state').value;
  const newIntent = el('drawer-new-intent').value;
  const msgEl = el(`transition-msg-${docId}`);

  if (!newState) { msgEl.innerHTML = `<span class="text-amber">No valid transition available.</span>`; return; }

  msgEl.innerHTML = `<span class="spinner"></span>`;
  const r = await api(`/api/workflow/${encodeURIComponent(docId)}`, {
    method: 'PATCH',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ operator_state: newState, operator_intent: newIntent }),
  });

  if (r.success) {
    msgEl.innerHTML = `<span class="text-green">✓ Transitioned: ${escHtml(r.previous_state)} → ${escHtml(r.new_state)}</span>`;
    setTimeout(() => { openDrawer(docId); }, 800);
  } else {
    msgEl.innerHTML = `<span class="text-red">✗ ${escHtml(JSON.stringify(r.detail||r))}</span>`;
  }
}

async function transitionDoc(docId, toState) {
  el('drawer-new-state').value = toState;
  submitTransition(docId);
}

async function loadReview(docPath, docId, forceRegenerate = false) {
  const panelId = `review-panel-${docId}`;
  const panel = el(panelId);
  if (!panel) return;

  panel.innerHTML = `<div style="padding:8px;color:var(--text-faint)"><span class="spinner"></span> ${forceRegenerate ? 'Regenerating…' : 'Loading…'}</div>`;

  const url = forceRegenerate
    ? withLibraryRoot(`/api/review/${encodeURIComponent(docPath)}/regenerate`)
    : withLibraryRoot(`/api/review/${encodeURIComponent(docPath)}`);
  const method = forceRegenerate ? 'POST' : 'GET';

  const r = await api(url, { method });
  if (r.error) {
    panel.innerHTML = `<div class="text-red font-sm">${escHtml(r.error)}</div>`;
    return;
  }

  const statusLabel = {
    existing:    `<span class="sig-badge sig-highconf">existing</span>`,
    generated:   `<span class="sig-badge sig-uncertain">freshly generated</span>`,
    regenerated: `<span class="sig-badge sig-stale">regenerated</span>`,
  }[r._status] || '';

  const genTime = r.generated_at ? ts(r.generated_at) : '—';

  // Suspected conflicts — now have title+path
  const conflictRows = (r.suspected_conflicts || []).map(sc => {
    const targets = (sc.conflict_with || []).map(t => {
      const label = typeof t === 'object' ? (t.title || t.doc_id) : t;
      const path  = typeof t === 'object' ? (t.path || '') : '';
      return `<span class="text-red" title="${escHtml(path)}">${escHtml(label)}</span>`;
    }).join(', ');
    return `<div class="font-sm" style="margin-bottom:4px"><span class="text-bright">${escHtml(sc.term)}</span> → ${targets}</div>`;
  }).join('');

  // Placement suggestion
  const ps = r.placement_suggestion || {};
  const placementReasoning = (ps.reasoning || []).map(l => `<div class="font-sm text-faint">• ${escHtml(l)}</div>`).join('');

  // Recommended patch
  const patchBlock = r.recommended_metadata_patch && Object.keys(r.recommended_metadata_patch).length
    ? `<div class="mt-8">
        <div class="text-amber font-sm font-bold" style="margin-bottom:4px">Suggested patch (requires explicit confirmation):</div>
        <pre style="font-size:11px">${escHtml(JSON.stringify(r.recommended_metadata_patch, null, 2))}</pre>
       </div>`
    : '';

  // Raw JSON accordion
  const rawId = `review-raw-${docId}`;

  panel.innerHTML = `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
      ${statusLabel}
      <span class="text-faint font-sm">${escHtml(r.reviewer || '')} · ${genTime}</span>
    </div>

    <div class="kv-grid font-sm" style="margin-bottom:10px">
      <div class="kv-key">Document</div>
      <div class="kv-val">${escHtml(r.doc_title || r.doc_path || '—')}</div>
      <div class="kv-key">Non-authoritative</div>
      <div class="kv-val text-amber font-bold">always true</div>
      <div class="kv-key">Requires confirmation</div>
      <div class="kv-val text-amber font-bold">always true</div>
      <div class="kv-key">Norm. hash</div>
      <div class="kv-val font-sm" style="word-break:break-all">${escHtml((r.normalization_output_hash||'').slice(0,24))}…</div>
    </div>

    <div class="accordion" style="margin-bottom:6px">
      <div class="accordion-head" onclick="toggleAccordion(this)">
        Topics (${(r.extracted_topics||[]).length}) <span class="chevron">▶</span>
      </div>
      <div class="accordion-body font-sm">
        ${(r.extracted_topics||[]).length ? escHtml((r.extracted_topics||[]).join(' · ')) : '<span class="text-faint">none found</span>'}
      </div>
    </div>

    <div class="accordion" style="margin-bottom:6px">
      <div class="accordion-head" onclick="toggleAccordion(this)">
        Definitions (${(r.extracted_definitions||[]).length}) <span class="chevron">▶</span>
      </div>
      <div class="accordion-body font-sm">
        ${(r.extracted_definitions||[]).length
          ? (r.extracted_definitions||[]).map(d => `<div><span class="text-bright">${escHtml(d.term)}</span></div>`).join('')
          : '<span class="text-faint">none found</span>'}
      </div>
    </div>

    <div class="accordion" style="margin-bottom:6px">
      <div class="accordion-head" onclick="toggleAccordion(this)">
        Suspected Conflicts (${(r.suspected_conflicts||[]).length})
        ${(r.suspected_conflicts||[]).length ? '<span class="badge badge-conflict" style="margin-left:6px">!</span>' : ''}
        <span class="chevron">▶</span>
      </div>
      <div class="accordion-body">
        ${conflictRows || '<span class="text-faint font-sm">none</span>'}
      </div>
    </div>

    <div class="accordion" style="margin-bottom:6px">
      <div class="accordion-head" onclick="toggleAccordion(this)">
        Placement Suggestion <span class="chevron">▶</span>
      </div>
      <div class="accordion-body">
        <div class="text-bright font-sm font-bold" style="margin-bottom:4px">${escHtml(ps.recommended_folder||'—')}</div>
        ${placementReasoning}
      </div>
    </div>

    ${patchBlock}

    <div class="accordion mt-8">
      <div class="accordion-head" onclick="toggleAccordion(this)">
        Raw JSON <span class="text-faint font-sm">(debug)</span> <span class="chevron">▶</span>
      </div>
      <div class="accordion-body">
        <pre id="${rawId}" style="font-size:10px;max-height:240px;overflow:auto">${escHtml(JSON.stringify(r, null, 2))}</pre>
      </div>
    </div>
  `;
}

function copyToClip(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    const orig = btn.textContent;
    btn.textContent = '✓ copied';
    btn.classList.add('text-green');
    setTimeout(() => { btn.textContent = orig; btn.classList.remove('text-green'); }, 1500);
  }).catch(() => {});
}

// ══════════════════════════════════════════════════════════════
// Panel 3: Search
// ══════════════════════════════════════════════════════════════
async function doSearch() {
  const q     = el('search-q').value.trim();
  const plane = el('search-plane').value.trim();
  const limit = el('search-limit').value;

  if (!q) return;

  el('search-results').innerHTML = `<div style="padding:20px;text-align:center"><span class="spinner"></span> Searching…</div>`;

  let url = `/api/search?q=${encodeURIComponent(q)}&limit=${limit}`;
  if (plane) url += `&plane=${encodeURIComponent(plane)}`;

  // Phase 8: collect Daenary filter params
  const dim     = el('sf-dimension')?.value.trim();
  const stateV  = el('sf-state')?.value;
  const minQ    = el('sf-min-quality')?.value;
  const minC    = el('sf-min-conf')?.value;
  const uncertain = el('sf-uncertain')?.checked;
  const stale   = el('sf-stale')?.checked;
  const conflicts = el('sf-conflicts')?.checked;

  if (dim)      url += `&dimension=${encodeURIComponent(dim)}`;
  if (stateV)   url += `&state=${encodeURIComponent(stateV)}`;
  if (minQ)     url += `&min_quality=${encodeURIComponent(minQ)}`;
  if (minC)     url += `&min_confidence=${encodeURIComponent(minC)}`;
  if (uncertain) url += `&uncertain_only=true`;
  if (stale)    url += `&stale=true`;
  if (conflicts) url += `&conflicts_only=true`;

  saveDaenaryFilters();

  const data = await api(url);

  if (data.error) {
    el('search-results').innerHTML = `<div class="text-red" style="padding:12px">${escHtml(data.error)}</div>`;
    return;
  }

  const results = data.results || [];
  el('search-count').textContent = `${results.length} result(s)`;

  if (results.length === 0) {
    el('search-results').innerHTML = `<div class="empty"><div class="icon">⌕</div>No results for "${escHtml(q)}"</div>`;
    return;
  }

  el('search-results').innerHTML = results.map(r => {
    const sb = r.score_breakdown || {};
    const scoreClass = r.final_score >= 0.6 ? 'good' : r.final_score >= 0.3 ? '' : 'warn';
    const id = `breakdown-${escHtml(r.doc_id).replace(/\W/g,'_')}`;
    const title = r.title || r.path.split('/').pop().replace(/\.md$/, '');
    const reason = matchReason(r);
    const daenaryRow = r.daenary_summary
      ? `<div class="daenary-summary">◈ ${escHtml(r.daenary_summary)}</div>`
      : '';
    const summaryRow = r.summary
      ? `<div class="text-muted font-sm" style="margin-bottom:4px;line-height:1.4">${escHtml(r.summary.slice(0,160))}${r.summary.length>160?'…':''}</div>`
      : '';
    return `
    <div class="result-card">
      <div class="result-card-head">
        <div class="result-title">${escHtml(title)}</div>
        ${statusBadge(r.status)} ${typeBadge(r.type)}
        ${r.has_conflict ? conflictBadge() : ''}
      </div>
      ${summaryRow}
      <div class="result-path">${escHtml(r.path)}</div>
      ${reason ? `<div class="match-reason font-sm text-faint" style="margin-bottom:4px">↳ ${escHtml(reason)}</div>` : ''}
      ${daenaryRow}
      <div class="score-bar-wrap" style="margin-bottom:8px">
        <div class="score-bar" style="flex:1">
          <div class="score-bar-fill ${scoreClass}" style="width:${Math.round(Math.max(0,r.final_score)*100)}%"></div>
        </div>
        <div class="score-num font-bold ${scoreClass==='good'?'text-green':scoreClass==='warn'?'text-amber':''}">${r.final_score.toFixed(4)}</div>
        <button class="btn btn-ghost btn-sm" onclick="toggleEl('${id}')">breakdown</button>
        <button class="btn btn-ghost btn-sm" onclick="openDrawer('${escHtml(r.doc_id)}')">detail →</button>
      </div>
      <div id="${id}" class="hidden">
        <div class="kv-grid font-sm" style="padding:8px;background:var(--bg-base);border-radius:4px">
          <div class="kv-key">text</div>
          <div class="kv-val">${scoreBar(sb.text_score||0)} × ${sb.text_weight||0.6}</div>
          <div class="kv-key">canon</div>
          <div class="kv-val">${scoreBar(sb.canon_score_normalized||0)} × ${sb.canon_weight||0.2} (raw: ${sb.canon_score_raw||0})</div>
          <div class="kv-key">planar</div>
          <div class="kv-val">${scoreBar(sb.planar_alignment_score||0)} × ${sb.planar_weight||0.2}</div>
          <div class="kv-key">conflict penalty</div>
          <div class="kv-val ${sb.conflict_penalty<0?'text-red':''}">${sb.conflict_penalty||0}</div>
          ${sb.daenary_adjustment !== undefined ? `
          <div class="kv-key">daenary adj.</div>
          <div class="kv-val ${sb.daenary_adjustment>0?'text-green':sb.daenary_adjustment<0?'text-red':''}">${(sb.daenary_adjustment||0).toFixed(4)}</div>` : ''}
        </div>
      </div>
    </div>`;
  }).join('');
}

function toggleEl(id) {
  const e = el(id);
  if (e) e.classList.toggle('hidden');
}

// ── Phase 9: Interaction polish ───────────────────────────────

/** Persist Daenary search filter values to localStorage. */
function saveDaenaryFilters() {
  try {
    const vals = {
      dim:       el('sf-dimension')?.value || '',
      state:     el('sf-state')?.value     || '',
      minQ:      el('sf-min-quality')?.value || '',
      minC:      el('sf-min-conf')?.value   || '',
      uncertain: el('sf-uncertain')?.checked || false,
      stale:     el('sf-stale')?.checked    || false,
      conflicts: el('sf-conflicts')?.checked || false,
    };
    localStorage.setItem('boh_daenary_filters', JSON.stringify(vals));
  } catch(_) {}
}

/** Restore persisted Daenary filter values on load. */
function restoreDaenaryFilters() {
  try {
    const raw = localStorage.getItem('boh_daenary_filters');
    if (!raw) return;
    const vals = JSON.parse(raw);
    if (el('sf-dimension'))   el('sf-dimension').value   = vals.dim   || '';
    if (el('sf-state'))       el('sf-state').value       = vals.state || '';
    if (el('sf-min-quality')) el('sf-min-quality').value = vals.minQ  || '';
    if (el('sf-min-conf'))    el('sf-min-conf').value    = vals.minC  || '';
    if (el('sf-uncertain'))   el('sf-uncertain').checked = vals.uncertain || false;
    if (el('sf-stale'))       el('sf-stale').checked     = vals.stale     || false;
    if (el('sf-conflicts'))   el('sf-conflicts').checked = vals.conflicts  || false;
  } catch(_) {}
}

/** Clear all Daenary filter inputs and remove from localStorage. */
function clearDaenaryFilters() {
  ['sf-dimension','sf-state','sf-min-quality','sf-min-conf'].forEach(id => {
    if (el(id)) el(id).value = '';
  });
  ['sf-uncertain','sf-stale','sf-conflicts'].forEach(id => {
    if (el(id)) el(id).checked = false;
  });
  try { localStorage.removeItem('boh_daenary_filters'); } catch(_) {}
}

// ══════════════════════════════════════════════════════════════
// Panel 4: Canon & Conflicts
// ══════════════════════════════════════════════════════════════
async function doCanon() {
  const topic = el('canon-topic').value.trim();
  const plane = el('canon-plane').value.trim();

  el('canon-result').innerHTML = `<div style="padding:12px;text-align:center"><span class="spinner"></span></div>`;

  let url = '/api/canon';
  const params = [];
  if (topic) params.push(`topic=${encodeURIComponent(topic)}`);
  if (plane) params.push(`plane=${encodeURIComponent(plane)}`);
  if (params.length) url += '?' + params.join('&');

  const data = await api(url);
  if (data.error) {
    el('canon-result').innerHTML = `<div class="text-red font-sm">${escHtml(data.error)}</div>`;
    return;
  }

  const winner = data.winner;
  let html = '';

  if (winner) {
    const doc = winner.doc || {};
    html += `
    <div class="winner-card">
      <div class="winner-label">◈ Canon Winner</div>
      <div class="winner-path">${escHtml(doc.path || '—')}</div>
      <div class="winner-score">Score: <strong>${winner.score?.toFixed(2)||'—'}</strong>
        &nbsp;·&nbsp; ${statusBadge(doc.status)} ${typeBadge(doc.type)}
      </div>
      <button class="btn btn-ghost btn-sm mt-8" onclick="openDrawer('${escHtml(doc.doc_id)}')">
        Open Document →
      </button>
    </div>`;
  } else {
    html += `<div class="alert alert-blue">No canonical document found for this query.</div>`;
  }

  if (data.ambiguity_conflicts?.length) {
    html += `<div class="alert alert-amber">⚠ Ambiguity detected — top candidates within 5% threshold. Collision recorded.</div>`;
  }

  if (data.candidates?.length > 1) {
    html += `<div class="section mt-8">
      <div class="section-head">All Candidates (${data.candidates.length})</div>
      <div class="section-body" style="padding:0">
      <table><thead><tr><th>Path</th><th>Score</th></tr></thead><tbody>
      ${data.candidates.map((c,i) => `<tr class="${i===0?'selected':''}" onclick="openDrawer('${escHtml(c.doc_id)}')">
        <td class="path" title="${escHtml(c.path)}">${escHtml(shortPath(c.path))}</td>
        <td>${scoreBar(Math.min(1,c.score/200), c.score?.toFixed(1)||'')}</td>
      </tr>`).join('')}
      </tbody></table></div></div>`;
  }

  // Score formula
  html += `<div class="accordion mt-8">
    <div class="accordion-head" onclick="toggleAccordion(this)">Score formula <span class="chevron">▶</span></div>
    <div class="accordion-body">
      <div class="kv-grid font-sm">
        ${Object.entries(data.score_formula||{}).map(([k,v]) =>
          `<div class="kv-key">${escHtml(k)}</div><div class="kv-val text-blue">${escHtml(v)}</div>`
        ).join('')}
      </div>
    </div>
  </div>`;

  el('canon-result').innerHTML = html;
}

async function loadConflicts() {
  const data = await api('/api/conflicts');
  _conflicts = data.conflicts || [];
  el('conflicts-count').textContent = `${_conflicts.length} total`;
  renderConflicts();
}

function renderConflicts() {
  const filter = el('conflict-filter').value;
  let visible = _conflicts;

  if (filter === 'open')        visible = _conflicts.filter(c => !c.acknowledged);
  else if (filter === 'acknowledged') visible = _conflicts.filter(c => c.acknowledged);
  else if (filter !== 'all')    visible = _conflicts.filter(c => c.conflict_type === filter);

  const container = el('conflicts-list');

  if (!visible.length) {
    const msg = filter === 'open' ? '✓ No open conflicts.' : 'No conflicts match this filter.';
    container.innerHTML = `<div class="empty"><div class="icon">${filter==='open'?'✓':'⚠'}</div>${msg}</div>`;
    return;
  }

  const typeCls = { definition_conflict:'badge-state', canon_collision:'badge-type', planar_conflict:'badge-conflict' };
  container.innerHTML = visible.map(c => `
    <div class="conflict-card ${c.acknowledged?'ack':''}">
      <div class="conflict-card-head">
        <span class="badge ${typeCls[c.conflict_type]||'badge-draft'}">${escHtml(c.conflict_type)}</span>
        ${c.acknowledged ? '<span class="badge badge-draft">acknowledged</span>' : ''}
        <span class="text-faint font-sm ml-auto">${ts(c.detected_ts)}</span>
      </div>
      <div class="conflict-card-body">
        ${c.term ? `<div><span class="text-muted">term:</span> <strong>${escHtml(c.term)}</strong></div>` : ''}
        ${c.plane_path ? `<div><span class="text-muted">plane:</span> ${escHtml(c.plane_path)}</div>` : ''}
        <div><span class="text-muted">docs:</span> <span class="font-sm">${escHtml(c.doc_ids||'—')}</span></div>
      </div>
      ${!c.acknowledged ? `<div style="margin-top:8px">
        <button class="btn btn-ghost btn-sm" onclick="acknowledgeConflict(${c.rowid}, this)">
          Acknowledge (does not resolve)
        </button>
      </div>` : ''}
    </div>`).join('');
}

async function acknowledgeConflict(rowid, btn) {
  btn.disabled = true;
  btn.textContent = '…';
  const r = await api(`/api/conflicts/${rowid}/acknowledge`, { method: 'PATCH' });
  if (r.acknowledged) {
    await loadConflicts();
    // Refresh topbar badge
    const dbData = await api('/api/dashboard');
    const oc = dbData.open_conflicts ?? 0;
    el('conflict-badge-count').textContent = oc;
    el('nav-conflict-badge').textContent = oc;
    el('conflict-badge').classList.toggle('visible', oc > 0);
    el('nav-conflict-badge').classList.toggle('hidden', oc === 0);
  } else {
    btn.textContent = 'Error';
    btn.classList.add('text-red');
  }
}

// ══════════════════════════════════════════════════════════════
// Panel 5: Import / Ingest
// ══════════════════════════════════════════════════════════════
async function doIndex() {
  const root = setActiveLibraryRoot(el('index-root').value.trim() || './library');
  const btn = el('index-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Indexing…';
  el('index-result').innerHTML = '';

  const data = await api('/api/index', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ library_root: root }),
  });

  btn.disabled = false;
  btn.textContent = 'Index Library';

  if (data.error) {
    el('index-result').innerHTML = `<div class="alert alert-red">${escHtml(data.error)}</div>`;
    return;
  }

  const results = data.results || [];
  const withErrors = results.filter(r => r.lint_errors?.length > 0);

  let html = `
    <div class="kv-grid font-sm" style="margin-bottom:12px;padding:12px;background:var(--bg-base);border-radius:4px;border:1px solid var(--border-dim)">
      <div class="kv-key">Total files</div><div class="kv-val text-bright">${data.total_files}</div>
      <div class="kv-key">Indexed</div><div class="kv-val text-green">${data.indexed}</div>
      <div class="kv-key">With lint errors</div><div class="kv-val ${data.files_with_lint_errors>0?'text-amber':''}">${data.files_with_lint_errors}</div>
      <div class="kv-key">Conflicts detected</div><div class="kv-val ${data.conflicts_detected>0?'text-red':''}">${data.conflicts_detected}</div>
    </div>`;

  if (withErrors.length > 0) {
    html += `<div class="accordion">
      <div class="accordion-head" onclick="toggleAccordion(this)">
        ⚠ Lint errors (${withErrors.length} file(s)) <span class="chevron">▶</span>
      </div>
      <div class="accordion-body">
        ${withErrors.map(r => `
          <div style="margin-bottom:10px">
            <div class="text-muted font-sm" style="margin-bottom:4px">${escHtml(r.path||'unknown')}</div>
            ${(r.lint_errors||[]).map(e => `<div class="lint-error">${escHtml(e)}</div>`).join('')}
          </div>`).join('')}
      </div>
    </div>`;
  }

  if (data.conflicts_detected > 0) {
    html += `<div class="alert alert-amber mt-8">
      ⚠ ${data.conflicts_detected} conflict(s) detected.
      <button class="btn btn-ghost btn-sm ml-auto" onclick="nav('canon-conflicts')">Review →</button>
    </div>`;
  }

  el('index-result').innerHTML = html;

  // Refresh dashboard badge
  const dash = await api('/api/dashboard');
  const oc = dash.open_conflicts ?? 0;
  el('conflict-badge-count').textContent = oc;
  el('nav-conflict-badge').textContent = oc;
  el('conflict-badge').classList.toggle('visible', oc > 0);
  el('nav-conflict-badge').classList.toggle('hidden', oc === 0);
}

async function doIngestSnapshot() {
  const path = el('snap-path').value.trim();
  if (!path) { el('snap-result').innerHTML = `<div class="alert alert-amber">Please enter a file path.</div>`; return; }

  const btn = el('snap-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Ingesting…';
  el('snap-result').innerHTML = '';

  const data = await api('/api/ingest/snapshot', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ path }),
  });

  btn.disabled = false;
  btn.textContent = 'Ingest Snapshot';

  if (data.error) {
    el('snap-result').innerHTML = `<div class="alert alert-red">${escHtml(data.error)}</div>`;
    return;
  }

  const skipped = data.skipped || [];
  const canonGuarded = skipped.filter(s => s.reason === 'would_overwrite_canon');

  el('snap-result').innerHTML = `
    <div class="kv-grid font-sm" style="padding:12px;background:var(--bg-base);border-radius:4px;border:1px solid var(--border-dim);margin-bottom:8px">
      <div class="kv-key">run_id</div><div class="kv-val">${escHtml(data.run_id||'—')}</div>
      <div class="kv-key">docs inserted</div><div class="kv-val text-green">${data.inserted_docs}</div>
      <div class="kv-key">defs inserted</div><div class="kv-val">${data.inserted_defs}</div>
      <div class="kv-key">events inserted</div><div class="kv-val">${data.inserted_events}</div>
      <div class="kv-key">skipped entries</div><div class="kv-val ${skipped.length?'text-amber':''}">${skipped.length}</div>
      ${canonGuarded.length ? `<div class="kv-key">canon protected</div><div class="kv-val text-amber">${canonGuarded.length} (not overwritten)</div>` : ''}
    </div>
    ${canonGuarded.length ? `<div class="alert alert-amber">◈ Canon guard: ${canonGuarded.length} document(s) skipped to protect existing canonical records.</div>` : ''}
    ${skipped.length && !canonGuarded.length ? `<div class="alert alert-blue">${skipped.length} entries skipped (missing meta).</div>` : ''}`;
}

// ══════════════════════════════════════════════════════════════
// Bootstrap
// ══════════════════════════════════════════════════════════════
async function boot() {
  // Restore panel from hash
  const hash = window.location.hash.replace('#', '') || 'dashboard';
  nav(hash);

  // Load conflicts into global state for Library conflict indicators
  const confData = await api('/api/conflicts');
  _conflicts = confData.conflicts || [];
}

window.addEventListener('hashchange', () => {
  const hash = window.location.hash.replace('#', '') || 'dashboard';
  nav(hash);
});

boot();

// ══════════════════════════════════════════════════════════════
// Phase 6 additions
// ══════════════════════════════════════════════════════════════

// ── Lineage panel (Canon & Conflicts) ─────────────────────────
async function loadLineage() {
  const filter = el('lineage-filter')?.value || '';
  let url = '/api/lineage?limit=200';
  if (filter) url += `&relationship=${encodeURIComponent(filter)}`;

  el('lineage-body').innerHTML = `<tr><td colspan="5" style="padding:16px;text-align:center"><span class="spinner"></span></td></tr>`;

  const data = await api(url);
  if (data.error) {
    el('lineage-body').innerHTML = `<tr><td colspan="5" class="text-red">${escHtml(data.error)}</td></tr>`;
    return;
  }

  el('lineage-count').textContent = `${data.count} records`;

  const rows = data.lineage || [];
  if (!rows.length) {
    el('lineage-body').innerHTML = `<tr><td colspan="5"><div class="empty"><div class="icon">⊞</div>No lineage records${filter ? ' for this type' : ''}.</div></td></tr>`;
    return;
  }

  const relCls = {
    duplicate_content: 'badge-conflict',
    supersedes: 'badge-canonical',
    derived_from: 'badge-state',
    snapshot_source: 'badge-type',
  };

  el('lineage-body').innerHTML = rows.map(r => `
    <tr class="clickable" onclick="openDrawer('${escHtml(r.doc_id)}')">
      <td class="path truncate" style="max-width:160px" title="${escHtml(r.doc_id)}">${escHtml(r.doc_id.slice(0,16))}…</td>
      <td><span class="badge ${relCls[r.relationship]||'badge-draft'}">${escHtml(r.relationship)}</span></td>
      <td class="path truncate" style="max-width:160px" title="${escHtml(r.related_doc_id)}">${escHtml(r.related_doc_id.slice(0,16))}…</td>
      <td class="text-faint font-sm">${escHtml(r.detail||'')}</td>
      <td class="text-faint font-sm">${ts(r.detected_ts)}</td>
    </tr>`).join('');
}

// ── Lineage in doc drawer ──────────────────────────────────────
async function loadDocLineage(docId, head) {
  head.classList.toggle('open');
  const body = el(`lineage-drawer-${docId}`);
  if (!body) return;
  body.classList.toggle('open');

  if (!body.classList.contains('open')) return;
  body.innerHTML = `<span class="spinner"></span>`;

  const data = await api(`/api/lineage/${encodeURIComponent(docId)}`);
  if (data.error) { body.innerHTML = `<span class="text-red">${escHtml(data.error)}</span>`; return; }

  const total = data.total || 0;
  if (!total) { body.innerHTML = `<span class="text-faint font-sm">No lineage records for this document.</span>`; return; }

  const relCls = { duplicate_content:'badge-conflict', supersedes:'badge-canonical', derived_from:'badge-state', snapshot_source:'badge-type' };

  const renderRows = (arr, dir) => arr.map(r => `
    <div style="padding:4px 0;border-bottom:1px solid var(--border-dim)" class="font-sm">
      <span class="badge ${relCls[r.relationship]||'badge-draft'}">${escHtml(r.relationship)}</span>
      <span class="text-muted" style="margin-left:6px">${dir === 'out' ? '→' : '←'}</span>
      <span class="text-bright" style="margin-left:4px">${escHtml((dir==='out'?r.related_doc_id:r.doc_id).slice(0,20))}…</span>
      ${r.detail ? `<span class="text-faint" style="margin-left:8px">${escHtml(r.detail)}</span>` : ''}
    </div>`).join('');

  body.innerHTML = `
    ${data.outbound?.length ? `<div class="text-faint font-sm" style="margin-bottom:4px">Outbound (this doc links to)</div>${renderRows(data.outbound,'out')}` : ''}
    ${data.inbound?.length  ? `<div class="text-faint font-sm" style="margin:8px 0 4px">Inbound (links to this doc)</div>${renderRows(data.inbound,'in')}` : ''}`;
}

// ── Migration report (Import/Ingest) ──────────────────────────
async function doMigrationReport() {
  const outputPath = el('report-path')?.value.trim() || 'docs/migration_report.md';
  const btn = el('report-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Generating…';
  el('report-result').innerHTML = '';

  const data = await api(`/api/corpus/migration-report?output_path=${encodeURIComponent(outputPath)}`, {method:'POST'});

  btn.disabled = false;
  btn.textContent = 'Generate Report';

  if (data.error) {
    el('report-result').innerHTML = `<div class="alert alert-red">${escHtml(data.error)}</div>`;
    return;
  }

  const invPass = data.invariants_passed;
  el('report-result').innerHTML = `
    <div class="kv-grid font-sm" style="padding:12px;background:var(--bg-base);border-radius:4px;border:1px solid var(--border-dim);margin-bottom:8px">
      <div class="kv-key">Output</div><div class="kv-val text-bright">${escHtml(data.output_path||outputPath)}</div>
      <div class="kv-key">Total docs</div><div class="kv-val">${data.total_docs}</div>
      <div class="kv-key">Open conflicts</div><div class="kv-val ${data.open_conflicts>0?'text-red':''}">${data.open_conflicts}</div>
      <div class="kv-key">Lineage records</div><div class="kv-val">${data.lineage_records}</div>
      <div class="kv-key">Invariants</div><div class="kv-val ${invPass?'text-green':'text-red'}">${invPass?'✓ All passed':'✗ Some failed'}</div>
    </div>
    ${data.invariant_results?.length ? `
    <div class="accordion">
      <div class="accordion-head" onclick="toggleAccordion(this)">Invariant details <span class="chevron">▶</span></div>
      <div class="accordion-body">
        ${data.invariant_results.map(r=>`<div class="font-sm" style="padding:3px 0">
          <span class="${r.passed?'text-green':'text-red'}">${r.passed?'✓':'✗'}</span>
          <span class="text-muted" style="margin-left:6px">${escHtml(r.check)}</span>
        </div>`).join('')}
      </div>
    </div>` : ''}
    <div class="alert alert-blue mt-8 font-sm">Report written to <code>${escHtml(data.output_path||outputPath)}</code></div>`;
}

// ══════════════════════════════════════════════════════════════
// Phase 7 — Knowledge Atlas: Force Graph + Document Reader
// ══════════════════════════════════════════════════════════════

// ── Global state ──────────────────────────────────────────────
let _graph = null;          // ForceGraph instance
let _graphData = null;      // raw { nodes, edges }
let _readerDocId = null;    // currently displayed doc
let _readerMode = 'rendered'; // 'rendered' | 'raw'
let _readerRaw = '';        // cached raw markdown

// ── Nav hook: initialize Atlas on first visit ─────────────────

// ── Atlas initialization ──────────────────────────────────────
async function initAtlas() {
  const canvas = el('graph-canvas');
  if (!canvas) return;

  const pane = el('graph-pane');
  canvas.width  = pane.offsetWidth  || 800;
  canvas.height = pane.offsetHeight || 600;

  el('graph-stats').textContent = 'Loading…';
  _graphData = await api('/api/graph?max_nodes=200');
  if (_graphData.error) { el('graph-stats').textContent = 'Error loading graph.'; return; }

  el('graph-stats').textContent =
    `${_graphData.nodes.length} nodes · ${_graphData.edges.length} edges`;

  _graph = new ForceGraph(canvas, _graphData.nodes, _graphData.edges);

  // Phase 11: shift-click expands neighborhood; plain click opens reader
  _graph.onNodeClick = async (node, ev) => {
    openDocInReader(node.id);
    _graph.selectNode(node);
    if (ev?.shiftKey) await expandAtlasNeighborhood(node.id, 1);
  };

  _graph.start();
  restoreAtlasReaderWidth();

  // ── Phase 12: Coordinate helper ───────────────────────────────
  // Converts a MouseEvent into canvas-pixel coordinates, accounting
  // for any CSS scaling difference between display size and canvas resolution.
  function toCanvasXY(e) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (canvas.width  / rect.width),
      y: (e.clientY - rect.top)  * (canvas.height / rect.height),
    };
  }

  // ── Phase 12: Drag / pan state ────────────────────────────────
  let _panActive = false, _dragNode = null;
  let _dragStartX = 0, _dragStartY = 0, _panStartTx = 0, _panStartTy = 0;
  // Track whether the mouse actually moved during a mousedown→mouseup
  // to distinguish click from drag (suppress click after drag).
  let _didDrag = false;

  // mousedown: start pan (empty canvas) or node drag
  canvas.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    const { x, y } = toCanvasXY(e);
    const g = _graph.screenToGraph(x, y);
    const node = _graph.hitTest(g.x, g.y);
    _didDrag = false;
    if (node) {
      _dragNode = node;
    } else {
      _panActive = true;
      _dragStartX = x; _dragStartY = y;
      _panStartTx = _graph._view.tx;
      _panStartTy = _graph._view.ty;
    }
    e.preventDefault();
  });

  // mousemove: pan canvas or drag node; otherwise update hover
  canvas.addEventListener('mousemove', (e) => {
    const { x, y } = toCanvasXY(e);
    _graph._mouseX = x;
    _graph._mouseY = y;

    if (_dragNode) {
      const g = _graph.screenToGraph(x, y);
      _dragNode.x = g.x; _dragNode.y = g.y;
      _dragNode.vx = 0;  _dragNode.vy = 0;
      _didDrag = true;
      _graph._renderDirty = true;
      canvas.style.cursor = 'grabbing';
      return;
    }
    if (_panActive) {
      _graph._view.tx = _panStartTx + (x - _dragStartX);
      _graph._view.ty = _panStartTy + (y - _dragStartY);
      _didDrag = true;
      _graph._renderDirty = true;
      canvas.style.cursor = 'grabbing';
      return;
    }

    // Hover detection
    const g = _graph.screenToGraph(x, y);
    const node = _graph.hitTest(g.x, g.y);
    const edge  = node ? null : _graph.hitTestEdge(g.x, g.y);
    const changed = node !== _graph.hoveredNode || edge !== _graph.hoveredEdge;
    _graph.hoveredNode = node || null;
    _graph.hoveredEdge = edge || null;
    if (changed) _graph._renderDirty = true;
    canvas.style.cursor = node ? 'pointer' : edge ? 'help' : 'default';
  });

  // mouseup: end drag/pan; re-energise physics after node drag
  window.addEventListener('mouseup', () => {
    if (_dragNode) { _graph.alpha = Math.max(_graph.alpha, 0.3); }
    _panActive = false;
    _dragNode  = null;
    canvas.style.cursor = 'default';
  });

  // click: open reader + select (suppressed if drag just occurred)
  canvas.addEventListener('click', (e) => {
    if (_didDrag) { _didDrag = false; return; }
    const { x, y } = toCanvasXY(e);
    const g = _graph.screenToGraph(x, y);
    const node = _graph.hitTest(g.x, g.y);
    if (node && _graph.onNodeClick) _graph.onNodeClick(node, e);
  });

  // dblclick: expand neighborhood (Phase 11 behaviour preserved)
  canvas.addEventListener('dblclick', async (e) => {
    if (!_graph) return;
    const { x, y } = toCanvasXY(e);
    const g = _graph.screenToGraph(x, y);
    const node = _graph.hitTest(g.x, g.y);
    if (node) await expandAtlasNeighborhood(node.id, 1);
  });

  // wheel: zoom centered on cursor
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (!_graph) return;
    const { x, y } = toCanvasXY(e);
    const factor = e.deltaY < 0 ? 1.12 : (1 / 1.12);
    _graph.zoomAt(x, y, factor);
    _graph._renderDirty = true;
  }, { passive: false });

  // mouseleave: clear hover state
  canvas.addEventListener('mouseleave', () => {
    if (!_graph) return;
    _graph.hoveredNode = null;
    _graph.hoveredEdge = null;
  });

  // resize: update canvas resolution, refit
  window.addEventListener('resize', () => {
    if (!_graph) return;
    canvas.width  = pane.offsetWidth;
    canvas.height = pane.offsetHeight;
  });
}

// ── Atlas reader width ────────────────────────────────────────
function setAtlasReaderWidth(mode) {
  const layout = el('atlas-layout');
  if (!layout) return;
  if (mode === 'hide')   layout.style.gridTemplateColumns = '1fr 0px';
  else if (mode === 'wide') layout.style.gridTemplateColumns = '1fr minmax(560px, 42vw)';
  else                   layout.style.gridTemplateColumns = '1fr 420px';
  try { localStorage.setItem('boh_atlas_reader_width_mode', mode); } catch (_) {}
}

function restoreAtlasReaderWidth() {
  try {
    const mode = localStorage.getItem('boh_atlas_reader_width_mode') || 'normal';
    setAtlasReaderWidth(mode);
  } catch (_) {}
}

// ── Neighborhood expansion ────────────────────────────────────
async function expandAtlasNeighborhood(docId, depth = 1) {
  if (!_graph) return;
  const res = await api(`/api/graph/neighborhood?doc_id=${encodeURIComponent(docId)}&depth=${depth}&limit=50`);
  if (res.error) return;

  const existingIds   = new Set(_graph.nodes.map(n => n.id));
  const existingEdges = new Set(_graph.edges.map(e => `${e.source}->${e.target}:${e.type||''}`));

  for (const n of res.nodes || []) {
    if (!existingIds.has(n.id)) {
      const anchor = _graph.nodeById?.get(docId) || { x: _graph.canvas.width / 2, y: _graph.canvas.height / 2 };
      _graph.nodes.push({ ...n, x: anchor.x + (Math.random() - .5) * 80, y: anchor.y + (Math.random() - .5) * 80, vx: 0, vy: 0 });
      existingIds.add(n.id);
    }
  }

  for (const e of res.edges || []) {
    const key = `${e.source}->${e.target}:${e.type||''}`;
    const rev = `${e.target}->${e.source}:${e.type||''}`;
    if (!existingEdges.has(key) && !existingEdges.has(rev)) {
      _graph.edges.push(e);
      existingEdges.add(key);
    }
  }

  _graph.rebuildAdjacency?.();
  _graph.expandedNodes?.add(docId);
  _graph.alpha = Math.max(_graph.alpha, .55);
  el('graph-stats').textContent = `${_graph.nodes.length} nodes · ${_graph.edges.length} edges`;
}

async function expandSelectedAtlasNode() {
  if (!_graph?.selectedNode) return;
  await expandAtlasNeighborhood(_graph.selectedNode.id, 1);
}

function collapseAtlasToInitial() {
  teardownAtlas();
  initAtlas();
}

async function reloadGraph() {
  if (_graph) { _graph.stop(); _graph = null; }
  await initAtlas();
}

function applyGraphFilter() {
  if (!_graph || !_graphData) return;
  const classFilter = el('graph-filter-class').value;
  const showRelated = el('graph-show-related').checked;

  const filteredNodes = classFilter
    ? _graphData.nodes.filter(n => n.corpusClass === classFilter)
    : _graphData.nodes;
  const nodeIds = new Set(filteredNodes.map(n => n.id));
  const filteredEdges = _graphData.edges.filter(e =>
    nodeIds.has(e.source) && nodeIds.has(e.target) &&
    (showRelated || e.type === 'lineage')
  );

  _graph.stop();
  const canvas = el('graph-canvas');
  _graph = new ForceGraph(canvas, filteredNodes, filteredEdges);
  _graph.onNodeClick = async (node, ev) => {
    openDocInReader(node.id);
    _graph.selectNode(node);
    if (ev?.shiftKey) await expandAtlasNeighborhood(node.id, 1);
  };
  _graph.start();
  el('graph-stats').textContent = `${filteredNodes.length} nodes · ${filteredEdges.length} edges`;
  if (_graph) _graph._renderDirty = true;
}

// ── Document Reader ───────────────────────────────────────────
async function openDocInReader(docId) {
  _readerDocId = docId;

  // Show spinner
  el('reader-content').innerHTML = `<div style="padding:40px;text-align:center"><span class="spinner"></span></div>`;
  el('reader-toggle').style.display = 'block';

  // Fetch doc metadata + content in parallel
  const [meta, content, related] = await Promise.all([
    api(`/api/docs/${encodeURIComponent(docId)}`),
    fetch(`/api/docs/${encodeURIComponent(docId)}/content`).then(r => r.text()),
    api(`/api/docs/${encodeURIComponent(docId)}/related?limit=6`),
  ]);

  if (meta.error) { el('reader-content').innerHTML = `<div class="text-red">${escHtml(meta.error)}</div>`; return; }

  const doc = meta.doc;
  _readerRaw = content;

  // Header
  const fname = (doc.path || '').split('/').pop().replace('.md', '');
  el('reader-title').textContent = fname || doc.doc_id;
  el('reader-meta').innerHTML = `
    ${statusBadge(doc.status)} ${typeBadge(doc.type)} ${corpusBadge(doc.corpus_class)}
    ${doc.version ? `<span class="text-faint font-sm">v${escHtml(doc.version)}</span>` : ''}`;

  // Related docs
  const relDocs = related.related || [];
  if (relDocs.length) {
    el('reader-related').style.display = 'block';
    el('reader-related-list').innerHTML = relDocs.map(r =>
      `<span class="related-chip" onclick="openDocInReader('${escHtml(r.doc_id)}')">
        ${escHtml((r.path||'').split('/').pop().replace('.md',''))}
        <span class="score">${(r.score*100).toFixed(0)}%</span>
      </span>`
    ).join('');
  } else {
    el('reader-related').style.display = 'none';
  }

  setReaderMode(_readerMode);
}

function setReaderMode(mode) {
  _readerMode = mode;
  el('btn-rendered').style.cssText = mode === 'rendered'
    ? 'border:none;border-radius:0;background:var(--blue);color:#fff'
    : 'border:none;border-radius:0;background:transparent;color:var(--text-muted)';
  el('btn-raw').style.cssText = mode === 'raw'
    ? 'border:none;border-radius:0;background:var(--blue);color:#fff'
    : 'border:none;border-radius:0;background:transparent;color:var(--text-muted)';

  if (!_readerRaw) return;

  const contentEl = el('reader-content');
  if (mode === 'raw') {
    contentEl.innerHTML = `<pre class="raw-view">${escHtml(_readerRaw)}</pre>`;
  } else {
    contentEl.innerHTML = `<div class="md-body">${renderMarkdown(_readerRaw)}</div>`;
  }
}

// ── Markdown renderer ─────────────────────────────────────────
function renderMarkdown(text) {
  if (!text) return '';

  // 1. Extract math blocks before marked processes them
  const mathStore = [];
  text = text.replace(/\$\$([\s\S]+?)\$\$/g, (_, math) => {
    const i = mathStore.length;
    mathStore.push({ type: 'block', math });
    return `<MATH${i}>`;
  });
  text = text.replace(/\$([^\n\$]+?)\$/g, (_, math) => {
    const i = mathStore.length;
    mathStore.push({ type: 'inline', math });
    return `<MATH${i}>`;
  });

  // 2. Run marked.js
  let html = '';
  try {
    html = marked.parse(text, { breaks: false, gfm: true });
  } catch(e) {
    html = `<pre>${escHtml(text)}</pre>`;
  }

  // 3. Restore math with KaTeX
  html = html.replace(/<MATH(\d+)>/g, (_, i) => {
    const { type, math } = mathStore[i];
    try {
      if (type === 'block') {
        return `<div class="math-display">${katex.renderToString(math.trim(), { displayMode: true, throwOnError: false })}</div>`;
      } else {
        return katex.renderToString(math.trim(), { throwOnError: false });
      }
    } catch(e) {
      return type === 'block'
        ? `<div class="math-display"><code>$$${escHtml(math)}$$</code></div>`
        : `<code>$${escHtml(math)}$</code>`;
    }
  });

  // 4. Detect structured callouts (blueprint §2)
  // Pattern: **Definition:** or **Proposition:** etc. at start of paragraph
  const calloutTypes = ['Definition', 'Proposition', 'Invariant', 'Operator', 'Lemma', 'Theorem', 'Corollary'];
  for (const label of calloutTypes) {
    const cls = label.toLowerCase();
    const re = new RegExp(`<p><strong>${label}[:\\.]?<\\/strong>`, 'gi');
    html = html.replace(re,
      `<div class="callout ${cls}"><div class="callout-label">${label}</div><p>`
    );
    // Close the callout after the enclosing </p>
    if (html.includes(`<div class="callout ${cls}">`)) {
      // Replace first unclosed callout's </p> with </p></div>
      html = html.replace(
        new RegExp(`(<div class="callout ${cls}">.*?</p>)`, 's'),
        '$1</div>'
      );
    }
  }

  return html;
}

// ── Force-directed graph ──────────────────────────────────────
class ForceGraph {
  constructor(canvas, nodes, edges) {
    this.canvas  = canvas;
    this.ctx     = canvas.getContext('2d');
    this.edges   = edges;
    this.ripples = [];
    this.hoveredNode  = null;
    this.hoveredEdge  = null;
    this.selectedNode = null;
    this.onNodeClick  = null;
    this._raf     = null;
    this._stopped = false;
    this.alpha    = 1.0;
    this._tooltip     = { node: null };
    this._mouseX      = 0;   // canvas/screen coords
    this._mouseY      = 0;
    this.expandedNodes = new Set();
    this.focusNode     = null;

    // ── Phase 12: view transform (zoom + pan) ────────────────────
    // All node positions are in "graph space". The view transform
    // maps graph space → screen space: screen = graph * scale + translate.
    this._view = { scale: 1.0, tx: 0, ty: 0 };
    // Drag bookkeeping (managed by initAtlas event handlers)
    this._drag = { active: false, node: null,
                   startX: 0, startY: 0, startTx: 0, startTy: 0 };

    // ── Phase 12.3: Performance options ──────────────────────────
    // Balanced defaults: no ripples, no glow, 30fps cap, straight bg edges.
    this.options = {
      animatedRipples:  false,   // ripple cascade on select
      edgeGlow:         false,   // shadowBlur / canon glow
      curvedEdgesAll:   false,   // curve ALL edges (expensive); false = curve only highlighted
      maxRipples:       8,       // hard cap on active ripples
      fpsTarget:        30,      // 30 = balanced, 60 = high, 0 = unlimited
      staticMode:       false,   // draw-on-demand only
      _perfMode:        'balanced',
    };
    this._lastFrameTs  = 0;      // rAF timestamp of last drawn frame
    this._renderDirty  = true;   // static mode: only draw when dirty
    this._lastRenderMs = 0;      // measured draw() duration
    this._perfWarned   = false;  // auto-reduce already triggered

    // Initialize node positions — spread across canvas
    this.nodes = nodes.map((n, i) => {
      const angle  = (i / nodes.length) * 2 * Math.PI;
      const radius = Math.min(canvas.width, canvas.height) * 0.35;
      return {
        ...n,
        x:  canvas.width  / 2 + radius * Math.cos(angle) + (Math.random() - .5) * 40,
        y:  canvas.height / 2 + radius * Math.sin(angle) + (Math.random() - .5) * 40,
        vx: 0, vy: 0,
      };
    });

    // Build nodeById lookup AFTER this.nodes exists (Phase 11 fix preserved)
    this.nodeById = new Map(this.nodes.map(n => [n.id, n]));

    // Build adjacency map for faster edge lookup
    this._adj = new Map();
    for (const node of this.nodes) this._adj.set(node.id, []);
    for (const edge of this.edges) {
      if (this._adj.has(edge.source)) this._adj.get(edge.source).push(edge.target);
      if (this._adj.has(edge.target)) this._adj.get(edge.target).push(edge.source);
    }
  }

  start() {
    this._stopped = false;
    const loop = (ts) => {
      if (this._stopped) return;
      this._raf = requestAnimationFrame(loop);

      // Static mode: only draw when something changed
      const isSettled = this.alpha <= 0.005 && !this.ripples.length;
      if (this.options.staticMode && isSettled && !this._renderDirty) return;

      // Frame-rate cap (0 = unlimited)
      if (this.options.fpsTarget > 0) {
        const minMs = 1000 / this.options.fpsTarget;
        if (ts - this._lastFrameTs < minMs) return;
      }
      this._lastFrameTs = ts;

      if (this.alpha > 0.005) this.tick();
      this.draw();
      this._renderDirty = false;
    };
    this._raf = requestAnimationFrame(loop);
  }

  stop() {
    this._stopped = true;
    if (this._raf) cancelAnimationFrame(this._raf);
  }

  tick() {
    const W = this.canvas.width, H = this.canvas.height;
    const k = Math.sqrt((W * H) / Math.max(this.nodes.length, 1)) * 0.8;

    // Repulsion (all pairs — Barnes-Hut approximation for large graphs)
    const N = this.nodes.length;
    if (N <= 100) {
      for (let i = 0; i < N; i++) {
        for (let j = i + 1; j < N; j++) {
          const a = this.nodes[i], b = this.nodes[j];
          const dx = b.x - a.x || .01, dy = b.y - a.y || .01;
          const dist2 = dx*dx + dy*dy;
          const dist  = Math.sqrt(dist2) || .01;
          const force = (k * k) / dist;
          const fx = force * dx / dist, fy = force * dy / dist;
          a.vx -= fx; a.vy -= fy;
          b.vx += fx; b.vy += fy;
        }
      }
    } else {
      // Simplified: use a grid for repulsion
      for (const node of this.nodes) {
        node.vx += (W/2 - node.x) * 0.002;
        node.vy += (H/2 - node.y) * 0.002;
      }
    }

    // Attraction along edges
    for (const edge of this.edges) {
      const source = this.nodes.find(n => n.id === edge.source);
      const target = this.nodes.find(n => n.id === edge.target);
      if (!source || !target) continue;
      const dx = target.x - source.x, dy = target.y - source.y;
      const dist = Math.sqrt(dx*dx + dy*dy) || .01;
      const targetDist = edge.type === 'lineage' ? 80 : 120;
      const force = (dist - targetDist) * 0.006 * (edge.weight || 1);
      const fx = force * dx / dist, fy = force * dy / dist;
      source.vx += fx; source.vy += fy;
      target.vx -= fx; target.vy -= fy;
    }

    // Center gravity
    for (const node of this.nodes) {
      node.vx += (W/2 - node.x) * 0.0015;
      node.vy += (H/2 - node.y) * 0.0015;
    }

    // Apply velocity + damping + boundary
    const damping = 0.78;
    for (const node of this.nodes) {
      node.vx *= damping; node.vy *= damping;
      node.x  = Math.max(16, Math.min(W - 16, node.x + node.vx * this.alpha));
      node.y  = Math.max(16, Math.min(H - 16, node.y + node.vy * this.alpha));
    }

    this.alpha *= 0.992;
  }

  draw() {
    const t0 = performance.now();
    const ctx = this.ctx;
    const W = this.canvas.width, H = this.canvas.height;
    const opts = this.options;
    ctx.clearRect(0, 0, W, H);

    // ── Background grid — screen space ───────────────────────────
    ctx.strokeStyle = 'rgba(30,39,54,0.4)';
    ctx.lineWidth = 0.5;
    for (let x = 0; x < W; x += 60) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,H); ctx.stroke(); }
    for (let y = 0; y < H; y += 60) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke(); }

    // ── Apply view transform ─────────────────────────────────────
    const { scale, tx, ty } = this._view;
    ctx.save();
    ctx.translate(tx, ty);
    ctx.scale(scale, scale);

    // ── Edge drawing (performance-critical) ──────────────────────
    // Strategy: background edges → single batched straight-line pass per colour.
    //           highlighted edges (hovered / selected-adjacent) → individual curves.
    // This collapses N ctx.stroke() calls into ≤4, saving ~10-15ms/frame at 240 edges.

    const selId = this.selectedNode?.id;
    const bgBucket = { lineage: [], conflict: [], topic: [], other: [] };
    const hlEdges  = [];

    for (const edge of this.edges) {
      const isHov = edge === this.hoveredEdge;
      const isSel = selId && (edge.source === selId || edge.target === selId);
      if (isHov || isSel || opts.curvedEdgesAll) {
        hlEdges.push(edge);
      } else {
        const t = edge.type;
        const cat =
          (t === 'lineage' || t === 'derives' || t === 'supersedes') ? 'lineage' :
          (t === 'conflicts' || t === 'duplicate_content')            ? 'conflict' :
          (t === 'related'  || t === 'semantic' || t === 'canon_relates_to') ? 'topic' :
          'other';
        bgBucket[cat].push(edge);
      }
    }

    // Batch draw: one beginPath + many moveTo/lineTo + one stroke per colour
    const batchLines = (edges, color, lw, dashed) => {
      if (!edges.length) return;
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth   = lw;
      if (dashed) ctx.setLineDash([2, 5]);
      for (const e of edges) {
        const s = this.nodeById?.get(e.source);
        const t = this.nodeById?.get(e.target);
        if (s && t) { ctx.moveTo(s.x, s.y); ctx.lineTo(t.x, t.y); }
      }
      ctx.stroke();
      if (dashed) ctx.setLineDash([]);
    };
    batchLines(bgBucket.lineage,  'rgba(96,165,250,0.13)',  0.8, false);
    batchLines(bgBucket.conflict, 'rgba(239,68,68,0.16)',   0.9, false);
    batchLines(bgBucket.topic,    'rgba(180,190,210,0.10)', 0.7, true);
    batchLines(bgBucket.other,    'rgba(120,135,160,0.10)', 0.7, false);

    // Highlighted edges — full curved treatment (only a few per frame)
    for (const edge of hlEdges) {
      const s = this.nodeById?.get(edge.source) || this.nodes.find(n => n.id === edge.source);
      const t = this.nodeById?.get(edge.target) || this.nodes.find(n => n.id === edge.target);
      if (s && t) this.drawEdge(edge, s, t);
    }

    // ── Ripples (gated) ──────────────────────────────────────────
    if (opts.animatedRipples && this.ripples.length) {
      // Prune aggressively, enforce hard cap
      this.ripples = this.ripples
        .filter(r => r.alpha > 0.04)
        .slice(0, opts.maxRipples);
      for (const r of this.ripples) {
        ctx.beginPath();
        ctx.arc(r.x, r.y, r.radius, 0, Math.PI*2);
        ctx.strokeStyle = `rgba(96,165,250,${r.alpha.toFixed(2)})`;
        ctx.lineWidth = 1.5;
        ctx.stroke();
        r.radius += 2.5; r.alpha *= 0.92;
      }
    } else {
      this.ripples = [];
    }

    // ── Nodes ────────────────────────────────────────────────────
    for (const node of this.nodes) {
      const r     = this._nodeRadius(node);
      const color = this._nodeColor(node);
      const isSelected = node === this.selectedNode;
      const isHovered  = node === this.hoveredNode;
      const isAdjacent = selId && this._adj.get(selId)?.includes(node.id);

      // Glow ring for selected node (replaces expensive shadowBlur)
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 9, 0, Math.PI*2);
        ctx.strokeStyle = 'rgba(96,165,250,0.20)';
        ctx.lineWidth = 6;
        ctx.stroke();
      } else if (opts.edgeGlow && node.corpusClass === 'CORPUS_CLASS:CANON' && this.alpha < 0.3) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 5, 0, Math.PI*2);
        ctx.strokeStyle = `${color}22`;
        ctx.lineWidth = 4;
        ctx.stroke();
      }

      // Node fill
      ctx.beginPath();
      ctx.arc(node.x, node.y, r + (isHovered ? 2 : 0), 0, Math.PI*2);
      ctx.fillStyle = isSelected ? '#60a5fa'
                    : isAdjacent ? this._lighten(color)
                    : color;
      ctx.fill();

      // Conflict halo
      if (node.conflictCount > 0) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 4, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(239,68,68,0.55)';
        ctx.lineWidth = 1.5;
        ctx.setLineDash([3, 2]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      // Stale halo
      if (node.expiredCoordinates > 0 && node.conflictCount === 0) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 4, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(245,158,11,0.45)';
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 3]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      // Uncertain dot
      if (node.uncertainCoordinates > 0) {
        ctx.beginPath();
        ctx.arc(node.x + r, node.y - r, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(96,165,250,0.8)';
        ctx.fill();
      }
      // Selection ring
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 5, 0, Math.PI*2);
        ctx.strokeStyle = 'rgba(96,165,250,0.6)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
      // Labels
      const showLabel = isSelected || isHovered ||
                        (this.nodes.length <= 25 && this.alpha < 0.2) ||
                        (scale >= 1.5 && this.alpha < 0.15);
      if (showLabel) {
        ctx.fillStyle = isSelected ? '#e6edf3' : '#b8c4d4';
        ctx.font = `${isSelected ? 11 : 10}px monospace`;
        const raw = (node.title && node.title.trim()) ? node.title : node.label;
        const lbl = raw.length > 26 ? raw.slice(0, 24) + '\u2026' : raw;
        ctx.fillText(lbl, node.x + r + 4, node.y + 3.5);
      }
    }

    ctx.restore();
    // ── End view transform ───────────────────────────────────────

    // ── Tooltips in screen space ─────────────────────────────────
    if (this.hoveredNode) {
      const node  = this.hoveredNode;
      const title = (node.title && node.title.trim()) ? node.title : node.label;
      const lines = [
        title.length > 32 ? title.slice(0, 30) + '\u2026' : title,
        node.status ? `${node.status}  \u00b7  ${node.type || ''}` : '',
        node.conflictCount > 0   ? `\u26a1 ${node.conflictCount} conflict(s)` : '',
        node.expiredCoordinates > 0 ? `\u23f1 ${node.expiredCoordinates} stale` : '',
        node.uncertainCoordinates > 0 ? `? ${node.uncertainCoordinates} uncertain` : '',
      ].filter(Boolean);

      const sx  = node.x * scale + tx;
      const sy  = node.y * scale + ty;
      const sr  = this._nodeRadius(node) * scale;
      const pad = 8, lh = 15;
      const bw  = 200, bh = pad * 2 + lines.length * lh;
      let ttx = sx + sr + 8;
      let tty = sy - bh / 2;
      if (ttx + bw > W) ttx = sx - bw - sr - 8;
      if (tty < 4) tty = 4;
      if (tty + bh > H) tty = H - bh - 4;

      ctx.fillStyle = 'rgba(18,27,38,0.93)';
      ctx.strokeStyle = 'rgba(96,165,250,0.3)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.roundRect ? ctx.roundRect(ttx, tty, bw, bh, 5) : ctx.rect(ttx, tty, bw, bh);
      ctx.fill(); ctx.stroke();
      lines.forEach((line, i) => {
        ctx.fillStyle = i === 0 ? '#e6edf3' : (line[0] === '\u26a1' ? '#ef4444' : '#7a8ea5');
        ctx.font = i === 0 ? '11px monospace' : '10px monospace';
        ctx.fillText(line, ttx + pad, tty + pad + i * lh + 11);
      });
    }

    if (this.hoveredEdge && !this.hoveredNode) {
      this.drawEdgeTooltip(this.hoveredEdge, this._mouseX || 0, this._mouseY || 0);
    }

    // Zoom indicator
    if (Math.abs(scale - 1.0) > 0.05) {
      ctx.fillStyle = 'rgba(122,142,170,0.55)';
      ctx.font = '10px monospace';
      ctx.fillText(`${scale.toFixed(2)}\u00d7`, W - 48, H - 14);
    }

    // ── Performance monitor ──────────────────────────────────────
    this._lastRenderMs = performance.now() - t0;
    if (this._lastRenderMs > 28 && !this._perfWarned) {
      this._perfWarned = true;
      opts.animatedRipples = false;
      opts.edgeGlow = false;
      // Notify UI
      const warn = document.getElementById('atlas-perf-warning');
      if (warn) { warn.style.display = 'block'; warn.style.opacity = '1'; }
      // Sync checkboxes if present
      const cb = document.getElementById('atlas-opt-ripples');
      if (cb) cb.checked = false;
      const cb2 = document.getElementById('atlas-opt-glow');
      if (cb2) cb2.checked = false;
    }
  }

  _nodeRadius(node) {
    const base = node.corpusClass === 'CORPUS_CLASS:CANON' ? 9 : 6;
    return base + Math.min(6, (node.canonScore || 0) * 0.035);
  }

  _nodeColor(node) {
    const map = {
      'CORPUS_CLASS:CANON':    '#10b981',
      'CORPUS_CLASS:DRAFT':    '#6b7a96',
      'CORPUS_CLASS:DERIVED':  '#f59e0b',
      'CORPUS_CLASS:ARCHIVE':  '#3d4d63',
      'CORPUS_CLASS:EVIDENCE': '#8b5cf6',
    };
    return map[node.corpusClass] || '#6b7a96';
  }

  _lighten(hex) {
    // Simple lightening: parse hex and add 40
    const r = parseInt(hex.slice(1,3),16), g = parseInt(hex.slice(3,5),16), b = parseInt(hex.slice(5,7),16);
    return `rgb(${Math.min(255,r+40)},${Math.min(255,g+40)},${Math.min(255,b+40)})`;
  }

  selectNode(node) {
    this.selectedNode = node;
    this._renderDirty = true;
    if (this.options.animatedRipples) {
      // Primary ripple on selected node
      if (this.ripples.length < this.options.maxRipples) {
        this.ripples.push({ x: node.x, y: node.y, radius: 12, alpha: 0.9 });
      }
      // Cascade to connected nodes (capped, no setTimeout storm on large graphs)
      const connected = this._adj.get(node.id) || [];
      const slots = this.options.maxRipples - this.ripples.length;
      connected.slice(0, Math.min(4, slots)).forEach((cid, i) => {
        const cnode = this.nodes.find(n => n.id === cid);
        if (!cnode) return;
        setTimeout(() => {
          if (this._stopped || !this.options.animatedRipples) return;
          if (this.ripples.length >= this.options.maxRipples) return;
          const dist = Math.sqrt((node.x-cnode.x)**2 + (node.y-cnode.y)**2);
          this.ripples.push({ x: cnode.x, y: cnode.y, radius: 6,
                              alpha: Math.max(0.15, 0.5 - dist/800) });
        }, 150 + i * 80);
      });
    }
    // Do not call onNodeClick here — click handler already does it.
  }

  hitTest(x, y) {
    for (const node of this.nodes) {
      const dx = node.x - x, dy = node.y - y;
      const r = this._nodeRadius(node) + 4;
      if (dx*dx + dy*dy <= r*r) return node;
    }
    return null;
  }

  hitTestEdge(x, y) {
    let best = null, bestDist = Infinity;
    for (const edge of this.edges) {
      const s = this.nodeById?.get(edge.source) || this.nodes.find(n => n.id === edge.source);
      const t = this.nodeById?.get(edge.target) || this.nodes.find(n => n.id === edge.target);
      if (!s || !t) continue;
      const d = pointToSegmentDistance(x, y, s.x, s.y, t.x, t.y);
      const threshold = Math.max(5, 3 + (edge.weight || 1));
      if (d < threshold && d < bestDist) { best = edge; bestDist = d; }
    }
    return best;
  }

  drawEdge(edge, s, t) {
    const ctx = this.ctx;
    const isHovered      = edge === this.hoveredEdge;
    const isSelectedPath = this.selectedNode &&
      (edge.source === this.selectedNode.id || edge.target === this.selectedNode.id);
    const isLineage  = edge.type === 'lineage' || edge.type === 'derives' || edge.type === 'supersedes';
    const isConflict = edge.type === 'conflicts' || edge.type === 'duplicate_content';
    const isTopic    = edge.type === 'related' || edge.type === 'semantic' || edge.type === 'canon_relates_to';

    const mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2;
    const dx = t.x - s.x, dy = t.y - s.y;
    const len = Math.hypot(dx, dy) || 1;
    const curve = Math.min(48, Math.max(10, len * 0.08));
    const cx = mx - (dy / len) * curve;
    const cy = my + (dx / len) * curve;

    ctx.beginPath();
    ctx.moveTo(s.x, s.y);
    ctx.quadraticCurveTo(cx, cy, t.x, t.y);

    const alpha = isHovered ? .82 : isSelectedPath ? .55 : .18;
    if (isLineage)       ctx.strokeStyle = `rgba(96,165,250,${alpha})`;
    else if (isConflict) ctx.strokeStyle = `rgba(239,68,68,${alpha})`;
    else if (isTopic)    ctx.strokeStyle = `rgba(180,190,210,${alpha})`;
    else                 ctx.strokeStyle = `rgba(120,135,160,${alpha})`;

    ctx.lineWidth = isHovered ? 2.6 : isSelectedPath ? 1.8
                 : Math.max(.7, Math.min(2.2, .6 + (edge.weight || 1) * .25));
    ctx.setLineDash(isTopic ? [2, 5] : []);
    ctx.stroke();
    ctx.setLineDash([]);

    // Crossover bead at curve midpoint when edge has reasons/crossovers
    if ((edge.reasons?.length) || (edge.crossovers?.length)) {
      ctx.beginPath();
      ctx.arc(cx, cy, isHovered ? 3.5 : 2, 0, Math.PI * 2);
      ctx.fillStyle = isHovered ? 'rgba(230,237,243,.9)' : 'rgba(122,142,170,.55)';
      ctx.fill();
    }
  }

  drawEdgeTooltip(edge, x, y) {
    const ctx     = this.ctx;
    const reasons = edge.reasons || [];
    const shared  = edge.shared_topics || [];
    const lines = [
      edge.label || edge.type || 'link',
      ...reasons.slice(0, 6),
      shared.length ? `shared: ${shared.slice(0, 6).join(', ')}` : '',
    ].filter(Boolean);

    const padding = 8, lineH = 15;
    const boxW = 260, boxH = padding * 2 + lines.length * lineH;
    const W = this.canvas.width, H = this.canvas.height;
    let tx = Math.min(x + 14, W - boxW - 8);
    let ty = Math.min(y + 14, H - boxH - 8);
    if (ty < 4) ty = 4;

    ctx.fillStyle   = 'rgba(18,27,38,.96)';
    ctx.strokeStyle = 'rgba(180,190,210,.28)';
    ctx.beginPath();
    ctx.roundRect ? ctx.roundRect(tx, ty, boxW, boxH, 6) : ctx.rect(tx, ty, boxW, boxH);
    ctx.fill(); ctx.stroke();

    lines.forEach((line, i) => {
      ctx.fillStyle = i === 0 ? '#e6edf3' : '#7a8ea5';
      ctx.font      = i === 0 ? '11px monospace' : '10px monospace';
      ctx.fillText(line.length > 44 ? line.slice(0, 42) + '…' : line,
                   tx + padding, ty + padding + i * lineH + 11);
    });
  }

  rebuildAdjacency() {
    this._adj = new Map();
    for (const node of this.nodes) this._adj.set(node.id, []);
    for (const edge of this.edges) {
      if (this._adj.has(edge.source)) this._adj.get(edge.source).push(edge.target);
      if (this._adj.has(edge.target)) this._adj.get(edge.target).push(edge.source);
    }
    this.nodeById = new Map(this.nodes.map(n => [n.id, n]));
  }

  // ── Phase 12: view transform helpers ─────────────────────────

  /** Convert screen/canvas coords → graph-space coords. */
  screenToGraph(sx, sy) {
    return {
      x: (sx - this._view.tx) / this._view.scale,
      y: (sy - this._view.ty) / this._view.scale,
    };
  }

  /** Convert graph-space coords → screen/canvas coords. */
  graphToScreen(gx, gy) {
    return {
      x: gx * this._view.scale + this._view.tx,
      y: gy * this._view.scale + this._view.ty,
    };
  }

  /** Reset zoom and pan to default (1×, centered). */
  resetView() {
    this._view = { scale: 1.0, tx: 0, ty: 0 };
  }

  /** Fit all nodes into the canvas with padding. Updates view transform only — does not move nodes. */
  fitView() {
    if (!this.nodes.length) return;
    const W = this.canvas.width, H = this.canvas.height;
    const pad = 60;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of this.nodes) {
      if (n.x < minX) minX = n.x; if (n.y < minY) minY = n.y;
      if (n.x > maxX) maxX = n.x; if (n.y > maxY) maxY = n.y;
    }
    const cw = maxX - minX || 1, ch = maxY - minY || 1;
    const scale = Math.min((W - pad * 2) / cw, (H - pad * 2) / ch, 3.0);
    this._view.scale = scale;
    this._view.tx = W / 2 - ((minX + maxX) / 2) * scale;
    this._view.ty = H / 2 - ((minY + maxY) / 2) * scale;
  }

  /** Zoom in or out centered on a screen-space point (cx, cy). */
  zoomAt(cx, cy, factor) {
    const oldScale = this._view.scale;
    const newScale = Math.max(0.08, Math.min(10.0, oldScale * factor));
    const ratio = newScale / oldScale;
    this._view.tx = cx - (cx - this._view.tx) * ratio;
    this._view.ty = cy - (cy - this._view.ty) * ratio;
    this._view.scale = newScale;
  }

  /** Pan view so the selected node is centered on canvas. */
  focusSelected() {
    if (!this.selectedNode) return;
    const W = this.canvas.width, H = this.canvas.height;
    this._view.tx = W / 2 - this.selectedNode.x * this._view.scale;
    this._view.ty = H / 2 - this.selectedNode.y * this._view.scale;
  }
}

function pointToSegmentDistance(px, py, x1, y1, x2, y2) {
  const dx = x2 - x1, dy = y2 - y1;
  if (dx === 0 && dy === 0) return Math.hypot(px - x1, py - y1);
  let t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy);
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

// Atlas init is wired directly in nav() above.

// ── App init ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  restoreDaenaryFilters();
  try {
    const savedRoot = sessionStorage.getItem('boh_active_library_root');
    if (savedRoot) setActiveLibraryRoot(savedRoot);
    else {
      const health = await api('/api/health');
      setActiveLibraryRoot(health.library || './library');
    }
  } catch (_) {
    setActiveLibraryRoot('./library');
  }
  // Route to hash on load
  const hash = window.location.hash.replace('#', '');
  if (hash) nav(hash);
  else loadDashboard();

  // Phase 12: update LLM queue nav badge after a short delay
  setTimeout(async () => {
    try {
      const q = await api('/api/llm/queue/count');
      const pending = q.pending ?? 0;
      const badge = el('nav-llm-badge');
      if (badge) { badge.textContent = pending; badge.classList.toggle('hidden', pending === 0); }
    } catch (_) {}
  }, 1200);
});

// ══════════════════════════════════════════════════════════════
// Panel 7: Governance
// ══════════════════════════════════════════════════════════════

// ── Ollama ────────────────────────────────────────────────────
async function checkOllama() {
  const badge = el('ollama-status-badge');
  const list  = el('ollama-models-list');
  if (badge) badge.textContent = 'Checking…';
  const data = await api('/api/ollama/health');
  if (data.available) {
    if (badge) { badge.textContent = '● available'; badge.className = 'text-green font-sm'; }
    if (list) list.innerHTML = data.models.length
      ? data.models.map(m => `<span class="badge badge-type" style="margin:2px">${escHtml(m)}</span>`).join('')
      : '<span class="text-faint font-sm">No models found — run: ollama pull llama3.2</span>';
  } else {
    if (badge) { badge.textContent = '● unavailable'; badge.className = 'text-red font-sm'; }
    if (list) list.innerHTML = `<span class="text-faint font-sm">Ollama not reachable at ${escHtml(data.url||'')} — is it running?</span>`;
  }
}

async function runOllamaTask() {
  const task    = el('ollama-task')?.value;
  const content = el('ollama-content')?.value.trim();
  const model   = el('ollama-model-input')?.value.trim() || undefined;
  const docId   = el('ollama-doc-id')?.value.trim() || undefined;
  const out     = el('ollama-result');

  if (!task) { if (out) out.innerHTML = '<span class="text-amber font-sm">Select a task type first.</span>'; return; }
  if (!content) { if (out) out.innerHTML = '<span class="text-amber font-sm">Enter content to send.</span>'; return; }

  if (out) out.innerHTML = '<span class="spinner"></span> Invoking model…';

  const r = await api('/api/ollama/invoke', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ task_type: task, content, model, doc_id: docId }),
  });

  if (r.error && !r.invocation_id) {
    if (out) out.innerHTML = `<div class="text-red font-sm">${escHtml(r.error)}</div>`;
    return;
  }

  const statusBadge = r.status === 'success'
    ? '<span class="sig-badge sig-highconf">success</span>'
    : '<span class="sig-badge sig-conflict">error</span>';
  const nonAuthBadge = '<span class="sig-badge sig-uncertain" title="All model outputs are non-authoritative">non-authoritative</span>';

  const responseBlock = r.response_json
    ? `<pre style="font-size:11px;max-height:300px;overflow:auto">${escHtml(JSON.stringify(r.response_json, null, 2))}</pre>`
    : r.response_text
      ? `<pre style="font-size:11px;max-height:300px;overflow:auto">${escHtml(r.response_text.slice(0,2000))}</pre>`
      : '<span class="text-faint font-sm">No response</span>';

  if (out) out.innerHTML = `
    <div style="display:flex;gap:6px;align-items:center;margin-bottom:8px">
      ${statusBadge} ${nonAuthBadge}
      <span class="text-faint font-sm">${escHtml(r.invocation_id||'')} · ${escHtml(r.model||'')}</span>
    </div>
    ${r.error ? `<div class="text-red font-sm" style="margin-bottom:6px">${escHtml(r.error)}</div>` : ''}
    ${responseBlock}
  `;
}

// ── Policies ──────────────────────────────────────────────────
async function loadPolicies() {
  const body = el('policies-body');
  if (!body) return;
  body.innerHTML = `<tr><td colspan="7" class="text-faint"><span class="spinner"></span></td></tr>`;
  const data = await api('/api/governance/policies');
  const policies = data.policies || [];
  if (!policies.length) {
    body.innerHTML = `<tr><td colspan="7" class="text-faint" style="padding:12px;text-align:center">No policies defined — system defaults apply.</td></tr>`;
    return;
  }
  const check = v => v ? '<span class="text-green">✓</span>' : '<span class="text-faint">–</span>';
  body.innerHTML = policies.map(p => `
    <tr>
      <td class="font-sm">${escHtml(p.workspace)}</td>
      <td class="font-sm">${escHtml(p.entity_type)} <span class="text-faint">${escHtml(p.entity_id)}</span></td>
      <td style="text-align:center">${check(p.can_read)}</td>
      <td style="text-align:center">${check(p.can_write)}</td>
      <td style="text-align:center">${check(p.can_execute)}</td>
      <td style="text-align:center">${check(p.can_propose)}</td>
      <td style="text-align:center">${check(p.can_promote)}</td>
    </tr>`).join('');
}

async function savePolicy() {
  const workspace   = el('pol-workspace')?.value.trim();
  const entityType  = el('pol-entity-type')?.value;
  const entityId    = el('pol-entity-id')?.value.trim() || '*';
  const msg         = el('policy-msg');

  if (!workspace) { if (msg) msg.innerHTML = '<span class="text-amber">Workspace is required.</span>'; return; }

  const body = {
    workspace, entity_type: entityType, entity_id: entityId,
    can_read:    el('pol-read')?.checked    ? 1 : 0,
    can_write:   el('pol-write')?.checked   ? 1 : 0,
    can_execute: el('pol-execute')?.checked ? 1 : 0,
    can_propose: el('pol-propose')?.checked ? 1 : 0,
    can_promote: el('pol-promote')?.checked ? 1 : 0,
  };

  const r = await api('/api/governance/policy', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });

  if (r.detail) {
    if (msg) msg.innerHTML = `<span class="text-red">${escHtml(r.detail)}</span>`;
  } else {
    if (msg) msg.innerHTML = '<span class="text-green">✓ Policy saved.</span>';
    loadPolicies();
  }
}

// ── Audit log ─────────────────────────────────────────────────
async function loadAuditLog() {
  const body = el('audit-body');
  if (!body) return;
  body.innerHTML = `<tr><td colspan="5" class="text-faint"><span class="spinner"></span></td></tr>`;
  const data = await api('/api/audit?limit=50');
  const events = data.events || [];
  if (!events.length) {
    body.innerHTML = `<tr><td colspan="5" class="text-faint" style="padding:12px;text-align:center">No audit events yet.</td></tr>`;
    return;
  }
  const eventCls = { run: 'badge-type', save: 'badge-canonical', llm_call: 'badge-state',
                     edit: 'badge-draft', promote: 'badge-canonical', conflict: 'badge-conflict' };
  body.innerHTML = events.map(e => `
    <tr>
      <td class="text-faint font-sm">${ts(e.event_ts)}</td>
      <td><span class="badge ${eventCls[e.event_type]||'badge-draft'}">${escHtml(e.event_type)}</span></td>
      <td class="font-sm">${escHtml(e.actor_type)} <span class="text-faint">${escHtml(e.actor_id||'')}</span></td>
      <td class="font-sm text-faint">${escHtml((e.doc_id||'').slice(0,20))}</td>
      <td class="font-sm text-faint">${escHtml((e.detail||'').slice(0,60))}</td>
    </tr>`).join('');
}

// ── Execution runs ────────────────────────────────────────────
async function loadExecRuns() {
  const body  = el('exec-body');
  const docId = el('exec-doc-filter')?.value.trim();
  if (!body) return;
  body.innerHTML = `<tr><td colspan="6" class="text-faint"><span class="spinner"></span></td></tr>`;

  const url = docId
    ? `/api/exec/runs/${encodeURIComponent(docId)}`
    : '/api/audit?event_type=run&limit=30';
  const data = await api(url);
  const runs = data.runs || data.events || [];

  if (!runs.length) {
    body.innerHTML = `<tr><td colspan="6" class="text-faint" style="padding:12px;text-align:center">No execution runs found.</td></tr>`;
    return;
  }
  const statusCls = { success: 'badge-canonical', error: 'badge-conflict', running: 'badge-draft', pending: 'badge-state' };
  body.innerHTML = runs.map(r => `
    <tr>
      <td class="font-sm" style="font-family:var(--font-mono)">${escHtml((r.run_id||r.detail||'').slice(0,18))}</td>
      <td class="text-faint font-sm">${escHtml((r.doc_id||'').slice(0,18))}</td>
      <td class="text-faint font-sm">${escHtml(r.block_id||'')}</td>
      <td class="font-sm">${escHtml(r.language||'')}</td>
      <td><span class="badge ${statusCls[r.status]||'badge-draft'}">${escHtml(r.status||r.event_type||'')}</span></td>
      <td class="text-faint font-sm">${ts(r.started_ts||r.event_ts)}</td>
    </tr>`).join('');
}

// ══════════════════════════════════════════════════════════════
// Phase 11 — Input Surface (New / Import panel)
// ══════════════════════════════════════════════════════════════

async function createMarkdownDoc() {
  const title   = el('new-doc-title')?.value.trim() || 'Untitled note';
  const body    = el('new-doc-body')?.value || '';
  const topicsRaw = el('new-doc-topics')?.value || '';
  const topics  = topicsRaw.split(',').map(s => s.trim()).filter(Boolean);
  const status  = el('new-doc-status');

  if (!body.trim()) {
    if (status) status.textContent = 'Body is empty. Nothing saved.';
    return;
  }
  if (status) status.innerHTML = '<span class="spinner"></span> Saving…';

  const res = await api('/api/input/markdown', {
    method:  'POST',
    headers: {'Content-Type': 'application/json'},
    body:    JSON.stringify({ title, body, topics, target_folder: 'notes' }),
  });

  if (res.error || res.ok === false) {
    if (status) status.innerHTML = `<span class="text-red">${escHtml(res.detail || res.error || 'Save failed')}</span>`;
    return;
  }

  if (status) status.innerHTML =
    `✓ Saved <button class="btn btn-ghost btn-sm" onclick="openDrawer('${escHtml(res.doc_id)}')">Open →</button>`;
  await refreshAfterIntake();
}

function previewNewDoc() {
  const body = el('new-doc-body')?.value || '';
  const card  = el('new-doc-preview-card');
  const prev  = el('new-doc-preview');
  if (!card || !prev) return;
  card.style.display = 'block';
  prev.innerHTML = renderMarkdown(body);
  renderMathIn?.(prev);
}

async function uploadDocuments() {
  const input  = el('upload-files');
  const folder = el('upload-target-folder')?.value.trim() || 'imports';
  const status = el('upload-status');
  if (!input?.files?.length) {
    if (status) status.textContent = 'No files selected.';
    return;
  }
  if (status) status.innerHTML = '<span class="spinner"></span> Uploading…';

  const fd = new FormData();
  for (const f of input.files) fd.append('files', f);
  fd.append('target_folder', folder);

  const res = await api('/api/input/upload', { method: 'POST', body: fd });

  if (res.error || res.ok === false) {
    if (status) status.innerHTML = `<span class="text-red">${escHtml(res.detail || res.error || 'Upload failed')}</span>`;
    return;
  }

  const saved    = res.saved    || [];
  const rejected = res.rejected || [];
  if (status) {
    const rejNote = rejected.length ? ` · ${rejected.length} rejected` : '';
    status.innerHTML = `✓ ${saved.length} uploaded${rejNote}` +
      (rejected.length ? `<div class="text-red font-sm">${rejected.map(r => escHtml(r.filename + ': ' + r.reason)).join(', ')}</div>` : '');
  }
  await refreshAfterIntake();
}

async function indexFolderFromInputPanel() {
  const path   = el('index-source-path')?.value.trim();
  const status = el('index-folder-status');
  if (!path) { if (status) status.textContent = 'Enter a folder path.'; return; }
  if (status) status.innerHTML = '<span class="spinner"></span> Indexing…';

  const res = await api('/api/index', {
    method:  'POST',
    headers: {'Content-Type': 'application/json'},
    body:    JSON.stringify({ root: path }),
  });
  if (res.error || res.ok === false) {
    if (status) status.innerHTML = `<span class="text-red">${escHtml(res.detail || res.error || 'Index failed')}</span>`;
    return;
  }
  if (status) status.textContent = `✓ Indexed ${res.indexed || 0} docs.`;
  await refreshAfterIntake();
}

async function refreshAfterIntake() {
  try { if (typeof loadDashboard === 'function') await loadDashboard(); } catch (_) {}
  try { if (typeof loadLibrary   === 'function') await loadLibrary();   } catch (_) {}
  try { if (_graph) { teardownAtlas(); initAtlas(); }                   } catch (_) {}
  try { await loadRecentInput();                                         } catch (_) {}
}

async function loadRecentInput() {
  const list = el('recent-input-list');
  if (!list) return;
  const data = await api('/api/input/recent?limit=15');
  const items = (data.items || []).filter(i => i.doc_id || i.detail);
  if (!items.length) {
    list.innerHTML = '<span class="text-faint font-sm">No recent intake events.</span>';
    return;
  }
  list.innerHTML = items.map(item => {
    let detail = '';
    try { detail = JSON.parse(item.detail || '{}').path || ''; } catch (_) {}
    return `<div style="padding:6px 0;border-bottom:1px solid var(--border-dim);font-size:11px">
      <span class="text-bright">${escHtml(detail || item.doc_id || '—')}</span>
      <span class="text-faint" style="margin-left:8px">${ts(item.event_ts)}</span>
      ${item.doc_id ? `<button class="btn btn-ghost btn-sm" style="margin-left:6px" onclick="openDrawer('${escHtml(item.doc_id)}')">Open</button>` : ''}
    </div>`;
  }).join('');
}

// ══════════════════════════════════════════════════════════════
// Phase 12 — Lifecycle undo / backward movement
// ══════════════════════════════════════════════════════════════

function showMoveBackwardModal(docId) {
  const form = el(`lifecycle-backward-form-${docId}`);
  if (!form) return;
  form.style.display = form.style.display === 'none' ? 'block' : 'none';
}

async function submitMoveBackward(docId) {
  const reason = el(`lc-reason-${docId}`)?.value.trim() || null;
  const msg    = el(`lifecycle-action-msg-${docId}`);
  if (msg) msg.innerHTML = '<span class="spinner"></span>';

  const r = await api(`/api/lifecycle/${encodeURIComponent(docId)}/backward`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ reason, actor: 'user' }),
  });

  if (r.error || !r.success) {
    if (msg) msg.innerHTML = `<span class="text-red">${escHtml(r.detail || r.error || 'Move failed')}</span>`;
    return;
  }
  if (msg) msg.innerHTML = `<span class="text-green">✓ Moved: ${escHtml(r.previous_state)} → ${escHtml(r.new_state)}</span>`;
  const form = el(`lifecycle-backward-form-${docId}`);
  if (form) form.style.display = 'none';

  // Refresh drawer to show new state
  setTimeout(() => openDrawer(docId), 600);
}

async function submitUndoLifecycle(docId) {
  const msg = el(`lifecycle-action-msg-${docId}`);
  if (msg) msg.innerHTML = '<span class="spinner"></span>';

  const r = await api(`/api/lifecycle/${encodeURIComponent(docId)}/undo`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ actor: 'user' }),
  });

  if (r.error || !r.success) {
    if (msg) msg.innerHTML = `<span class="text-red">${escHtml(r.detail || r.error || 'Undo failed')}</span>`;
    return;
  }
  if (msg) msg.innerHTML = `<span class="text-green">✓ Undone → ${escHtml(r.new_state)}</span>`;
  setTimeout(() => openDrawer(docId), 600);
}

async function toggleLifecycleHistory(docId) {
  const container = el(`lifecycle-history-${docId}`);
  if (!container) return;
  if (container.style.display !== 'none' && container.dataset.loaded) {
    container.style.display = 'none';
    return;
  }
  container.style.display = 'block';
  container.dataset.loaded = '1';
  container.innerHTML = '<span class="spinner"></span>';

  const r = await api(`/api/lifecycle/${encodeURIComponent(docId)}/history?limit=30`);
  const events = r.events || [];

  if (!events.length) {
    container.innerHTML = '<span class="text-faint font-sm">No lifecycle history recorded yet.</span>';
    return;
  }

  const dirIcon = d =>
    d === 'backward' ? '←' : d === 'undo' ? '↺' : '→';
  const dirCls  = d =>
    d === 'backward' ? 'text-amber' : d === 'undo' ? 'text-blue-300' : 'text-green';

  container.innerHTML = `
    <div style="font-size:10px;color:var(--text-faint);letter-spacing:.08em;text-transform:uppercase;margin-bottom:6px">Lifecycle History</div>
    ${events.map(ev => `
      <div style="padding:5px 0;border-bottom:1px solid var(--border-dim);font-size:11px">
        <span class="${dirCls(ev.direction)}">${dirIcon(ev.direction)}</span>
        <span class="text-bright" style="margin-left:4px">${escHtml(ev.from_state)}</span>
        <span class="text-faint"> → </span>
        <span class="text-bright">${escHtml(ev.to_state)}</span>
        <span class="text-faint" style="margin-left:8px">${ts(ev.event_ts)}</span>
        <span class="badge badge-draft" style="margin-left:6px;font-size:9px">${escHtml(ev.direction)}</span>
        ${ev.reason ? `<div class="text-faint" style="margin-top:2px;padding-left:12px">${escHtml(ev.reason)}</div>` : ''}
      </div>
    `).join('')}
  `;
}

// ══════════════════════════════════════════════════════════════
// Phase 12 — System Status panel
// ══════════════════════════════════════════════════════════════

async function loadStatus() {
  const r = await api('/api/status');
  if (r.error) return;

  // Stat cards
  const serverEl = el('st-server');
  if (serverEl) { serverEl.textContent = r.server === 'ok' ? '✓ ok' : r.server; serverEl.style.color = r.server === 'ok' ? 'var(--green-bright)' : 'var(--red)'; }
  if (el('st-docs'))   el('st-docs').textContent   = r.indexed_docs ?? '—';
  if (el('st-edges'))  el('st-edges').textContent  = r.graph_edges ?? '—';
  if (el('st-queue'))  el('st-queue').textContent  = `${r.review_queue?.pending ?? 0} pending`;
  if (el('st-errors')) el('st-errors').textContent = r.index_errors ?? '—';

  // Ollama card
  const ollamaEl = el('st-ollama');
  if (ollamaEl) {
    const ol = r.ollama || {};
    if (!ol.enabled) { ollamaEl.textContent = 'disabled'; ollamaEl.style.color = 'var(--text-faint)'; }
    else if (ol.available) { ollamaEl.textContent = '✓ available'; ollamaEl.style.color = 'var(--green-bright)'; }
    else { ollamaEl.textContent = '✗ unavailable'; ollamaEl.style.color = 'var(--red)'; }
  }

  // Library KV
  const libKv = el('st-library-kv');
  if (libKv) {
    const ai = r.autoindex || {};
    const lastRun = r.last_indexed_at ? new Date(r.last_indexed_at * 1000).toLocaleString() : 'Never';
    libKv.innerHTML = `
      <div class="kv-key">Library root</div><div class="kv-val font-sm"><code>${escHtml(r.library_root || '—')}</code></div>
      <div class="kv-key">Library found</div><div class="kv-val">${r.library_found ? '<span class="text-green">✓ yes</span>' : '<span class="text-red">✗ missing</span>'}</div>
      <div class="kv-key">Last indexed</div><div class="kv-val font-sm">${escHtml(lastRun)}</div>
      <div class="kv-key">Auto-index</div><div class="kv-val font-sm">${ai.enabled ? '<span class="text-green">enabled</span>' : 'disabled (set BOH_AUTO_INDEX=true)'}</div>
      <div class="kv-key">Last run stats</div><div class="kv-val font-sm">${ai.last_indexed ?? 0} indexed · ${ai.last_skipped ?? 0} skipped · ${ai.last_failed ?? 0} failed · ${ai.elapsed_ms ?? 0}ms</div>
    `;
  }

  // Ollama KV
  const olKv = el('st-ollama-kv');
  if (olKv) {
    const ol = r.ollama || {};
    olKv.innerHTML = `
      <div class="kv-key">Enabled</div><div class="kv-val">${ol.enabled ? 'yes' : 'no'}</div>
      <div class="kv-key">Available</div><div class="kv-val">${ol.available ? '<span class="text-green">✓ yes</span>' : '✗ no'}</div>
      <div class="kv-key">Model</div><div class="kv-val">${escHtml(ol.model || '—')}</div>
      <div class="kv-key">URL</div><div class="kv-val font-sm"><code>${escHtml(ol.url || '—')}</code></div>
    `;
  }
}

// ══════════════════════════════════════════════════════════════
// Phase 12 — Auto-index trigger (dashboard + status panel)
// ══════════════════════════════════════════════════════════════

async function triggerAutoIndex(changedOnly = true) {
  const resultEl = el('st-index-result') || el('dash-library-status');
  if (resultEl) resultEl.innerHTML = '<span class="spinner"></span> Indexing…';

  const r = await api('/api/autoindex/run', {
    method:  'POST',
    headers: {'Content-Type': 'application/json'},
    body:    JSON.stringify({ changed_only: changedOnly }),
  });

  if (r.error) {
    if (resultEl) resultEl.innerHTML = `<span class="text-red">${escHtml(r.error)}</span>`;
    return;
  }

  const summary = `✓ Scanned ${r.scanned} · Indexed ${r.indexed} · Skipped ${r.skipped} · Failed ${r.failed} · ${r.elapsed_ms}ms`;
  if (resultEl) resultEl.innerHTML = `<span class="text-green">${escHtml(summary)}</span>`;

  // Refresh dashboard stats and library
  try { await loadDashboard(); } catch (_) {}
  try { if (typeof loadLibrary === 'function') await loadLibrary(); } catch (_) {}
}

// ══════════════════════════════════════════════════════════════
// Phase 12 — LLM Review Queue panel
// ══════════════════════════════════════════════════════════════

async function loadLlmQueue() {
  const statusFilter = el('llmq-status-filter')?.value || 'pending';
  const body  = el('llmq-body');
  const count = el('llmq-count');
  if (!body) return;
  body.innerHTML = '<span class="spinner"></span>';

  const r = await api(`/api/llm/queue?status=${encodeURIComponent(statusFilter)}&limit=50`);
  const items = r.items || [];

  if (count) count.textContent = `${items.length} item${items.length !== 1 ? 's' : ''}`;

  if (!items.length) {
    body.innerHTML = `<div class="empty" style="padding:24px">
      <div class="icon">◈</div>
      <div>No ${escHtml(statusFilter)} proposals in the LLM queue.</div>
      ${statusFilter === 'pending' ? '<div class="text-faint font-sm" style="margin-top:6px">Invoke Ollama from the Governance panel to generate metadata proposals.</div>' : ''}
    </div>`;
    return;
  }

  body.innerHTML = items.map(item => renderLlmQueueItem(item)).join('');

  // Update nav badge
  if (statusFilter === 'pending') {
    const badge = el('nav-llm-badge');
    if (badge) { badge.textContent = items.length; badge.classList.toggle('hidden', items.length === 0); }
  }
}

function renderLlmQueueItem(item) {
  const p = item.proposed || {};
  const conf = typeof item.confidence === 'number' ? `${Math.round(item.confidence * 100)}%` : '—';
  const isPending = item.status === 'pending';

  const topicsList = (p.proposed_topics || []).slice(0, 8).map(t => `<span class="badge badge-type">${escHtml(t)}</span>`).join(' ');

  const conflictRows = (p.conflicts || []).map(c => `
    <div class="font-sm" style="color:var(--red);margin-top:2px">
      ⚡ ${escHtml(c.reason || '')} <span class="badge badge-conflict">${escHtml(c.severity || '')}</span>
    </div>`).join('');

  const rubrixBlock = p.rubrix ? `
    <div class="font-sm" style="margin-top:4px">
      <span class="text-faint">Rubrix:</span>
      state=<code>${escHtml(p.rubrix.operator_state || '—')}</code>
      intent=<code>${escHtml(p.rubrix.operator_intent || '—')}</code>
    </div>` : '';

  return `
    <div style="padding:14px;border-bottom:1px solid var(--border-dim)">
      <div style="display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap;margin-bottom:8px">
        <div style="flex:1;min-width:0">
          <div class="text-bright font-bold font-sm" style="margin-bottom:2px">
            ${escHtml(p.proposed_title || item.file_path || item.doc_id || 'Unknown')}
          </div>
          <div class="text-faint font-sm">${escHtml(p.summary || '(no summary)')}</div>
        </div>
        <div style="display:flex;gap:4px;align-items:center;flex-shrink:0">
          <span class="badge badge-state">${escHtml(p.proposed_type || '—')}</span>
          <span class="badge badge-draft" title="LLM confidence">${conf}</span>
          <span class="badge ${item.status === 'approved' ? 'badge-canonical' : item.status === 'rejected' ? 'badge-conflict' : 'badge-state'}">${escHtml(item.status)}</span>
        </div>
      </div>

      ${topicsList ? `<div style="margin-bottom:6px">${topicsList}</div>` : ''}
      ${rubrixBlock}
      ${conflictRows}

      <div class="kv-grid" style="font-size:10px;margin-top:6px;margin-bottom:8px">
        <div class="kv-key">File</div><div class="kv-val" style="color:var(--text-faint)">${escHtml(item.file_path || '—')}</div>
        <div class="kv-key">Model</div><div class="kv-val">${escHtml(item.model || '—')}</div>
        <div class="kv-key">Queued</div><div class="kv-val">${ts(item.queued_ts)}</div>
      </div>

      <div class="alert alert-amber font-sm" style="margin-bottom:8px;padding:5px 10px">
        ⚠ Approving applies: title, summary, topics, type (if not canon). Canonical status is <strong>never applied</strong> automatically.
      </div>

      ${isPending ? `
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button class="btn btn-primary btn-sm" onclick="approveLlmItem('${escHtml(item.queue_id)}')">✓ Approve (safe fields)</button>
          <button class="btn btn-danger btn-sm"  onclick="rejectLlmItem('${escHtml(item.queue_id)}')">✗ Reject</button>
          ${item.doc_id ? `<button class="btn btn-ghost btn-sm" onclick="openDrawer('${escHtml(item.doc_id)}')">Open doc →</button>` : ''}
        </div>
        <div id="llmq-msg-${escHtml(item.queue_id)}" class="font-sm" style="margin-top:4px"></div>
      ` : `<div class="text-faint font-sm">Reviewed ${ts(item.reviewed_ts)} by ${escHtml(item.actor || '—')}</div>`}
    </div>`;
}

async function approveLlmItem(queueId) {
  const msg = el(`llmq-msg-${queueId}`);
  if (msg) msg.innerHTML = '<span class="spinner"></span>';
  const r = await api(`/api/llm/queue/${encodeURIComponent(queueId)}/approve`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ actor: 'user' }),
  });
  if (r.success) {
    if (msg) msg.innerHTML = `<span class="text-green">✓ Approved. Applied: ${escHtml(JSON.stringify(r.applied || {}))}</span>`;
    setTimeout(loadLlmQueue, 1000);
  } else {
    if (msg) msg.innerHTML = `<span class="text-red">${escHtml(r.detail || r.error || 'Approve failed')}</span>`;
  }
}

async function rejectLlmItem(queueId) {
  const msg = el(`llmq-msg-${queueId}`);
  if (msg) msg.innerHTML = '<span class="spinner"></span>';
  const r = await api(`/api/llm/queue/${encodeURIComponent(queueId)}/reject`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ actor: 'user' }),
  });
  if (r.success) {
    if (msg) msg.innerHTML = '<span class="text-green">✓ Rejected — no changes applied.</span>';
    setTimeout(loadLlmQueue, 1000);
  } else {
    if (msg) msg.innerHTML = `<span class="text-red">${escHtml(r.detail || r.error || 'Reject failed')}</span>`;
  }
}

// ══════════════════════════════════════════════════════════════
// Phase 12 — Atlas: fit-to-screen, reset, neighborhood mode
// ══════════════════════════════════════════════════════════════

function fitAtlasToScreen() {
  if (!_graph) return;
  _graph.fitView();
  _graph._renderDirty = true;
}

function resetAtlasGraph() {
  teardownAtlas();
  initAtlas();
}

function resetAtlasView() {
  if (!_graph) return;
  _graph.resetView();
  _graph._renderDirty = true;
}

function focusSelectedAtlasNode() {
  if (!_graph) return;
  _graph.focusSelected();
  _graph._renderDirty = true;
}

function zoomAtlas(factor) {
  if (!_graph) return;
  const W = _graph.canvas.width, H = _graph.canvas.height;
  _graph.zoomAt(W / 2, H / 2, factor);
  _graph._renderDirty = true;
}

function toggleAtlasNeighborhoodMode() {
  if (!_graph?.selectedNode) return;
  expandSelectedAtlasNode();
}

// ── Phase 12.3: Performance mode control ─────────────────────────────────────

function setAtlasPerfMode(mode) {
  if (!_graph) return;
  const opts = _graph.options;
  opts._perfMode = mode;

  switch (mode) {
    case 'high':
      opts.fpsTarget        = 60;
      opts.animatedRipples  = el('atlas-opt-ripples')?.checked ?? true;
      opts.edgeGlow         = el('atlas-opt-glow')?.checked ?? true;
      opts.maxRipples       = 24;
      opts.staticMode       = false;
      break;
    case 'static':
      opts.fpsTarget        = 16;   // low-rate poll loop; draw only when dirty
      opts.animatedRipples  = false;
      opts.edgeGlow         = false;
      opts.maxRipples       = 0;
      opts.staticMode       = true;
      if (el('atlas-opt-ripples')) el('atlas-opt-ripples').checked = false;
      if (el('atlas-opt-glow'))    el('atlas-opt-glow').checked    = false;
      break;
    default: // balanced
      opts.fpsTarget        = 30;
      opts.animatedRipples  = false;
      opts.edgeGlow         = false;
      opts.maxRipples       = 8;
      opts.staticMode       = false;
      if (el('atlas-opt-ripples')) el('atlas-opt-ripples').checked = false;
      if (el('atlas-opt-glow'))    el('atlas-opt-glow').checked    = false;
  }
  // Clear auto-reduce warning on mode change
  _graph._perfWarned = false;
  const warn = el('atlas-perf-warning');
  if (warn) warn.style.display = 'none';
  _graph._renderDirty = true;
}

function setAtlasOption(key, value) {
  if (!_graph) return;
  _graph.options[key] = value;
  if (key === 'animatedRipples' && !value) _graph.ripples = [];
  _graph._renderDirty = true;
}

// (Phase 12 DOMContentLoaded additions merged into the main handler above)

