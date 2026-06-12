// Deep interaction + error-state probes for /v2 governed UI.
// Drives the REAL app/ui2/js ES modules through the Node DOM harness with real fetch.
// For token-gated MUTATIONS, a fetch-spy records the outgoing call (proving the API is
// invoked) and returns a synthetic success for the mutating endpoints so the seeded DB
// is not modified. All READ traffic passes through to the live server unchanged.
import { text, byClass, sleep, mkEl } from './dom.mjs';

const R = [];
const rec = (s, p, d) => R.push({ s, p, d });

// Capture async failures from inside .then() callbacks (e.g. a rebuild() ReferenceError
// thrown after a successful API call surfaces here, NOT as a sync throw at the click site).
const REJECTIONS = [];
process.on('unhandledRejection', (e) => { REJECTIONS.push((e && (e.stack || e.message || String(e)) || '').split('\n')[0]); });
process.on('uncaughtException', (e) => { REJECTIONS.push('UNCAUGHT: ' + (e && (e.stack || e.message || String(e)) || '').split('\n')[0]); });
const rejectionsMatching = (re) => REJECTIONS.filter(r => re.test(r));
const ev = (t, extra = {}) => ({ target: t, stopPropagation() {}, preventDefault() {}, key: 'Enter', clientX: 10, clientY: 10, ...extra });
function mount(el) { const c = mkEl('div'); c.appendChild(el); return c; }
function findByText(root, txt) {
  const els = [];
  (function w(e) { if (!e || typeof e !== 'object') return; if (e._handlers && e._handlers.click) { if (text(e).includes(txt)) els.push(e); } (e.children || []).forEach(w); })(root);
  return els;
}
function clickByText(root, txt) { const e = findByText(root, txt); if (e.length) { e[0]._handlers.click.forEach(f => f(ev(e[0]))); return true; } return false; }
async function tab(root, label) { const ok = clickByText(root, label); await sleep(400); return ok; }

// ── fetch spy: record every call; intercept mutating endpoints with synthetic OK ──
const CALLS = [];
const realFetch = globalThis.fetch;
const MUT = /\/approve$|\/reject$|operator-disposition$/;
globalThis.fetch = (url, opts = {}) => {
  const u = String(url); const method = (opts.method || 'GET').toUpperCase();
  CALLS.push({ url: u, method, headers: opts.headers || {}, body: opts.body });
  if (MUT.test(u)) {
    // synthetic success — do NOT touch the seeded DB
    return Promise.resolve({ ok: true, status: 200, headers: { get: () => 'application/json' }, json: async () => ({ ok: true, status: 'approved' }), text: async () => '{}' });
  }
  return realFetch(url, opts);
};
const callsTo = (re) => CALLS.filter(c => re.test(c.url));
function resetCalls() { CALLS.length = 0; }

const toasts = [];
const onToast = (msg, ns) => toasts.push({ msg, ns });

const SS = globalThis.sessionStorage;

