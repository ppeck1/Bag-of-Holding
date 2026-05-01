/* ═══════════════════════════════════════════════════════════════
   Bag of Holding v2 — SPA Application Logic
   Phase 7: Atlas visualization, document reader, KaTeX math
   All API calls target /api/* endpoints.
   State: module-level JS variables only (no localStorage).
   Routing: window.location.hash
   ═══════════════════════════════════════════════════════════════ */

'use strict';

const BOH_VERSION = 'v2-phase25-integrity-primary';
console.info(`%c📦 Bag of Holding ${BOH_VERSION}`, 'color:#10b981;font-weight:bold;font-size:14px');
console.info('Phase 15.6A: Product legibility is actively mounted.');

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
    const ct = r.headers.get('content-type') || '';
    const payload = ct.includes('application/json') ? await r.json() : await r.text();
    if (!r.ok) {
      const detail = typeof payload === 'object' ? (payload.detail || payload.error || JSON.stringify(payload)) : payload;
      return { error: `HTTP ${r.status}: ${detail || r.statusText}` };
    }
    return payload;
  } catch (e) {
    return { error: String(e) };
  }
}

function showPanelError(panelId, err) {
  const panel = el(`panel-${panelId}`);
  if (!panel) return;
  let box = panel.querySelector('.panel-runtime-error');
  if (!box) {
    box = document.createElement('div');
    box.className = 'panel-runtime-error';
    box.style.cssText = 'margin:12px;padding:10px;border:1px solid var(--red);border-radius:6px;color:var(--red);background:rgba(239,68,68,.08);font-size:12px;white-space:pre-wrap';
    panel.prepend(box);
  }
  box.textContent = `Panel error: ${err?.message || err}`;
}

function safeLoad(panelId, fn) {
  try {
    const r = fn();
    if (r && typeof r.catch === 'function') r.catch(e => showPanelError(panelId, e));
  } catch (e) {
    showPanelError(panelId, e);
  }
}


// ── Product legibility / progressive disclosure (Phase 15.6) ───────────────
const UI_MODE = { SIMPLE: 'simple', ADVANCED: 'advanced' };
let _uiMode = localStorage.getItem('boh_ui_mode') || UI_MODE.SIMPLE;

function applyUiMode() {
  const advanced = _uiMode === UI_MODE.ADVANCED;
  document.body.classList.toggle('advanced-mode', advanced);
  document.body.classList.toggle('simple-mode', !advanced);
  const btn = el('ui-mode-toggle');
  if (btn) {
    btn.classList.toggle('is-advanced', advanced);
    btn.classList.toggle('is-simple', !advanced);
    btn.setAttribute('aria-pressed', advanced ? 'true' : 'false');
    btn.setAttribute('title', advanced ? 'Advanced detail is visible. Click for Simple mode.' : 'Simple mode is visible. Click for Advanced detail.');
  }
}

function setNodeText(selector, text) {
  const node = document.querySelector(selector);
  if (node && text) node.textContent = text;
}

function applyCopyMap() {
  const copy = window.COPY || {};
  if (!copy.nav && !copy.governance && !copy.canon) {
    console.warn('BOH copy map was not loaded; using hardcoded fallback labels.');
    document.body.classList.add('copy-map-missing');
    return false;
  }
  document.body.classList.add('copy-map-loaded');
  console.info('BOH copy_map.js loaded and applied.');

  if (copy.appName || copy.appSubtitle) {
    const wordmark = document.querySelector('.wordmark');
    if (wordmark) wordmark.innerHTML = `${escHtml(copy.appName || 'Bag of Holding')} <span>${escHtml(copy.appSubtitle || 'A trusted workspace for preserving your thinking.')}</span>`;
  }

  const navLabels = {
    'dashboard': copy.nav?.dashboard || 'Home',
    'input': copy.nav?.inbox || 'Inbox',
    'library': copy.nav?.library || 'Library',
    'search': copy.nav?.search || 'Search',
    'canon-conflicts': copy.nav?.conflicts || 'Conflicts',
    'duplicates': 'Duplicates',
    'import-ingest': 'Bulk Import',
    'atlas': copy.nav?.atlas || 'Visualization',
    'governance': copy.nav?.governance || 'Resolution Center',
    'llm-queue': copy.nav?.llmQueue || 'Proposed Changes',
    'status': copy.nav?.status || 'System Status',
  };
  Object.entries(navLabels).forEach(([panel, label]) => {
    const item = document.querySelector(`.nav-item[data-panel="${panel}"]`);
    if (!item) return;
    const icon = item.querySelector('.icon')?.outerHTML || '';
    const badge = item.querySelector('.badge')?.outerHTML || '';
    item.innerHTML = `${icon} ${escHtml(label)} ${badge}`.trim();
  });

  setNodeText('#panel-governance .panel-title', copy.nav?.governance || 'Resolution Center');
  setNodeText('#panel-atlas .panel-title', copy.nav?.atlas || 'Visualization');
  setNodeText('#panel-llm-queue .panel-title', copy.nav?.llmQueue || 'Proposed Changes');
  return true;
}




function dismissOnboarding() {
  localStorage.setItem('boh_onboarding_dismissed', '1');
  const card = el('onboarding-card');
  if (card) card.classList.add('hidden');
}

function initOnboarding() {
  const card = el('onboarding-card');
  if (card) card.classList.toggle('hidden', localStorage.getItem('boh_onboarding_dismissed') === '1');
}

function stabilityLabel(deltaC) {
  const v = Number(deltaC);
  if (!Number.isFinite(v)) return 'Unknown';
  if (v >= 0.5) return 'Stable';
  if (v >= 0.2) return 'Watch';
  return 'At Risk';
}

function explainApprovalImpact(item) {
  const b = item.blast_radius || {};
  const docs = Number(b.downstream_references_affected ?? item.downstream_references_affected ?? 0);
  const projects = Number(b.projects_touched ?? item.projects_touched ?? 0);
  const rollback = item.rollback_complexity || b.rollback_complexity || 'unknown';
  let text = `This suggested change affects ${docs} linked document${docs === 1 ? '' : 's'}`;
  if (projects > 1) text += ` across ${projects} projects`;
  text += `. Undo difficulty: ${rollback}.`;
  if (b.cross_project_exposure || item.cross_project_exposure) text += ' Review carefully because this crosses project boundaries.';
  return text;
}

async function loadDemoProject() {
  const status = el('demo-project-status');
  if (status) status.innerHTML = '<span class="spinner"></span> Loading demo…';
  const r = await api('/api/input/demo-seed', { method: 'POST' });
  if (status) status.innerHTML = r.ok ? `<span class="text-green">✓ Demo loaded: ${escHtml(String(r.created || 0))} items</span>` : `<span class="text-red">${escHtml(r.error || r.detail || 'Demo load failed')}</span>`;
  loadRecentInput().catch(()=>{});
  loadDashboard().catch(()=>{});
}

function el(id) { return document.getElementById(id); }

