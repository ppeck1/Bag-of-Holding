/* ═══════════════════════════════════════════════════════════════
   Bag of Holding v2 — SPA Application Logic
   Phase 7: Atlas visualization, document reader, KaTeX math
   All API calls target /api/* endpoints.
   State: module-level JS variables only (no localStorage).
   Routing: window.location.hash
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BOH_VERSION = 'v2-phase8';
console.info(`%c📦 Bag of Holding ${BOH_VERSION}`, 'color:#10b981;font-weight:bold;font-size:14px');
console.info('Phase 8 active: Daenary · DCNS · Drawer Viewer · Coordinate Search');

// ── Global state ──────────────────────────────────────────────
let _conflicts = [];
let _libPage = 1;
const LIB_PER_PAGE = 50;

// ── Phase 8: Drawer reader state ──────────────────────────────
let _drawerDocId   = null;
let _drawerRawText = '';
let _drawerMode    = 'rendered'; // 'rendered' | 'raw'

// ── Phase 8: Shared reader helpers ────────────────────────────

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
    fetch(`/api/docs/${encodeURIComponent(docId)}/content`),
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
  if (panelId === 'atlas' && !_graph) {
    setTimeout(initAtlas, 50); // allow CSS .active display to take effect first
  }
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
    return `
    <tr class="clickable${hasConflict?' selected':''}" onclick="openDrawer('${escHtml(d.doc_id)}')">
      <td class="path" title="${escHtml(d.path)}">${escHtml(shortPath(d.path, 52))}</td>
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

  el('doc-drawer-content').innerHTML = `
    <div style="margin-bottom:16px">
      <div class="text-faint font-sm" style="margin-bottom:4px">Document Detail</div>
      <div class="text-bright font-bold" style="font-size:14px;margin-bottom:8px">${escHtml(shortPath(doc.path, 40))}</div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        ${statusBadge(doc.status)} ${typeBadge(doc.type)} ${stateBadge(doc.operator_state)}
      </div>
    </div>

    <div class="kv-grid" style="margin-bottom:16px">
      <div class="kv-key">doc_id</div><div class="kv-val font-sm">${escHtml(doc.doc_id)}</div>
      <div class="kv-key">path</div><div class="kv-val font-sm">${escHtml(doc.path)}</div>
      <div class="kv-key">version</div><div class="kv-val">${escHtml(doc.version||'—')}</div>
      <div class="kv-key">updated</div><div class="kv-val font-sm">${ts(doc.updated_ts)}</div>
      <div class="kv-key">source_type</div><div class="kv-val">${escHtml(doc.source_type||'—')}</div>
      <div class="kv-key">operator_intent</div><div class="kv-val">${escHtml(doc.operator_intent||'—')}</div>
      <div class="kv-key">topics_tokens</div><div class="kv-val font-sm">${escHtml(doc.topics_tokens||'—')}</div>
      <div class="kv-key">plane_scope</div><div class="kv-val font-sm">${escHtml(doc.plane_scope_json||'[]')}</div>
      <div class="kv-key">corpus_class</div><div class="kv-val">${corpusBadge(doc.corpus_class)}</div>
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
      </div>
    </div>

    <!-- LLM Review -->
    <div class="accordion" style="margin-bottom:12px">
      <div class="accordion-head" onclick="toggleAccordion(this)">
        ◈ LLM Review Artifact <span class="text-faint font-sm">(non-authoritative)</span>
        <span class="chevron">▶</span>
      </div>
      <div class="accordion-body">
        <div class="alert alert-amber font-sm" style="margin-bottom:8px">
          Review artifacts are non-authoritative. Applying suggestions requires explicit user action.
        </div>
        <button class="btn btn-ghost btn-sm" onclick="loadReview('${escHtml(doc.path)}')">Generate Review →</button>
        <div id="review-out-${escHtml(docId)}" style="margin-top:8px"></div>
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
  _drawerMode  = 'rendered';
  loadDocPayload(docId).then(({ rawText, related }) => {
    _drawerRawText = rawText || '';
    renderDocBodyInto('drawer-reader-content', rawText, _drawerMode);
    renderRelatedInto('drawer-reader-related', related, 'openDrawer');
  });
}

function closeDrawer() {
  el('doc-drawer').classList.remove('open');
}

// Phase 8: Drawer rendered/raw toggle
function setDrawerMode(mode) {
  _drawerMode = mode;
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

async function loadReview(docPath) {
  const docId = docPath; // used as key only
  const outEl = document.getElementById(`review-out-${docId.replace(/\W/g,'_')}`);
  const allReviewOuts = document.querySelectorAll('[id^="review-out-"]');
  // find by content proximity
  const btn = event.target;
  const container = btn.closest('.accordion-body');
  const reviewDiv = container.querySelector('[id^="review-out-"]');
  if (!reviewDiv) return;

  reviewDiv.innerHTML = `<span class="spinner"></span> Generating…`;
  const r = await api(`/api/review/${encodeURIComponent(docPath)}`);
  if (r.error) { reviewDiv.innerHTML = `<span class="text-red">${escHtml(r.error)}</span>`; return; }

  reviewDiv.innerHTML = `
    <div class="kv-grid font-sm">
      <div class="kv-key">reviewer</div><div class="kv-val">${escHtml(r.reviewer)}</div>
      <div class="kv-key">non_authoritative</div><div class="kv-val text-amber">${r.non_authoritative}</div>
      <div class="kv-key">topics found</div><div class="kv-val">${escHtml((r.extracted_topics||[]).join(', ')||'none')}</div>
      <div class="kv-key">definitions</div><div class="kv-val">${(r.extracted_definitions||[]).length}</div>
      <div class="kv-key">suspected conflicts</div><div class="kv-val ${r.suspected_conflicts?.length?'text-red':''}">${(r.suspected_conflicts||[]).length}</div>
    </div>
    ${r.recommended_metadata_patch && Object.keys(r.recommended_metadata_patch).length ? `
    <div class="mt-8">
      <div class="text-amber font-sm">Suggested patch (requires explicit confirmation):</div>
      <pre>${escHtml(JSON.stringify(r.recommended_metadata_patch, null, 2))}</pre>
    </div>` : ''}`;
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
    const daenaryRow = r.daenary_summary
      ? `<div class="daenary-summary" style="margin-bottom:6px">◈ ${escHtml(r.daenary_summary)}</div>`
      : '';
    return `
    <div class="result-card">
      <div class="result-card-head">
        <div class="result-title">${escHtml(r.title || r.path.split('/').pop())}</div>
        ${statusBadge(r.status)} ${typeBadge(r.type)}
        ${r.has_conflict ? conflictBadge() : ''}
      </div>
      <div class="result-path">${escHtml(r.path)}</div>
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
  const root = el('index-root').value.trim() || './library';
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

  // Size canvas to its container
  const pane = el('graph-pane');
  canvas.width  = pane.offsetWidth  || 800;
  canvas.height = pane.offsetHeight || 600;

  // Load graph data
  el('graph-stats').textContent = 'Loading…';
  _graphData = await api('/api/graph?max_nodes=200');
  if (_graphData.error) { el('graph-stats').textContent = 'Error loading graph.'; return; }

  el('graph-stats').textContent =
    `${_graphData.nodes.length} nodes · ${_graphData.edges.length} edges`;

  _graph = new ForceGraph(canvas, _graphData.nodes, _graphData.edges);
  _graph.onNodeClick = (node) => openDocInReader(node.id);
  _graph.start();

  // Mouse events
  canvas.addEventListener('mousemove', (e) => {
    const r = canvas.getBoundingClientRect();
    const scaleX = canvas.width  / r.width;
    const scaleY = canvas.height / r.height;
    const node = _graph.hitTest(
      (e.clientX - r.left) * scaleX,
      (e.clientY - r.top)  * scaleY
    );
    canvas.classList.toggle('hovering', !!node);
    _graph.hoveredNode = node || null;
  });

  canvas.addEventListener('click', (e) => {
    const r = canvas.getBoundingClientRect();
    const scaleX = canvas.width  / r.width;
    const scaleY = canvas.height / r.height;
    const node = _graph.hitTest(
      (e.clientX - r.left) * scaleX,
      (e.clientY - r.top)  * scaleY
    );
    if (node) _graph.selectNode(node);
  });

  // Resize handler
  window.addEventListener('resize', () => {
    if (!_graph) return;
    canvas.width  = pane.offsetWidth;
    canvas.height = pane.offsetHeight;
  });
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
  _graph.onNodeClick = (node) => openDocInReader(node.id);
  _graph.start();
  el('graph-stats').textContent = `${filteredNodes.length} nodes · ${filteredEdges.length} edges`;
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
    this.selectedNode = null;
    this.onNodeClick  = null;
    this._raf = null;
    this._stopped = false;
    this.alpha = 1.0;

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
    const loop = () => {
      if (this._stopped) return;
      if (this.alpha > 0.005) this.tick();
      this.draw();
      this._raf = requestAnimationFrame(loop);
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
    const ctx = this.ctx;
    const W = this.canvas.width, H = this.canvas.height;
    ctx.clearRect(0, 0, W, H);

    // Background grid (subtle)
    ctx.strokeStyle = 'rgba(30,39,54,0.4)';
    ctx.lineWidth = 0.5;
    for (let x = 0; x < W; x += 60) { ctx.beginPath(); ctx.moveTo(x,0); ctx.lineTo(x,H); ctx.stroke(); }
    for (let y = 0; y < H; y += 60) { ctx.beginPath(); ctx.moveTo(0,y); ctx.lineTo(W,y); ctx.stroke(); }

    // Draw edges
    for (const edge of this.edges) {
      const s = this.nodes.find(n => n.id === edge.source);
      const t = this.nodes.find(n => n.id === edge.target);
      if (!s || !t) continue;
      const isLineage = edge.type === 'lineage';
      ctx.beginPath();
      ctx.moveTo(s.x, s.y);
      ctx.lineTo(t.x, t.y);
      ctx.strokeStyle = isLineage ? 'rgba(59,130,246,0.35)' : 'rgba(107,122,150,0.15)';
      ctx.lineWidth   = isLineage ? 1.5 : 0.8;
      ctx.setLineDash(isLineage ? [] : [3, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Ripple animations
    this.ripples = this.ripples.filter(r => r.alpha > 0.01);
    for (const r of this.ripples) {
      ctx.beginPath();
      ctx.arc(r.x, r.y, r.radius, 0, Math.PI*2);
      ctx.strokeStyle = `rgba(96,165,250,${r.alpha})`;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      r.radius += 2.5; r.alpha *= 0.94;
    }

    // Draw nodes
    const nodeMap = new Map(this.nodes.map(n => [n.id, n]));
    for (const node of this.nodes) {
      const r = this._nodeRadius(node);
      const color = this._nodeColor(node);
      const isSelected = node === this.selectedNode;
      const isHovered  = node === this.hoveredNode;
      const isAdjacent = this.selectedNode && this._adj.get(this.selectedNode.id)?.includes(node.id);

      // Glow for selected / canon
      if (isSelected || (node.corpusClass === 'CORPUS_CLASS:CANON' && this.alpha < 0.3)) {
        ctx.shadowColor = color;
        ctx.shadowBlur  = isSelected ? 14 : 6;
      }

      ctx.beginPath();
      ctx.arc(node.x, node.y, r + (isHovered ? 2 : 0), 0, Math.PI*2);
      ctx.fillStyle = isSelected ? '#60a5fa'
                    : isAdjacent ? this._lighten(color)
                    : color;
      ctx.fill();
      ctx.shadowBlur = 0;

      // Phase 8: DCNS diagnostic halos
      // Conflict halo — red outer ring
      if (node.conflictCount > 0) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 4, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(239,68,68,0.55)`;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([3, 2]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      // Stale coordinate halo — amber dashed
      if (node.expiredCoordinates > 0 && node.conflictCount === 0) {
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 4, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(245,158,11,0.45)`;
        ctx.lineWidth = 1;
        ctx.setLineDash([2, 3]);
        ctx.stroke();
        ctx.setLineDash([]);
      }
      // Uncertain coordinate halo — blue pulse dot
      if (node.uncertainCoordinates > 0) {
        const dotR = 2.5;
        ctx.beginPath();
        ctx.arc(node.x + r, node.y - r, dotR, 0, Math.PI * 2);
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

      // Labels: always for selected, for hovered, for small graphs
      if (isSelected || isHovered || (this.nodes.length <= 25 && this.alpha < 0.2)) {
        ctx.fillStyle = isSelected ? '#e6edf3' : '#b8c4d4';
        ctx.font = `${isSelected ? 11 : 10}px monospace`;
        const label = node.label.length > 22 ? node.label.slice(0, 20) + '…' : node.label;
        ctx.fillText(label, node.x + r + 4, node.y + 3.5);
      }
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
    // Primary ripple
    this.ripples.push({ x: node.x, y: node.y, radius: 12, alpha: 0.9 });
    // Ripples on connected nodes with delay (drop-and-ripple)
    const connected = this._adj.get(node.id) || [];
    connected.slice(0, 8).forEach((cid, i) => {
      const cnode = this.nodes.find(n => n.id === cid);
      if (!cnode) return;
      setTimeout(() => {
        if (this._stopped) return;
        const dist = Math.sqrt((node.x-cnode.x)**2 + (node.y-cnode.y)**2);
        const delay_alpha = Math.max(0.2, 0.6 - dist/800);
        this.ripples.push({ x: cnode.x, y: cnode.y, radius: 6, alpha: delay_alpha });
      }, 150 + i * 60);
    });
    if (this.onNodeClick) this.onNodeClick(node);
  }

  hitTest(x, y) {
    for (const node of this.nodes) {
      const dx = node.x - x, dy = node.y - y;
      const r = this._nodeRadius(node) + 4;
      if (dx*dx + dy*dy <= r*r) return node;
    }
    return null;
  }
}

// Atlas init is wired directly in nav() above.