// ════════════════════════════════════════════════════════════════════════════
// 1. REVIEW CENTER — Admit / Reject proposals (token-gated)
// ════════════════════════════════════════════════════════════════════════════
try {
  const { ReviewScreen } = await import('../../app/ui2/js/screens/review.js');

  // 1a. NO token -> guidance toast, NO api call
  SS.removeItem('boh_operator_token'); toasts.length = 0; resetCalls();
  let c = mount(ReviewScreen({ onToast }));
  await tab(c, 'Proposed Changes'); await sleep(400);
  const admitBtns0 = findByText(c, 'Admit as Draft');
  rec('Review/Proposed-has-Admit-button', admitBtns0.length > 0, admitBtns0.length + ' admit buttons');
  if (admitBtns0.length) {
    resetCalls(); toasts.length = 0;
    admitBtns0[0]._handlers.click.forEach(f => f(ev(admitBtns0[0])));
    await sleep(400);
    const apiCalls = callsTo(/\/api\/llm\/queue\/.+\/approve/);
    rec('Review/Admit-no-token-blocks-API', apiCalls.length === 0, 'apiCalls=' + apiCalls.length + ' toast=' + JSON.stringify(toasts[0] || null));
  }

  // 1b. WITH token -> Admit issues POST .../approve with token header, then rebuild()
  SS.setItem('boh_operator_token', 'demo'); toasts.length = 0; resetCalls();
  c = mount(ReviewScreen({ onToast }));
  await tab(c, 'Proposed Changes'); await sleep(400);
  const admitBtns = findByText(c, 'Admit as Draft');
  let admitThrew = '';
  if (admitBtns.length) {
    try {
      admitBtns[0]._handlers.click.forEach(f => f(ev(admitBtns[0])));
    } catch (e) { admitThrew = (e && (e.stack || e.message || String(e))).split('\n')[0]; }
    await sleep(500);
  }
  const approveCalls = callsTo(/\/api\/llm\/queue\/.+\/approve/);
  const hdrTok = approveCalls[0] && (approveCalls[0].headers['X-BOH-Operator-Token']);
  rec('Review/Admit-issues-POST-approve', approveCalls.length >= 1 && approveCalls[0].method === 'POST',
    'calls=' + approveCalls.length + ' url=' + (approveCalls[0] ? approveCalls[0].url.replace('http://127.0.0.1:8150','') : '-') + ' tokenHdr=' + (hdrTok || 'MISSING'));
  // The post-success rebuild() is invoked inside ProposedTab's .then() — but `rebuild` is
  // defined in ReviewScreen, NOT in ProposedTab's scope. Expect a ReferenceError surfaced
  // as an unhandled rejection.
  await sleep(300);
  const rebuildErr = rejectionsMatching(/rebuild is not defined|ReferenceError/);
  rec('Review/Admit-rebuild-after-success', admitThrew === '' && rebuildErr.length === 0,
    admitThrew ? 'SYNC THREW: ' + admitThrew : (rebuildErr.length ? 'ASYNC REJECTION: ' + rebuildErr[0] : 'no error — rebuild succeeded'));

  // 1c. Reject issues POST .../reject
  resetCalls(); toasts.length = 0;
  const rejectBtns = findByText(c, 'Reject');
  let rejectThrew = '';
  if (rejectBtns.length) {
    try { rejectBtns[0]._handlers.click.forEach(f => f(ev(rejectBtns[0]))); } catch (e) { rejectThrew = (e.stack || String(e)).split('\n')[0]; }
    await sleep(500);
  }
  const rejectCalls = callsTo(/\/api\/llm\/queue\/.+\/reject/);
  rec('Review/Reject-issues-POST-reject', rejectCalls.length >= 1 && rejectCalls[0].method === 'POST',
    'calls=' + rejectCalls.length + ' threw=' + (rejectThrew || 'no'));
} catch (e) { rec('Review/interactions', false, 'THREW ' + (e.stack || e).split('\n').slice(0,2).join(' | ')); }