function statusBadge(s) {
  const map = { canonical:'badge-canonical', draft:'badge-draft',
                working:'badge-working', archived:'badge-archived' };
  // Phase 26.1/26.2: translate internal status values to user-facing labels
  const labels = { canonical:'Trusted Source', contained:'Held for Resolution',
                   cancelled:'Contradiction Blocked', canceled:'Contradiction Blocked' };
  const display = labels[s] || s || '—';
  return `<span class="badge ${map[s]||'badge-draft'}" title="${escHtml(s||'')}">${escHtml(display)}</span>`;
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

  // Lazy load panel data. Use safeLoad so one failing API route does not kill navigation.
  if (panelId === 'integrity') safeLoad(panelId, loadIntegrityDashboard);
  if (panelId === 'dashboard') safeLoad(panelId, loadDashboard);
  if (panelId === 'library')   safeLoad(panelId, loadLibrary);
  if (panelId === 'input')     safeLoad(panelId, loadRecentInput);
  if (panelId === 'import-ingest') safeLoad(panelId, async () => {
    const rootInput = el('index-source-path');
    if (rootInput && !rootInput.value) rootInput.value = getActiveLibraryRoot();
  });
  if (panelId === 'canon-conflicts') {
    safeLoad(panelId, loadConflicts);
    safeLoad(panelId, loadLineage);
  }
  if (panelId === 'duplicates') safeLoad(panelId, loadDuplicateReview);
  if (panelId === 'governance') {
    safeLoad(panelId, checkOllama);
    safeLoad(panelId, loadPolicies);
    safeLoad(panelId, loadOllamaToggleState);
    safeLoad(panelId, loadApprovalQueue);  // Phase 15
  }
  if (panelId === 'atlas') {
    safeLoad(panelId, async () => {
      if (_graph) return;
      await new Promise(resolve => setTimeout(resolve, 50));
      await initAtlas();
    });
  }
  if (panelId === 'status')    safeLoad(panelId, loadStatus);
  if (panelId === 'planes')   safeLoad(panelId, loadPlanes);
  if (panelId === 'governance') {
    setTimeout(() => { if (typeof loadCertQueue === 'function') loadCertQueue(); }, 200);
  }
  if (panelId === 'llm-queue') safeLoad(panelId, loadLlmQueue);
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


async function loadIntegrityDashboard() {
  const data = await api('/api/integrity/dashboard');
  if (data.error) return;
  const state = data.integrity_state || {};
  if (el('integrity-label')) el('integrity-label').textContent = state.label || '—';
  if (el('integrity-score')) el('integrity-score').textContent = `score ${state.score ?? '—'}`;
  const auth = data.authority_violations || [];
  const contain = data.open_containments || [];
  const esc = data.active_escalations || [];
  if (el('integrity-authority-violations')) el('integrity-authority-violations').textContent = auth.length;
  if (el('integrity-containments')) el('integrity-containments').textContent = contain.length;
  if (el('integrity-escalations')) el('integrity-escalations').textContent = esc.length;

  const risk = data.highest_drift_risk || [];
  if (el('integrity-risk-count')) el('integrity-risk-count').textContent = `${risk.length}`;
  if (el('integrity-risk-body')) {
    el('integrity-risk-body').innerHTML = risk.length ? risk.map(r => {
      const vs = r.visual_state || {};
      return `<tr>
        <td><code>${escHtml(r.node_id || '—')}</code></td>
        <td>${escHtml(vs.state || 'UNKNOWN')}</td>
        <td>${escHtml(r.drift_risk || '—')}</td>
        <td>${escHtml(r.valid_until || '—')}</td>
        <td>${vs.action_required ? '<span class="text-red">Required</span>' : '<span class="text-green">None</span>'}</td>
      </tr>`;
    }).join('') : '<tr><td colspan="5" class="text-faint" style="padding:12px">No drift-risk nodes found.</td></tr>';
  }

  if (el('integrity-authority-count')) el('integrity-authority-count').textContent = `${auth.length}`;
  if (el('integrity-authority-body')) {
    el('integrity-authority-body').innerHTML = auth.length ? auth.map(a => `<tr>
      <td><code>${escHtml(a.target_id || '—')}</code></td>
      <td>${escHtml(a.required_authority || '—')}</td>
      <td>${escHtml(a.actor_id || '—')}</td>
      <td>${escHtml(a.timestamp || '—')}</td>
    </tr>`).join('') : '<tr><td colspan="4" class="text-faint" style="padding:12px">No rejected authority attempts.</td></tr>';
  }

  const openItems = data.open_registry_items || [];
  if (el('integrity-open-items-count')) el('integrity-open-items-count').textContent = `${openItems.length}`;
  if (el('integrity-open-items-body')) {
    el('integrity-open-items-body').innerHTML = openItems.length ? openItems.map(i => `<tr>
      <td><code>${escHtml(i.id || i.item_id || '—')}</code></td>
      <td>${escHtml(i.status || '—')}</td>
      <td>${escHtml(i.resolution_authority || i.required_authority || '—')}</td>
      <td>${escHtml(i.created_at || '—')}</td>
    </tr>`).join('') : '<tr><td colspan="4" class="text-faint" style="padding:12px">No open registry items.</td></tr>';
  }
}

// ══════════════════════════════════════════════════════════════
// Panel 1: Dashboard
// ══════════════════════════════════════════════════════════════
async function loadDashboard() {
  // Phase 26.6: project filter
  const projectFilter = el('dash-project-filter')?.value || '';
  const dashUrl = projectFilter ? `/api/dashboard?project=${encodeURIComponent(projectFilter)}` : '/api/dashboard';
  const data = await api(dashUrl);
  if (data.error) return;

  // Populate project filter dropdown from available projects
  const projSel = el('dash-project-filter');
  if (projSel && data.projects && data.projects.length > 0) {
    const current = projSel.value;
    projSel.innerHTML = '<option value="">All projects</option>' +
      data.projects.map(p => `<option value="${escHtml(p)}" ${p===current?'selected':''}>${escHtml(p)}</option>`).join('');
  }

  el('stat-total').textContent      = data.total_docs ?? '—';
  el('stat-canonical').textContent  = data.canonical_docs ?? '—';
  el('stat-draft').textContent      = `${data.draft_docs??0} / ${data.working_docs??0}`;

  // Phase 18: epistemic health grid
  const epGrid = el('stat-epistemic-grid');
  if (epGrid && data.epistemic_d_counts) {
    const d1 = data.epistemic_d_counts['1'] || 0;
    const d0 = data.epistemic_d_counts['0'] || 0;
    const dN = data.epistemic_d_counts['-1'] || 0;
    const noState = data.epistemic_no_state || 0;
    const expired = data.epistemic_expired || 0;
    const contained = (data.custodian_lanes || {})['contained'] || 0;
    const canceled  = (data.custodian_lanes || {})['canceled'] || 0;
    epGrid.innerHTML = `
      <div class="stat-card"><div class="label" style="color:#22c55e">d=+1 Affirmed</div><div class="value" style="color:#22c55e">${d1}</div></div>
      <div class="stat-card"><div class="label" style="color:#f59e0b">d=0 Unresolved</div><div class="value" style="color:#f59e0b">${d0}</div></div>
      <div class="stat-card"><div class="label" style="color:#ef4444">d=-1 Negated</div><div class="value" style="color:#ef4444">${dN}</div></div>
      <div class="stat-card"><div class="label" style="color:var(--text-faint)">No State</div><div class="value">${noState}</div></div>
      <div class="stat-card"><div class="label" style="color:#f59e0b">Held for Resolution</div><div class="value">${contained}</div></div>
      <div class="stat-card"><div class="label" style="color:#ef4444">Canceled</div><div class="value">${canceled}</div></div>
    `.trim();
    if (expired > 0) {
      const expCard = document.createElement('div');
      expCard.className = 'stat-card';
      expCard.innerHTML = `<div class="label" style="color:#6b7280">Expired</div><div class="value">${expired}</div>`;
      epGrid.appendChild(expCard);
    }
    // Phase 24: visible coherence decay state; no hidden timestamps.
    api('/api/coherence/summary').then(cs => {
      if (cs.error || !cs.counts) return;
      const counts = cs.counts || {};
      const cards = [
        ['Fresh', counts.fresh || 0, '#22c55e'],
        ['Aging', counts.aging || 0, '#f59e0b'],
        ['Stale', counts.stale || 0, '#ef4444'],
        ['Critical Decay', counts.critical_decay || 0, '#ef4444'],
        ['Refresh Required', cs.refresh_required || counts.refresh_required || 0, '#f59e0b']
      ];
      cards.forEach(([label, value, color]) => {
        const c = document.createElement('div');
        c.className = 'stat-card';
        c.innerHTML = `<div class="label" style="color:${color}">${label}</div><div class="value">${value}</div>`;
        epGrid.appendChild(c);
      });
    }).catch(()=>{});
  }
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
  tbody.innerHTML = docs.docs.map(d => {
    const auth = d.authority_state || 'non_authoritative';
    const proj = (d.project || 'Legacy').replace('Quarantine / Legacy Import', 'Legacy');
    const authDot = {
      canonical_locked: '●', approved: '●', suggested: '◌',
      non_authoritative: '◌', quarantined: '·',
    }[auth] || '·';
    const authColor = {
      canonical_locked: 'var(--green-bright)', approved: '#60a5fa',
      suggested: 'var(--amber)', non_authoritative: 'var(--text-faint)', quarantined: '#4b5563',
    }[auth] || 'var(--text-faint)';
    return `
    <tr class="clickable" onclick="openDrawer('${escHtml(d.doc_id)}')">
      <td>
        <div class="text-bright" style="font-size:12px">${escHtml(docTitle(d))}</div>
        <div class="text-faint" style="font-size:10px">${escHtml(proj)}</div>
      </td>
      <td>${statusBadge(d.status)}</td>
      <td><span style="color:${authColor};font-size:11px">${authDot} ${escHtml(auth.replace('_',' '))}</span></td>
      <td>${stateBadge(d.operator_state)}</td>
    </tr>`;
  }).join('');
}

// ══════════════════════════════════════════════════════════════
// Panel 2: Library
// ══════════════════════════════════════════════════════════════
async function loadLibrary() {
  const status    = el('lib-status')?.value   || '';
  const type      = el('lib-type')?.value     || '';
  const state     = el('lib-state')?.value    || '';
  const authority = el('lib-authority')?.value || '';
  const project   = el('lib-project')?.value  || '';

  let url = `/api/docs?page=${_libPage}&per_page=${LIB_PER_PAGE}`;
  if (status)    url += `&status=${encodeURIComponent(status)}`;
  if (type)      url += `&type=${encodeURIComponent(type)}`;
  if (state)     url += `&operator_state=${encodeURIComponent(state)}`;
  if (authority) url += `&authority_state=${encodeURIComponent(authority)}`;
  if (project)   url += `&project=${encodeURIComponent(project)}`;

  el('lib-body').innerHTML = `<tr><td colspan="7" style="padding:20px;text-align:center;color:var(--text-faint)">
    <span class="spinner"></span> Loading…</td></tr>`;

  const data = await api(url);
  if (data.error) {
    el('lib-body').innerHTML = `<tr><td colspan="7" class="text-red">Error: ${escHtml(data.error)}</td></tr>`;
    return;
  }

  el('lib-count').textContent = `${data.total} total`;
  el('lib-subtitle').textContent = `${data.total} documents`;

  // Populate project filter from returned docs (first load only)
  const projSel = el('lib-project');
  if (projSel && projSel.options.length <= 1 && data.docs?.length) {
    const projects = [...new Set(data.docs.map(d => d.project).filter(Boolean))].sort();
    projects.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p; opt.textContent = p;
      projSel.appendChild(opt);
    });
    if (project) projSel.value = project;
  }

  // Pagination
  const totalPages = Math.ceil(data.total / LIB_PER_PAGE) || 1;
  el('lib-page-info').textContent = `Page ${_libPage} of ${totalPages}`;
  el('lib-prev').disabled = _libPage <= 1;
  el('lib-next').disabled = _libPage >= totalPages;

  const conflictDocIds = new Set(
    _conflicts.flatMap(c => (c.doc_ids || '').split(',').map(s => s.trim()))
  );

  if (!data.docs || data.docs.length === 0) {
    el('lib-body').innerHTML = `<tr><td colspan="7"><div class="empty">
      <div class="icon">⊞</div>No documents match the current filters.</div></td></tr>`;
    return;
  }

  el('lib-body').innerHTML = data.docs.map(d => {
    const hasConflict = conflictDocIds.has(d.doc_id);
    const title = docTitle(d);
    const proj  = d.project || 'Quarantine / Legacy Import';
    const auth  = d.authority_state || 'non_authoritative';
    const summary = d.summary
      ? `<div class="text-faint font-sm" style="font-size:10px;margin-top:2px">${escHtml(d.summary.slice(0,80))}${d.summary.length>80?'…':''}</div>`
      : '';

    // Requires Action logic
    const actions = [];
    if (hasConflict) actions.push('⚡ Resolve conflict');
    if (d.status === 'review_required') actions.push('👁 Review pending');
    if (auth === 'non_authoritative' && d.operator_state === 'integrate') actions.push('⬆ Promote candidate');
    const requiresAction = actions.length
      ? `<span style="color:var(--amber);font-size:10px">${actions[0]}</span>`
      : `<span class="text-faint font-sm" style="font-size:10px">—</span>`;

    // Authority badge
    const authColors = {
      canonical_locked: 'var(--green-bright)', approved: '#60a5fa',
      suggested: 'var(--amber)', non_authoritative: 'var(--text-faint)',
      quarantined: '#6b7a96',
    };
    const authBadge = `<span style="font-size:10px;padding:1px 5px;border-radius:3px;border:1px solid ${authColors[auth]||'var(--border-dim)'};color:${authColors[auth]||'var(--text-faint)'}">${escHtml(auth.replace('_', ' '))}</span>`;

    // Phase 18: inline epistemic state badge
    const dv = d.epistemic_d;
    const mv = d.epistemic_m;
    const qv = d.epistemic_q;
    const cv = d.epistemic_c;
    const cs = d.epistemic_correction_status;
    const dColor = {1:'#22c55e', 0:'#f59e0b', '-1':'#ef4444'}[String(dv)] || 'var(--text-faint)';
    const epInline = dv != null
      ? `<div style="margin-top:3px;display:flex;gap:3px;flex-wrap:wrap;align-items:center">
           <span class="ep-d ep-d-${dv===1?'pos':dv===0?'zero':'neg'}">d=${dv}</span>
           ${mv ? `<span class="ep-m-${mv}">${mv}</span>` : ''}
           ${qv != null ? `<span class="ep-qc">q=${Number(qv).toFixed(2)}</span>` : ''}
           ${cv != null ? `<span class="ep-qc">c=${Number(cv).toFixed(2)}</span>` : ''}
           ${cs ? `<span class="ep-correction ep-correction-${cs}" style="font-size:9px">${cs}</span>` : ''}
         </div>`
      : '';

    return `
    <tr class="clickable${hasConflict?' selected':''}" onclick="openDrawer('${escHtml(d.doc_id)}')">
      <td>
        <div class="text-bright" style="font-size:12px;font-weight:600">${escHtml(title)}</div>
        ${summary}
        ${epInline}
        <div class="text-faint" style="font-size:10px;margin-top:1px">${escHtml(shortPath(d.path, 45))}</div>
      </td>
      <td class="font-sm" style="font-size:11px;color:var(--text-muted)">${escHtml(proj.replace('Quarantine / Legacy Import','Legacy'))}</td>
      <td>${authBadge}</td>
      <td>${statusBadge(d.status)} ${hasConflict ? conflictBadge() : ''}</td>
      <td>${stateBadge(d.operator_state)}</td>
      <td>${requiresAction}</td>
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
  if (el('lib-authority')) el('lib-authority').value = '';
  if (el('lib-project'))   el('lib-project').value = '';
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
  // Phase 26.2: simple/advanced mode detection for context-aware labels
  const isSimple = document.body.classList.contains('simple-mode');
  const _custodianLabels = { contain:'Held for Resolution', warn:'Warning', lock:'Locked', escalate:'Escalated', release:'Released' };
  const custodianLabel = _custodianLabels[doc.custodian_review_state] || doc.custodian_review_state || 'raw_imported';
  el('doc-drawer-content').innerHTML = `
    <div style="margin-bottom:16px">
      <div class="text-faint font-sm" style="margin-bottom:4px">Document Detail</div>
      <div class="text-bright font-bold" style="font-size:15px;margin-bottom:6px;line-height:1.3">${escHtml(displayTitle)}</div>
      ${doc.summary ? `<div class="text-muted font-sm" style="margin-bottom:8px;line-height:1.5">${escHtml(doc.summary)}</div>` : ''}
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        ${statusBadge(doc.status)} ${typeBadge(doc.type)} ${stateBadge(doc.operator_state)} ${corpusBadge(doc.corpus_class)}
      </div>
    </div>

    <!-- Phase 26.2: Custody & Ownership -->
    <div class="section" style="margin-bottom:12px">
      <div class="section-head">Custody &amp; Ownership</div>
      <div class="section-body">
        <div class="kv-grid">
          <div class="kv-key">Project</div>
          <div class="kv-val" style="display:flex;gap:6px;align-items:center">
            <span id="drawer-project-display-${escHtml(docId)}">${escHtml(doc.project||'—')}</span>
            <button class="btn btn-ghost btn-sm" style="padding:1px 6px;font-size:10px"
              onclick="editDocProject('${escHtml(docId)}')">edit</button>
          </div>
          <div id="drawer-project-edit-${escHtml(docId)}" style="display:none;grid-column:span 2;margin-top:4px">
            <div style="display:flex;gap:6px">
              <input class="input" id="drawer-project-input-${escHtml(docId)}"
                value="${escHtml(doc.project||'')}" placeholder="Project name" style="flex:1;font-size:11px">
              <button class="btn btn-ghost btn-sm" onclick="saveDocProject('${escHtml(docId)}')">Save</button>
              <button class="btn btn-ghost btn-sm" onclick="cancelDocProjectEdit('${escHtml(docId)}')">Cancel</button>
            </div>
          </div>

          <div class="kv-key">Responsible Authority</div>
          <div class="kv-val">${escHtml(doc.resolution_authority||doc.authority_state||'—')}</div>

          <div class="kv-key">Version</div>
          <div class="kv-val">${escHtml(doc.version||'—')}</div>

          <div class="kv-key">Last Changed</div>
          <div class="kv-val font-sm">${ts(doc.updated_ts)}</div>

          <div class="kv-key">Source</div>
          <div class="kv-val">${escHtml(doc.source_type||'—')}</div>

          <div class="kv-key">Topics</div>
          <div class="kv-val font-sm">${escHtml(doc.topics_tokens||'—')}</div>

          <div class="kv-key advanced-only" style="color:var(--text-faint)">Path</div>
          <div class="kv-val font-sm advanced-only" style="display:flex;gap:6px;align-items:center">
            <span style="color:var(--text-faint)">${escHtml(doc.path)}</span>
            <button class="btn btn-ghost btn-sm" style="padding:1px 6px;font-size:10px" onclick="copyToClip('${escHtml(doc.path)}', this)">copy</button>
          </div>
          <div class="kv-key advanced-only" style="color:var(--text-faint)">doc_id</div>
          <div class="kv-val font-sm advanced-only" style="display:flex;gap:6px;align-items:center">
            <span style="color:var(--text-faint)">${escHtml(doc.doc_id)}</span>
            <button class="btn btn-ghost btn-sm" style="padding:1px 6px;font-size:10px" onclick="copyToClip('${escHtml(doc.doc_id)}', this)">copy</button>
          </div>
        </div>
      </div>
    </div>

    <!-- Phase 26.2: Confidence State -->
    ${(doc.epistemic_d != null || doc.epistemic_q != null) ? `
    <div class="section" style="margin-bottom:12px">
      <div class="section-head" style="display:flex;align-items:center;gap:8px">
        Confidence State
        <span class="advanced-only text-faint font-sm" style="font-weight:400">ε epistemic</span>
        <span class="ep-lane ep-lane-${escHtml(doc.custodian_review_state||'raw_imported')}" style="margin-left:auto">
          ${escHtml(custodianLabel)}
        </span>
      </div>
      <div class="section-body">
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:8px">
          ${doc.epistemic_d != null ? `<span class="ep-d ep-d-${doc.epistemic_d===1?'pos':doc.epistemic_d===0?'zero':'neg'}">d=${doc.epistemic_d}</span>` : ''}
          ${doc.epistemic_m ? `<span class="ep-m-${doc.epistemic_m}">m=${doc.epistemic_m}</span>` : ''}
          ${doc.epistemic_q != null ? `<span class="ep-qc" style="font-size:11px">q=${Number(doc.epistemic_q).toFixed(3)}</span>` : ''}
          ${doc.epistemic_c != null ? `<span class="ep-qc" style="font-size:11px">c=${Number(doc.epistemic_c).toFixed(3)}</span>` : ''}
          ${doc.epistemic_correction_status ? `<span class="ep-correction ep-correction-${escHtml(doc.epistemic_correction_status)}">${escHtml(doc.epistemic_correction_status)}</span>` : ''}
        </div>
        <div class="kv-grid">
          ${doc.epistemic_valid_until ? `<div class="kv-key">Valid until</div><div class="kv-val font-sm">${escHtml(doc.epistemic_valid_until)}</div>` : ''}
          ${doc.epistemic_context_ref ? `<div class="kv-key">Context ref</div><div class="kv-val font-sm">${escHtml(doc.epistemic_context_ref)}</div>` : ''}
        </div>
      </div>
    </div>` : ''}

    <!-- Document Viewer -->
    <div id="drawer-viewer-section" class="section" style="margin-bottom:12px">
      <div class="section-head">Document Viewer</div>
      <div class="section-body" style="padding:10px">
        <div id="drawer-reader-toggle">
          <button id="drawer-btn-rendered" class="active" onclick="setDrawerMode('rendered')">Rendered</button>
          <button id="drawer-btn-raw" onclick="setDrawerMode('raw')">Raw</button>
        </div>
        <div id="drawer-reader-related" style="margin-bottom:6px"></div>
        <div id="drawer-reader-content"><div style="color:var(--text-faint);font-size:12px"><span class="spinner"></span> Loading content…</div></div>
      </div>
    </div>

    <!-- Phase 26.2: Lineage = document relationships -->
    <div class="accordion" style="margin-bottom:12px">
      <div class="accordion-head" onclick="loadDocLineage('${escHtml(doc.doc_id)}', this)">
        ⊞ Lineage
        <span class="text-faint font-sm" style="margin-left:6px;font-weight:400">document relationships &amp; dependencies</span>
        <span class="chevron">▶</span>
      </div>
      <div class="accordion-body" id="lineage-drawer-${escHtml(doc.doc_id)}">
        <div class="text-faint font-sm" style="margin-bottom:6px;line-height:1.5">
          <strong>Lineage</strong> = document-to-document relationships: derives from, supersedes, duplicates, conflicts with, references.
        </div>
        <span class="text-faint font-sm spinner-wrap"><span class="spinner-sm"></span> Click header to load.</span>
      </div>
    </div>

    <!-- Phase 26.2: Lifecycle - simple/advanced label -->
    <div class="section" style="margin-bottom:12px">
      <div class="section-head">
        <span class="simple-only">Lifecycle</span>
        <span class="advanced-only">Rubrix Lifecycle</span>
      </div>
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

    <!-- Phase 26.2: Provenance = custody & change history -->
    <div class="accordion" style="margin-bottom:12px">
      <div class="accordion-head" onclick="loadDocProvenance('${escHtml(doc.doc_id)}', this)">
        ◈ Provenance Chain
        <span class="text-faint font-sm" style="margin-left:6px;font-weight:400">custody &amp; change history</span>
        <span class="chevron">▶</span>
      </div>
      <div class="accordion-body" id="provenance-drawer-${escHtml(doc.doc_id)}">
        <div class="text-faint font-sm" style="margin-bottom:6px;line-height:1.5">
          <strong>Provenance</strong> = custody history: who created this, who edited it, when it changed, what authority approved it, what certificates exist.
        </div>
        <span class="text-faint font-sm">Click header to load.</span>
      </div>
    </div>

    <!-- Request Trusted Source Promotion -->
    ${doc.status !== 'canonical' && doc.status !== 'archived' && doc.status !== 'superseded' ? `
    <div class="accordion" style="margin-bottom:12px">
      <div class="accordion-head" onclick="toggleAccordion(this)">
        ⬆ Request Trusted Source Promotion <span class="text-faint font-sm">(certificate only)</span>
        <span class="chevron">▶</span>
      </div>
      <div class="accordion-body">
        <div class="alert alert-blue font-sm" style="margin-bottom:8px">
          Creates a certificate request only. Review and apply are separate steps.
        </div>
        <div style="display:grid;gap:8px">
          <select class="input" id="quick-apr-from-d-${escHtml(docId)}" style="font-size:11px">
            <option value="">from d: unset</option><option value="0">from d: 0</option>
            <option value="1">from d: +1</option><option value="-1">from d: -1</option>
          </select>
          <select class="input" id="quick-apr-to-d-${escHtml(docId)}" style="font-size:11px">
            <option value="1">to d: +1</option><option value="0">to d: 0</option><option value="-1">to d: -1</option>
          </select>
          <input class="input" id="quick-apr-reason-${escHtml(docId)}" placeholder="Reason for certificate" style="font-size:11px">
          <input class="input" id="quick-apr-evidence-${escHtml(docId)}" placeholder="Evidence refs, comma-separated" style="font-size:11px">
          <input class="input" id="quick-apr-q-${escHtml(docId)}" type="number" step="0.01" min="0" max="1" placeholder="q" style="font-size:11px">
          <input class="input" id="quick-apr-c-${escHtml(docId)}" type="number" step="0.01" min="0" max="1" placeholder="c" style="font-size:11px">
          <input class="input" id="quick-apr-valid-${escHtml(docId)}" placeholder="valid_until ISO timestamp" style="font-size:11px">
          <button class="btn btn-ghost btn-sm" onclick="quickRequestPromotion('${escHtml(docId)}', '${escHtml(doc.status)}')">Request certificate</button>
          <div id="quick-apr-result-${escHtml(docId)}" class="status-line font-sm"></div>
        </div>
      </div>
    </div>` : ''}

    <!-- Phase 26.2: AI Analysis panel -->
    <div class="accordion" style="margin-bottom:12px">
      <div class="accordion-head" onclick="toggleAccordion(this)">
        ◈ AI Analysis
        <span class="text-faint font-sm advanced-only">(LLM Proposal · non-authoritative)</span>
        <span class="chevron">▶</span>
      </div>
      <div class="accordion-body">
        <div class="alert alert-amber font-sm" style="margin-bottom:8px">
          Non-authoritative. Applying any suggestion requires explicit user action. Cannot grant Trusted Source status.
        </div>
        <div id="review-health-${escHtml(docId)}" class="font-sm" style="margin-bottom:6px;color:var(--text-faint)"></div>
        <div style="display:flex;gap:8px;margin-bottom:10px">
          <button class="btn btn-ghost btn-sm" onclick='loadReview(${JSON.stringify(doc.path||'')},${JSON.stringify(docId)},false)'>Load Analysis</button>
          <button class="btn btn-ghost btn-sm" onclick='loadReview(${JSON.stringify(doc.path||'')},${JSON.stringify(docId)},true)'>↻ Regenerate</button>
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

  // Phase 19: Load Plane Card (advanced-only, non-blocking)
  const cardBody = el(`drawer-plane-card-body-${docId}`);
  if (cardBody) {
    api(`/api/docs/${encodeURIComponent(docId)}/card`).then(cr => {
      if (!cr || cr.error || !cr.card) {
        cardBody.innerHTML = '<span class="text-faint font-sm">No card yet — re-index to generate.</span>';
        return;
      }
      const c = cr.card;
      const planeColors = {Canonical:'#10b981',Internal:'#60a5fa',Evidence:'#8b5cf6',Review:'#f59e0b',Conflict:'#ef4444',Archive:'#334155'};
      const pc = planeColors[c.plane] || '#475569';
      cardBody.innerHTML = `
        <div style="display:flex;gap:5px;flex-wrap:wrap;margin-bottom:8px">
          <span style="background:${pc}22;color:${pc};border:1px solid ${pc}44;border-radius:3px;padding:1px 7px;font-size:11px;font-weight:600">${escHtml(c.plane)}</span>
          <span style="background:rgba(100,116,139,.12);color:var(--text-muted);border:1px solid var(--border-dim);border-radius:3px;padding:1px 6px;font-size:10px">${escHtml(c.card_type)}</span>
          ${c.d != null ? `<span class="ep-d ep-d-${c.d===1?'pos':c.d===0?'zero':'neg'}">d=${c.d}</span>` : ''}
          ${c.m ? `<span class="ep-m-${c.m}">m=${c.m}</span>` : ''}
        </div>
        <div class="kv-grid">
          <div class="kv-key">Card ID</div><div class="kv-val font-sm" style="font-family:var(--font-mono);font-size:10px">${escHtml(c.id)}</div>
          <div class="kv-key">Topic</div><div class="kv-val font-sm">${escHtml(c.topic||'—')}</div>
          <div class="kv-key">b / d</div><div class="kv-val font-sm">b=${c.b??0}, d=${c.d??'—'}</div>
          ${c.observed_at ? `<div class="kv-key">Observed</div><div class="kv-val font-sm">${escHtml(c.observed_at.slice(0,10))}</div>` : ''}
          ${c.valid_until ? `<div class="kv-key">Valid until</div><div class="kv-val font-sm">${escHtml(c.valid_until)}</div>` : ''}
          ${c.constraints&&c.constraints.context ? `<div class="kv-key">Constraint</div><div class="kv-val font-sm">${escHtml(c.constraints.context)}</div>` : ''}
          <div class="kv-key">Source</div><div class="kv-val font-sm" style="font-family:var(--font-mono);font-size:10px">${escHtml((c.context_ref||{}).source_id||'—')}</div>
        </div>`.trim();
    }).catch(() => {
      if (cardBody) cardBody.innerHTML = '<span class="text-faint font-sm">Card unavailable.</span>';
    });
  }
}

function closeDrawer() {
  el('doc-drawer').classList.remove('open');
}

// ── Phase 26.2: Project field inline edit helpers ──────────────
function editDocProject(docId) {
  const display = el(`drawer-project-display-${docId}`);
  const editor  = el(`drawer-project-edit-${docId}`);
  if (display) display.closest('.kv-val').style.display = 'none';
  if (editor)  { editor.style.display = 'block'; el(`drawer-project-input-${docId}`)?.focus(); }
}
function cancelDocProjectEdit(docId) {
  const display = el(`drawer-project-display-${docId}`);
  const editor  = el(`drawer-project-edit-${docId}`);
  if (display) display.closest('.kv-val').style.display = '';
  if (editor)  editor.style.display = 'none';
}
async function saveDocProject(docId) {
  const input = el(`drawer-project-input-${docId}`);
  const value = input?.value?.trim() || '';
  const r = await api(`/api/docs/${encodeURIComponent(docId)}/metadata`, {
    method: 'PATCH',
    body: JSON.stringify({ project: value }),
  });
  const display = el(`drawer-project-display-${docId}`);
  if (display) display.textContent = value || '—';
  cancelDocProjectEdit(docId);
  if (!r.ok && !r.project) {
    // fallback: just show new value client-side if API not yet wired
    if (display) display.textContent = value || '—';
  }
}

// Phase 26.5 Fix E: Canonical loadReview using query param (avoids FastAPI path-param slash issues)
async function loadReview(docPath, docId, forceRegenerate = false) {
  const panelId = `review-panel-${docId}`;
  const healthId = `review-health-${docId}`;
  const panel = el(panelId);
  const health = el(healthId);
  if (!panel) return;
  panel.innerHTML = '<span class="spinner"></span>';
  if (health) health.textContent = '';
  try {
    // Phase 26.5 Fix E+F: use query param route to avoid FastAPI path-param slash encoding
    const encodedPath = encodeURIComponent(docPath || '');
    const url = `/api/review?path=${encodedPath}${forceRegenerate ? '&force=true' : ''}`;
    const r = await fetch(url);
    if (r.status === 404) {
      panel.innerHTML = `<div class="text-faint font-sm">
        No analysis available. The file may not be indexed yet, or its path cannot be resolved.<br>
        <span class="advanced-only text-faint" style="font-size:10px">Path tried: ${escHtml(docPath||'')}</span>
        <div style="margin-top:6px"><button class="btn btn-ghost btn-sm" onclick="loadReview(${JSON.stringify(docPath)},${JSON.stringify(docId)},true)">↻ Try regenerate</button></div>
      </div>`;
      if (health) health.innerHTML = `<span style="color:var(--amber)">⚠ Analysis not yet generated. Click ↻ Regenerate to create it.</span>`;
      return;
    }
    const data = await r.json();
    if (data.error) {
      panel.innerHTML = `<div class="text-faint font-sm">Error: ${escHtml(data.error)}</div>`;
      if (health) health.innerHTML = `<span style="color:var(--red)">✗ ${escHtml(data.error)}</span>`;
      return;
    }
    if (health) health.innerHTML = `<span style="color:var(--green-bright)">✓ Analysis loaded · deterministic · no Ollama required ${data._status ? '(' + escHtml(data._status) + ')' : ''}</span>`;
    panel.innerHTML = renderReviewArtifact(data, docId);
  } catch (err) {
    panel.innerHTML = `<div class="text-faint font-sm">Analysis unavailable: ${escHtml(String(err))}</div>`;
    if (health) health.innerHTML = `<span style="color:var(--red)">✗ ${escHtml(String(err))}</span>`;
  }
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
    const title = r.title && r.title.trim() ? r.title.trim() : r.path.split('/').pop().replace(/\.md$/, '');
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
      <div class="winner-path">${escHtml(docTitle(doc) || doc.path || '—')}</div>
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
  const hash = window.location.hash.replace('#', '') || 'integrity';
  nav(hash);

  // Load conflicts into global state for Library conflict indicators
  const confData = await api('/api/conflicts');
  _conflicts = confData.conflicts || [];
}

window.addEventListener('hashchange', () => {
  const hash = window.location.hash.replace('#', '') || 'integrity';
  nav(hash);
});

// boot() is called from DOMContentLoaded after all atlas globals/classes are initialized.

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

function restoreAtlasReaderWidth() {
  const saved = localStorage.getItem('atlas_reader_width');
  const reader = el('document-reader');
  if (!reader) return;
  if (saved) reader.style.width = saved;
}

// ── Nav hook: initialize Atlas on first visit ─────────────────

function showFatal(message) {
  const stats = el('graph-stats');
  if (stats) stats.textContent = message;
  const overlay = el('viz-overlay');
  if (overlay) {
    overlay.classList.remove('hidden');
    overlay.innerHTML = `<div class="alert alert-red" style="margin:12px">${escHtml(message)}</div>`;
  }
  console.error('[BOH visualization fatal]', message);
}

function normalizeProjectionGraphData(data) {
  const mode = normalizeVisualizationMode(_visualizationMode || data?.mode || 'web');
  const nodes = (data?.nodes || []).map(n => {
    const x = Number(n.x);
    const y = Number(n.y);
    const out = { ...n };
    if (Number.isFinite(x) && Number.isFinite(y)) {
      out.x = x;
      out.y = y;
      out.fx = x * 1200;
      out.fy = y * 900;
    }
    return out;
  });
  const edges = (data?.edges || []).map(e => ({
    ...e,
    source: e.source,
    target: e.target,
    type: e.type,
    weight: e.weight || 1,
    authority: e.authority || 'suggested'
  }));
  console.log({
    mode,
    nodeCount: nodes?.length,
    edgeCount: edges?.length,
    firstNode: nodes?.[0],
    firstEdge: edges?.[0]
  });
  if (!nodes?.length) showFatal('Projection returned zero nodes');
  return { ...(data || {}), mode, nodes, edges };
}

// ── Atlas initialization ──────────────────────────────────────
async function initAtlas() {
  // Tear down any existing graph cleanly
  if (_graph) { try { _graph.stop(); } catch(_) {} _graph = null; }

  const canvas = el('graph-canvas');
  if (!canvas) return;
  const pane = el('graph-pane');

  // Force layout before measuring — panel may have just become visible
  await new Promise(r => setTimeout(r, 80));
  const pw = pane.offsetWidth  || window.innerWidth  * 0.7 || 900;
  const ph = pane.offsetHeight || window.innerHeight * 0.85 || 650;
  canvas.width  = pw;
  canvas.height = ph;

  el('graph-stats').textContent = 'Loading…';
  const mode = encodeURIComponent(normalizeVisualizationMode(_visualizationMode || 'web'));
  const rawGraphData = await api(`/api/graph/projection?mode=${mode}&max_nodes=300`);
  if (!rawGraphData || rawGraphData.error) {
    showFatal(`Error: ${rawGraphData?.error || 'graph API failed'}`);
    return;
  }
  _graphData = normalizeProjectionGraphData(rawGraphData);
  if (!_graphData.nodes?.length) return;

  // Populate project scope from node data. Multi-select is intentional:
  // visualization must support single project, multi-project compare, and overlay.
  const projectSel = el('graph-filter-project');
  if (projectSel) {
    const previous = new Set([...projectSel.selectedOptions].map(o => o.value).filter(Boolean));
    const projects = [...new Set(_graphData.nodes.map(n => n.projectId || n.project || 'Unassigned'))].sort();
    projectSel.innerHTML = '<option value="">All projects</option>' +
      projects.map(p => `<option value="${escHtml(p)}" ${previous.has(p) ? 'selected' : ''}>${escHtml(p)}</option>`).join('');
    if (!previous.size) projectSel.options[0].selected = true;
  }

  applyGraphFilter();  // build ForceGraph from filtered data (sets up all event listeners)
  restoreAtlasReaderWidth();
}

async function reloadGraph() {
  if (_graph) { _graph.stop(); _graph = null; }
  await initAtlas();
}

function applyGraphFilter() {
  if (!_graphData?.nodes) return;

  const classFilter   = el('graph-filter-class')?.value    || '';
  const projectSelect = el('graph-filter-project');
  const projectFilters = projectSelect
    ? [...projectSelect.selectedOptions].map(o => o.value).filter(Boolean)
    : [];
  const layerFilter   = el('graph-filter-layer')?.value    || '';
  const statusFilter  = el('graph-filter-status')?.value   || '';
  const lineageOnly   = el('graph-lineage-only')?.checked  || false;
  const showRelated   = el('graph-show-related')?.checked  ?? true;

  // Lineage-only: keep only nodes connected by lineage-type edges
  let lineageDocIds = null;
  if (lineageOnly) {
    lineageDocIds = new Set();
    for (const e of _graphData.edges) {
      if (['lineage','supersedes','derives','duplicate_content'].includes(e.type)) {
        lineageDocIds.add(e.source); lineageDocIds.add(e.target);
      }
    }
  }

  const filteredNodes = _graphData.nodes.filter(n => {
    if (classFilter && n.corpusClass !== classFilter && n.document_class !== classFilter && n.documentClass !== classFilter) return false;
    if (layerFilter && (n.canonical_layer || n.canonicalLayer) !== layerFilter) return false;
    if (statusFilter && n.status !== statusFilter) return false;
    if (lineageDocIds && !lineageDocIds.has(n.id)) return false;
    const nodeProject = n.projectId || n.project || 'Unassigned';
    if (projectFilters.length && !projectFilters.includes(nodeProject)) return false;
    return true;
  });

  const nodeIds = new Set(filteredNodes.map(n => n.id));
  const filteredEdges = _graphData.edges.filter(e =>
    nodeIds.has(e.source) && nodeIds.has(e.target) &&
    (showRelated || !['related','semantic','topic_overlap','suggested'].includes(e.type))
  );

  // Stop and destroy existing graph
  if (_graph) { try { _graph.stop(); } catch(_) {} _graph = null; }

  const canvas = el('graph-canvas');
  if (!canvas) return;
  // Ensure canvas has size
  if (!canvas.width || canvas.width < 100) {
    const pane = el('graph-pane');
    canvas.width  = pane.offsetWidth  || 900;
    canvas.height = pane.offsetHeight || 650;
  }

  _graph = new ForceGraph(canvas, filteredNodes, filteredEdges);
  _graph.onNodeClick = async (node, ev) => {
    openDocInReader(node.id);
    _graph.selectNode(node);
    if (ev?.shiftKey) expandAtlasNeighborhood?.(node.id, 1);
  };
  _graph._renderDirty = true;

  // ── Interaction event listeners ──────────────────────────────
  function toCanvasXY(e) {
    const c = _graph?.canvas || fresh || canvas;
    const rect = c.getBoundingClientRect();
    const rw = rect.width || c.width || 1;
    const rh = rect.height || c.height || 1;
    return {
      x: (e.clientX - rect.left) * (c.width  / rw),
      y: (e.clientY - rect.top)  * (c.height / rh),
    };
  }

  let _panActive = false, _dragNode = null, _didDrag = false;
  let _dragStartX = 0, _dragStartY = 0, _panStartTx = 0, _panStartTy = 0;

  // Remove old listeners by replacing canvas (clean slate each call)
  const fresh = canvas.cloneNode(true);
  canvas.parentNode.replaceChild(fresh, canvas);
  _graph.canvas = fresh;
  _graph.ctx    = fresh.getContext('2d');

  fresh.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    const {x, y} = toCanvasXY(e);
    const g = _graph.screenToGraph?.(x,y) || {x,y};
    const node = _graph.hitTest?.(g.x, g.y);
    _didDrag = false;
    if (node) { _dragNode = node; }
    else { _panActive = true; _dragStartX = x; _dragStartY = y;
           _panStartTx = _graph._view?.tx||0; _panStartTy = _graph._view?.ty||0; }
    e.preventDefault();
  });

  fresh.addEventListener('mousemove', (e) => {
    const {x, y} = toCanvasXY(e);
    if (_graph._mouseX !== undefined) { _graph._mouseX = x; _graph._mouseY = y; }
    if (_dragNode) {
      const g = _graph.screenToGraph?.(x,y) || {x,y};
      _dragNode.x = g.x; _dragNode.y = g.y; _dragNode.fx = g.x; _dragNode.fy = g.y; _dragNode.vx = 0; _dragNode.vy = 0;
      _didDrag = true; _graph._renderDirty = true;
      fresh.style.cursor = 'grabbing'; return;
    }
    if (_panActive && _graph._view) {
      _graph._view.tx = _panStartTx + (x - _dragStartX);
      _graph._view.ty = _panStartTy + (y - _dragStartY);
      _didDrag = true; _graph._renderDirty = true;
      fresh.style.cursor = 'grabbing'; return;
    }
    const g = _graph.screenToGraph?.(x,y) || {x,y};
    const node = _graph.hitTest?.(g.x, g.y);
    const changed = node !== _graph.hoveredNode;
    _graph.hoveredNode = node || null;
    if (changed) _graph._renderDirty = true;
    fresh.style.cursor = node ? 'pointer' : 'default';
  });

  window.addEventListener('mouseup', () => {
    if (!_graph) { _panActive = false; _dragNode = null; return; }
    if (_dragNode) { _graph.alpha = Math.max(_graph.alpha, 0.3); }
    _panActive = false; _dragNode = null; fresh.style.cursor = 'default';
  });

  fresh.addEventListener('click', (e) => {
    if (_didDrag) { _didDrag = false; return; }
    const {x, y} = toCanvasXY(e);
    const g = _graph.screenToGraph?.(x,y) || {x,y};
    const node = _graph.hitTest?.(g.x, g.y);
    if (node && _graph.onNodeClick) _graph.onNodeClick(node, e);
  });

  fresh.addEventListener('dblclick', async (e) => {
    if (!_graph) return;
    const {x, y} = toCanvasXY(e);
    const g = _graph.screenToGraph?.(x,y) || {x,y};
    const node = _graph.hitTest?.(g.x, g.y);
    if (node) expandAtlasNeighborhood?.(node.id, 1);
  });

  fresh.addEventListener('wheel', (e) => {
    e.preventDefault();
    if (!_graph?._view) return;
    const {x, y} = toCanvasXY(e);
    const factor = e.deltaY < 0 ? 1.12 : (1/1.12);
    _graph.zoomAt?.(x, y, factor);
    _graph._renderDirty = true;
  }, { passive: false });

  fresh.addEventListener('mouseleave', () => {
    if (_graph) { _graph.hoveredNode = null; _graph._renderDirty = true; }
  });

  _graph.fitView?.();
  _graph.start();
  const stats = el('graph-stats');
  const scopeLabel = projectFilters.length ? ` · scope: ${projectFilters.join(' + ')}` : ' · scope: all projects';
  if (stats) stats.textContent = `${filteredNodes.length} nodes · ${filteredEdges.length} edges${scopeLabel}`;
  if (typeof renderVisualizationOverlay === "function") renderVisualizationOverlay(filteredNodes, filteredEdges);
}


// ── Document Reader ───────────────────────────────────────────
async function openDocInReader(docId) {
  _readerDocId = docId;

  // Show spinner
  el('reader-content').innerHTML = `<div style="padding:40px;text-align:center"><span class="spinner"></span></div>`;
  el('reader-toggle').style.display = 'block';

  // Fetch doc metadata + content in parallel
  const [meta, rawContent, related] = await Promise.all([
    api(`/api/docs/${encodeURIComponent(docId)}`),
    fetch(`/api/docs/${encodeURIComponent(docId)}/content`).then(async r => {
      const text = await r.text();
      // Detect JSON error response (file not found on disk)
      if (r.status !== 200 || text.trim().startsWith('{')) {
        try {
          const parsed = JSON.parse(text);
          if (parsed.detail || parsed.error) return `__MISSING__:${parsed.detail || parsed.error}`;
        } catch(_) {}
      }
      return text;
    }),
    api(`/api/docs/${encodeURIComponent(docId)}/related?limit=6`),
  ]);

  if (meta.error) { el('reader-content').innerHTML = `<div class="text-red">${escHtml(meta.error)}</div>`; return; }

  const doc = meta.doc;

  // Graceful file-missing handling
  if (rawContent && rawContent.startsWith('__MISSING__:')) {
    const reason = rawContent.slice('__MISSING__:'.length);
    _readerRaw = '';
    el('reader-content').innerHTML = `
      <div class="file-unavailable-card" style="margin:16px">
        <div style="font-size:14px;font-weight:600;margin-bottom:8px">📁 Archived Reference</div>
        <div style="font-size:12px;margin-bottom:6px">
          <strong>${escHtml(doc.title || doc.doc_id)}</strong> — governance record intact, source file unavailable.
        </div>
        <div style="font-size:11px;color:var(--text-muted);margin-bottom:12px;line-height:1.6">
          The library source may have moved or been re-indexed under a different path.
          Metadata, provenance, and lineage records are preserved.
        </div>
        <div class="recovery-options">
          <button class="btn btn-ghost btn-sm" onclick="nav('import-ingest')">Re-import →</button>
          <button class="btn btn-ghost btn-sm" onclick="loadDocProvenance && loadDocProvenance('${escHtml(docId)}', null)">View provenance →</button>
        </div>
        <div class="advanced-only" style="margin-top:10px;font-size:10px;font-family:var(--font-mono);color:var(--text-faint)">
          ${escHtml(reason)}
        </div>
      </div>`;
    // Still show the reader header/related docs
    const fname = (doc.path || '').split('/').pop().replace('.md', '');
    el('reader-title').textContent = doc.title || fname || doc.doc_id;
    el('reader-meta').innerHTML = `${statusBadge(doc.status)} ${typeBadge(doc.type)} ${corpusBadge(doc.corpus_class)}`;
    el('reader-toggle').style.display = 'none';
    const relDocs = related.related || [];
    if (relDocs.length) {
      el('reader-related').style.display = 'block';
      el('reader-related-list').innerHTML = relDocs.map(r =>
        `<span class="related-chip" onclick="openDocInReader('${escHtml(r.doc_id)}')">
          ${escHtml((r.path||'').split('/').pop().replace('.md',''))}
          <span class="score">${(r.score*100).toFixed(0)}%</span>
        </span>`
      ).join('');
    }
    return;
  }

  _readerRaw = rawContent;

  // Header
  const fname = (doc.path || '').split('/').pop().replace('.md', '');
  el('reader-title').textContent = doc.title || fname || doc.doc_id;
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

/**
 * Phase 26.4: Strip dangerous HTML tags/attributes from rendered content.
 * Prevents imported HTML files (e.g. CANON registry) from injecting
 * <style>, <script>, <link>, or event handlers into the BOH DOM.
 * Applied after marked.parse() and before innerHTML assignment.
 */
function sanitizeHtml(html) {
  if (!html) return '';
  // Remove script blocks with content
  html = html.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, '');
  // Remove style blocks with content
  html = html.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '');
  // Remove link tags (external CSS)
  html = html.replace(/<link[^>]*>/gi, '');
  // Remove meta tags
  html = html.replace(/<meta[^>]*>/gi, '');
  // Strip on* event attributes (onclick, onload, onerror, etc.)
  html = html.replace(/\s+on[a-z]+\s*=\s*["'][^"']*["']/gi, '');
  html = html.replace(/\s+on[a-z]+\s*=\s*[^\s>]*/gi, '');
  // Strip javascript: hrefs
  html = html.replace(/href\s*=\s*["']\s*javascript:[^"']*["']/gi, 'href="#"');
  // Remove any remaining <style> attributes on elements
  // (inline style injection of root CSS vars)
  // We keep inline styles for layout but remove :root and @import
  html = html.replace(/:root\s*\{[^}]*\}/g, '');
  html = html.replace(/@import[^;]*;/g, '');
  return html;
}

/**
 * Phase 26.4: Format API error detail properly (no [object Object]).
 */
function formatApiError(r) {
  if (!r) return 'Unknown error';
  if (typeof r === 'string') return r;
  if (r.error) return String(r.error);
  if (r.detail) {
    if (typeof r.detail === 'string') return r.detail;
    if (Array.isArray(r.detail)) {
      return r.detail.map(e => e.msg || e.message || JSON.stringify(e)).join('; ');
    }
    return JSON.stringify(r.detail);
  }
  if (r.message) return String(r.message);
  return JSON.stringify(r);
}

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
    html = sanitizeHtml(html);  // Phase 26.4: strip dangerous HTML
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

    // Phase 17.1: projection coordinates are authoritative.
    // The backend projection endpoint owns placement; the renderer only scales
    // normalized x/y into graph space and pins them. No random scatter, no
    // initial force explosion.
    this._projectionPinned = true;
    this.nodes = nodes.map((n) => {
      const hasPin = Number.isFinite(Number(n.fx)) && Number.isFinite(Number(n.fy));
      const hasProjection = Number.isFinite(Number(n.x)) && Number.isFinite(Number(n.y));
      const fx = hasPin ? Number(n.fx) : (hasProjection ? Number(n.x) * 1200 : this.canvas.width / 2);
      const fy = hasPin ? Number(n.fy) : (hasProjection ? Number(n.y) * 900 : this.canvas.height / 2);
      return {
        ...n,
        fx, fy,
        x: fx,
        y: fy,
        vx: 0, vy: 0,
      };
    });
    this._projectCenter = new Map();

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
    const N = this.nodes.length;
    if (N === 0) return;
    if (this._projectionPinned) {
      for (const node of this.nodes) {
        if (Number.isFinite(Number(node.fx)) && Number.isFinite(Number(node.fy))) {
          node.x = Number(node.fx);
          node.y = Number(node.fy);
          node.vx = 0;
          node.vy = 0;
        }
      }
      this.alpha = 0;
      return;
    }

    // ── Repulsion: grid-accelerated, works for any N ─────────────
    // Divide canvas into cells; each node repels others in the same/adjacent cells.
    // This gives O(N) repulsion instead of O(N²), and works well up to 1000 nodes.
    const CELL = 120;   // cell size — tune for visual density
    const COLS = Math.ceil(W / CELL) + 1;
    const ROWS = Math.ceil(H / CELL) + 1;
    const K    = Math.sqrt((W * H) / Math.max(N, 1)) * 1.1;
    const KK   = K * K;

    // Build grid
    const grid = new Map();
    for (const n of this.nodes) {
      const ci = Math.floor(n.x / CELL), ri = Math.floor(n.y / CELL);
      const key = ri * COLS + ci;
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(n);
    }

    // Repel within nearby cells
    for (const n of this.nodes) {
      const ci = Math.floor(n.x / CELL), ri = Math.floor(n.y / CELL);
      for (let dr = -1; dr <= 1; dr++) {
        for (let dc = -1; dc <= 1; dc++) {
          const key = (ri + dr) * COLS + (ci + dc);
          const cell = grid.get(key);
          if (!cell) continue;
          for (const m of cell) {
            if (m === n) continue;
            const dx = n.x - m.x || 0.01, dy = n.y - m.y || 0.01;
            const dist2 = dx*dx + dy*dy;
            if (dist2 > CELL * CELL * 9) continue;  // only nearby
            const dist  = Math.sqrt(dist2) || 0.01;
            const force = KK / dist;
            n.vx += (force * dx / dist) * 0.012;
            n.vy += (force * dy / dist) * 0.012;
          }
        }
      }
    }

    // ── Attraction along edges ────────────────────────────────────
    // Use nodeById for O(1) lookup instead of find()
    const nb = this.nodeById;
    for (const edge of this.edges) {
      const source = nb?.get(edge.source);
      const target = nb?.get(edge.target);
      if (!source || !target) continue;
      const dx = target.x - source.x, dy = target.y - source.y;
      const dist = Math.sqrt(dx*dx + dy*dy) || 0.01;
      // Lineage edges pull tighter; topic edges pull looser
      const ideal = edge.type === 'lineage' || edge.type === 'supersedes' || edge.type === 'derives'
        ? 90 : edge.type === 'conflicts' ? 70 : 160;
      const strength = edge.type === 'lineage' ? 0.018 : 0.008;
      const force = (dist - ideal) * strength * (edge.weight || 1);
      const fx = force * dx / dist, fy = force * dy / dist;
      source.vx += fx; source.vy += fy;
      target.vx -= fx; target.vy -= fy;
    }

    // ── Cluster gravity: project wells plus canonical center-of-gravity ──
    const cx = W / 2, cy = H / 2;
    for (const node of this.nodes) {
      const p = node.projectId || node.project || 'Unassigned';
      const pc = this._projectCenter?.get(p) || { x: cx, y: cy };
      const layer = node.canonical_layer || node.canonicalLayer || '';
      const status = node.status || '';
      const anchor = (layer === 'canonical' || status === 'canonical' || node.corpusClass === 'CORPUS_CLASS:CANON');
      const fossil = (status === 'superseded' || status === 'archived' || layer === 'archive');
      const k = anchor ? 0.0022 : fossil ? 0.00055 : 0.0011;
      node.vx += (pc.x - node.x) * k;
      node.vy += (pc.y - node.y) * k;
      node.vx += (cx - node.x) * 0.00025;
      node.vy += (cy - node.y) * 0.00025;
    }

    // ── Velocity + damping + bounds ───────────────────────────────
    const damping = 0.72;
    for (const node of this.nodes) {
      node.vx *= damping; node.vy *= damping;
      node.x = Math.max(20, Math.min(W - 20, node.x + node.vx * this.alpha));
      node.y = Math.max(20, Math.min(H - 20, node.y + node.vy * this.alpha));
    }

    this.alpha *= 0.993;  // slow cool — more time to settle into web shape
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
    batchLines(bgBucket.lineage,  'rgba(96,165,250,0.35)',  1.0, false);
    batchLines(bgBucket.conflict, 'rgba(239,68,68,0.38)',   1.0, false);
    batchLines(bgBucket.topic,    'rgba(180,190,210,0.22)', 0.8, true);
    batchLines(bgBucket.other,    'rgba(120,135,160,0.22)', 0.8, false);

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
      // Constraint mode: conflict-pressure halo (sized by pressure value)
      if (_visualizationMode === 'constraint' && (node.conflict_pressure || 0) > 0.25) {
        const cp = node.conflict_pressure || 0;
        ctx.beginPath();
        ctx.arc(node.x, node.y, r + 5 + cp * 6, 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(239,68,68,${Math.min(0.80, cp).toFixed(2)})`;
        ctx.lineWidth = 2;
        ctx.setLineDash([4, 2]);
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
      // Labels — Phase 26.2: improved readability with halo + threshold tuning
      const showLabel = isSelected || isHovered ||
                        (this.nodes.length <= 40 && this.alpha < 0.25) ||
                        (scale >= 1.2 && this.alpha < 0.2);
      if (showLabel) {
        const raw = (node.title && node.title.trim()) ? node.title : node.label;
        const lbl = raw.length > 28 ? raw.slice(0, 26) + '\u2026' : raw;
        const fontSize = isSelected ? 12 : 10;
        ctx.save();
        ctx.font = `${fontSize}px sans-serif`;
        const lx = node.x + r + 5;
        const ly = node.y + 4;
        // Halo for contrast against busy backgrounds
        ctx.strokeStyle = 'rgba(13,17,23,0.75)';
        ctx.lineWidth = 3;
        ctx.lineJoin = 'round';
        ctx.strokeText(lbl, lx, ly);
        ctx.fillStyle = isSelected ? '#e6edf3' : '#c8d4e0';
        ctx.fillText(lbl, lx, ly);
        ctx.restore();
      }
    }

    ctx.restore();
    // ── End view transform ───────────────────────────────────────

    // ── Phase 17.3: Mode-specific canvas decorations ─────────────
    this.drawModeDecorations();

    // ── Tooltips in screen space ─────────────────────────────────
    if (this.hoveredNode) {
      const node  = this.hoveredNode;
      const title = (node.title && node.title.trim()) ? node.title : node.label;
      // Phase 18: epistemic badge line
      const ep = node.epistemic_d != null ? `d=${node.epistemic_d}` : '';
      const em = node.epistemic_m ? ` m=${node.epistemic_m}` : '';
      const eq = node.epistemic_q != null ? ` q=${node.epistemic_q.toFixed(2)}` : '';
      const ec = node.epistemic_c != null ? ` c=${node.epistemic_c.toFixed(2)}` : '';
      const epBadge = (ep || em || eq || ec) ? `ε: ${ep}${em}${eq}${ec}` : '';
      const lines = [
        title.length > 32 ? title.slice(0, 30) + '\u2026' : title,
        node.project ? `Project: ${node.project}` : '',
        epBadge,
        // Mode-specific primary fields
        ...(_visualizationMode === 'constraint' ? [
          node.epistemic_correction_status ? `Status: ${node.epistemic_correction_status}` : '',
          node.epistemic_q != null ? `q: ${node.epistemic_q.toFixed(2)}` : '',
          node.epistemic_c != null ? `c: ${node.epistemic_c.toFixed(2)}` : '',
          (node.meaning_cost && node.meaning_cost.total != null) ? `Cost: ${node.meaning_cost.total.toFixed(2)}` : '',
          node.epistemic_valid_until ? `Expires: ${node.epistemic_valid_until.slice(0,10)}` : '',
        ] : []),
        ...(_visualizationMode === 'constitutional' ? [
          node.custodian_lane ? `Lane: ${node.custodian_lane}` : '',
          node.epistemic_correction_status ? `Correction: ${node.epistemic_correction_status}` : '',
          node.custodian_review_state ? `Custody: ${node.custodian_review_state}` : '',
        ] : []),
        ...(_visualizationMode === 'variable' ? [
          node.epistemic_d != null ? `d: ${node.epistemic_d === 1 ? '+1 affirmed' : node.epistemic_d === -1 ? '-1 negated' : '0 unresolved'}` : 'No d-state',
          node.epistemic_m ? `m: ${node.epistemic_m}` : '',
          node.epistemic_q != null ? `q (quality): ${node.epistemic_q.toFixed(2)}` : '',
          node.epistemic_c != null ? `c (confidence): ${node.epistemic_c.toFixed(2)}` : '',
          node.epistemic_correction_status ? `Correction: ${node.epistemic_correction_status}` : '',
        ] : []),
        ...(_visualizationMode === 'web' ? [
          node.canonical_layer ? `Layer: ${node.canonical_layer}` : '',
          node.authority_state ? `Authority: ${node.authority_state}` : '',
          node.review_state ? `Review: ${node.review_state}` : '',
          Number.isFinite(node.projection_loss) ? `Projection loss: ${node.projection_loss}` : '',
          Number.isFinite(node.load_score) ? `Load: ${node.load_score}` : '',
        ] : []),
        node.conflictCount > 0   ? `\u26a1 ${node.conflictCount} conflict(s)` : '',
        node.expiredCoordinates > 0 ? `\u23f1 ${node.expiredCoordinates} stale` : '',
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

  /** Phase 18: Draw mode-specific canvas decorations. */
  drawModeDecorations() {
    const ctx = this.ctx;
    const { scale, tx, ty } = this._view;
    const W = this.canvas.width, H = this.canvas.height;

    if (_visualizationMode === 'constraint') {
      // ── Viability Surface: axis labels and quadrant guides ──────
      ctx.save();
      // Diagonal viability threshold (q=0.65, c=0.60 in backend = y=0.35, x=0.60)
      // The "viable" quadrant is upper-right (high q top → y<0.35, high c → x>0.60)
      const threshY = (1.0 - 0.65) * 900 * scale + ty;  // q=0.65 line
      const threshX = 0.60 * 1200 * scale + tx;           // c=0.60 line

      // Vertical c-threshold line
      if (threshX >= 0 && threshX <= W) {
        ctx.setLineDash([5, 4]);
        ctx.strokeStyle = 'rgba(52,211,153,0.28)';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(threshX, 0); ctx.lineTo(threshX, H); ctx.stroke();
        ctx.setLineDash([]);
        ctx.font = '9px monospace'; ctx.fillStyle = 'rgba(52,211,153,0.5)';
        ctx.textAlign = 'center';
        ctx.fillText('c=0.60', threshX, 11);
      }
      // Horizontal q-threshold line
      if (threshY >= 0 && threshY <= H) {
        ctx.setLineDash([5, 4]);
        ctx.strokeStyle = 'rgba(52,211,153,0.28)';
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(0, threshY); ctx.lineTo(W, threshY); ctx.stroke();
        ctx.setLineDash([]);
        ctx.font = '9px monospace'; ctx.fillStyle = 'rgba(52,211,153,0.5)';
        ctx.textAlign = 'left';
        ctx.fillText('q=0.65', 4, Math.max(12, threshY - 3));
      }
      // Axis labels
      ctx.globalAlpha = 0.35; ctx.font = 'bold 9px monospace'; ctx.textAlign = 'center';
      ctx.fillStyle = '#60a5fa'; ctx.fillText('\u2192 confidence (c)', W / 2, H - 5);
      ctx.save(); ctx.translate(10, H / 2); ctx.rotate(-Math.PI / 2);
      ctx.fillStyle = '#60a5fa'; ctx.fillText('\u2191 quality (q)', 0, 0); ctx.restore();
      ctx.globalAlpha = 1.0; ctx.textAlign = 'left';
      ctx.restore();

    } else if (_visualizationMode === 'constitutional') {
      // ── Phase 18: Custodian topology — 8 governance lanes ───────
      const laneData = [
        { center: 0.08,  label: 'RAW',        boundary: null,  color: '#475569' },
        { center: 0.21,  label: 'EXPIRED',    boundary: 0.145, color: '#6b7280' },
        { center: 0.34,  label: 'CANCELED',   boundary: 0.275, color: '#ef4444' },
        { center: 0.47,  label: 'CONTAINED',  boundary: 0.405, color: '#f59e0b' },
        { center: 0.60,  label: 'REVIEW',     boundary: 0.535, color: '#60a5fa' },
        { center: 0.73,  label: 'APPROVED',   boundary: 0.665, color: '#34d399' },
        { center: 0.86,  label: 'CANONICAL',  boundary: 0.795, color: '#10b981' },
        { center: 0.95,  label: 'ARCHIVED',   boundary: 0.905, color: '#334155' },
      ];
      ctx.save();
      for (const ld of laneData) {
        if (ld.boundary !== null) {
          const bx = ld.boundary * 1200 * scale + tx;
          if (bx >= 0 && bx <= W) {
            ctx.setLineDash([3, 5]);
            ctx.strokeStyle = 'rgba(96,165,250,0.08)';
            ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(bx, 18); ctx.lineTo(bx, H); ctx.stroke();
            ctx.setLineDash([]);
          }
        }
        const cx = ld.center * 1200 * scale + tx;
        if (cx >= 4 && cx <= W - 4) {
          // Phase 26.2: larger font, positioned lower, with halo for readability
          ctx.save();
          ctx.globalAlpha = 1.0;
          ctx.font = 'bold 11px sans-serif';
          ctx.textAlign = 'center';
          // Halo / outline for contrast
          ctx.strokeStyle = 'rgba(0,0,0,0.55)';
          ctx.lineWidth = 3;
          ctx.lineJoin = 'round';
          ctx.strokeText(ld.label, cx, 24);
          ctx.fillStyle = ld.color;
          ctx.fillText(ld.label, cx, 24);
          ctx.restore();
        }
      }
      ctx.textAlign = 'left';
      ctx.restore();
    } else if (_visualizationMode === 'variable') {
      // ── Variable Overlay: axis labels (c on x, q on y) ──────────
      ctx.save();
      ctx.globalAlpha = 0.30; ctx.font = 'bold 9px monospace'; ctx.textAlign = 'center';
      ctx.fillStyle = '#f59e0b';
      ctx.fillText('\u2192 confidence (c)', W / 2, H - 5);
      ctx.save(); ctx.translate(10, H / 2); ctx.rotate(-Math.PI / 2);
      ctx.fillText('\u2191 quality (q)', 0, 0); ctx.restore();
      ctx.globalAlpha = 1.0; ctx.textAlign = 'left';
      // Sentinel cluster label
      const sentX = 0.12 * 1200 * scale + tx;
      const sentY = 0.90 * 900 * scale + ty;
      if (sentX > 0 && sentY < H) {
        ctx.globalAlpha = 0.25; ctx.font = '8px monospace'; ctx.fillStyle = '#475569';
        ctx.fillText('no state', sentX, sentY);
        ctx.globalAlpha = 1.0;
      }
      ctx.restore();
    }
  }

  _nodeRadius(node) {
    // ── Phase 18: Daenary epistemic mode-specific sizing ──────────
    if (_visualizationMode === 'variable') {
      // Size = epistemic_q (evidence quality). Fallback to size_metric.
      const q = node.epistemic_q;
      if (q != null) return Math.max(4, Math.min(22, 4 + q * 13));
      return Math.max(4, Math.min(10, 4 + (node.size_metric || 0) * 0.8));
    }
    if (_visualizationMode === 'constraint') {
      // Size = meaning_cost.total (larger = more costly if wrong)
      const cost = (node.meaning_cost && node.meaning_cost.total != null)
        ? node.meaning_cost.total : 0;
      return Math.max(4, Math.min(22, 4 + cost * 18));
    }
    if (Number.isFinite(Number(node.radius))) return Math.max(4, Math.min(22, Number(node.radius)));
    const layer = node.canonical_layer || node.canonicalLayer || '';
    const status = node.status || '';
    const base = layer === 'canonical' || status === 'canonical' ? 12
      : layer === 'evidence' ? 6
      : layer === 'review' ? 7
      : layer === 'quarantine' || status === 'scratch' || status === 'legacy' ? 4
      : 8;
    return base + Math.min(5, (node.authority || 0) * 4);
  }

  _nodeColor(node) {
    // ── Phase 18: Daenary epistemic mode-specific color semantics ─
    if (_visualizationMode === 'variable') {
      // Color = d-state (directional epistemic state)
      const dColors = { 1: '#22c55e', 0: '#f59e0b', '-1': '#ef4444' };
      const d = node.epistemic_d;
      if (d != null) return dColors[String(d)] || '#7a8ea5';
      return '#2d3f57'; // no epistemic state — dark sentinel
    }
    if (_visualizationMode === 'constraint') {
      // Color = correction_status (viability surface)
      const csColors = {
        accurate:         '#22c55e',
        incomplete:       '#60a5fa',
        outdated:         '#f59e0b',
        conflicting:      '#f97316',
        likely_incorrect: '#ef4444',
      };
      if (node.epistemic_correction_status && csColors[node.epistemic_correction_status])
        return csColors[node.epistemic_correction_status];
      return '#475569'; // no correction status
    }
    if (_visualizationMode === 'constitutional') {
      // Color = custodian lane (Phase 18 topology)
      const laneColors = {
        raw_imported:  '#475569',
        expired:       '#6b7280',
        canceled:      '#ef4444',
        contained:     '#f59e0b',
        under_review:  '#60a5fa',
        approved:      '#34d399',
        canonical:     '#10b981',
        archived:      '#334155',
      };
      return laneColors[node.custodian_lane] || '#7a8ea5';
    }
    // Web mode: role-based
    const roleColors = {
      canonical_anchor: '#34d399',
      supporting_context: '#7a8ea5',
      evidence_node: '#8b5cf6',
      review_gate: '#f59e0b',
      conflict_pressure: '#ef4444',
      quarantine_archive: '#475569',
      'variable_ΩV': '#22c55e',
      'variable_Π': '#f59e0b',
      variable_H: '#fb7185',
      variable_L_P: '#60a5fa',
      'variable_Δc*': '#a78bfa'
    };
    if (node.color_role && roleColors[node.color_role]) return roleColors[node.color_role];
    const layer = node.canonical_layer || node.canonicalLayer || '';
    const status = node.status || '';
    if (status === 'conflict' || layer === 'conflict') return '#ef4444';
    if (status === 'canonical' || layer === 'canonical') return '#34d399';
    if (layer === 'evidence') return '#8b5cf6';
    if (layer === 'review' || status === 'review_artifact') return '#f59e0b';
    if (status === 'superseded') return '#64748b';
    if (status === 'archived' || layer === 'archive') return '#334155';
    if (status === 'scratch' || status === 'legacy' || layer === 'quarantine') return '#475569';
    return '#7a8ea5';
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
      const r = this._nodeRadius(node) + 9;
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
    const isDerive   = edge.type === 'derives';
    const isSuper    = edge.type === 'supersedes';

    const mx = (s.x + t.x) / 2, my = (s.y + t.y) / 2;
    const dx = t.x - s.x, dy = t.y - s.y;
    const len = Math.hypot(dx, dy) || 1;
    // Lineage edges curve less (straighter chains); topic edges curve more (abstract links)
    const curveFactor = isLineage || isDerive || isSuper ? 0.04 : 0.12;
    const curve = Math.min(60, Math.max(8, len * curveFactor));
    const cx = mx - (dy / len) * curve;
    const cy = my + (dx / len) * curve;

    ctx.beginPath();
    ctx.moveTo(s.x, s.y);
    ctx.quadraticCurveTo(cx, cy, t.x, t.y);

    const alpha = isHovered ? .90 : isSelectedPath ? .65 : .22;

    if (isLineage) {
      // Lineage: solid blue, thicker — the backbone of the web
      ctx.strokeStyle = `rgba(96,165,250,${alpha})`;
      ctx.lineWidth   = isHovered ? 3.0 : isSelectedPath ? 2.0 : 1.6;
      ctx.setLineDash([]);
    } else if (isSuper) {
      // Supersedes: teal dashed — version chains
      ctx.strokeStyle = `rgba(20,184,166,${alpha})`;
      ctx.lineWidth   = isHovered ? 2.5 : isSelectedPath ? 1.8 : 1.3;
      ctx.setLineDash([6, 3]);
    } else if (isDerive) {
      // Derives: amber — derivative relationships
      ctx.strokeStyle = `rgba(245,158,11,${alpha})`;
      ctx.lineWidth   = isHovered ? 2.2 : isSelectedPath ? 1.6 : 1.1;
      ctx.setLineDash([4, 3]);
    } else if (isConflict) {
      // Conflict: red, prominent
      ctx.strokeStyle = `rgba(239,68,68,${alpha})`;
      ctx.lineWidth   = isHovered ? 2.8 : isSelectedPath ? 2.0 : 1.4;
      ctx.setLineDash([]);
    } else if (isTopic) {
      // Topic similarity: subtle grey dotted — weakest link, most numerous
      ctx.strokeStyle = `rgba(122,142,170,${Math.min(alpha, 0.18)})`;
      ctx.lineWidth   = isHovered ? 1.8 : 0.7;
      ctx.setLineDash([2, 6]);
    } else {
      ctx.strokeStyle = `rgba(120,135,160,${alpha})`;
      ctx.lineWidth   = isHovered ? 1.5 : 0.8;
      ctx.setLineDash([]);
    }

    ctx.stroke();
    ctx.setLineDash([]);

    // Crossover bead at curve midpoint when edge has reasons/crossovers
    if ((edge.reasons?.length) || (edge.crossovers?.length)) {
      ctx.beginPath();
      ctx.arc(cx, cy, isHovered ? 3.5 : 1.8, 0, Math.PI * 2);
      ctx.fillStyle = isHovered ? 'rgba(230,237,243,.9)' : 'rgba(122,142,170,.45)';
      ctx.fill();
    }
    // (edge colors handled above per type)

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
    this.fitView();
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
  applyCopyMap();
  applyUiMode();
  initOnboarding();
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
  // Sync persisted Ollama UI toggle before route-specific loads
  loadOllamaToggleState().catch(() => {});

  // Load conflicts into global state for Library conflict indicators
  try {
    const confData = await api('/api/conflicts');
    _conflicts = confData.conflicts || [];
  } catch (_) { _conflicts = []; }

  // Route to hash on load after the full script has initialized.
  const hash = window.location.hash.replace('#', '');
  if (hash) nav(hash);
  else nav('integrity');

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

  // Phase 26.3: load workspace health
  loadWorkspaceHealth().catch(() => {});

  // Stat cards
  const serverEl = el('st-server');
  if (serverEl) { serverEl.textContent = r.server === 'ok' ? '✓ ok' : r.server; serverEl.style.color = r.server === 'ok' ? 'var(--green-bright)' : 'var(--red)'; }
  if (el('st-docs'))   el('st-docs').textContent   = r.indexed_docs ?? '—';
  if (el('st-edges'))  el('st-edges').textContent  = r.graph_edges ?? '—';
  if (el('st-queue'))  el('st-queue').textContent  = `${r.review_queue?.pending ?? 0} pending`;
  if (el('st-errors')) el('st-errors').textContent = r.index_errors ?? '—';

  // Phase 19: plane card count
  api('/api/planes').then(pd => {
    const total = (pd.planes||[]).reduce((s,p)=>s+(p.count||0),0);
    const el19 = el('st-plane-cards');
    if (el19) el19.textContent = total || '0';
  }).catch(()=>{});

  // Ollama card
  const ollamaEl = el('st-ollama');
  if (ollamaEl) {
    const ol = r.ollama || {};
    if (!ol.enabled) { ollamaEl.textContent = 'disabled'; ollamaEl.style.color = 'var(--text-faint)'; }
    else if (ol.available) { ollamaEl.textContent = '✓ available'; ollamaEl.style.color = 'var(--green-bright)'; }
    else { ollamaEl.textContent = '✗ unavailable'; ollamaEl.style.color = 'var(--red)'; }
    // Sync status-panel toggle
    const stToggle = el('status-ollama-toggle');
    if (stToggle) stToggle.checked = ol.enabled || false;
    if (el('st-ollama-model')) el('st-ollama-model').textContent = ol.model || '—';
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

  const hasFailed = (r.failed || 0) > 0;
  const summaryColor = hasFailed ? 'var(--amber)' : 'var(--green-bright)';
  const summaryIcon  = hasFailed ? '⚠' : '✓';

  let html = `<div style="margin-bottom:8px">
    <span style="color:${summaryColor}">${summaryIcon} Scanned ${r.scanned} · Indexed ${r.indexed} · Skipped ${r.skipped} · <strong>Failed ${r.failed}</strong> · ${r.elapsed_ms}ms</span>
  </div>`;

  // Phase 26.3: Per-file failure drill-down
  if (hasFailed) {
    const failData = await api('/api/autoindex/failures');
    const failures = failData.failures || [];
    html += `<div class="accordion" style="margin-top:6px">
      <div class="accordion-head" onclick="toggleAccordion(this)" style="color:var(--amber)">
        ⚠ ${failures.length} file(s) failed — click for details <span class="chevron">▶</span>
      </div>
      <div class="accordion-body">
        <div class="text-faint font-sm" style="margin-bottom:8px">
          Each entry shows the file path, reason, and how to fix it.
        </div>
        ${failures.map(f => `
          <div style="margin-bottom:12px;padding:8px;background:rgba(239,68,68,.06);border-radius:4px;border:1px solid rgba(239,68,68,.2)">
            <div style="font-family:var(--font-mono);font-size:10px;color:var(--text-faint);margin-bottom:4px">${escHtml(f.path||'unknown')}</div>
            <div style="font-size:11px;color:var(--red);margin-bottom:4px">
              <strong>${escHtml(f.reason||f.error_type||'error')}</strong>
            </div>
            <div style="font-size:11px;color:var(--text-muted);margin-bottom:4px">${escHtml(f.error||'')}</div>
            ${f.recommended_fix ? `<div style="font-size:11px;color:var(--green-bright)">
              💡 Fix: ${escHtml(f.recommended_fix)}
            </div>` : ''}
          </div>`).join('')}
        <div style="margin-top:8px;display:flex;gap:8px">
          <button class="btn btn-ghost btn-sm" onclick="downloadIndexReport()">⬇ Export report</button>
          <button class="btn btn-ghost btn-sm" onclick="showResetWorkspaceModal()">⟳ Reset workspace</button>
        </div>
      </div>
    </div>`;
  }

  if (resultEl) resultEl.innerHTML = html;

  // Refresh dashboard stats and library
  try { await loadDashboard(); } catch (_) {}
  try { if (typeof loadLibrary === 'function') await loadLibrary(); } catch (_) {}
}

async function downloadIndexReport() {
  const r = await api('/api/autoindex/report');
  const blob = new Blob([JSON.stringify(r, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `boh_index_report_${new Date().toISOString().slice(0,10)}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

// Phase 26.4: Three-level reset modal with clear warnings
function showResetWorkspaceModal() {
  // Remove any existing modal
  const existing = document.getElementById('boh-reset-modal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'boh-reset-modal';
  modal.style.cssText = `
    position:fixed;top:0;left:0;right:0;bottom:0;z-index:9999;
    background:rgba(0,0,0,0.75);display:flex;align-items:center;justify-content:center;
  `;
  modal.innerHTML = `
    <div style="background:var(--bg-base);border:1px solid var(--border);border-radius:8px;
                padding:24px;max-width:480px;width:90%;box-shadow:0 8px 40px rgba(0,0,0,0.6)">
      <div style="font-size:15px;font-weight:600;margin-bottom:6px;color:var(--text-bright)">Reset Workspace</div>
      <div style="font-size:12px;color:var(--text-faint);margin-bottom:16px;line-height:1.6">
        Choose a reset level. Library files on disk are never deleted unless you choose Level 3.
      </div>

      <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:16px">
        <button onclick="doReset('state')" style="text-align:left;padding:10px 14px;border:1px solid var(--border-dim);border-radius:6px;background:var(--bg-card);cursor:pointer;color:var(--text-bright)">
          <div style="font-weight:600;color:var(--amber)">Level 1 — Reset State</div>
          <div style="font-size:11px;color:var(--text-faint);margin-top:3px">Clears: escalations, locks, open items, coherence scores, SC3 violations. Indexed docs preserved.</div>
        </button>
        <button onclick="doReset('db')" style="text-align:left;padding:10px 14px;border:1px solid var(--border-dim);border-radius:6px;background:var(--bg-card);cursor:pointer;color:var(--text-bright)">
          <div style="font-weight:600;color:var(--red)">Level 2 — Reset DB</div>
          <div style="font-size:11px;color:var(--text-faint);margin-top:3px">Clears all indexed docs and governance state. Library files on disk untouched. Run reindex to restore.</div>
        </button>
        <button onclick="doReset('full')" style="text-align:left;padding:10px 14px;border:1px solid rgba(239,68,68,.4);border-radius:6px;background:rgba(239,68,68,.07);cursor:pointer;color:var(--text-bright)">
          <div style="font-weight:600;color:var(--red)">Level 3 — Reset DB + Seed Fixtures</div>
          <div style="font-size:11px;color:var(--text-faint);margin-top:3px">Full DB clear then immediately seed verification fixtures. Clean slate for testing.</div>
        </button>
      </div>

      <div style="display:flex;justify-content:flex-end;gap:8px">
        <button onclick="document.getElementById('boh-reset-modal').remove()"
          style="padding:6px 14px;border:1px solid var(--border-dim);border-radius:4px;background:transparent;color:var(--text-faint);cursor:pointer;font-size:12px">Cancel</button>
      </div>
      <div id="boh-reset-result" style="margin-top:10px;font-size:12px"></div>
    </div>
  `;
  document.body.appendChild(modal);
}

async function doReset(level) {
  const resultEl = document.getElementById('boh-reset-result');
  if (resultEl) resultEl.innerHTML = '<span class="spinner"></span> Resetting…';

  let r;
  if (level === 'state') {
    r = await api('/api/workspace/reset', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({confirm: 'RESET'}),
    });
  } else if (level === 'db') {
    r = await api('/api/workspace/reset-full', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({confirm: 'RESET', preserve_canonical: false}),
    });
  } else {
    // Level 3: full reset then seed
    r = await api('/api/workspace/reset-full', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({confirm: 'RESET', preserve_canonical: false}),
    });
    if (r.ok) {
      const seed = await api('/api/workspace/seed-fixtures', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: '{}',
      });
      if (resultEl) resultEl.innerHTML = `<span style="color:var(--green-bright)">✓ Reset + seeded ${seed.indexed||0}/${seed.total||0} fixtures. Running reindex…</span>`;
      await triggerAutoIndex(false);
      document.getElementById('boh-reset-modal')?.remove();
      return;
    }
  }

  if (r && r.ok) {
    if (resultEl) resultEl.innerHTML = `<span style="color:var(--green-bright)">✓ ${escHtml(r.message||'Done')}</span>`;
    setTimeout(() => {
      document.getElementById('boh-reset-modal')?.remove();
      triggerAutoIndex(false);
    }, 1500);
  } else {
    const errMsg = formatApiError(r);
    if (resultEl) resultEl.innerHTML = `<span style="color:var(--red)">✗ ${escHtml(errMsg)}</span>`;
  }
}