// ════════════════════════════════════════════════════════════════════════════
// 2. CAPTURE — Quarantine disposition, Capture note, Add documents
// ════════════════════════════════════════════════════════════════════════════
try {
  const { CaptureScreen } = await import('../../app/ui2/js/screens/capture.js');

  // 2a. Quarantine: NO token -> blocked
  SS.removeItem('boh_operator_token'); toasts.length = 0; resetCalls();
  let c = mount(CaptureScreen({ onToast }));
  await tab(c, 'Quarantine'); await sleep(500);
  const holdBtns0 = findByText(c, 'Hold');
  rec('Capture/Quarantine-has-Hold-button', holdBtns0.length > 0, holdBtns0.length + ' hold buttons');
  if (holdBtns0.length) {
    resetCalls(); toasts.length = 0;
    holdBtns0[0]._handlers.click.forEach(f => f(ev(holdBtns0[0])));
    await sleep(300);
    rec('Capture/Quarantine-no-token-blocks', callsTo(/operator-disposition/).length === 0,
      'dispoCalls=' + callsTo(/operator-disposition/).length + ' toast=' + JSON.stringify(toasts[0] || null));
  }

  // 2b. Quarantine: WITH token -> Hold issues PATCH operator-disposition + rebuild via load()
  SS.setItem('boh_operator_token', 'demo'); toasts.length = 0; resetCalls();
  c = mount(CaptureScreen({ onToast }));
  await tab(c, 'Quarantine'); await sleep(500);
  const holdBtns = findByText(c, 'Hold');
  let holdThrew = '';
  if (holdBtns.length) {
    try { holdBtns[0]._handlers.click.forEach(f => f(ev(holdBtns[0]))); } catch (e) { holdThrew = (e.stack || String(e)).split('\n')[0]; }
    await sleep(500);
  }
  const dispo = callsTo(/operator-disposition/);
  let bodyAction = ''; try { bodyAction = JSON.parse(dispo[0].body).action; } catch (_) {}
  rec('Capture/Quarantine-Hold-issues-PATCH', dispo.length >= 1 && dispo[0].method === 'PATCH',
    'calls=' + dispo.length + ' method=' + (dispo[0] ? dispo[0].method : '-') + ' action=' + bodyAction + ' threw=' + (holdThrew || 'no'));

  // 2c. Approve for Retry -> action:release
  SS.setItem('boh_operator_token', 'demo'); resetCalls();
  c = mount(CaptureScreen({ onToast }));
  await tab(c, 'Quarantine'); await sleep(500);
  const retryBtns = findByText(c, 'Approve for Retry');
  if (retryBtns.length) { retryBtns[0]._handlers.click.forEach(f => f(ev(retryBtns[0]))); await sleep(400); }
  const dispo2 = callsTo(/operator-disposition/);
  let act2 = ''; try { act2 = JSON.parse(dispo2[0].body).action; } catch (_) {}
  rec('Capture/Quarantine-ApproveRetry-action-release', dispo2.length >= 1 && act2 === 'release',
    'calls=' + dispo2.length + ' action=' + act2);

  // 2d. Capture note: blank body -> submit disabled; typed body -> POST /api/input/markdown
  SS.setItem('boh_operator_token', 'demo'); resetCalls(); toasts.length = 0;
  c = mount(CaptureScreen({ onToast }));
  await tab(c, 'Capture note'); await sleep(300);
  const saveBtns = findByText(c, 'Capture note').filter(b => (b._attr_class || b.className || '').includes('btn'));
  const saveBtn = saveBtns[saveBtns.length - 1];
  rec('Capture/Note-blank-submit-disabled', !!saveBtn && saveBtn.disabled === true, 'disabledBlank=' + (saveBtn ? saveBtn.disabled : 'no-btn'));
  // find the textarea
  let ta = null; (function w(e){ if(!e||typeof e!=='object')return; if(e.tagName==='textarea') ta=e; (e.children||[]).forEach(w); })(c);
  if (ta) {
    ta.value = 'Probe note body content.';
    if (ta._handlers.input) ta._handlers.input.forEach(f => f({ target: ta }));
    await sleep(50);
    rec('Capture/Note-typed-enables-submit', saveBtn && saveBtn.disabled === false, 'disabledTyped=' + (saveBtn ? saveBtn.disabled : 'no-btn'));
    resetCalls();
    if (saveBtn && saveBtn._handlers.click) saveBtn._handlers.click.forEach(f => f(ev(saveBtn)));
    await sleep(500);
    const mdCalls = callsTo(/\/api\/input\/markdown/);
    rec('Capture/Note-submit-issues-POST-markdown', mdCalls.length >= 1 && mdCalls[0].method === 'POST', 'calls=' + mdCalls.length);
  } else { rec('Capture/Note-typed-enables-submit', false, 'NO textarea found'); }

  // 2e. Add documents: index-path form -> POST /api/index; file upload present
  SS.setItem('boh_operator_token', 'demo'); resetCalls();
  c = mount(CaptureScreen({ onToast }));
  await tab(c, 'Add documents'); await sleep(300);
  const idxBtns = findByText(c, 'Index path');
  let fileInputPresent = false; (function w(e){ if(!e||typeof e!=='object')return; if(e.tagName==='input' && (e.type==='file'||e._attr_type==='file')) fileInputPresent=true; (e.children||[]).forEach(w); })(c);
  rec('Capture/AddDocs-has-file-upload', fileInputPresent, 'fileInput=' + fileInputPresent);
  if (idxBtns.length) {
    idxBtns[0]._handlers.click.forEach(f => f(ev(idxBtns[0])));
    await sleep(600);
    const idxCalls = callsTo(/\/api\/index/);
    rec('Capture/AddDocs-IndexPath-issues-POST-index', idxCalls.length >= 1 && idxCalls[0].method === 'POST', 'calls=' + idxCalls.length);
  } else { rec('Capture/AddDocs-IndexPath-issues-POST-index', false, 'no Index path button'); }
} catch (e) { rec('Capture/interactions', false, 'THREW ' + (e.stack || e).split('\n').slice(0,2).join(' | ')); }