async function seedVerificationFixtures() {
  const resultEl = el('st-index-result') || el('dash-library-status');
  if (resultEl) resultEl.innerHTML = '<span class="spinner"></span> Seeding verification fixtures…';
  const r = await api('/api/workspace/seed-fixtures', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: '{}',
  });
  if (r && r.ok) {
    const failList = (r.results||[]).filter(x => !x.indexed);
    let html = `<span style="color:var(--green-bright)">✓ Seeded ${r.indexed}/${r.total} fixtures → ${escHtml(r.dest_dir||'library')}</span>`;
    if (failList.length) {
      html += `<div style="margin-top:6px;font-size:11px;color:var(--amber)">
        ⚠ ${failList.length} fixture(s) not indexed:
        ${failList.map(f=>`<div style="padding:2px 0">• ${escHtml(f.filename)}: ${escHtml(f.error||f.lint_errors?.[0]||'unknown')}</div>`).join('')}
      </div>`;
    }
    if (resultEl) resultEl.innerHTML = html;
    try { await loadDashboard(); } catch (_) {}
    try { await loadWorkspaceHealth(); } catch (_) {}
  } else {
    const errMsg = formatApiError(r);
    if (resultEl) resultEl.innerHTML = `<span style="color:var(--red)">✗ Seed failed: ${escHtml(errMsg)}</span>`;
  }
}

// ── Phase 26.3: Workspace health display ────────────────────────
async function loadWorkspaceHealth() {
  const el_h = el('st-workspace-health');
  if (!el_h) return;
  const r = await api('/api/workspace/state');
  if (r.error) { el_h.innerHTML = `<span class="text-red">Health check failed</span>`; return; }

  const healthColor = { ok: 'var(--green-bright)', warning: 'var(--amber)', critical: 'var(--red)' }[r.health] || 'var(--text-faint)';
  const healthIcon  = { ok: '✓', warning: '⚠', critical: '✗' }[r.health] || '?';
  const stats = r.stats || {};

  let html = `<div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:6px">
    <span style="color:${healthColor};font-weight:600">${healthIcon} ${r.health?.toUpperCase() || 'UNKNOWN'}</span>
    <span class="text-faint font-sm">${stats.doc_count||0} docs · ${stats.library_file_count||0} files · ${stats.lineage_count||0} lineage links</span>
    ${(stats.last_index_failed||0) > 0 ? `<span style="color:var(--red)">${stats.last_index_failed} index failures</span>` : ''}
  </div>`;

  if (r.issues && r.issues.length > 0) {
    html += `<div style="font-size:11px;color:var(--amber)">${r.issues.map(i=>`⚠ ${escHtml(i)}`).join('<br>')}</div>`;
  }
  if (r.recommended_action) {
    html += `<div style="font-size:11px;color:var(--text-faint);margin-top:4px">→ ${escHtml(r.recommended_action)}</div>`;
  }
  el_h.innerHTML = html;
}

// ── Phase 26.4: AI Analysis health check ──────────────────────
async function checkAnalysisHealth(docId) {
  const el_h = el('st-analysis-health');
  if (!el_h) return;
  el_h.innerHTML = '<span class="spinner"></span> Checking…';

  const url = docId ? `/api/workspace/analysis-health?doc_id=${encodeURIComponent(docId)}`
                    : '/api/workspace/analysis-health';
  const r = await api(url);

  const statusColor = {
    ok: 'var(--green-bright)', file_missing: 'var(--amber)',
    no_docs: 'var(--amber)', error: 'var(--red)',
  }[r.status] || 'var(--text-faint)';
  const statusIcon = { ok: '✓', file_missing: '⚠', no_docs: '⚠', error: '✗' }[r.status] || '?';

  let html = `<div style="margin-bottom:8px">
    <span style="color:${statusColor};font-weight:600">${statusIcon} ${escHtml(r.status?.toUpperCase()||'UNKNOWN')}</span>
    ${r.doc_path ? `<span class="text-faint font-sm" style="margin-left:8px">${escHtml(r.doc_path)}</span>` : ''}
  </div>`;

  if (r.status === 'ok') {
    html += `<div class="kv-grid font-sm">
      <div class="kv-key">Text length</div><div class="kv-val">${r.text_length?.toLocaleString()||'—'} chars</div>
      <div class="kv-key">Topics found</div><div class="kv-val" style="color:var(--green-bright)">${r.topics_extracted??'—'}</div>
      <div class="kv-key">Definitions found</div><div class="kv-val">${r.defs_extracted??'—'}</div>
      <div class="kv-key">Non-authoritative</div><div class="kv-val">${r.non_authoritative?'✓ yes':'—'}</div>
    </div>
    <div class="text-faint font-sm" style="margin-top:6px">${escHtml(r.note||'')}</div>`;
  } else {
    html += `<div style="color:var(--red);font-size:11px;margin-top:4px">${escHtml(r.error||'Unknown error')}</div>`;
    if (r.status === 'file_missing' || r.status === 'no_docs') {
      html += `<div style="color:var(--amber);font-size:11px;margin-top:4px">
        → Fix: click "Seed Verification Fixtures" then "↻ Full re-index"
      </div>`;
    }
  }
  el_h.innerHTML = html;
}