// ════════════════════════════════════════════════════════════════════════════
// 3. CONTEXT PACK — search -> select -> assemble
// ════════════════════════════════════════════════════════════════════════════
try {
  const { ContextPackScreen } = await import('../../app/ui2/js/screens/context-pack.js');
  let c = mount(ContextPackScreen());
  await sleep(200);
  // set query on the search input + trigger search
  let qInput = null; (function w(e){ if(!e||typeof e!=='object')return; if(e.tagName==='input' && (e._attr_class||e.className||'').includes('s-input')) qInput=e; (e.children||[]).forEach(w); })(c);
  rec('ContextPack/has-search-input', !!qInput, qInput ? 'found' : 'missing');
  if (qInput) {
    qInput.value = 'test';
    if (qInput._handlers.input) qInput._handlers.input.forEach(f => f({ target: qInput }));
    // trigger search via Enter keydown handler
    if (qInput._handlers.keydown) qInput._handlers.keydown.forEach(f => f({ target: qInput, key: 'Enter' }));
    await sleep(800);
    const checks = []; (function w(e){ if(!e||typeof e!=='object')return; if(e.tagName==='input' && (e.type==='checkbox'||e._attr_type==='checkbox')) checks.push(e); (e.children||[]).forEach(w); })(c);
    rec('ContextPack/search-renders-candidates', checks.length > 0, checks.length + ' checkboxes');
    if (checks.length) {
      // select first candidate (onChange handler)
      if (checks[0]._handlers.change) checks[0]._handlers.change.forEach(f => f({ target: checks[0] }));
      await sleep(300);
      const asm = findByText(c, 'Assemble pack');
      rec('ContextPack/select-shows-Assemble', asm.length > 0, asm.length + ' assemble buttons');
      if (asm.length) {
        resetCalls();
        asm[0]._handlers.click.forEach(f => f(ev(asm[0])));
        await sleep(1000);
        const asmCalls = callsTo(/\/api\/context-pack\/assemble/);
        const t = text(c);
        rec('ContextPack/Assemble-issues-POST', asmCalls.length >= 1 && asmCalls[0].method === 'POST', 'calls=' + asmCalls.length);
        rec('ContextPack/Assemble-renders-result', /Assembled context pack|Posture|Assembly error/i.test(t), t.match(/Assembled context pack|Posture|Assembly error/i) ? 'rendered' : 'no result text');
      }
    }
  }
} catch (e) { rec('ContextPack/interactions', false, 'THREW ' + (e.stack || e).split('\n').slice(0,2).join(' | ')); }

// ════════════════════════════════════════════════════════════════════════════
// 4. SETTINGS — session token save / clear
// ════════════════════════════════════════════════════════════════════════════
try {
  const { SettingsFullScreen } = await import('../../app/ui2/js/screens/settings-full.js');
  SS.removeItem('boh_operator_token');
  let c = mount(SettingsFullScreen({ settings: {}, onSet: () => {}, onConfirm: () => {}, onToast }));
  // SecurityTab renders after /api/status resolves; that endpoint is slow (~2.1s observed).
  await tab(c, 'Security'); await sleep(3000);
  // find the password input + Save / Clear buttons
  let pwd = null; (function w(e){ if(!e||typeof e!=='object')return; if(e.tagName==='input' && (e.type==='password'||e._attr_type==='password')) pwd=e; (e.children||[]).forEach(w); })(c);
  rec('Settings/Security-has-token-input', !!pwd, pwd ? 'found' : 'missing');
  if (pwd) {
    pwd.value = 'session-token-xyz';
    const saveBtns = findByText(c, 'Save for session');
    if (saveBtns.length) saveBtns[0]._handlers.click.forEach(f => f(ev(saveBtns[0])));
    await sleep(100);
    rec('Settings/Save-sets-sessionStorage', SS.getItem('boh_operator_token') === 'session-token-xyz', 'stored=' + SS.getItem('boh_operator_token'));
    const clearBtns = findByText(c, 'Clear');
    if (clearBtns.length) clearBtns[0]._handlers.click.forEach(f => f(ev(clearBtns[0])));
    await sleep(100);
    rec('Settings/Clear-removes-sessionStorage', SS.getItem('boh_operator_token') == null, 'afterClear=' + SS.getItem('boh_operator_token'));
  }
} catch (e) { rec('Settings/interactions', false, 'THREW ' + (e.stack || e).split('\n').slice(0,2).join(' | ')); }