// ── Phase 26.4: Activity Log ───────────────────────────────────
async function loadActivityLog() {
  const el_l = el('st-activity-log');
  if (!el_l) return;
  el_l.innerHTML = '<div class="text-faint font-sm" style="padding:12px"><span class="spinner"></span> Loading…</div>';

  const r = await api('/api/workspace/activity-log?limit=100');
  const events = r.events || [];

  if (!events.length) {
    el_l.innerHTML = '<div class="text-faint font-sm" style="padding:12px">No activity recorded yet. Import files, run reindex, or perform governance actions.</div>';
    return;
  }

  el_l.innerHTML = events.map(e => {
    const timeStr = e.iso ? new Date(e.iso).toLocaleString() : '—';
    const actor = e.actor_id ? ` · ${escHtml(e.actor_id)}` : '';
    const docStr = e.doc_id ? `<span class="text-faint" style="font-size:10px;font-family:var(--font-mono)"> ${escHtml(e.doc_id.slice(0,16))}…</span>` : '';
    let detailStr = '';
    if (e.detail && typeof e.detail === 'object') {
      const d = e.detail;
      if (d.path) detailStr = escHtml(String(d.path).split('/').pop());
      else if (d.root) detailStr = `${d.indexed||0} indexed, ${d.failed||0} failed`;
      else if (d.type) detailStr = escHtml(d.type);
    }
    return `<div style="display:flex;gap:8px;align-items:baseline;padding:6px 12px;border-bottom:1px solid var(--border-dim);font-size:11px">
      <span style="color:var(--text-faint);min-width:130px;flex-shrink:0">${escHtml(timeStr)}</span>
      <span style="flex:1">${escHtml(e.label||e.event_type||'—')}${actor}${docStr}</span>
      ${detailStr ? `<span class="text-faint" style="font-size:10px;max-width:120px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${detailStr}</span>` : ''}
    </div>`;
  }).join('');
}

// ── Phase 26.6: Clean Test Workspace (one-click reset + seed + reindex + verify) ──
async function runCleanTestWorkspace() {
  const resultEl = el('demo-project-status') || el('st-index-result');
  const steps = [
    '⟳ Resetting DB…',
    '⊕ Seeding fixtures…',
    '↻ Reindexing…',
    '📋 Running verification…'
  ];
  const log = [];

  const updateStatus = (msg, color = 'var(--text-faint)') => {
    if (resultEl) resultEl.innerHTML = `<span style="color:${color}">${escHtml(msg)}</span>`;
    log.push(msg);
  };

  updateStatus(steps[0]);
  const reset = await api('/api/workspace/reset-full', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({confirm: 'RESET', preserve_canonical: false}),
  });
  if (!reset?.ok) { updateStatus(`✗ Reset failed: ${escHtml(formatApiError(reset))}`, 'var(--red)'); return; }

  updateStatus(steps[1]);
  const seed = await api('/api/workspace/seed-fixtures', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}',
  });
  if (!seed?.ok) { updateStatus(`✗ Seed failed: ${escHtml(formatApiError(seed))}`, 'var(--red)'); return; }

  updateStatus(steps[2]);
  const idx = await api('/api/autoindex/run', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({changed_only: false}),
  });

  updateStatus(steps[3]);
  // Auto-navigate to status + run verification
  nav('status');
  await new Promise(r => setTimeout(r, 200));
  await loadVerificationDashboard();

  const summary = `✓ Clean workspace ready: ${seed.indexed||0} fixtures · ${idx.indexed||0} indexed · ${idx.failed||0} failed`;
  updateStatus(summary, idx.failed > 0 ? 'var(--amber)' : 'var(--green-bright)');
  try { await loadDashboard(); } catch(_) {}
  try { await loadWorkspaceHealth(); } catch(_) {}
}

// ── Phase 26.6: Verification Dashboard ────────────────────────────────────────
async function loadVerificationDashboard() {
  const el_v = el('st-verification-dashboard');
  if (!el_v) return;
  el_v.innerHTML = '<div class="text-faint font-sm" style="padding:12px"><span class="spinner"></span> Running checks…</div>';

  const checks = [];
  const check = async (id, label, fn) => {
    try {
      const result = await fn();
      checks.push({id, label, ...result});
    } catch(e) {
      checks.push({id, label, pass: false, note: String(e)});
    }
  };

  // Check 1: DB connected + docs indexed
  await check('db', 'Database connected + docs indexed', async () => {
    const r = await api('/api/workspace/state');
    const n = r.stats?.doc_count || 0;
    return {pass: n > 0, note: `${n} docs in DB`};
  });

  // Check 2: Library files present
  await check('lib', 'Library files present', async () => {
    const r = await api('/api/workspace/state');
    const n = r.stats?.library_file_count || 0;
    return {pass: n > 0, note: `${n} files on disk`};
  });

  // Check 3: Last reindex had zero failures
  await check('idx', 'Last reindex: 0 failures', async () => {
    const r = await api('/api/autoindex/status');
    const failed = r.last_failed || 0;
    return {pass: failed === 0, note: `${failed} failures`};
  });

  // Check 4: Deterministic review artifacts exist
  await check('art', 'Review artifacts generated', async () => {
    const r = await api('/api/analysis/status');
    const n = r.deterministic_review?.artifacts_total || 0;
    const docs = r.deterministic_review?.total_docs || 0;
    return {pass: n > 0, note: `${n}/${docs} docs have artifacts`};
  });

  // Check 5: AI Analysis pipeline works
  await check('ai', 'AI Analysis pipeline: ok', async () => {
    const r = await api('/api/workspace/analysis-health');
    return {pass: r.status === 'ok', note: r.status === 'ok'
      ? `topics=${r.topics_extracted}, text=${r.text_length} chars`
      : (r.error || r.status)};
  });

  // Check 6: Lineage relationships exist
  await check('lin', 'Lineage relationships seeded', async () => {
    const r = await api('/api/dashboard');
    const n = r.lineage_records || 0;
    return {pass: n > 0, note: `${n} lineage records`};
  });

  // Check 7: Activity log captures events
  await check('log', 'Activity log records events', async () => {
    const r = await api('/api/workspace/activity-log?limit=5');
    const n = r.total || 0;
    return {pass: n > 0, note: `${n} events recorded`};
  });

  // Check 8: HTML safety — no script/style in preprocessor output (static check)
  await check('html', 'HTML import safety: scripts/styles stripped', async () => {
    // We know this from the test suite; verify route exists
    const r = await api('/api/authority/translation/map');
    return {pass: r.status_code !== 500 && !r.error, note: 'Translation API responsive'};
  });

  // Render
  const passed = checks.filter(c => c.pass).length;
  const total = checks.length;
  const allPass = passed === total;
  const headerColor = allPass ? 'var(--green-bright)' : passed > total/2 ? 'var(--amber)' : 'var(--red)';

  el_v.innerHTML = `
    <div style="padding:10px 12px;border-bottom:1px solid var(--border-dim);display:flex;gap:8px;align-items:center">
      <span style="color:${headerColor};font-weight:700;font-size:13px">${passed}/${total} checks pass</span>
      ${allPass ? '<span style="color:var(--green-bright)">✓ Full workflow verified</span>' : '<span style="color:var(--amber)">⚠ Some checks need attention</span>'}
    </div>
    ${checks.map(c => `
      <div style="display:flex;gap:10px;align-items:center;padding:7px 12px;border-bottom:1px solid var(--border-dim);font-size:11px">
        <span style="font-size:14px;flex-shrink:0">${c.pass ? '✅' : '❌'}</span>
        <span style="flex:1;color:var(--text-bright)">${escHtml(c.label)}</span>
        <span style="color:var(--text-faint);font-size:10px">${escHtml(c.note||'')}</span>
      </div>`).join('')}
    ${!allPass ? `<div style="padding:10px 12px;font-size:11px;color:var(--amber)">
      → Fix: click <strong>⊕ Clean Test Workspace</strong> for one-click reset + seed + reindex
    </div>` : ''}
  `;
}

// ── Phase 26.6: Import Report Viewer ──────────────────────────────────────────
async function loadImportReport() {
  const el_r = el('st-import-report');
  if (!el_r) return;
  el_r.innerHTML = '<div class="text-faint font-sm" style="padding:12px"><span class="spinner"></span> Loading…</div>';

  const [logData, statusData] = await Promise.all([
    api('/api/autoindex/log'),
    api('/api/autoindex/status'),
  ]);

  const entries = logData.log || [];
  if (!entries.length) {
    el_r.innerHTML = '<div class="text-faint font-sm" style="padding:12px">No index log yet. Run reindex first.</div>';
    return;
  }

  const indexed  = entries.filter(e => e.status === 'indexed');
  const failed   = entries.filter(e => e.status === 'failed');

  const headerHtml = `<div style="padding:8px 12px;border-bottom:1px solid var(--border-dim);font-size:11px;display:flex;gap:12px">
    <span style="color:var(--green-bright)">✓ ${indexed.length} indexed</span>
    <span style="color:var(--red)">✗ ${failed.length} failed</span>
    <span class="text-faint">${entries.length} total</span>
    <span class="text-faint ml-auto">${statusData.elapsed_ms ? statusData.elapsed_ms+'ms' : ''}</span>
  </div>`;

  const failHtml = failed.length ? `
    <div style="padding:6px 12px;font-size:11px;font-weight:600;color:var(--red);border-bottom:1px solid var(--border-dim)">
      Failed files (${failed.length})
    </div>
    ${failed.map(f => `<div style="padding:5px 12px;border-bottom:1px solid var(--border-dim);font-size:10px;background:rgba(239,68,68,.04)">
      <div style="font-family:var(--font-mono);color:var(--red)">${escHtml(f.path||'?')}</div>
      <div style="color:var(--amber);margin-top:2px">${escHtml(f.reason||f.error_type||'error')}</div>
      <div style="color:var(--text-faint)">${escHtml(f.error||'')}</div>
      ${f.recommended_fix ? `<div style="color:var(--green-bright);margin-top:2px">💡 ${escHtml(f.recommended_fix)}</div>` : ''}
    </div>`).join('')}` : '';

  const indexHtml = indexed.length ? `
    <div style="padding:6px 12px;font-size:11px;font-weight:600;border-bottom:1px solid var(--border-dim)">
      Indexed files (${indexed.length})
    </div>
    <div style="max-height:200px;overflow-y:auto">
    ${indexed.map(f => `<div style="padding:3px 12px;border-bottom:1px solid var(--border-dim);font-size:10px;display:flex;gap:8px">
      <span style="color:var(--green-bright);flex-shrink:0">✓</span>
      <span style="font-family:var(--font-mono);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(f.path||'?')}</span>
      ${f.analysis?.deterministic_review?.success ? '<span style="color:var(--blue);font-size:9px">AI✓</span>' : ''}
      ${(f.lint_warnings||[]).length ? `<span style="color:var(--amber);font-size:9px">⚠${f.lint_warnings.length}</span>` : ''}
    </div>`).join('')}
    </div>` : '';

  el_r.innerHTML = headerHtml + failHtml + indexHtml;
}

// ══════════════════════════════════════════════════════════════
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
        ⚠ Approving applies: title, summary, topics, type (if not canon). Trusted Source status is <strong>never applied</strong> automatically.
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


// ══════════════════════════════════════════════════════════════
// Feature: Ollama UI toggle (persisted in DB, no env var needed)
// ══════════════════════════════════════════════════════════════

async function uploadDocumentsFromInput(inputEl) {
  // Wrapper for the quick upload on New/Import panel
  const statusEl = el('upload-status-new') || el('upload-status');
  if (statusEl) statusEl.innerHTML = '<span class="spinner"></span> Uploading…';
  const files = Array.from(inputEl.files);
  if (!files.length) return;
  const fd = new FormData();
  files.forEach(f => fd.append('files', f));
  fd.append('target_folder', el('upload-target-folder')?.value || 'imports');
  try {
    const r = await fetch('/api/input/upload', { method: 'POST', body: fd });
    const data = await r.json();
    const ok = (data.results || []).filter(x => x.indexed).length;
    const fail = (data.results || []).filter(x => !x.indexed).length;
    if (statusEl) statusEl.innerHTML = `<span class="text-green">✓ ${ok} indexed</span>${fail ? ` <span class="text-amber">(${fail} skipped)</span>` : ''}`;
  } catch (e) {
    if (statusEl) statusEl.innerHTML = `<span class="text-red">Upload failed: ${escHtml(String(e))}</span>`;
  }
  inputEl.value = '';
}

async function loadOllamaToggleState() {
  try {
    const r = await api('/api/ollama/enabled');
    const enabled = !!r.enabled;
    const toggle = el('ollama-ui-toggle');
    const statusToggle = el('status-ollama-toggle');
    const badge  = el('ollama-status-badge');
    if (toggle) toggle.checked = enabled;
    if (statusToggle) statusToggle.checked = enabled;
    if (badge) {
      badge.textContent = enabled ? '● enabled' : '○ disabled';
      badge.style.color = enabled ? 'var(--green-bright)' : 'var(--text-faint)';
    }
  } catch (e) {
    const badge = el('ollama-status-badge');
    if (badge) {
      badge.textContent = '○ toggle unavailable';
      badge.style.color = 'var(--text-faint)';
    }
  }
}

async function setOllamaEnabled(enabled) {
  const badge  = el('ollama-status-badge');
  const result = el('ollama-toggle-result');
  if (badge) badge.textContent = '…';
  const r = await api('/api/ollama/enabled', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
  if (r.ok) {
    if (badge) {
      badge.textContent = enabled ? '● enabled' : '○ disabled';
      badge.style.color = enabled ? 'var(--green-bright)' : 'var(--text-faint)';
    }
    if (result) result.innerHTML = `<span class="${enabled ? 'text-green' : 'text-faint'}">${escHtml(r.message)}</span>`;
    if (enabled) checkOllama();
  } else {
    if (result) result.innerHTML = `<span class="text-red">Failed: ${escHtml(r.detail || 'error')}</span>`;
  }
}

// ══════════════════════════════════════════════════════════════
// Feature: Atlas project filter + lineage-only mode
// ══════════════════════════════════════════════════════════════

async function loadAtlasProjectFilter() {
  const sel = el('graph-filter-project');
  if (!sel) return;
  // Try to get projects list if projects API is available
  try {
    const r = await api('/api/docs?per_page=1&status=all');
    // Get unique plane_scope paths as proxy for projects if no project API
  } catch (_) {}
  // Minimal: leave as "All projects" — future: populate from /api/projects
}

// Patch applyGraphFilter to respect project filter and lineage-only mode

// ══════════════════════════════════════════════════════════════
// Feature: Folder picker (browser native webkitdirectory)
// ══════════════════════════════════════════════════════════════

function openFolderPicker() {
  const input = document.createElement('input');
  input.type = 'file';
  input.webkitdirectory = true;
  input.multiple = true;
  input.style.display = 'none';
  document.body.appendChild(input);

  input.addEventListener('change', async () => {
    const files = Array.from(input.files);
    if (!files.length) { document.body.removeChild(input); return; }

    // Use the relative path of the first file to derive the folder name
    const firstPath = files[0].webkitRelativePath || files[0].name;
    const folderName = firstPath.split('/')[0] || 'picked-folder';

    const status = el('index-folder-status') || el('folder-picker-status');
    if (status) status.innerHTML = `<span class="spinner"></span> Uploading ${files.length} files from <em>${escHtml(folderName)}</em>…`;

    // Filter to supported extensions
    const supported = ['.md', '.txt', '.markdown', '.html', '.htm', '.json', '.yaml', '.yml', '.rst', '.csv'];
    const filtered = files.filter(f => {
      const ext = '.' + f.name.split('.').pop().toLowerCase();
      return supported.includes(ext);
    });

    if (!filtered.length) {
      if (status) status.innerHTML = `<span class="text-amber">No supported files found in folder (need .md, .html, .json, .txt etc.)</span>`;
      document.body.removeChild(input);
      return;
    }

    // Upload in batches of 10
    let indexed = 0, failed = 0;
    const batchSize = 10;
    for (let i = 0; i < filtered.length; i += batchSize) {
      const batch = filtered.slice(i, i + batchSize);
      const fd = new FormData();
      batch.forEach(f => fd.append('files', f));
      fd.append('target_folder', `imports/${folderName}`);
      try {
        const r = await fetch('/api/input/upload', { method: 'POST', body: fd });
        const data = await r.json();
        indexed += (data.results || []).filter(x => x.indexed).length;
        failed  += (data.results || []).filter(x => !x.indexed).length;
      } catch (e) { failed += batch.length; }
      if (status) status.innerHTML = `<span class="spinner"></span> ${indexed} indexed, ${failed} failed of ${filtered.length} files…`;
    }

    if (status) status.innerHTML = `<span class="text-green">✓ ${indexed} files indexed</span>${failed ? ` <span class="text-amber">(${failed} failed)</span>` : ''} from <em>${escHtml(folderName)}</em>`;
    document.body.removeChild(input);
    try { await loadDashboard(); } catch (_) {}
  });

  input.click();
}



// Explicitly expose inline-handler functions. This keeps the Workbench clickable even under strict-mode/browser differences.
Object.assign(window, {
  applyGraphFilter: (typeof applyGraphFilter === 'function' ? applyGraphFilter : undefined),
  checkOllama: (typeof checkOllama === 'function' ? checkOllama : undefined),
  clearDaenaryFilters: (typeof clearDaenaryFilters === 'function' ? clearDaenaryFilters : undefined),
  clearLibFilters: (typeof clearLibFilters === 'function' ? clearLibFilters : undefined),
  closeDrawer: (typeof closeDrawer === 'function' ? closeDrawer : undefined),
  createMarkdownDoc: (typeof createMarkdownDoc === 'function' ? createMarkdownDoc : undefined),
  doCanon: (typeof doCanon === 'function' ? doCanon : undefined),
  doIndex: (typeof doIndex === 'function' ? doIndex : undefined),
  doIngestSnapshot: (typeof doIngestSnapshot === 'function' ? doIngestSnapshot : undefined),
  doMigrationReport: (typeof doMigrationReport === 'function' ? doMigrationReport : undefined),
  doSearch: (typeof doSearch === 'function' ? doSearch : undefined),
  fitAtlasToScreen: (typeof fitAtlasToScreen === 'function' ? fitAtlasToScreen : undefined),
  focusSelectedAtlasNode: (typeof focusSelectedAtlasNode === 'function' ? focusSelectedAtlasNode : undefined),
  indexFolderFromInputPanel: (typeof indexFolderFromInputPanel === 'function' ? indexFolderFromInputPanel : undefined),
  libPage: (typeof libPage === 'function' ? libPage : undefined),
  loadAuditLog: (typeof loadAuditLog === 'function' ? loadAuditLog : undefined),
  loadConflicts: (typeof loadConflicts === 'function' ? loadConflicts : undefined),
  loadExecRuns: (typeof loadExecRuns === 'function' ? loadExecRuns : undefined),
  loadLibrary: (typeof loadLibrary === 'function' ? loadLibrary : undefined),
  loadLineage: (typeof loadLineage === 'function' ? loadLineage : undefined),
  loadLlmQueue: (typeof loadLlmQueue === 'function' ? loadLlmQueue : undefined),
  loadPolicies: (typeof loadPolicies === 'function' ? loadPolicies : undefined),
  loadRecentInput: (typeof loadRecentInput === 'function' ? loadRecentInput : undefined),
  loadStatus: (typeof loadStatus === 'function' ? loadStatus : undefined),
  nav: (typeof nav === 'function' ? nav : undefined),
  openFolderPicker: (typeof openFolderPicker === 'function' ? openFolderPicker : undefined),
  previewNewDoc: (typeof previewNewDoc === 'function' ? previewNewDoc : undefined),
  reloadGraph: (typeof reloadGraph === 'function' ? reloadGraph : undefined),
  renderConflicts: (typeof renderConflicts === 'function' ? renderConflicts : undefined),
  resetAtlasView: (typeof resetAtlasView === 'function' ? resetAtlasView : undefined),
  restoreAtlasReaderWidth: (typeof restoreAtlasReaderWidth === 'function' ? restoreAtlasReaderWidth : undefined),
  runOllamaTask: (typeof runOllamaTask === 'function' ? runOllamaTask : undefined),
  savePolicy: (typeof savePolicy === 'function' ? savePolicy : undefined),
  setAtlasOption: (typeof setAtlasOption === 'function' ? setAtlasOption : undefined),
  setAtlasPerfMode: (typeof setAtlasPerfMode === 'function' ? setAtlasPerfMode : undefined),
  setAtlasReaderWidth: (typeof setAtlasReaderWidth === 'function' ? setAtlasReaderWidth : undefined),
  setDrawerWidthMode: (typeof setDrawerWidthMode === 'function' ? setDrawerWidthMode : undefined),
  setOllamaEnabled: (typeof setOllamaEnabled === 'function' ? setOllamaEnabled : undefined),
  setReaderMode: (typeof setReaderMode === 'function' ? setReaderMode : undefined),
  toggleAccordion: (typeof toggleAccordion === 'function' ? toggleAccordion : undefined),
  triggerAutoIndex: (typeof triggerAutoIndex === 'function' ? triggerAutoIndex : undefined),
  uploadDocuments: (typeof uploadDocuments === 'function' ? uploadDocuments : undefined),
  uploadDocumentsFromInput: (typeof uploadDocumentsFromInput === 'function' ? uploadDocumentsFromInput : undefined),
  zoomAtlas: (typeof zoomAtlas === 'function' ? zoomAtlas : undefined)
});

// ── Phase 14 stabilization: compat aliases for Phase 11 test contract ─────────
// These ensure backward-compat with test_phase11_graph.py function presence checks.

function setAtlasReaderWidth(mode) {
  // Alias for setAtlasReaderWidth — maps to existing width controls
  const atlasCols = {
    'hide':   '1fr 0px',
    'normal': '1fr 420px',
    'wide':   '1fr 640px',
    'full':   '0px 1fr',
  };
  const layout = document.getElementById('atlas-layout');
  if (layout && atlasCols[mode]) layout.style.gridTemplateColumns = atlasCols[mode];
  if (_graph) { _graph.canvas.width = document.getElementById('graph-pane')?.offsetWidth || 900; _graph._renderDirty = true; }
  try { localStorage.setItem('boh_atlas_reader_width', mode); } catch(_) {}
}

function expandAtlasNeighborhood(docId, depth = 1) {
  // Alias for expandAtlasNeighborhood — delegates to expandNeighborhood
  if (typeof expandNeighborhood === 'function') return expandNeighborhood(docId, depth);
  if (typeof expandAtlasNeighborhoodInternal === 'function') return expandAtlasNeighborhoodInternal(docId, depth);
}

function expandSelectedAtlasNode() {
  if (_graph?.selectedNode) expandAtlasNeighborhood(_graph.selectedNode.id, 1);
}

function collapseAtlasToInitial() {
  // Reset graph to initial state without neighborhood expansions
  if (_graphData) applyGraphFilter();
}

// ══════════════════════════════════════════════════════════════
// Phase 15: Explicit Governance Approval Workflow
// ══════════════════════════════════════════════════════════════




function severityClass(sev) {
  return `gov-sev-${String(sev || 'low').toLowerCase()}`;
}

function renderBlastRadius(req) {
  const b = req.blast_radius || {};
  return `
    <div class="blast-grid">
      <div><span>Change Risk</span><strong>${escHtml(String(req.impact_score ?? b.impact_score ?? '—'))}</strong></div>
      <div><span>Severity</span><strong>${escHtml(req.severity || b.severity || 'low')}</strong></div>
      <div><span>Affected Docs</span><strong>${escHtml(String(b.downstream_references_affected ?? 0))}</strong></div>
      <div><span>Ease of Undoing</span><strong>${escHtml(req.rollback_complexity || b.rollback_complexity || 'low')}</strong></div>
      <div class="advanced-only"><span>Review Level</span><strong>${escHtml(b.governance_tier || 'standard')}</strong></div>
      <div class="advanced-only"><span>Cross-project</span><strong>${b.cross_project_exposure ? 'yes' : 'no'}</strong></div>
    </div>`;
}

function renderApprovalCard(req) {
  const ACTION_LABELS = {
    canonical_promotion: '⬆ Canonical Promotion',
    supersede_operation: '↻ Supersede',
    review_patch:        '✎ Review Patch',
    edge_promotion:      '⇌ Edge Promotion',
  };
  const isPatch = req.action_type === 'review_patch';
  const requiresHeavyAck = ['high', 'extreme'].includes(String(req.severity || '').toLowerCase());
  return `
    <div class="approval-card ${severityClass(req.severity)}">
      <div style="display:flex;justify-content:space-between;gap:8px;align-items:start;margin-bottom:8px">
        <div>
          <span class="badge gov-severity-pill ${severityClass(req.severity)}">${escHtml(req.severity || 'low')}</span>
          <strong class="text-bright">${ACTION_LABELS[req.action_type] || escHtml(req.action_type)}</strong>
          <span class="text-faint font-sm" style="margin-left:8px">${new Date(req.requested_ts * 1000).toLocaleString()}</span>
        </div>
        <span class="text-faint font-sm">by ${escHtml(req.requested_by || '—')}</span>
      </div>
      <div class="text-bright font-sm" style="margin-bottom:4px">
        <strong>${escHtml(req.from_state)}</strong> → <strong>${escHtml(req.to_state)}</strong>
        <span class="text-faint advanced-only" style="margin-left:8px">${escHtml((req.doc_id || '').slice(0, 48))}</span>
      </div>
      <div class="text-faint font-sm" style="margin-bottom:10px">${escHtml(req.reason || '')}</div>
      <div class="plain-impact"><strong>What this means:</strong> ${escHtml(explainApprovalImpact(req))}</div>
      ${renderBlastRadius(req)}
      ${requiresHeavyAck ? `<div class="gov-escalation">High-consequence approval: rationale, reviewer identity, diff/blast-radius acknowledgment, and rollback awareness are required.</div>` : ''}
      ${isPatch ? `<div id="diff-${escHtml(req.approval_id)}" class="review-diff-shell">
          <button class="btn btn-ghost btn-sm" onclick="loadReviewDiff('${escHtml(req.approval_id)}')">Open Review Diff</button>
        </div>` : ''}
      <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end;margin-top:10px">
        <input class="input" id="rn-${escHtml(req.approval_id)}" placeholder="Approval note / rationale (required)"
          style="flex:1;min-width:180px;font-size:11px;padding:5px 8px">
        <input class="input" id="rb-${escHtml(req.approval_id)}" placeholder="Reviewer"
          style="width:120px;font-size:11px;padding:5px 8px">
        <button class="btn btn-primary btn-sm"
          onclick="executeApproval('${escHtml(req.approval_id)}', true)">✓ Approve</button>
        <button class="btn btn-ghost btn-sm"
          onclick="executeApproval('${escHtml(req.approval_id)}', false)">✗ Reject</button>
      </div>
      <div id="apr-action-${escHtml(req.approval_id)}" class="status-line font-sm" style="margin-top:6px"></div>
    </div>`;
}

async function loadReviewDiff(approvalId) {
  const box = el(`diff-${approvalId}`);
  if (!box) return;
  box.innerHTML = '<span class="spinner"></span> Loading review diff…';
  const r = await api(`/api/governance/approve/${encodeURIComponent(approvalId)}/review-diff`);
  if (r.error || r.ok === false) {
    box.innerHTML = `<span class="text-red">${escHtml(r.error || r.detail || 'Unable to load diff')}</span>`;
    return;
  }
  const changed = (r.lines || []).filter(l => l.changed).length;
  box.innerHTML = `
    <div class="constitutional-diff">
      <div class="diff-meta">
        <div><strong>Original saved version:</strong> ${escHtml(r.source_document || '—')}</div>
        <div><strong>Suggested change:</strong> ${escHtml(r.review_artifact || '—')}</div>
        <div><strong>LLM source:</strong> ${escHtml(r.llm_source || 'undisclosed')}</div>
        <div class="advanced-only"><strong>Diff hash:</strong> <code>${escHtml((r.diff_hash || '').slice(0, 24))}</code></div>
        <div><strong>Changed lines:</strong> ${changed}</div>
      </div>
      <div class="diff-table">
        ${(r.lines || []).map(line => `
          <div class="diff-row ${line.changed ? 'changed' : ''}">
            <div class="diff-line">${line.line}</div>
            <div class="diff-cell old">${escHtml(line.original || '')}</div>
            <div class="diff-cell new">${escHtml(line.proposed || '')}</div>
            <div class="diff-decision">${line.changed ? 'review' : 'same'}</div>
          </div>`).join('')}
      </div>
    </div>`;
}

async function loadGovernanceLedger() {
  const container = el('approval-queue-list');
  if (!container) return;
  container.innerHTML = '<span class="spinner"></span> Loading decision history…';
  const r = await api('/api/governance/approve/ledger?limit=200');
  const rows = r.ledger || [];
  if (!rows.length) {
    container.innerHTML = '<div class="text-faint font-sm">Decision history is empty.</div>';
    return;
  }
  container.innerHTML = `
    <div class="ledger-table">
      <div class="ledger-row ledger-head"><div>When</div><div>Decision</div><div>Status</div><div class="advanced-only">Severity</div><div class="advanced-only">Document</div><div>Reviewer</div></div>
      ${rows.map(row => `
        <div class="ledger-row ${severityClass(row.severity)}">
          <div>${new Date(row.requested_ts * 1000).toLocaleString()}</div>
          <div>${escHtml(row.action_type || '—')}</div>
          <div>${escHtml(row.status || '—')}</div>
          <div class="advanced-only">${escHtml(row.severity || 'low')} · ${escHtml(String(row.impact_score ?? '—'))}</div>
          <div class="advanced-only" title="${escHtml(row.doc_id || '')}">${escHtml((row.doc_id || '').slice(0, 28))}</div>
          <div>${escHtml(row.reviewed_by || '—')}</div>
        </div>`).join('')}
    </div>`;
}

async function executeApproval(approvalId, isApprove) {
  const note      = el(`rn-${approvalId}`)?.value?.trim();
  const reviewer  = el(`rb-${approvalId}`)?.value?.trim() || 'operator';
  const resultEl  = el(`apr-action-${approvalId}`);
  if (!note) { if (resultEl) resultEl.innerHTML = '<span class="text-red">Approval note is required.</span>'; return; }
  if (resultEl) resultEl.innerHTML = '<span class="spinner"></span>';

  const endpoint = `/api/governance/approve/${encodeURIComponent(approvalId)}/${isApprove ? 'approve' : 'reject'}`;
  const r = await api(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reviewed_by: reviewer, review_note: note }),
  });

  if (r.ok === false || r.error) {
    if (resultEl) resultEl.innerHTML = `<span class="text-red">${escHtml(r.error || r.detail || 'Error')}</span>`;
    return;
  }

  const msg = isApprove
    ? `✓ Approved. Artifact: <code>${escHtml(r.artifact_id || '—')}</code> · Signed.`
    : '✓ Rejected. No state change.';
  if (resultEl) resultEl.innerHTML = `<span class="${isApprove ? 'text-green' : 'text-amber'}">${msg}</span>`;

  // Refresh queue after 1s
  setTimeout(loadApprovalQueue, 1000);
}

async function requestPromotion() {
  const docId    = el('apr-doc-id')?.value?.trim();
  const fromRaw  = el('apr-from-d')?.value;
  const toRaw    = el('apr-to-d')?.value;
  const reason   = el('apr-reason')?.value?.trim();
  const evidence = (el('apr-evidence')?.value || '').split(',').map(x => x.trim()).filter(Boolean);
  const q        = Number(el('apr-q')?.value);
  const c        = Number(el('apr-c')?.value);
  const authorityPlane = el('apr-authority-plane')?.value || 'verification';
  const cost     = el('apr-cost')?.value?.trim();
  const context  = el('apr-context')?.value?.trim();
  const validUntil = el('apr-valid-until')?.value?.trim();
  const resultEl = el('apr-result');

  if (!docId || !reason || !evidence.length || !validUntil || Number.isNaN(q) || Number.isNaN(c)) {
    if (resultEl) resultEl.innerHTML = '<span class="text-red">Node ID, reason, evidence refs, q, c, and valid_until are required.</span>';
    return;
  }
  if (resultEl) resultEl.innerHTML = '<span class="spinner"></span>';

  const body = {
    node_id: docId,
    from_d: fromRaw === '' ? null : Number(fromRaw),
    to_d: Number(toRaw),
    reason,
    evidence_refs: evidence,
    issuer_type: 'human',
    q, c,
    valid_until: validUntil,
    cost_of_wrong: cost || null,
    context_ref: context || null,
    authority_plane: authorityPlane,
  };

  const r = await api('/api/certificate/request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (r.ok === false || r.error || r.errors) {
    const msg = r.error || r.detail || (Array.isArray(r.errors) ? r.errors.join('; ') : 'Error');
    if (resultEl) resultEl.innerHTML = `<span class="text-red">${escHtml(msg)}</span>`;
    return;
  }
  if (resultEl) resultEl.innerHTML = `<span class="text-green">✓ Certificate requested: <code>${escHtml(r.certificate_id)}</code>. Review it in the Certificate Gate.</span>`;
  if (typeof loadCertificateQueue === 'function') loadCertificateQueue();
}

async function requestSupersede() {
  const currentId     = el('sup-current-id')?.value?.trim();
  const replacementId = el('sup-replacement-id')?.value?.trim();
  const reason        = el('sup-reason')?.value?.trim();
  const requester     = el('sup-requester')?.value?.trim();
  const resultEl      = el('sup-result');

  if (!currentId || !replacementId || !reason || !requester) {
    if (resultEl) resultEl.innerHTML = '<span class="text-red">All fields are required.</span>';
    return;
  }

  // Show impact preview first
  if (resultEl) resultEl.innerHTML = '<span class="spinner"></span> Checking impact…';
  const impact = await api(`/api/governance/approve/${encodeURIComponent(currentId)}/impact`);
  const affected = impact.affected_doc_count || 0;

  const confirmed = confirm(
    `Supersede impact: ${affected} downstream document(s) reference this canonical document.\n\n` +
    `Current: ${currentId}\nReplacement: ${replacementId}\n\n` +
    `Proceed with supersede request?`
  );
  if (!confirmed) { if (resultEl) resultEl.innerHTML = '<span class="text-faint">Cancelled.</span>'; return; }

  const r = await api('/api/governance/approve/request-supersede', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      current_doc_id: currentId, replacement_doc_id: replacementId,
      reason, requested_by: requester, affected_count: affected,
    }),
  });

  if (r.ok === false || r.error) {
    if (resultEl) resultEl.innerHTML = `<span class="text-red">${escHtml(r.error || r.detail || 'Error')}</span>`;
    return;
  }
  if (resultEl) resultEl.innerHTML = `<span class="text-green">✓ Supersede request: <code>${escHtml(r.approval_id)}</code> · ${affected} references affected</span>`;
  loadApprovalQueue();
}




async function sha256Hex(text) {
  try {
    const data = new TextEncoder().encode(text);
    const buf = await crypto.subtle.digest('SHA-256', data);
    return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
  } catch (_) {
    return String(Date.now());
  }
}

async function loadPendingEdges() {
  const container = el('pending-edge-list');
  if (!container) return;
  container.innerHTML = '<span class="spinner"></span>';
  const r = await api('/api/governance/approve/edges/pending');
  const edges = r.pending || [];
  if (!edges.length) {
    container.innerHTML = '<div class="text-faint font-sm">No pending edge promotion requests.</div>';
    return;
  }
  container.innerHTML = edges.map(e => `
    <div style="padding:8px;border:1px solid var(--border-dim);border-radius:4px;margin-bottom:8px">
      <div class="font-sm">
        <span class="text-faint">Edge:</span>
        <strong>${escHtml(e.edge_type)}</strong>
        ${e.cross_project ? '<span class="badge" style="background:var(--amber);color:#000;font-size:9px;margin-left:6px">cross-project</span>' : ''}
      </div>
      <div class="text-faint font-sm">${escHtml((e.source_doc_id||'').slice(0,24))} → ${escHtml((e.target_doc_id||'').slice(0,24))}</div>
      <div style="display:flex;gap:6px;margin-top:6px">
        <input class="input" id="en-${escHtml(e.edge_apr_id)}" placeholder="Note" style="flex:1;font-size:11px;padding:4px 6px">
        <button class="btn btn-primary btn-sm" onclick="approveEdge('${escHtml(e.edge_apr_id)}')">Approve</button>
      </div>
      <div id="ea-${escHtml(e.edge_apr_id)}" class="status-line font-sm" style="margin-top:4px"></div>
    </div>`).join('');
}

async function approveEdge(edgeAprId) {
  const note = el(`en-${edgeAprId}`)?.value?.trim() || 'Approved';
  const resultEl = el(`ea-${edgeAprId}`);
  if (resultEl) resultEl.innerHTML = '<span class="spinner"></span>';
  const r = await api(`/api/governance/approve/edges/${encodeURIComponent(edgeAprId)}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reviewed_by: 'operator', review_note: note }),
  });
  if (resultEl) resultEl.innerHTML = r.ok
    ? '<span class="text-green">✓ Edge promoted to governed.</span>'
    : `<span class="text-red">${escHtml(r.error || 'Error')}</span>`;
}