// ════════════════════════════════════════════════════════════════════════════
// 5. FOLD — dblclick cluster expand/collapse, keyboard nav, Escape, why-current
// ════════════════════════════════════════════════════════════════════════════
try {
  const api = await import('../../app/ui2/js/api.js');
  const { FoldWorkspace } = await import('../../app/ui2/js/screens/fold.js');
  const data = await api.fetchFoldGraph();
  const tree = FoldWorkspace({ scope: 'Atlas', data, onToast });
  await sleep(300);
  const svg = byClass(tree, 'fold-svg')[0];
  const nodes = byClass(tree, 'fnode');
  rec('Fold/render-nodes', nodes.length > 0, nodes.length + ' nodes');

  // helper: synthesize an event whose target.closest('.fnode') resolves to node g
  const nodeEvt = (g) => ({ target: g, stopPropagation(){}, preventDefault(){} });

  // 5.0 hover must be NON-DESTRUCTIVE: mouseenter must not rebuild the node layer (which would
  // detach the element under the pointer and break the subsequent click).
  if (nodes.length) {
    const n0 = nodes[0]; const cntBefore = byClass(tree, 'fnode').length;
    if (n0._handlers.mouseenter) n0._handlers.mouseenter.forEach(f => f(nodeEvt(n0)));
    await sleep(30);
    rec('Fold/hover-nondestructive', byClass(tree, 'fnode').includes(n0) && byClass(tree, 'fnode').length === cntBefore,
      'sameNode=' + byClass(tree, 'fnode').includes(n0) + ' count=' + cntBefore + '->' + byClass(tree, 'fnode').length);
    if (n0._handlers.mouseleave) n0._handlers.mouseleave.forEach(f => f(nodeEvt(n0)));
    await sleep(20);
  }

  // 5a. click a node -> inspector populates + sel-ring
  if (svg && nodes.length) {
    svg._handlers.click.forEach(f => f(nodeEvt(nodes[0])));
    await sleep(500);
    rec('Fold/node-click-selects', byClass(tree, 'sel-ring').length > 0, 'selRing=' + byClass(tree, 'sel-ring').length);
    // why-current rows present in inspector
    const t = text(tree);
    rec('Fold/why-current-rows', /Why current/i.test(t), /Why current/i.test(t) ? 'present' : 'absent');
    rec('Fold/view-full-trace-row', /View full trace/i.test(t) || /Resolver trace/i.test(t), 'traceRow');
  }

  // 5b. keyboard arrow nav (move selection among neighbors) — invoke svg keydown
  let kbThrew = '';
  const selBefore = byClass(tree, 'sel-ring').length;
  try {
    if (svg._handlers.keydown) {
      svg._handlers.keydown.forEach(f => f({ key: 'ArrowRight', preventDefault(){}, target: svg }));
      await sleep(300);
      svg._handlers.keydown.forEach(f => f({ key: 'ArrowLeft', preventDefault(){}, target: svg }));
      await sleep(300);
    }
  } catch (e) { kbThrew = (e.stack || String(e)).split('\n')[0]; }
  rec('Fold/keyboard-arrow-nav-no-throw', kbThrew === '', kbThrew ? 'THREW ' + kbThrew : 'ok (selRingNow=' + byClass(tree, 'sel-ring').length + ')');

  // 5c. Escape clears selection
  let escThrew = '';
  try { if (svg._handlers.keydown) svg._handlers.keydown.forEach(f => f({ key: 'Escape', preventDefault(){}, target: svg })); await sleep(300); }
  catch (e) { escThrew = (e.stack || String(e)).split('\n')[0]; }
  rec('Fold/Escape-clears-selection', escThrew === '' && byClass(tree, 'sel-ring').length === 0, escThrew ? 'THREW ' + escThrew : 'selRingAfterEsc=' + byClass(tree, 'sel-ring').length);

  // 5d. cluster double-click expand/collapse
  const clusters = nodes.filter(g => (g._attr_class || g.className || '').includes('fnode') && (g.getAttribute && /^cluster:/.test(g.getAttribute('data-node-id') || '')));
  rec('Fold/cluster-nodes-present', clusters.length > 0, clusters.length + ' cluster nodes (data-node-id cluster:*)');
  if (clusters.length && svg && svg._handlers.dblclick) {
    const before = byClass(tree, 'fnode').length;
    let dblThrew = '';
    try {
      svg._handlers.dblclick.forEach(f => f(nodeEvt(clusters[0])));
      await sleep(400);
    } catch (e) { dblThrew = (e.stack || String(e)).split('\n')[0]; }
    const afterExpand = byClass(tree, 'fnode').length;
    rec('Fold/cluster-dblclick-expand', dblThrew === '' && afterExpand !== before, 'before=' + before + ' afterExpand=' + afterExpand + (dblThrew ? ' THREW ' + dblThrew : ''));
    // collapse again
    try { svg._handlers.dblclick.forEach(f => f(nodeEvt(clusters[0]))); await sleep(400); } catch (_) {}
    const afterCollapse = byClass(tree, 'fnode').length;
    rec('Fold/cluster-dblclick-collapse', afterCollapse === before, 'afterCollapse=' + afterCollapse + ' (orig=' + before + ')');
  } else {
    rec('Fold/cluster-dblclick-expand', false, 'no cluster nodes OR no dblclick handler');
  }
} catch (e) { rec('Fold/interactions', false, 'THREW ' + (e.stack || e).split('\n').slice(0,2).join(' | ')); }

// ════════════════════════════════════════════════════════════════════════════
// 6. GLOBAL SEARCH deep-link -> Library pre-filled
// ════════════════════════════════════════════════════════════════════════════
try {
  const { LibraryScreen } = await import('../../app/ui2/js/screens/library.js');
  // Simulate app.js wiring: pendingSearch passed in
  const c = mount(LibraryScreen({ onNavigate: () => {}, onToast, pendingSearch: 'governance' }));
  await sleep(700);
  const t = text(c);
  // Deep-link PRE-FILLS the Search tab query (does not auto-execute). Confirm the search
  // input's value === pendingSearch AND the Search tab is active.
  let searchInputVal = null;
  (function w(e){ if(!e||typeof e!=='object')return; if(e.tagName==='input' && e['_attr_aria-label']==='Search query') searchInputVal = e.value; (e.children||[]).forEach(w); })(c);
  // fallback: any text input whose value is the query
  if (searchInputVal == null) { (function w(e){ if(!e||typeof e!=='object')return; if(e.tagName==='input' && e.value==='governance') searchInputVal=e.value; (e.children||[]).forEach(w); })(c); }
  rec('GlobalSearch/Library-prefills-query', searchInputVal === 'governance',
    'inputValue=' + JSON.stringify(searchInputVal) + ' (deep-link prefills; does not auto-run)');
} catch (e) { rec('GlobalSearch', false, 'THREW ' + (e.stack || e).split('\n').slice(0,2).join(' | ')); }