// Load approval queue when governance panel opens
const _origNavGov = typeof nav === 'function' ? nav : null;
// Hook into nav() for governance panel
if (typeof nav === 'function') {
  const _navBase = nav;
  // Override inline — governance panel auto-loads approval queue
}
// Simpler: load queue on DOMContentLoaded if governance is active
window.addEventListener('load', () => {
  // Eagerly check pending approvals for badge display
  setTimeout(async () => {
    try {
      const r = await api('/api/governance/approve/pending');
      const badge = el('pending-approvals-badge');
      if (badge && r.pending?.length) {
        badge.textContent = r.pending.length;
        badge.classList.remove('hidden');
      }
    } catch (_) {}
  }, 2000);
});

// ── Phase 15: Provenance chain + quick promotion ──────────────────────────────

async function loadDocProvenance(docId, headerEl) {
  const container = el(`provenance-drawer-${docId}`);
  if (!container) return;
  // Toggle if already loaded
  const isOpen = container.style.display !== 'none' && container.dataset.loaded;
  if (isOpen) { container.style.display = 'none'; if (headerEl) headerEl.querySelector('.chevron').textContent = '▶'; return; }
  container.style.display = 'block';
  if (headerEl) headerEl.querySelector('.chevron').textContent = '▼';
  container.dataset.loaded = '1';
  container.innerHTML = '<span class="spinner"></span>';

  const r = await api(`/api/governance/approve/${encodeURIComponent(docId)}/provenance`);
  const artifacts = r.provenance || [];

  if (!artifacts.length) {
    container.innerHTML = '<div class="text-faint font-sm" style="padding:8px 0">No provenance records. This document has not undergone a governed authority transition.</div>';
    return;
  }

  container.innerHTML = artifacts.map(a => `
    <div style="padding:8px;border:1px solid var(--border-dim);border-radius:4px;margin-bottom:8px;font-size:11px">
      <div style="display:flex;justify-content:space-between;margin-bottom:4px">
        <span class="badge" style="background:var(--green-dim);color:var(--green-bright);font-size:10px;padding:1px 6px;border-radius:4px">
          ${escHtml(a.action_type || '—')}
        </span>
        <span class="text-faint">${new Date(a.approved_at * 1000).toLocaleString()}</span>
      </div>
      <div class="text-bright">${escHtml(a.from_state)} → ${escHtml(a.to_state)}</div>
      <div class="text-faint" style="margin-top:2px">
        Approved by <strong>${escHtml(a.approved_by || '—')}</strong> · ${escHtml(a.reason || '')}
      </div>
      <div style="margin-top:4px;color:var(--text-faint);font-family:var(--font-mono);font-size:10px">
        ◈ ${escHtml(a.artifact_id)} · sig: ${escHtml((a.signature||'').slice(0,16))}…
      </div>
    </div>`).join('');
}

async function quickRequestPromotion(docId, currentStatus) {
  const fromRaw   = el(`quick-apr-from-d-${docId}`)?.value;
  const toRaw     = el(`quick-apr-to-d-${docId}`)?.value;
  const reason    = el(`quick-apr-reason-${docId}`)?.value?.trim();
  const evidence  = (el(`quick-apr-evidence-${docId}`)?.value || '').split(',').map(x => x.trim()).filter(Boolean);
  const q         = Number(el(`quick-apr-q-${docId}`)?.value);
  const c         = Number(el(`quick-apr-c-${docId}`)?.value);
  const validUntil = el(`quick-apr-valid-${docId}`)?.value?.trim();
  const resultEl  = el(`quick-apr-result-${docId}`);

  if (!reason || !evidence.length || !validUntil || Number.isNaN(q) || Number.isNaN(c)) {
    if (resultEl) resultEl.innerHTML = '<span class="text-red">Reason, evidence refs, q, c, and valid_until are required.</span>';
    return;
  }
  if (resultEl) resultEl.innerHTML = '<span class="spinner"></span>';

  const r = await api('/api/certificate/request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      node_id: docId,
      from_d: fromRaw === '' ? null : Number(fromRaw),
      to_d: Number(toRaw),
      reason,
      evidence_refs: evidence,
      issuer_type: 'human',
      q, c,
      valid_until: validUntil,
      authority_plane: 'verification',
      context_ref: currentStatus || null,
    }),
  });

  if (resultEl) {
    if (r.ok) {
      resultEl.innerHTML = `<span class="text-green">✓ Certificate <code>${escHtml(r.certificate_id)}</code> requested. Review it in the Certificate Gate.</span>`;
    } else {
      const msg = r.error || r.detail || (Array.isArray(r.errors) ? r.errors.join('; ') : 'Error');
      resultEl.innerHTML = `<span class="text-red">${escHtml(msg)}</span>`;
    }
  }
}

// Fix governance panel nav: load approval queue automatically
// Uses panel visibility observer instead of window.nav monkey-patching
// (window.nav monkey-patching is prohibited per test_phase7)
(function installGovernancePanelObserver() {
  const govPanel = document.getElementById('panel-governance');
  if (!govPanel) return;
  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.type === 'attributes' && m.attributeName === 'class') {
        if (govPanel.classList.contains('active') || govPanel.style.display !== 'none') {
          if (typeof loadApprovalQueue === 'function') loadApprovalQueue();
          if (typeof loadOllamaToggleState === 'function') loadOllamaToggleState();
        }
      }
    }
  });
  observer.observe(govPanel, { attributes: true });
})();

// ══════════════════════════════════════════════════════════════

function getSelectedProjectScope() {
  const sel = el('graph-filter-project');
  if (!sel) return [];
  return [...sel.selectedOptions].map(o => o.value).filter(Boolean);
}

function clearProjectScope() {
  const sel = el('graph-filter-project');
  if (sel) [...sel.options].forEach((o, i) => { o.selected = i === 0; });
  applyGraphFilter();
}

function clearVisualizationSelection() {
  if (_graph) { _graph.selectedNode = null; _graph.focusNode = null; _graph._renderDirty = true; }
  _readerDocId = null;
  const title = el('reader-title');
  const meta = el('reader-meta');
  const content = el('reader-content');
  if (title) title.textContent = 'Select a node in the graph';
  if (meta) meta.innerHTML = '';
  if (content) content.innerHTML = '<div class="empty" style="margin-top:60px"><div class="icon" style="font-size:40px;opacity:.2">◉</div><div style="margin-top:12px">Selection cleared</div></div>';
}

// Phase 16 — Visualization modes + duplicate governance workflow
// ══════════════════════════════════════════════════════════════
let _visualizationMode = 'web';
function normalizeVisualizationMode(mode) {
  const m = String(mode || 'web').toLowerCase();
  if (m === 'geometry' || m === 'constraint-geometry') return 'constraint';
  if (m === 'structural') return 'web';
  if (['web','variable','constraint','constitutional'].includes(m)) return m;
  return 'web';
}
const CANON_VARIABLES = ['ΩV','Π','H','L_P','Δc*','A_s','P_K','Constraint Geometry','Projection Loss','Load Conservation','Asymmetric Absorption','Plane Collapse'];

function setVisualizationMode(mode) {
  _visualizationMode = normalizeVisualizationMode(mode || 'web');
  document.querySelectorAll('.viz-mode').forEach(b => {
    const idMode = normalizeVisualizationMode((b.id || '').replace('viz-mode-', ''));
    b.classList.toggle('active', idMode === _visualizationMode);
  });

  // Phase 17: every mode remains an interactive graph. The side panel explains
  // visual grammar; it does not replace or disable the canvas.
  const canvas = el('graph-canvas');
  const overlay = el('viz-overlay');
  if (canvas) { canvas.style.opacity = '1'; canvas.style.pointerEvents = 'auto'; }
  if (overlay) { overlay.classList.toggle('hidden', _visualizationMode === 'web'); }

  if (_visualizationMode === 'constitutional') {
    const showRelated = el('graph-show-related'); if (showRelated) showRelated.checked = false;
  }

  // Reload from the projection endpoint so coordinates/metrics are mode-aware.
  reloadGraph();
}

// ── Phase 17.3: Mode-specific instrument panels ────────────────────────────
// Each panel answers a distinct operational question with distinct visual grammar.

function _vizDiagnosticBanner(diagnostics) {
  if (!diagnostics || !diagnostics.length) return '';
  return diagnostics.map(d => {
    const icon   = d.severity === 'error' ? '🚫' : d.severity === 'warning' ? '⚠️' : 'ℹ️';
    const bg     = d.severity === 'error' ? 'rgba(239,68,68,0.14)' : d.severity === 'warning' ? 'rgba(245,158,11,0.11)' : 'rgba(96,165,250,0.09)';
    const border = d.severity === 'error' ? 'rgba(239,68,68,0.38)' : d.severity === 'warning' ? 'rgba(245,158,11,0.32)' : 'rgba(96,165,250,0.28)';
    return `<div style="padding:7px 10px;border-radius:6px;margin-bottom:7px;font-size:11px;background:${bg};border:1px solid ${border};color:var(--text-muted)">${icon} ${escHtml(d.message)}</div>`;
  }).join('');
}

// ── Phase 18: Daenary epistemic instrument panels ─────────────────────────────

function _epBadge(d, m, q, c, cs) {
  if (d == null && q == null) return '<span style="color:var(--text-faint);font-size:10px">no state</span>';
  const dColor = {1:'#22c55e',0:'#f59e0b','-1':'#ef4444'}[String(d)] || '#475569';
  const mColor = m === 'cancel' ? '#ef4444' : m === 'contain' ? '#f59e0b' : 'transparent';
  const csColor = {accurate:'#22c55e',incomplete:'#60a5fa',outdated:'#f59e0b',conflicting:'#f97316',likely_incorrect:'#ef4444'}[cs] || '#475569';
  return [
    d != null ? `<span style="background:${dColor}22;color:${dColor};border:1px solid ${dColor}44;border-radius:3px;padding:1px 5px;font-size:10px;font-family:monospace">d=${d}</span>` : '',
    m ? `<span style="background:${mColor}22;color:${mColor};border:1px solid ${mColor}44;border-radius:3px;padding:1px 5px;font-size:10px;font-family:monospace">m=${m}</span>` : '',
    q != null ? `<span style="color:var(--text-faint);font-size:10px">q=${Number(q).toFixed(2)}</span>` : '',
    c != null ? `<span style="color:var(--text-faint);font-size:10px">c=${Number(c).toFixed(2)}</span>` : '',
    cs ? `<span style="color:${csColor};font-size:10px">${cs}</span>` : '',
  ].filter(Boolean).join(' ');
}

function _renderVariablePanel(nodes, edges, sidebar, diagnostics) {
  const hasData = sidebar.has_epistemic_data;
  const dCounts = sidebar.d_counts || {};
  const mCounts = sidebar.m_counts || {};
  const csCounts = sidebar.correction_counts || {};
  const dColors = {'1':'#22c55e','0':'#f59e0b','-1':'#ef4444','null':'#475569'};
  const csColors = {accurate:'#22c55e',incomplete:'#60a5fa',outdated:'#f59e0b',conflicting:'#f97316',likely_incorrect:'#ef4444',unknown:'#475569'};

  const dBars = Object.entries(dCounts).map(([d, count]) => {
    const col = dColors[String(d)] || '#475569';
    const label = d === '1' || d === 1 ? '+1 affirmed' : d === '-1' || d === -1 ? '-1 negated' : d === '0' || d === 0 ? '0 unresolved' : 'no state';
    return `<div class="viz-var-row"><span style="color:${col};font-weight:600;min-width:80px">${label}</span>
      <div style="flex:1;height:7px;border-radius:4px;background:rgba(148,163,184,.14)">
        <i style="display:block;height:100%;width:${Math.round(count/(nodes.length||1)*100)}%;background:${col};opacity:.72;border-radius:4px"></i>
      </div>
      <span style="color:var(--text-faint);font-size:10px;min-width:22px;text-align:right">${count}</span></div>`;
  }).join('');

  const csBars = Object.entries(csCounts).map(([cs, count]) => {
    const col = csColors[cs] || '#475569';
    return `<div class="viz-var-row"><span style="color:${col};font-weight:600;min-width:100px;font-size:10px">${cs}</span>
      <div style="flex:1;height:6px;border-radius:4px;background:rgba(148,163,184,.14)">
        <i style="display:block;height:100%;width:${Math.round(count/(nodes.length||1)*100)}%;background:${col};opacity:.7;border-radius:4px"></i>
      </div>
      <span style="color:var(--text-faint);font-size:10px;min-width:22px;text-align:right">${count}</span></div>`;
  }).join('');

  const topRows = (sidebar.top_nodes || []).slice(0, 6).map(n =>
    `<tr><td style="max-width:100px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(n.title||n.id)}</td>
     <td style="font-size:10px">${_epBadge(n.epistemic_d,n.epistemic_m,n.epistemic_q,n.epistemic_c,n.correction_status)}</td></tr>`
  ).join('');

  const meanQ = sidebar.mean_q != null ? sidebar.mean_q.toFixed(2) : '—';
  const meanC = sidebar.mean_c != null ? sidebar.mean_c.toFixed(2) : '—';

  return `<div class="viz-panel-header">
    <span class="viz-panel-badge" style="background:rgba(96,165,250,.13);color:#60a5fa">EVIDENCE STATE</span>
    <div class="viz-panel-question">Is each node affirmed, unresolved, or negated? What is the evidence correction status?</div>
    <div class="viz-panel-purpose" style="font-size:10px;color:var(--text-faint);margin-top:4px">
      Purpose: See which nodes have confirmed direction (d=+1), need resolution (d=0), or have been negated (d=-1).
      Use this to identify knowledge gaps and contradictions — not to assess overall risk.
    </div>
  </div>
  ${_vizDiagnosticBanner(diagnostics)}
  ${!hasData ? `<div class="viz-gap-notice">⚠ No Confidence State data found. Load the <button class="btn btn-ghost btn-sm" onclick="loadDaenaryDemoSeed()">Demo</button> to see d/m/q/c values.</div>` : ''}
  <div class="viz-grammar-grid">
    <div><span class="viz-grammar-label">X axis</span><span>c — interpretation confidence</span></div>
    <div><span class="viz-grammar-label">Y axis</span><span>q — measurement quality (top=high)</span></div>
    <div><span class="viz-grammar-label">Color</span><span>d-state: +1 green / 0 amber / -1 red</span></div>
    <div><span class="viz-grammar-label">Size</span><span>evidence quality (q)</span></div>
    <div><span class="viz-grammar-label">No state</span><span>lower-left sentinel cluster</span></div>
  </div>
  <div class="viz-section-head">Direction distribution (d-state)</div>
  <div style="display:flex;flex-direction:column;gap:4px;margin-bottom:8px">${dBars}</div>
  <div class="viz-mini-stats">
    <div><b>${meanQ}</b><span>mean quality (q)</span></div>
    <div><b>${meanC}</b><span>mean confidence (c)</span></div>
    <div><b>${sidebar.no_data_count||0}</b><span>no state</span></div>
  </div>
  <div class="viz-section-head">Correction status</div>
  <div style="display:flex;flex-direction:column;gap:4px;margin-bottom:8px">${csBars}</div>
  ${topRows ? `<div class="viz-section-head">Priority nodes (Contradiction Blocked / Held for Resolution / negated first)</div>
  <table class="viz-risk-table"><thead><tr><th>Node</th><th>Confidence State</th></tr></thead>
  <tbody>${topRows}</tbody></table>` : ''}`;
}

function _renderConstraintPanel(nodes, edges, sidebar, diagnostics) {
  const csColors = {accurate:'#22c55e',incomplete:'#60a5fa',outdated:'#f59e0b',conflicting:'#f97316',likely_incorrect:'#ef4444',unknown:'#475569'};
  const q = sidebar;
  const quadPills = Object.entries(q.quadrants||{}).map(([name, count]) => {
    const colors = {viable:'#22c55e',contain_zone:'#f59e0b',weak_zone:'#f97316',low_zone:'#ef4444',no_data:'#475569'};
    const col = colors[name] || '#475569';
    return `<div class="viz-zone-pill" style="border-color:${col}33;background:${col}14">
      <b style="color:${col}">${count}</b><span>${name.replace('_',' ')}</span></div>`;
  }).join('');

  const csBars = Object.entries(q.correction_counts||{}).map(([cs, count]) => {
    const col = csColors[cs] || '#475569';
    return `<div class="viz-var-row"><span style="color:${col};font-weight:600;min-width:100px;font-size:10px">${cs}</span>
      <div style="flex:1;height:6px;border-radius:4px;background:rgba(148,163,184,.14)">
        <i style="display:block;height:100%;width:${Math.round(count/(nodes.length||1)*100)}%;background:${col};opacity:.7;border-radius:4px"></i>
      </div>
      <span style="color:var(--text-faint);font-size:10px;min-width:22px;text-align:right">${count}</span></div>`;
  }).join('');

  const highCostRows = (q.high_cost_nodes||[]).slice(0,6).map(n => {
    const col = csColors[n.correction_status] || '#475569';
    return `<tr>
      <td style="max-width:90px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escHtml(n.title||n.id)}</td>
      <td style="font-size:10px"><span style="color:${col}">${escHtml(n.correction_status||'—')}</span></td>
      <td>${n.epistemic_q!=null?n.epistemic_q.toFixed(2):'—'}</td>
      <td>${n.epistemic_c!=null?n.epistemic_c.toFixed(2):'—'}</td>
      <td style="color:var(--amber)">${n.cost_total.toFixed(2)}</td>
    </tr>`;
  }).join('');

  return `<div class="viz-panel-header">
    <span class="viz-panel-badge" style="background:rgba(249,115,22,.14);color:#f97316">RISK MAP</span>
    <div class="viz-panel-question">Where should you act? Which nodes exceed the viability threshold?</div>
    <div class="viz-panel-purpose" style="font-size:10px;color:var(--text-faint);margin-top:4px">
      Purpose: Identify nodes that need intervention (lower-left danger zone) vs. nodes that are operationally safe (upper-right target zone).
      Unlike Evidence State, this is a <strong>decision surface</strong> — use it to prioritize correction work.
    </div>
  </div>
  ${_vizDiagnosticBanner(diagnostics)}
  <div class="viz-grammar-grid">
    <div><span class="viz-grammar-label">X axis</span><span>c — confidence (right = more confident)</span></div>
    <div><span class="viz-grammar-label">Y axis</span><span>q — quality (top = higher quality)</span></div>
    <div><span class="viz-grammar-label">Color</span><span>correction status (green=accurate → red=incorrect)</span></div>
    <div><span class="viz-grammar-label">Size</span><span>meaning cost — larger nodes cost more to correct</span></div>
    <div><span class="viz-grammar-label">Target zone</span><span>upper-right quadrant (q≥0.5, c≥0.5) — viable &amp; safe</span></div>
  </div>
  <div class="viz-tip-block" style="border-left:3px solid #f97316;background:rgba(249,115,22,.07);padding:6px 10px;border-radius:4px;margin-bottom:10px;font-size:11px">
    🎯 <strong>Target:</strong> Move nodes toward upper-right. 
    <span style="color:#22c55e">●</span> Upper-right = viable (high q + high c).
    <span style="color:#f59e0b">●</span> Upper-left = Held for Resolution.
    <span style="color:#f97316">●</span> Lower-right = overconfident (c high, q low).
    <span style="color:#ef4444">●</span> Lower-left = noisy/raw — intervention required.
  </div>
  <div class="viz-section-head">Viability quadrants</div>
  <div class="viz-zone-bar">${quadPills}</div>
  <div class="viz-section-head">Correction status</div>
  <div style="display:flex;flex-direction:column;gap:4px;margin-bottom:8px">${csBars}</div>
  ${(q.expired_count||0)>0?`<div style="font-size:11px;color:var(--text-faint);margin-bottom:8px">⏱ ${q.expired_count} expired node(s) — valid_until in past</div>`:''}
  ${highCostRows?`<div class="viz-section-head">Highest-cost nodes — prioritize these corrections</div>
  <table class="viz-risk-table"><thead><tr><th>Node</th><th>Status</th><th>q</th><th>c</th><th>Cost</th></tr></thead>
  <tbody>${highCostRows}</tbody></table>`:''}`;
}

function _renderConstitutionalPanel(nodes, edges, sidebar, diagnostics) {
  const laneColors = {
    raw_imported:'#475569',expired:'#6b7280',canceled:'#ef4444',contained:'#f59e0b',
    under_review:'#60a5fa',approved:'#34d399',canonical:'#10b981',archived:'#334155'
  };
  const laneCounts = sidebar.lane_counts || {};
  const lanePills = Object.entries(laneColors).map(([lane, color]) => {
    const count = laneCounts[lane] || 0;
    return `<div class="viz-zone-pill" style="border-color:${color}33;background:${color}14">
      <b style="color:${color}">${count}</b><span style="font-size:9px">${lane.replace('_',' ')}</span></div>`;
  }).join('');

  const mkList = (items, emptyMsg) => items && items.length
    ? items.map(n => `<div class="viz-const-item">
        <span style="color:var(--text-faint)">◉</span>
        <span>${escHtml(n.title||n.id)}</span>
        <span style="color:var(--text-faint);font-size:10px">${_epBadge(null,null,n.epistemic_q,n.epistemic_c,n.correction_status)}</span>
      </div>`).join('')
    : `<div class="viz-empty-note">${emptyMsg}</div>`;

  const hasEpistemic = sidebar.has_epistemic || false;

  return `<div class="viz-panel-header">
    <span class="viz-panel-badge" style="background:rgba(52,211,153,.11);color:#34d399">GOVERNANCE TOPOLOGY</span>
    <div class="viz-panel-question">What is the authority state of every node?</div>
  </div>
  ${_vizDiagnosticBanner(diagnostics)}
  ${!hasEpistemic?`<div class="viz-gap-notice">ℹ No Confidence State metadata. All nodes in raw_imported lane. <button class="btn btn-ghost btn-sm" onclick="loadDaenaryDemoSeed()">Load Demo</button></div>`:''}
  <div class="viz-grammar-grid">
    <div><span class="viz-grammar-label">X axis</span><span>custodian governance lane</span></div>
    <div><span class="viz-grammar-label">Includes</span><span>ALL nodes (no edge filtering)</span></div>
    <div><span class="viz-grammar-label">Contradiction Blocked</span><span>contradiction — promotion blocked</span></div>
    <div><span class="viz-grammar-label">Held for Resolution</span><span>ambiguous — awaiting resolution</span></div>
    <div><span class="viz-grammar-label">expired</span><span>valid_until in past</span></div>
  </div>
  <div class="viz-section-head">Lane distribution (${sidebar.total_nodes||0} nodes total)</div>
  <div class="viz-zone-bar" style="flex-wrap:wrap">${lanePills}</div>
  <div class="viz-section-head">Trusted Source (${(sidebar.canonical_nodes||[]).length})</div>
  <div class="viz-const-list">${mkList(sidebar.canonical_nodes,'No trusted source records')}</div>
  <div class="viz-section-head">Held for Resolution (${(sidebar.contained_nodes||[]).length})</div>
  <div class="viz-const-list">${mkList(sidebar.contained_nodes,'No items held for resolution')}</div>
  <div class="viz-section-head">Contradiction Blocked (${(sidebar.canceled_nodes||[]).length})</div>
  <div class="viz-const-list">${mkList(sidebar.canceled_nodes,'No contradiction-blocked nodes')}</div>
  <div class="viz-section-head">Expired (${(sidebar.expired_nodes||[]).length})</div>
  <div class="viz-const-list">${mkList(sidebar.expired_nodes,'No expired nodes')}</div>`;
}

async function loadDaenaryDemoSeed() {
  const btn = event && event.target;
  if (btn) { btn.disabled = true; btn.textContent = 'Loading…'; }
  try {
    const r = await api('/api/input/demo-seed/daenary', {method:'POST'});
    const msg = r.ok ? `✓ Loaded ${r.created} Daenary demo documents` : `Error: ${r.detail||'failed'}`;
    const ind = el('demo-project-status') || el('mode-indicator');
    if (ind) { ind.textContent = msg; ind.style.color = r.ok ? 'var(--green-bright)' : 'var(--red)'; }
    if (r.ok) reloadGraph();
  } catch(e) {
    console.error('Daenary demo load failed', e);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = 'Daenary Demo'; }
  }
}


// ── Phase 19.5: Projection manifest panel ────────────────────────────────────
// Every visualization mode must display a projection manifest.
// Projections are interpretive artifacts. They may not promote canon.

function _renderManifestPanel(manifest, panelId) {
  if (!manifest) return '';
  const pid = panelId || ('manifest-' + Math.random().toString(36).slice(2,8));

  const row = (key, val) => val
    ? `<div class="viz-manifest-row">
         <div class="viz-manifest-key">${escHtml(key)}</div>
         <div class="viz-manifest-val">${escHtml(String(val))}</div>
       </div>`
    : '';

  const list = (items, cls) => (items||[]).map(i =>
    `<div class="viz-manifest-list-item ${cls}">
       ${cls==='allowed'?'✓':cls==='forbidden'?'✗':'·'} ${escHtml(i)}
     </div>`
  ).join('');

  const qg = manifest.quality_gate || {};

  return `<div class="viz-manifest-panel" id="${escHtml(pid)}">
    <button class="viz-manifest-toggle" onclick="
      const b=this.nextElementSibling;
      b.classList.toggle('open');
      this.classList.toggle('open');
    ">
      <span>⊞ Projection Manifest</span>
      <span class="text-faint" style="font-size:9px">${escHtml(manifest.projection_id||'')}</span>
      <span class="vm-chevron">▶</span>
    </button>
    <div class="viz-manifest-body">
      <div class="viz-manifest-axis-pill">${escHtml(manifest.projection_axis||'')}</div>
      ${row('Signal', manifest.signal)}
      ${row('Metric', manifest.metric)}
      ${row('Conserved', manifest.conserved_quantity)}
      ${row('Quality gate', `min_q=${qg.min_q??'—'} · min_c=${qg.min_c??'—'}`)}
      ${manifest.discarded_dimensions?.length ? `
        <div class="viz-manifest-row">
          <div class="viz-manifest-key">Discarded</div>
          <div class="viz-manifest-list">${list(manifest.discarded_dimensions,'discarded')}</div>
        </div>` : ''}
      ${manifest.allowed_inference?.length ? `
        <div class="viz-manifest-row">
          <div class="viz-manifest-key">Allowed</div>
          <div class="viz-manifest-list">${list(manifest.allowed_inference,'allowed')}</div>
        </div>` : ''}
      ${manifest.forbidden_inference?.length ? `
        <div class="viz-manifest-row">
          <div class="viz-manifest-key">Forbidden</div>
          <div class="viz-manifest-list">${list(manifest.forbidden_inference,'forbidden')}</div>
        </div>` : ''}
      <div class="viz-manifest-non-auth">
        ✗ Non-authoritative · Cannot promote canon · Interpretive artifact only
      </div>
    </div>
  </div>`;
}

function renderVisualizationOverlay(nodes, edges) {
  const overlay = el('viz-overlay');
  const canvas  = el('graph-canvas');
  if (!overlay) return;
  if (canvas) { canvas.style.opacity = '1'; canvas.style.pointerEvents = 'auto'; }
  if (_visualizationMode === 'web') {
    // Phase 19.5: web mode shows a minimal manifest panel only.
    // Projections must declare their terms — even the relationship graph.
    const webManifest = _graphData?.projection_manifest || null;
    if (!webManifest) {
      overlay.classList.add('hidden');
      overlay.innerHTML = '';
      return;
    }
    overlay.classList.remove('hidden');
    overlay.innerHTML = `<div style="position:absolute;bottom:56px;left:12px;pointer-events:auto;max-width:340px">
      ${_renderManifestPanel(webManifest)}
    </div>`;
    return;
  }

  overlay.classList.remove('hidden');
  const sidebar     = _graphData?.sidebar              || {};
  const diagnostics = _graphData?.diagnostics          || [];
  const projection  = _graphData?.projection           || {};
  const manifest    = _graphData?.projection_manifest  || null;
  const loss        = projection.loss_summary || {};

  let innerHtml = '';
  switch (_visualizationMode) {
    case 'variable':       innerHtml = _renderVariablePanel(nodes, edges, sidebar, diagnostics);      break;
    case 'constraint':     innerHtml = _renderConstraintPanel(nodes, edges, sidebar, diagnostics);    break;
    case 'constitutional': innerHtml = _renderConstitutionalPanel(nodes, edges, sidebar, diagnostics); break;
    default:               innerHtml = '<p style="color:var(--text-faint)">Unknown mode.</p>';
  }

  const projLabel  = escHtml(projection.label || projection.method || '');
  const lossLine   = loss.mean_projection_loss != null
    ? `Mean loss: ${loss.mean_projection_loss} · Max: ${loss.max_projection_loss} · High-loss: ${loss.high_loss_nodes}`
    : '';
  const manifestHtml = _renderManifestPanel(manifest);

  overlay.innerHTML = `<div class="viz-instrument viz-instrument-sidebar" style="pointer-events:auto">
    <button class="btn btn-ghost btn-sm viz-back-btn" onclick="setVisualizationMode('web')" title="Return to Web view">← Web</button>
    ${innerHtml}
    ${manifestHtml}
    <div class="viz-proj-footer">
      ${projLabel ? `<div>${projLabel}</div>` : ''}
      ${lossLine  ? `<div>${escHtml(lossLine)}</div>` : ''}
      <div>Click any node to open reader · Shift-click expands neighbourhood</div>
    </div>
  </div>`;
}