// ════════════════════════════════════════════════════════════════════════════
// 7. ERROR / EMPTY STATE branches reached when data is [] (point screens at failing route)
//    We re-import api.js with fetch returning errors to drive the error branch.
// ════════════════════════════════════════════════════════════════════════════
try {
  // Force every read to fail, then mount Review/Capture/Library and confirm they render an
  // error string rather than throwing.
  resetCalls();
  const realF2 = globalThis.fetch;
  globalThis.fetch = () => Promise.resolve({ ok: false, status: 500, headers: { get: () => 'application/json' }, json: async () => ({ detail: 'forced-500' }), text: async () => 'forced-500' });

  // Collect innerHTML (_h) too: the err() helper renders via wrap.innerHTML, which the
  // DOM stub stores on _h (not as a text node), so text() alone won't see it.
  const allHtml = (root) => { const a = []; (function w(e){ if(!e||typeof e!=='object')return; if(e._h) a.push(e._h); (e.children||[]).forEach(w); })(root); return a.join(' '); };
  const shows500 = (root) => /forced-500/.test(text(root)) || /forced-500/.test(allHtml(root));

  const { ReviewScreen } = await import('../../app/ui2/js/screens/review.js');
  let c = mount(ReviewScreen({ onToast }));
  await tab(c, 'Conflicts'); await sleep(400);   // reset module-level _tab to conflicts
  rec('ErrorState/Review-conflicts-renders-error', shows500(c), shows500(c) ? 'error string rendered (no throw)' : 'no error text: ' + text(c).slice(0, 60));

  const { CaptureScreen } = await import('../../app/ui2/js/screens/capture.js');
  c = mount(CaptureScreen({ onToast }));
  await tab(c, 'Quarantine'); await sleep(400);
  rec('ErrorState/Capture-quarantine-renders-error', shows500(c), shows500(c) ? 'error string rendered (no throw)' : 'no error text: ' + text(c).slice(0,60));

  // empty-state: make fetch return ok with empty arrays
  globalThis.fetch = (url) => Promise.resolve({ ok: true, status: 200, headers: { get: () => 'application/json' },
    json: async () => ({ conflicts: [], items: [], pending: [], proposals: [], docs: [], total: 0, planes: [], duplicates: [] }), text: async () => '{}' });
  const { ReviewScreen: RS2 } = await import('../../app/ui2/js/screens/review.js?empty=1').catch(() => ({ ReviewScreen }));
  c = mount((RS2 || ReviewScreen)({ onToast }));
  await sleep(400);
  rec('EmptyState/Review-conflicts-empty', /No conflicts/i.test(text(c)), /No conflicts/i.test(text(c)) ? 'EmptyState shown' : 'no empty text: ' + text(c).slice(0,60));
  await tab(c, 'Proposed Changes'); await sleep(400);
  rec('EmptyState/Review-proposed-empty', /No pending proposals/i.test(text(c)), /No pending proposals/i.test(text(c)) ? 'EmptyState shown' : text(c).slice(0,60));

  globalThis.fetch = realF2;
} catch (e) { rec('ErrorState/interactions', false, 'THREW ' + (e.stack || e).split('\n').slice(0,2).join(' | ')); }