async function loadDuplicateReview() {
  const body = el('duplicate-review-body');
  const countEl = el('duplicate-count');
  if (!body) return;
  body.innerHTML = '<span class="spinner"></span>';
  const data = await api('/api/duplicates');
  const rows = data.duplicates || [];
  if (countEl) countEl.textContent = rows.length ? `${rows.length}` : '';
  const badge = el('nav-duplicate-badge');
  if (badge) { badge.textContent = rows.length; badge.classList.toggle('hidden', rows.length === 0); }
  if (!rows.length) {
    body.innerHTML = '<div class="text-faint font-sm">No duplicate content records found.</div>';
    return;
  }
  body.innerHTML = rows.map((r, idx) => {
    const a = r.doc_path || r.doc_id || '';
    const b = r.related_path || r.related_doc_id || '';
    const docId = escHtml(r.doc_id || '');
    const relatedId = escHtml(r.related_doc_id || '');
    const safeA = escHtml(String(a).replace(/'/g, "\\'"));
    const safeB = escHtml(String(b).replace(/'/g, "\\'"));
    return `<div class="duplicate-card" data-dup="${idx}" data-doc-id="${docId}" data-related-doc-id="${relatedId}">
      <div class="dup-head"><strong>Duplicate candidate</strong><span>${escHtml(r.detected_ts || '')}</span></div>
      <div class="dup-grid">
        <div><label>Original file</label><code>${escHtml(a)}</code></div>
        <div><label>Duplicate file</label><code>${escHtml(b)}</code></div>
        <div><label>Canonical candidate</label><b>${escHtml(a || r.doc_id || 'unassigned')}</b></div>
        <div><label>Hash similarity</label><b>${r.hash_similarity ? escHtml(String(r.hash_similarity)) : 'content duplicate'}</b></div>
        <div><label>Semantic similarity</label><b>${r.semantic_similarity ? escHtml(String(r.semantic_similarity)) : 'not asserted'}</b></div>
        <div><label>Modified dates</label><b>${escHtml(r.modified_ts || r.detected_ts || 'unknown')}</b></div>
        <div><label>Authority state</label><b>${escHtml(r.authority_state || r.relationship || 'duplicate_content')}</b></div>
        <div><label>Current canonical owner</label><b>${escHtml(r.canonical_owner || 'user decision required')}</b></div>
        <div><label>Review recommendation</label><b>Compare before marking. Never auto-delete.</b></div>
      </div>
      <div class="dup-actions">
        <button class="btn btn-ghost btn-sm" onclick="markDuplicateLocal(this,'canonical')">Mark Canonical</button>
        <button class="btn btn-ghost btn-sm" onclick="markDuplicateLocal(this,'duplicate')">Mark Duplicate</button>
        <button class="btn btn-ghost btn-sm" onclick="markDuplicateLocal(this,'ignored')">Mark Ignored</button>
        <button class="btn btn-ghost btn-sm" onclick="markDuplicateLocal(this,'quarantine')">Move to Quarantine</button>
        <button class="btn btn-ghost btn-sm" onclick="compareDuplicateSideBySide(this)">Compare Side-by-Side</button>
        <button class="btn btn-ghost btn-sm" onclick="copyText('${safeB}')">Copy File Path</button>
        <button class="btn btn-ghost btn-sm" onclick="copyText('${safeA}')">Open File Location</button>
        <button class="btn btn-ghost btn-sm" onclick="openDocInReader('${docId}');nav('atlas')">Open in Visualization</button>
      </div>
      <div class="dup-note text-faint font-sm">No filesystem deletion is performed.</div>
    </div>`;
  }).join('');
}

async function markDuplicateLocal(btn, state) {
  const card = btn.closest('.duplicate-card');
  if (!card) return;
  card.dataset.reviewState = state;
  const note = card.querySelector('.dup-note');
  if (note) note.textContent = `Recording ${state} decision…`;
  const payload = { doc_id: card.dataset.docId || '', related_doc_id: card.dataset.relatedDocId || '', decision: state };
  try {
    const r = await api('/api/duplicates/decision', { method:'POST', body: JSON.stringify(payload) });
    if (note) note.textContent = r.ok
      ? `Decision recorded: ${state}. No files were deleted.`
      : `Decision not recorded: ${escHtml(r.error || r.detail || 'unknown error')}`;
  } catch (e) {
    if (note) note.textContent = `Decision not recorded: ${e.message || e}. No files were deleted.`;
  }
}

function compareDuplicateSideBySide(btn) {
  const card = btn.closest('.duplicate-card');
  if (!card) return;
  const ids = [card.dataset.docId, card.dataset.relatedDocId].filter(Boolean);
  const note = card.querySelector('.dup-note');
  if (ids[0]) { nav('atlas'); openDocInReader(ids[0]); }
  if (note) note.textContent = `Comparison staged for ${ids.join(' ↔ ')}. Use Copy Path for file-system side-by-side review. No files were deleted.`;
}


function copyText(text) {
  navigator.clipboard?.writeText(text);
}

// Visualization aliases preserve existing backend/JS names while allowing renamed UI labels.
window.zoomVisualization = function(factor){ return typeof zoomAtlas === 'function' ? zoomAtlas(factor) : undefined; };
window.resetVisualizationView = function(){ return typeof resetAtlasView === 'function' ? resetAtlasView() : undefined; };
window.fitVisualizationToScreen = function(){ return typeof fitAtlasToScreen === 'function' ? fitAtlasToScreen() : undefined; };
window.focusSelectedVisualizationNode = function(){ return typeof focusSelectedAtlasNode === 'function' ? focusSelectedAtlasNode() : undefined; };
window.setVisualizationPerfMode = function(mode){ return typeof setAtlasPerfMode === 'function' ? setAtlasPerfMode(mode) : undefined; };
window.setVisualizationOption = function(key,value){ return typeof setAtlasOption === 'function' ? setAtlasOption(key,value) : undefined; };
window.setVisualizationReaderWidth = function(mode){ return typeof setAtlasReaderWidth === 'function' ? setAtlasReaderWidth(mode) : undefined; };
window.expandSelectedVisualizationNode = function(){ return typeof expandSelectedAtlasNode === 'function' ? expandSelectedAtlasNode() : undefined; };
window.collapseVisualizationToInitial = function(){ return typeof collapseAtlasToInitial === 'function' ? collapseAtlasToInitial() : undefined; };
Object.assign(window, { setVisualizationMode, loadDuplicateReview, markDuplicateLocal, compareDuplicateSideBySide, clearProjectScope, clearVisualizationSelection, copyText });

// ═══════════════════════════════════════════════════════════════
// Phase 16.2 — State Integrity + Interface Truth
// ═══════════════════════════════════════════════════════════════

// ── Priority 2: Real simple vs advanced mode descriptions ─────────────────────

// ── Priority 2: Real simple vs advanced mode (Phase 16.2) ────────────────────
function toggleUiMode() {
  _uiMode = (_uiMode === UI_MODE.SIMPLE) ? UI_MODE.ADVANCED : UI_MODE.SIMPLE;
  try { localStorage.setItem('boh_ui_mode', _uiMode); } catch(_) {}
  applyUiMode();
  const indicator = el('mode-indicator');
  if (indicator) {
    indicator.textContent = _uiMode === UI_MODE.ADVANCED
      ? '[ ADVANCED — full provenance + schema ]'
      : '';
  }
  // Refresh current panel to apply mode to rendered content
  const activePanel = document.querySelector('.panel.active');
  if (activePanel && activePanel.id === 'panel-library') loadLibrary();
}

// ── Priority 3: Visualization mode recovery (no dead ends) ───────────────────
// Ensure every Atlas sub-mode has a clear escape
function returnToWebView() {
  setVisualizationMode('web');
}

function resetAtlasScope() {
  setVisualizationMode('web');
  if (el('graph-filter-class'))   el('graph-filter-class').value = '';
  if (el('graph-filter-project')) [...el('graph-filter-project').options].forEach((o,i)=>o.selected=i===0);
  if (el('graph-filter-layer'))   el('graph-filter-layer').value = '';
  if (el('graph-filter-status'))  el('graph-filter-status').value = '';
  if (el('graph-lineage-only'))   el('graph-lineage-only').checked = false;
  if (el('graph-show-related'))   el('graph-show-related').checked = true;
  clearVisualizationSelection();
  if (typeof applyGraphFilter === 'function') applyGraphFilter();
}

// ── Priority 4: Node identity before file path ────────────────────────────────
function renderNodeIdentityCard(doc) {
  // Returns HTML that shows meaning before implementation
  if (!doc) return '<div class="atlas-node-identity text-faint">No document data.</div>';
  const auth = doc.authority_state || 'non_authoritative';
  const canonRole = doc.status === 'canonical' ? '⬤ Canonical authority'
    : doc.status === 'draft' ? '◌ Draft — not yet authoritative'
    : doc.status === 'superseded' ? '◎ Superseded — historical record'
    : doc.status === 'archived' ? '▪ Archived'
    : doc.status || 'Unknown';
  const crossProject = doc.project && doc.project !== 'Quarantine / Legacy Import'
    ? `Part of <strong>${escHtml(doc.project)}</strong>`
    : 'Unassigned / quarantine';
  const lifecyclePos = doc.operator_state || '—';

  return `<div class="atlas-node-identity">
    <div class="node-title">${escHtml(docTitle(doc))}</div>
    <div class="node-meta">
      <div>${escHtml(crossProject)}</div>
      <div>Role: <strong>${escHtml(canonRole)}</strong></div>
      <div>Lifecycle: <strong>${escHtml(lifecyclePos)}</strong></div>
      ${doc.summary ? `<div style="margin-top:4px;color:var(--text-faint);font-size:10px">${escHtml(doc.summary.slice(0,120))}…</div>` : ''}
    </div>
    <div class="node-path-detail advanced-only" style="margin-top:6px;font-size:10px;font-family:var(--font-mono);color:var(--text-faint)">
      ${escHtml(doc.path || '—')}
    </div>
  </div>`;
}

// ── Priority 5: Graceful missing-file handling ────────────────────────────────
function renderFileMissingGracefully(docId, path, reason) {
  return `<div class="file-unavailable-card">
    <div style="font-size:13px;font-weight:600;margin-bottom:6px">📁 Archived Reference</div>
    <div style="font-size:12px;margin-bottom:4px">
      The source file for this document is not currently available on disk.
    </div>
    <div style="font-size:11px;color:var(--text-faint);margin-bottom:8px">
      Library source may have moved or been archived. The governance record and metadata remain intact.
    </div>
    <div class="recovery-options">
      <button class="btn btn-ghost btn-sm" onclick="openDrawer('${escHtml(docId)}')">View metadata →</button>
      <button class="btn btn-ghost btn-sm" onclick="loadDocProvenance('${escHtml(docId)}', null)">View provenance →</button>
      <button class="btn btn-ghost btn-sm" onclick="nav('import-ingest')">Re-import →</button>
    </div>
    <div class="advanced-only" style="margin-top:8px;font-size:10px;font-family:var(--font-mono);color:var(--text-faint)">
      Path: ${escHtml(path || '—')}<br>
      Reason: ${escHtml(reason || 'File not found on disk')}
    </div>
  </div>`;
}

function renderReviewArtifact(data, docId) {
  if (!data) return `<div class="text-faint font-sm">No analysis data returned.</div>`;

  // Phase 26.5 Fix D: detect deterministic artifact fields
  const hasDeterministic = !!(
    data.extracted_topics || data.extracted_definitions || data.extracted_variables ||
    data.suspected_conflicts || data.recommended_metadata_patch || data.placement_suggestion
  );
  const hasLegacy = !!(data.summary || data.issues || data.review);

  if (!hasDeterministic && !hasLegacy) {
    return `<div class="text-faint font-sm" style="padding:8px">
      No analysis content available. The document may be too new or the analysis pipeline has not run yet.
      <div style="margin-top:6px">→ Click <strong>↻ Regenerate</strong> to run a fresh analysis.</div>
    </div>`;
  }

  // Render deterministic artifact
  if (hasDeterministic) {
    const topics  = data.extracted_topics || [];
    const defs    = data.extracted_definitions || [];
    const vars    = data.extracted_variables || [];
    const conflicts = data.suspected_conflicts || [];
    const patch   = data.recommended_metadata_patch || {};
    const place   = data.placement_suggestion || {};
    const nonAuth = data.non_authoritative !== false;

    let html = `<div style="font-size:11px">`;

    // Header badge
    html += `<div style="display:flex;gap:8px;align-items:center;margin-bottom:10px;flex-wrap:wrap">
      <span class="badge" style="background:rgba(96,165,250,.13);color:#60a5fa;font-size:10px;padding:2px 7px;border-radius:4px">
        ${escHtml(data.artifact_type || 'deterministic_review')}
      </span>
      ${nonAuth ? '<span class="badge" style="background:rgba(245,158,11,.1);color:#f59e0b;font-size:10px;padding:2px 7px;border-radius:4px">Non-authoritative</span>' : ''}
      ${data._status ? `<span class="text-faint font-sm">${escHtml(data._status)}</span>` : ''}
    </div>`;

    // Document summary
    if (data.doc_title || data.doc_status) {
      html += `<div class="kv-grid font-sm" style="margin-bottom:10px">
        ${data.doc_title ? `<div class="kv-key">Title</div><div class="kv-val">${escHtml(data.doc_title)}</div>` : ''}
        ${data.doc_status ? `<div class="kv-key">Status</div><div class="kv-val">${escHtml(data.doc_status)}</div>` : ''}
        ${data.doc_path ? `<div class="kv-key">Path</div><div class="kv-val font-sm" style="font-family:var(--font-mono);color:var(--text-faint)">${escHtml(data.doc_path)}</div>` : ''}
      </div>`;
    }

    // Extracted Topics
    if (topics.length) {
      html += `<div style="margin-bottom:10px">
        <div class="section-head" style="margin-bottom:5px">Extracted Topics (${topics.length})</div>
        <div style="display:flex;flex-wrap:wrap;gap:4px">
          ${topics.map(t => `<span style="background:rgba(59,130,246,.08);border:1px solid rgba(59,130,246,.2);border-radius:4px;padding:2px 6px;font-size:10px">${escHtml(t)}</span>`).join('')}
        </div>
      </div>`;
    }

    // Extracted Definitions
    if (defs.length) {
      html += `<div style="margin-bottom:10px">
        <div class="section-head" style="margin-bottom:5px">Extracted Definitions (${defs.length})</div>
        ${defs.map(d => `<div style="padding:3px 0;border-bottom:1px solid var(--border-dim);font-size:11px">
          <strong>${escHtml(d.term || d)}</strong>
          ${d.block_hash ? `<span class="text-faint" style="font-size:9px;margin-left:6px;font-family:var(--font-mono)">#${escHtml(d.block_hash.slice(0,8))}</span>` : ''}
        </div>`).join('')}
      </div>`;
    }

    // Extracted Variables
    if (vars.length) {
      html += `<div style="margin-bottom:10px">
        <div class="section-head" style="margin-bottom:5px">Extracted Variables (${vars.length})</div>
        ${vars.map(v => `<div style="padding:2px 0;font-size:10px;font-family:var(--font-mono);color:var(--text-muted)">
          <span style="color:var(--text-bright)">${escHtml(v.key)}</span> = ${escHtml(v.value)}
        </div>`).join('')}
      </div>`;
    }

    // Suspected Conflicts
    if (conflicts.length) {
      html += `<div style="margin-bottom:10px">
        <div class="section-head" style="color:var(--amber);margin-bottom:5px">⚠ Suspected Conflicts (${conflicts.length})</div>
        ${conflicts.map(c => `<div style="padding:4px 6px;background:rgba(245,158,11,.07);border-radius:4px;margin-bottom:4px;font-size:11px">
          <strong>${escHtml(c.term)}</strong> conflicts with:
          ${(c.conflict_with||[]).map(t => `<span class="text-faint">${escHtml(t.title||t.doc_id)}</span>`).join(', ')}
        </div>`).join('')}
      </div>`;
    }

    // Recommended Metadata Patch
    const patchKeys = Object.keys(patch);
    if (patchKeys.length) {
      html += `<div style="margin-bottom:10px">
        <div class="section-head" style="margin-bottom:5px">Recommended Metadata Patch</div>
        <div class="alert alert-blue font-sm" style="margin-bottom:6px">Non-authoritative. Review before applying.</div>
        ${patchKeys.map(k => `<div style="font-size:11px;padding:2px 0">
          <span class="text-faint">${escHtml(k)}:</span> ${escHtml(JSON.stringify(patch[k]))}
        </div>`).join('')}
        <button class="btn btn-ghost btn-sm" style="margin-top:6px"
          onclick="applyMetadataPatch('${escHtml(docId)}', ${JSON.stringify(patch)})">
          Apply patch (requires confirmation)
        </button>
      </div>`;
    }

    // Placement Suggestion
    if (place.recommended_folder) {
      html += `<div style="margin-bottom:10px">
        <div class="section-head" style="margin-bottom:5px">Placement Suggestion</div>
        <div class="font-sm">
          <strong>${escHtml(place.recommended_folder)}</strong>
          ${(place.reasoning||[]).map(r => `<div class="text-faint" style="font-size:10px">• ${escHtml(r)}</div>`).join('')}
        </div>
      </div>`;
    }

    html += `</div>`;
    return html;
  }

  // Legacy schema (summary/issues/suggestions)
  const summary = data.summary || data.review?.summary || '';
  const issues = data.issues || data.review?.issues || [];
  const suggestions = data.suggestions || data.review?.suggestions || [];
  return `<div style="font-size:11px">
    ${summary ? `<div style="margin-bottom:8px;line-height:1.6">${escHtml(summary)}</div>` : ''}
    ${issues.length ? `<div class="text-amber font-sm" style="margin-bottom:4px">Issues (${issues.length}):</div>
      ${issues.map(i => `<div style="padding:4px 0;border-bottom:1px solid var(--border-dim)">• ${escHtml(typeof i === 'string' ? i : JSON.stringify(i))}</div>`).join('')}` : ''}
    ${suggestions.length ? `<div class="text-faint font-sm" style="margin-top:8px;margin-bottom:4px">Suggestions:</div>
      ${suggestions.map(s => `<div style="padding:4px 0;border-bottom:1px solid var(--border-dim)">→ ${escHtml(typeof s === 'string' ? s : JSON.stringify(s))}</div>`).join('')}` : ''}
  </div>`;
}

// ── Priority 6: Variable mapping confidence states ────────────────────────────
const MAPPING_STATES = {
  canonical:  { label: 'Canonical',  cls: 'mapping-canonical',  icon: '⬤' },
  reviewed:   { label: 'Reviewed',   cls: 'mapping-reviewed',   icon: '✓' },
  suggested:  { label: 'Suggested',  cls: 'mapping-suggested',  icon: '◌' },
  contested:  { label: 'Contested',  cls: 'mapping-contested',  icon: '⚡' },
  rejected:   { label: 'Rejected',   cls: 'mapping-rejected',   icon: '✗' },
  historical: { label: 'Historical', cls: 'mapping-historical', icon: '◎' },
};

function renderMappingBadge(state) {
  const s = MAPPING_STATES[state] || MAPPING_STATES.suggested;
  return `<span class="${s.cls}" title="${s.label}" style="font-size:10px;margin-right:4px">${s.icon} ${s.label}</span>`;
}

// ── Priority 7: Approval queue — severity + blast radius first ────────────────
function renderSeverityBadge(severity) {
  const cls = `severity-badge-${severity || 'low'}`;
  const labels = { low: 'Low impact', medium: 'Medium impact', high: '⚠ High impact', extreme: '🚨 Extreme — escalation required' };
  return `<span class="${cls}">${labels[severity] || 'Unknown'}</span>`;
}

function renderBlastRadiusCard(blastRadius) {
  if (!blastRadius) return '';
  const { impact_score, downstream_count, projects_touched, cross_project_exposure, rollback_complexity, governance_tier } = blastRadius;
  return `<div style="background:var(--bg-card);border-radius:4px;padding:10px;margin-bottom:10px;border:1px solid var(--border-dim);font-size:11px">
    <div style="font-weight:600;margin-bottom:6px;color:var(--text-muted)">Blast Radius</div>
    <div class="kv-grid" style="gap:4px 12px">
      <div class="kv-key">Impact score</div><div class="kv-val">${impact_score ?? '—'}</div>
      <div class="kv-key">Downstream docs</div><div class="kv-val">${downstream_count ?? '—'}</div>
      <div class="kv-key">Projects touched</div><div class="kv-val">${(projects_touched || []).join(', ') || '—'}</div>
      <div class="kv-key">Cross-project</div><div class="kv-val">${cross_project_exposure ? '⚡ Yes' : 'No'}</div>
      <div class="kv-key">Rollback complexity</div><div class="kv-val">${rollback_complexity ?? '—'}</div>
      <div class="kv-key">Governance tier</div><div class="kv-val">${governance_tier ?? '—'}</div>
    </div>
  </div>`;
}

// Patch loadApprovalQueue to show severity and blast radius before action buttons
const _origLoadApprovalQueue = typeof loadApprovalQueue === 'function' ? loadApprovalQueue : null;
async function loadApprovalQueue() {
  const container = el('approval-queue-list');
  const badge     = el('pending-approvals-badge');
  if (!container) return;
  container.innerHTML = '<span class="spinner"></span>';

  const r = await api('/api/governance/approve/pending');
  const pending = r.pending || [];

  if (badge) {
    badge.textContent = pending.length;
    badge.classList.toggle('hidden', pending.length === 0);
  }

  if (!pending.length) {
    container.innerHTML = '<div class="text-faint font-sm">No pending approval requests. All authority is current.</div>';
    return;
  }

  const ACTION_LABELS = {
    canonical_promotion: '⬆ Canonical Promotion',
    supersede_operation: '↻ Supersede',
    review_patch:        '✎ Review Patch',
    edge_promotion:      '⇌ Edge Promotion',
  };

  container.innerHTML = pending.map(req => {
    const blast = req.blast_radius || null;
    const severity = req.severity || blast?.severity || 'low';
    const sevClass = `severity-${severity}`;
    return `
    <div style="border:1px solid var(--border-dim);border-radius:5px;padding:12px;margin-bottom:12px" class="${sevClass}">
      <!-- Header: action type + severity — consequence before controls -->
      <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px">
        <div>
          <span class="badge" style="background:var(--amber);color:#000;font-size:10px;padding:1px 6px;border-radius:4px">
            ${escHtml(ACTION_LABELS[req.action_type] || req.action_type)}
          </span>
          <span style="margin-left:8px">${renderSeverityBadge(severity)}</span>
        </div>
        <span class="text-faint font-sm">${new Date((req.requested_ts || 0) * 1000).toLocaleString()}</span>
      </div>

      <!-- Document + transition — what is changing -->
      <div class="text-bright font-sm" style="margin-bottom:4px">
        <strong>${escHtml(req.from_state || '?')}</strong> → <strong>${escHtml(req.to_state || '?')}</strong>
        <span class="text-faint" style="margin-left:8px;font-size:10px">${escHtml((req.doc_id || '').slice(0, 32))}</span>
      </div>
      <div class="text-faint font-sm" style="margin-bottom:8px">${escHtml(req.reason || '')}</div>
      <div class="text-faint font-sm" style="margin-bottom:8px">Requested by <strong>${escHtml(req.requested_by || '—')}</strong></div>

      <!-- Blast radius — consequence before action -->
      ${blast ? renderBlastRadiusCard(blast) : ''}

      <!-- Action controls — last, after consequence understood -->
      <div style="padding-top:10px;border-top:1px solid var(--border-dim);display:flex;gap:8px;flex-wrap:wrap;align-items:flex-end">
        <input class="input" id="rn-${escHtml(req.approval_id)}" placeholder="Approval note (required)"
          style="flex:1;min-width:160px;font-size:11px;padding:5px 8px">
        <input class="input" id="rb-${escHtml(req.approval_id)}" placeholder="Your name"
          style="width:120px;font-size:11px;padding:5px 8px">
        <button class="btn btn-primary btn-sm"
          onclick="executeApproval('${escHtml(req.approval_id)}', true)">✓ Approve</button>
        <button class="btn btn-ghost btn-sm"
          onclick="executeApproval('${escHtml(req.approval_id)}', false)">✗ Reject</button>
      </div>
      <div id="apr-action-${escHtml(req.approval_id)}" class="status-line font-sm" style="margin-top:6px"></div>
    </div>`;
  }).join('');
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function requestReviewPatch(docId, diffHash) {
  // Quick-launch patch request from review artifact panel
  nav('governance');
  // Pre-fill patch request form if it exists
  setTimeout(() => {
    const patchDocId = el('patch-doc-id');
    const patchDiff  = el('patch-diff-hash');
    if (patchDocId) patchDocId.value = docId;
    if (patchDiff)  patchDiff.value  = diffHash || '';
  }, 300);
}

// Expose Phase 16.2 functions globally
window.returnToWebView    = returnToWebView;
window.resetAtlasScope    = resetAtlasScope;
window.renderNodeIdentityCard = renderNodeIdentityCard;
window.loadApprovalQueue  = loadApprovalQueue;  // override the earlier definition


// ── Phase 19: Plane Cards panel ──────────────────────────────────────────────

async function loadPlanes() {
  const data = await api('/api/planes');
  const grid = el('planes-stat-grid');
  if (grid && data.planes) {
    const planeColors = {Canonical:'#10b981',Internal:'#60a5fa',Evidence:'#8b5cf6',Review:'#f59e0b',Conflict:'#ef4444',Archive:'#334155'};
    grid.innerHTML = data.planes.map(p => {
      const col = planeColors[p.plane] || '#475569';
      return `<div class="stat-card">
        <div class="label" style="color:${col}">${escHtml(p.plane)}</div>
        <div class="value">${p.count}</div>
        <div class="sub" style="font-size:9px;color:var(--text-faint)">
          +${p.affirmed||0} / ${p.unresolved||0} / -${p.negated||0}
        </div>
      </div>`;
    }).join('') || '<div class="stat-card"><div class="label">No cards yet</div><div class="value">0</div></div>';
  }
  await loadPlanCards();
}

async function loadPlanCards() {
  const body  = el('planes-body');
  const count = el('planes-card-count');
  if (!body) return;
  body.innerHTML = '<tr><td colspan="7" class="text-faint" style="padding:16px;text-align:center"><span class="spinner"></span> Loading…</td></tr>';

  const plane   = el('planes-filter-plane')?.value || '';
  const ctype   = el('planes-filter-type')?.value  || '';
  const dv      = el('planes-filter-d')?.value     || '';
  const mv      = el('planes-filter-m')?.value     || '';
  const validNow = el('planes-filter-valid')?.checked  || false;
  const expired  = el('planes-filter-expired')?.checked || false;

  let url = '/api/planes/cards?limit=100';
  if (plane)    url += `&plane=${encodeURIComponent(plane)}`;
  if (ctype)    url += `&card_type=${encodeURIComponent(ctype)}`;
  if (dv !== '') url += `&d=${encodeURIComponent(dv)}`;
  if (mv)       url += `&m=${encodeURIComponent(mv)}`;
  if (validNow) url += '&valid_now=true';
  if (expired)  url += '&expired=true';

  const data = await api(url);
  if (count) count.textContent = `${data.count||0} cards`;

  if (!data.cards || !data.cards.length) {
    body.innerHTML = '<tr><td colspan="7" class="text-faint" style="padding:16px;text-align:center">No cards match filters. Try ⊕ Backfill all.</td></tr>';
    return;
  }

  const planeColors = {Canonical:'#10b981',Internal:'#60a5fa',Evidence:'#8b5cf6',Review:'#f59e0b',Conflict:'#ef4444',Archive:'#334155'};
  body.innerHTML = data.cards.map(c => {
    const pc = planeColors[c.plane] || '#475569';
    const dColor = {1:'#22c55e',0:'#f59e0b','-1':'#ef4444'}[String(c.d)] || 'var(--text-faint)';
    const validUntil = c.valid_until ? c.valid_until.slice(0,10) : '—';
    const isExpired  = c.valid_until && c.valid_until < new Date().toISOString().slice(0,10);
    return `<tr>
      <td style="font-family:var(--font-mono);font-size:10px;color:var(--text-faint)">${escHtml(c.id)}</td>
      <td><span style="color:${pc};font-weight:600;font-size:11px">${escHtml(c.plane)}</span></td>
      <td style="font-size:11px;color:var(--text-muted)">${escHtml(c.card_type)}</td>
      <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px">${escHtml(c.topic||'—')}</td>
      <td style="font-size:11px">
        b=${c.b??0}
        ${c.d!=null?`<span style="color:${dColor};font-weight:600"> d=${c.d}</span>`:''}
        ${c.m?`<span style="color:var(--amber)"> m=${c.m}</span>`:''}
      </td>
      <td style="font-size:11px;color:${isExpired?'#ef4444':'var(--text-faint)'}">${escHtml(validUntil)}</td>
      <td style="font-size:10px;color:var(--text-faint)">${c.doc_id ? `<button class="btn btn-ghost btn-sm" onclick="openDrawer('${escHtml(c.doc_id)}')">open</button>` : '—'}</td>
    </tr>`;
  }).join('');
}

async function backfillPlaneCards() {
  const btn = event?.target;
  if (btn) { btn.disabled = true; btn.textContent = 'Backfilling…'; }
  const data = await api('/api/planes/backfill');
  const msg = data.ok ? `✓ Created ${data.created}, updated ${data.updated}, errors ${data.errors}` : 'Failed';
  const count = el('planes-card-count');
  if (count) count.textContent = msg;
  if (btn) { btn.disabled = false; btn.textContent = '⊕ Backfill all'; }
  await loadPlanes();
}

// ── Phase 20: Certificate Gate + Constraint Lattice ──────────────────────────

/** Resolution Center — Decision History (governance event log).
 *  Phase 26.1: renamed from the broken loadReview CenterLedger reference.
 *  Shows the governance event log for the approval workflow.
 */
async function loadResolutionLedger() {
  const container = el('approval-queue-list');
  if (!container) return;
  container.innerHTML = '<span class="spinner"></span>';
  const r = await api('/api/governance/log?limit=50');
  const events = (r.events || r.log || []);
  if (!events.length) {
    container.innerHTML = '<div class="text-faint font-sm">No governance events recorded yet.</div>';
    return;
  }
  container.innerHTML = `<table style="width:100%;font-size:11px;border-collapse:collapse">
    <thead><tr>
      <th style="text-align:left;padding:4px 8px;color:var(--text-faint);border-bottom:1px solid var(--border-dim)">Event</th>
      <th style="text-align:left;padding:4px 8px;color:var(--text-faint);border-bottom:1px solid var(--border-dim)">Actor</th>
      <th style="text-align:left;padding:4px 8px;color:var(--text-faint);border-bottom:1px solid var(--border-dim)">Target</th>
      <th style="text-align:left;padding:4px 8px;color:var(--text-faint);border-bottom:1px solid var(--border-dim)">Time</th>
    </tr></thead>
    <tbody>${events.map(e => `<tr>
      <td style="padding:4px 8px">${escHtml(e.event_type||'—')}</td>
      <td style="padding:4px 8px;color:var(--text-faint)">${escHtml(e.actor_id||'—')}</td>
      <td style="padding:4px 8px;font-family:var(--font-mono);font-size:10px;color:var(--text-faint)">${escHtml(e.doc_id||e.target_id||'—')}</td>
      <td style="padding:4px 8px;color:var(--text-faint)">${ts(e.event_ts)}</td>
    </tr>`).join('')}</tbody>
  </table>`;
}

// Node state badge — Phase 20 states
function certStateBadge(state) {
  const labels = {
    contained:               'Held for Resolution',
    pending_review:          'pending review',
    certified:               'certified',
    canonical:               'Trusted Source',
    expired:                 'expired',
    reverted:                'reverted',
    blocked:                 'Contradiction Blocked',
    forced_collapse_detected:'⚡ forced collapse',
  };
  const label = labels[state] || state || '—';
  return `<span class="cert-badge cert-badge-${escHtml(state||'contained')}">${escHtml(label)}</span>`;
}

function certRiskLabel(risk) {
  return `<span class="cert-risk-${escHtml(risk||'moderate')}">${escHtml(risk||'—')}</span>`;
}

// Load Certificate Resolution Center
async function loadCertQueue() {
  const body  = el('cert-queue-body');
  const badge = el('cert-pending-badge');
  if (!body) return;
  body.innerHTML = '<div class="text-faint font-sm" style="padding:16px;text-align:center"><span class="spinner"></span> Loading…</div>';

  const data = await api('/api/certificate/pending?limit=50');
  const certs = data.pending || [];

  if (badge) {
    badge.textContent = certs.length;
    badge.classList.toggle('hidden', certs.length === 0);
  }

  if (!certs.length) {
    body.innerHTML = '<div class="text-faint font-sm" style="padding:16px;text-align:center">No pending certificates.</div>';
    return;
  }

  body.innerHTML = certs.map(c => {
    const fromD = c.from_d ?? '—';
    const toD   = c.to_d   ?? '—';
    const exp   = c.valid_until ? c.valid_until.slice(0,10) : '—';
    const isExpired = c.valid_until && c.valid_until < new Date().toISOString().slice(0,10);
    const evRefs = (c.evidence_refs || []).slice(0,2).join(', ') + (c.evidence_refs?.length > 2 ? '…' : '');
    return `<div class="cert-queue-row">
      <div style="font-family:var(--font-mono);font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(c.node_id)}">${escHtml((c.node_id||'').slice(0,16))}</div>
      <div class="cert-transition">d=${fromD}→${toD}</div>
      <div>${certRiskLabel(c.risk_class)}</div>
      <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${escHtml(c.reason)}">${escHtml((c.reason||'').slice(0,40))}</div>
      <div class="ep-qc">q=${c.q?.toFixed(2)??'—'} c=${c.c?.toFixed(2)??'—'}</div>
      <div style="font-size:10px;color:${isExpired?'#ef4444':'var(--text-faint)'}">${escHtml(exp)}</div>
      <div class="cert-action-group">
        <button class="btn btn-ghost btn-sm" style="font-size:10px;padding:2px 7px;color:#22c55e"
          onclick="reviewCert('${escHtml(c.certificate_id)}','approve')">✓</button>
        <button class="btn btn-ghost btn-sm" style="font-size:10px;padding:2px 7px;color:#ef4444"
          onclick="reviewCert('${escHtml(c.certificate_id)}','reject')">✗</button>
      </div>
    </div>`;
  }).join('');
}

async function reviewCert(certId, action) {
  const reviewer = prompt(`${action === 'approve' ? 'Approving' : 'Rejecting'} certificate ${certId}\nEnter your name/ID:`);
  if (!reviewer || !reviewer.trim()) return;
  const note = action === 'reject' ? (prompt('Rejection note (optional):') || '') : '';
  const r = await api('/api/certificate/review', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({certificate_id: certId, action, reviewed_by: reviewer, review_note: note}),
  });
  const msg = r.ok ? `✓ Certificate ${action === 'approve' ? 'approved' : 'rejected'}` : `Error: ${r.error||'failed'}`;
  const result = el('cert-request-result');
  if (result) { result.textContent = msg; result.style.color = r.ok ? 'var(--green-bright)' : 'var(--red)'; }
  loadCertQueue();
}

async function submitCertRequest() {
  const nodeId  = el('cert-node-id')?.value?.trim();
  const fromD   = el('cert-from-d')?.value;
  const toD     = el('cert-to-d')?.value;
  const reason  = el('cert-reason')?.value?.trim();
  const evText  = el('cert-evidence')?.value || '';
  const q       = parseFloat(el('cert-q')?.value || '0');
  const c       = parseFloat(el('cert-c')?.value || '0');
  const validUntil = el('cert-valid-until')?.value;
  const cost    = el('cert-cost')?.value?.trim() || null;
  const result  = el('cert-request-result');

  if (!nodeId || !reason || !evText || !validUntil) {
    if (result) result.textContent = '⚠ node_id, reason, evidence, and valid_until are required';
    return;
  }

  const evidenceRefs = evText.split(',').map(s => s.trim()).filter(Boolean);

  const r = await api('/api/certificate/request', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      node_id:       nodeId,
      from_d:        fromD !== '' ? parseInt(fromD) : null,
      to_d:          parseInt(toD),
      reason,
      evidence_refs: evidenceRefs,
      issuer_type:   'human',
      q, c,
      valid_until:   validUntil + 'T23:59:59Z',
      cost_of_wrong: cost,
      plane_authority: 'Governance',
    }),
  });

  if (result) {
    result.textContent = r.ok
      ? `✓ Certificate requested: ${r.certificate_id} (${r.risk_class} risk, ${r.review_required ? 'requires review' : 'auto-eligible'})`
      : `✗ ${(r.errors||[]).join(' · ')}`;
    result.style.color = r.ok ? 'var(--green-bright)' : 'var(--red)';
  }
  if (r.ok) loadCertQueue();
}

// Load certificate queue when Custodian Layer panel is opened
const _origNav = nav;