// ════════════════════════════════════════════════════════════════════════════
// 8. LIBRARY — shared Inspector selection; no mutations; PlaneCard distinct type
// ════════════════════════════════════════════════════════════════════════════
try {
  const { LibraryScreen } = await import('../../app/ui2/js/screens/library.js?ro=1');
  const { Inspector } = await import('../../app/ui2/js/shell.js?ro=1');

  let docSel = null, cardSel = null;
  const onSelectDoc  = (doc)  => { docSel  = doc;  };
  const onSelectCard = (card) => { cardSel = card; };

  const c = mount(LibraryScreen({ onNavigate: () => {}, onToast, onSelectDoc, onSelectCard, selectedId: null, selectedCardId: null }));
  await sleep(500);

  // Documents tab — row click fires onSelectDoc; no mutations
  const lrows = [];
  (function w(e){ if(!e||typeof e!=='object')return; if(e.tagName==='tr'&&e._handlers&&e._handlers.click) lrows.push(e); (e.children||[]).forEach(w); })(c);
  rec('Library/RO-rows-clickable', lrows.length > 0, lrows.length + ' interactive rows');

  if (lrows.length) {
    resetCalls(); docSel = null;
    lrows[0]._handlers.click.forEach(f => f(ev(lrows[0])));
    await sleep(300);
    const mutating = CALLS.filter(c2 => /POST|PUT|PATCH|DELETE/.test(c2.method));
    rec('Library/RO-no-mutation', mutating.length === 0,
      'mutatingCalls=' + mutating.length + ' verbs=' + CALLS.map(x => x.method).join(','));
    rec('Library/RO-row-fires-onSelectDoc', !!docSel && !!docSel.id, 'id=' + (docSel && docSel.id));

    // Inspector populated from doc selection
    if (docSel) {
      const sel = { type: 'doc', doc: docSel };
      const insp = mount(Inspector({ selection: sel, onClose: () => {}, onCollapse: () => {}, onTrace: () => {} }));
      await sleep(100);
      rec('Library/RO-Inspector-renders-doc', text(insp).length > 10 && byClass(insp, 'inspector').length > 0,
        'len=' + text(insp).length);

      // Clear selection (onClose) fires callback
      let closed = false;
      const insp2 = mount(Inspector({ selection: sel, onClose: () => { closed = true; }, onCollapse: () => {}, onTrace: () => {} }));
      const closeBtn = []; (function w(e){ if(!e||typeof e!=='object')return; if(e['_attr_aria-label']==='Clear selection'&&e._handlers&&e._handlers.click) closeBtn.push(e); (e.children||[]).forEach(w); })(insp2);
      if (closeBtn.length) closeBtn[0]._handlers.click.forEach(f => f(ev(closeBtn[0])));
      rec('Library/RO-clear-fires-onClose', closed, 'closed=' + closed);

      // Collapse (onCollapse) fires callback
      let collapsed = false;
      const insp3 = mount(Inspector({ selection: sel, onClose: () => {}, onCollapse: () => { collapsed = true; }, onTrace: () => {} }));
      const colBtn = []; (function w(e){ if(!e||typeof e!=='object')return; if(e['_attr_aria-label']==='Collapse inspector'&&e._handlers&&e._handlers.click) colBtn.push(e); (e.children||[]).forEach(w); })(insp3);
      if (colBtn.length) colBtn[0]._handlers.click.forEach(f => f(ev(colBtn[0])));
      rec('Library/RO-collapse-fires-onCollapse', collapsed, 'collapsed=' + collapsed);
    }
  }

  // PlaneCards tab — card selection is raw PlaneCard (NOT a normalized "doc" shape)
  const tabOk = clickByText(c, 'PlaneCards'); await sleep(400);
  const crowRows = []; (function w(e){ if(!e||typeof e!=='object')return; if(e.tagName==='tr'&&e._handlers&&e._handlers.click) crowRows.push(e); (e.children||[]).forEach(w); })(c);
  if (crowRows.length) {
    resetCalls(); cardSel = null;
    crowRows[0]._handlers.click.forEach(f => f(ev(crowRows[0]))); await sleep(300);
    const mutating2 = CALLS.filter(c2 => /POST|PUT|PATCH|DELETE/.test(c2.method));
    rec('Library/RO-card-no-mutation', mutating2.length === 0, 'mutatingCalls=' + mutating2.length);
    rec('Library/RO-card-fires-onSelectCard', !!cardSel && !!cardSel.id, 'id=' + (cardSel && cardSel.id));
    // Raw card must NOT have been normalized into the doc shape (no "currentness" or "why" fields)
    rec('Library/RO-card-type-is-raw', !!cardSel && !('currentness' in cardSel) && !('why' in cardSel),
      'isRawCard=' + (cardSel ? (!('currentness' in cardSel)) : 'no card'));
    if (cardSel) {
      const csel = { type: 'card', card: cardSel };
      const insp = mount(Inspector({ selection: csel, onClose: () => {}, onCollapse: () => {}, onTrace: () => {} }));
      rec('Library/RO-card-Inspector-renders', text(insp).length > 10, 'len=' + text(insp).length);
    }
  } else {
    rec('Library/RO-card-no-mutation',         true, 'no cards (skipped)');
    rec('Library/RO-card-fires-onSelectCard',  true, 'no cards (skipped)');
    rec('Library/RO-card-type-is-raw',         true, 'no cards (skipped)');
    rec('Library/RO-card-Inspector-renders',   true, 'no cards (skipped)');
  }
} catch (e) { rec('Library/RO-interactions', false, 'THREW ' + (e.stack || e).split('\n').slice(0,2).join(' | ')); }

await sleep(300);
console.log('\n=== DEEP INTERACTION + ERROR-STATE PROBE (live seeded server) ===');
if (REJECTIONS.length) { console.log('UNHANDLED REJECTIONS observed (' + REJECTIONS.length + '):'); REJECTIONS.forEach(r => console.log('  ! ' + r)); console.log(''); }
for (const r of R) console.log((r.p ? 'PASS ' : 'FAIL ') + r.s.padEnd(46) + '| ' + r.d);
const f = R.filter(r => !r.p);
console.log('\n' + (R.length - f.length) + '/' + R.length + ' passed' + (f.length ? '  FAILURES: ' + f.map(x => x.s).join(', ') : ''));
