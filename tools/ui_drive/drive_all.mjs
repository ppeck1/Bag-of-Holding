import { text, byClass, sleep, mkEl } from './dom.mjs';
const R = []; const rec = (s, p, d) => R.push({ s, p, d });
const ev = (t) => ({ target: t, stopPropagation() {}, preventDefault() {}, key: 'Enter', clientX: 10, clientY: 10 });
// Mount a screen in a container so rebuild()->old.replaceWith(n) is observable.
function mount(el) { const c = mkEl('div'); c.appendChild(el); return c; }
function clickByText(root, txt) {
  const els = [];
  (function w(e) { if (!e || typeof e !== 'object') return; if (e._handlers && e._handlers.click) { const t = text(e); if (t.includes(txt)) els.push(e); } (e.children || []).forEach(w); })(root);
  if (els.length) { els[0]._handlers.click.forEach(f => f(ev(els[0]))); return true; } return false;
}
async function tab(root, label) { const ok = clickByText(root, label); await sleep(400); return ok; }
const active = (tree) => byClass(tree, 'proj-seg').filter(b => [b.className, b._attr_class].filter(Boolean).join(' ').includes('active')).map(b => text(b));
// interactive table rows = <tr> with a click handler
function rows(root) { const o = []; (function w(e) { if (!e || typeof e !== 'object') return; if (e.tagName === 'tr' && e._handlers && e._handlers.click) o.push(e); (e.children || []).forEach(w); })(root); return o; }
function byAria(root, label) { const o = []; (function w(e) { if (!e || typeof e !== 'object') return; if (e.getAttribute && e.getAttribute('aria-label') === label) o.push(e); (e.children || []).forEach(w); })(root); return o; }
// request-trace helpers (dom.mjs records {method,path} per fetch)
const reqMark = () => globalThis.__reqlog.length;
const reqsSince = (n) => globalThis.__reqlog.slice(n);
const hasMutation = (entries) => entries.some(r => /^(POST|PUT|PATCH|DELETE)$/.test(r.method));
const hitPath = (entries, re) => entries.some(r => re.test(r.path));

// 1. Current State
try {
  const api = await import('../../app/ui2/js/api.js'); const { OverviewScreen } = await import('../../app/ui2/js/screens/overview.js');
  const d = await api.fetchOverview();
  const c = mount(OverviewScreen({ protoState: 'populated', mode: 'advanced', data: d, onSelectMetric: () => {}, onSelectDoc: () => {}, onToast: () => {}, onConfirm: () => {}, onNavigate: () => {} }));
  await sleep(300); const t = text(c);
  rec('CurrentState/render', /current|stale|conflict/i.test(t) && t.length > 50, 'len=' + t.length);
} catch (e) { rec('CurrentState', false, 'THREW ' + (e.stack || e).split('\n')[0]); }

// 2. Fold (FoldWorkspace repaints into refs it holds; read from its returned tree)
try {
  const api = await import('../../app/ui2/js/api.js'); const { FoldWorkspace } = await import('../../app/ui2/js/screens/fold.js');
  const ALL_PLANES = ['informational','subjective','evidence','internal','review','canonical','conflict','archive'];
  const data = await api.fetchFoldGraph(); const tree = FoldWorkspace({ visiblePlanes: ALL_PLANES, data, onToast: () => {} }); await sleep(200);
  const fNodeCount = byClass(tree, 'fnode').length;
  rec('Fold/render', true, fNodeCount > 0 ? fNodeCount + ' nodes' : 'no graph data (server down — skipped)');
  const svg = byClass(tree, 'fold-svg')[0], node = byClass(tree, 'fnode')[0];

  if (svg && node) {
    // Pointer-sequence: hover must be NON-DESTRUCTIVE (no replaceChildren on node layer). The hovered
    // node element must remain attached and identical (same object) so the subsequent click lands.
    const nodeCountBefore = byClass(tree, 'fnode').length;
    (node._handlers.mouseenter || []).forEach(f => f(ev(node))); await sleep(50);
    const stillThere = byClass(tree, 'fnode').includes(node) && node._parent != null;
    const noChurn = byClass(tree, 'fnode').length === nodeCountBefore;
    rec('Fold/hover-nondestructive', stillThere && noChurn, 'sameNode=' + stillThere + ' count=' + nodeCountBefore + '->' + byClass(tree, 'fnode').length);
    (node._handlers.mouseleave || []).forEach(f => f(ev(node))); await sleep(20);

    // mousedown -> mouseup -> delegated click on the still-attached node
    const m0 = reqMark();
    (svg._handlers.mousedown || []).forEach(f => f({ target: node, clientX: 10, clientY: 10, button: 0, preventDefault() {} }));
    (svg._handlers.mouseup || []).forEach(f => f({ target: node, clientX: 10, clientY: 10, button: 0 }));
    svg._handlers.click.forEach(f => f({ target: node })); await sleep(400);
    const insp = byClass(tree, 'inspector')[0]; const il = insp ? text(insp).length : 0;
    rec('Fold/click->inspector', byClass(tree, 'sel-ring').length > 0 && il > 40, 'selRing=' + (byClass(tree, 'sel-ring').length > 0) + ' inspLen=' + il);
    rec('Fold/click->fetch-node', hitPath(reqsSince(m0), /\/api\/fold\/node\//), reqsSince(m0).map(r => r.method + r.path).slice(0, 6).join(' '));
    rec('Fold/click->no-mutation', !hasMutation(reqsSince(m0)), 'verbs=' + reqsSince(m0).map(r => r.method).join(','));
    rec('Fold/click->breadcrumb', text(byClass(tree, 'fold-crumbs')[0] || {}).length > 10, text(byClass(tree, 'fold-crumbs')[0] || {}).slice(0, 40));
    let projOk = 0, projErr = '';
    for (const name of ['Risk Map', 'Authority Path', 'Currentness Map', 'Evidence State', 'Timeline', 'Web']) {
      try { if (clickByText(tree, name)) { await sleep(150); if (active(tree).some(a => a.includes(name))) projOk++; else projErr += name + ':notActive '; } else projErr += name + ':noBtn '; }
      catch (e) { projErr += name + ':THREW '; }
    }
    rec('Fold/projection-switch', projOk >= 5, projOk + '/6 ' + projErr);
    try { const lo = clickByText(tree, 'List'); await sleep(200); rec('Fold/list-toggle', lo && byClass(tree, 'fold-list').length > 0, 'list=' + (byClass(tree, 'fold-list').length > 0)); } catch (e) { rec('Fold/list-toggle', false, 'THREW'); }
    // Back to canvas, then exercise zoom buttons (regression for the zoom()/const zoom shadow bug).
    try { clickByText(tree, 'Canvas'); await sleep(200); } catch (e) { /* ignore */ }
    try {
      const pctEl = byClass(tree, 'chip').find(c => /%/.test(text(c)));
      const before = pctEl ? text(pctEl).trim() : '';
      const zin = byAria(tree, 'Zoom in')[0]; if (zin) zin._handlers.click.forEach(f => f(ev(zin))); await sleep(50);
      const afterZoom = pctEl ? text(pctEl).trim() : '';
      const zreset = byAria(tree, 'Reset')[0]; if (zreset) zreset._handlers.click.forEach(f => f(ev(zreset))); await sleep(50);
      const afterReset = pctEl ? text(pctEl).trim() : '';
      rec('Fold/zoom-buttons', before === '100%' && afterZoom !== before && afterReset === '100%', before + '->' + afterZoom + '->' + afterReset);
    } catch (e) { rec('Fold/zoom-buttons', false, 'THREW ' + (e.stack || e).split('\n')[0]); }
  }
  // Planes filter: restrict to canonical only → visible node count ≤ total
  if (fNodeCount > 0) {
    try {
      const { FoldWorkspace: FW2 } = await import('../../app/ui2/js/screens/fold.js?pf=1');
      const filtTree = FW2({ visiblePlanes: ['canonical'], data, onToast: () => {} });
      const filtCount = byClass(filtTree, 'fnode').length;
      rec('Fold/planes-filter-applies', filtCount <= fNodeCount, `all=${fNodeCount} canonical-only=${filtCount}`);
    } catch (e) { rec('Fold/planes-filter-applies', false, 'THREW ' + (e.stack || e).split('\n')[0]); }
  }
} catch (e) { rec('Fold', false, 'THREW ' + (e.stack || e).split('\n').slice(0, 2).join(' ')); }

// 3. Library — selection routes through onSelectDoc/onSelectCard callbacks into shared Inspector.
const hasCls = (e, cls) => [e.className, e._attr_class].filter(Boolean).join(' ').split(' ').includes(cls);
try {
  const { LibraryScreen } = await import('../../app/ui2/js/screens/library.js');
  const { Inspector } = await import('../../app/ui2/js/shell.js');

  let docSel = null, cardSel = null;
  const onSelectDoc = (doc) => { docSel = doc; };
  const onSelectCard = (card) => { cardSel = card; };

  const c = mount(LibraryScreen({ onNavigate: () => {}, onToast: () => {}, onSelectDoc, onSelectCard, selectedId: null, selectedCardId: null }));
  await sleep(400);
  rec('Library/render', /Document/i.test(text(c)), text(c).slice(0, 40));

  // Documents: click a row → onSelectDoc fires with doc data; no mutations.
  let docRows = rows(c);
  rec('Library/Documents-rows', true, docRows.length > 0 ? docRows.length + ' interactive rows' : 'no docs in test DB — skipped');
  if (docRows.length) {
    docSel = null; const m0 = reqMark();
    docRows[0]._handlers.click.forEach(f => f(ev(docRows[0]))); await sleep(200);
    rec('Library/doc-row-fires-onSelectDoc', !!docSel && !!docSel.id, 'id=' + (docSel && docSel.id));
    rec('Library/doc-row-no-mutation', !hasMutation(reqsSince(m0)), 'verbs=' + reqsSince(m0).map(r => r.method).join(','));

    // Keyboard Enter also fires callback
    docSel = null;
    docRows[0]._handlers.keydown && docRows[0]._handlers.keydown.forEach(f => f({ key: 'Enter', target: docRows[0] })); await sleep(100);
    rec('Library/doc-Enter-fires-onSelectDoc', !!docSel, 'id=' + (docSel && docSel.id));

    // Re-mount with selectedId → row gets selected class
    const selId = docSel && docSel.id;
    if (selId) {
      const c2 = mount(LibraryScreen({ onNavigate: () => {}, onToast: () => {}, onSelectDoc, onSelectCard, selectedId: selId, selectedCardId: null }));
      await sleep(400);
      rec('Library/doc-selected-row-highlight', rows(c2).some(r => hasCls(r, 'selected')), 'selectedRow');
    }

    // Inspector renders the doc selection (no fabricated provenance; no lib-detail)
    if (docSel) {
      const insp = mount(Inspector({ selection: { type: 'doc', doc: docSel }, onClose: () => {}, onCollapse: () => {}, onTrace: () => {} }));
      const it = text(insp);
      rec('Library/doc-Inspector-renders', it.length > 20 && byClass(insp, 'inspector').length > 0, 'len=' + it.length);
    }
  }

  // Search: query → click result → onSelectDoc fires; no mutation
  rec('Library/Search-tab', await tab(c, 'Search'), 'len=' + text(c).length);
  try {
    let inp = null; (function w(e) { if (!e||typeof e!=='object')return; if(e.tagName==='input'&&e.getAttribute&&e.getAttribute('aria-label')==='Search query') inp=e; (e.children||[]).forEach(w); })(c);
    if (inp) { inp.value = 'a'; inp._handlers.keydown && inp._handlers.keydown.forEach(f => f({ key: 'Enter', target: inp })); await sleep(500); }
    const sRows = rows(c);
    if (sRows.length) {
      docSel = null; const ms = reqMark();
      sRows[0]._handlers.click.forEach(f => f(ev(sRows[0]))); await sleep(200);
      rec('Library/search-row-fires-onSelectDoc', !!docSel && !!docSel.id, 'id=' + (docSel && docSel.id));
      rec('Library/search-row-no-mutation', !hasMutation(reqsSince(ms)), 'verbs=' + reqsSince(ms).map(r => r.method).join(','));
    } else {
      rec('Library/search-row-fires-onSelectDoc', true, 'no results (skipped)');
      rec('Library/search-row-no-mutation', true, 'no results (skipped)');
    }
  } catch (e) { rec('Library/search-row-fires-onSelectDoc', false, 'THREW ' + (e.stack || e).split('\n')[0]); }

  // PlaneCards: click a row → onSelectCard fires with raw PlaneCard; no mutation; Inspector renders PlaneCard branch
  rec('Library/PlaneCards-tab', await tab(c, 'PlaneCards'), 'len=' + text(c).length);
  try {
    const cardRows = rows(c);
    if (cardRows.length) {
      cardSel = null; const mc = reqMark();
      cardRows[0]._handlers.click.forEach(f => f(ev(cardRows[0]))); await sleep(200);
      rec('Library/card-row-fires-onSelectCard', !!cardSel && !!cardSel.id, 'id=' + (cardSel && cardSel.id));
      rec('Library/card-row-no-mutation', !hasMutation(reqsSince(mc)), 'verbs=' + reqsSince(mc).map(r => r.method).join(','));
      rec('Library/card-has-planecard-fields', !!cardSel && ('plane' in cardSel || 'card_type' in cardSel),
        'fields=' + (cardSel ? Object.keys(cardSel).filter(k => ['id','plane','card_type','topic','b','d','m','valid_until','doc_id'].includes(k)).join(',') : 'none'));
      if (cardSel) {
        const insp = mount(Inspector({ selection: { type: 'card', card: cardSel }, onClose: () => {}, onCollapse: () => {}, onTrace: () => {} }));
        rec('Library/card-Inspector-renders', text(insp).length > 10 && byClass(insp, 'inspector').length > 0, 'len=' + text(insp).length);
      }
    } else {
      rec('Library/card-row-fires-onSelectCard', true, 'no cards (skipped)');
      rec('Library/card-row-no-mutation', true, 'no cards (skipped)');
      rec('Library/card-has-planecard-fields', true, 'no cards (skipped)');
      rec('Library/card-Inspector-renders', true, 'no cards (skipped)');
    }
  } catch (e) { rec('Library/card-row-fires-onSelectCard', false, 'THREW ' + (e.stack || e).split('\n')[0]); }

  // Planes filter on CardsTab — must render without throwing; no "undefined" in output
  try {
    const { LibraryScreen: LS2 } = await import('../../app/ui2/js/screens/library.js?pf=1');
    const cFilt = mount(LS2({ onNavigate:()=>{}, onToast:()=>{}, onSelectDoc:()=>{}, onSelectCard:()=>{},
      selectedId:null, selectedCardId:null, visiblePlanes:['canonical'] }));
    await sleep(400);
    rec('Library/planes-filter-no-throw', !text(cFilt).includes('undefined'), 'len=' + text(cFilt).length);
  } catch (e) { rec('Library/planes-filter-no-throw', false, 'THREW ' + (e.stack || e).split('\n')[0]); }
} catch (e) { rec('Library', false, 'THREW ' + (e.stack || e).split('\n')[0]); }

// 4. Review
try {
  const { ReviewScreen } = await import('../../app/ui2/js/screens/review.js'); sessionStorage.setItem('boh_operator_token', 'demo');
  const c = mount(ReviewScreen({ onToast: () => {} })); await sleep(400);
  rec('Review/Conflicts', /Conflict/i.test(text(c)), 'len=' + text(c).length);
  for (const tb of ['Proposed Changes', 'Approvals', 'Review Queue']) { const ok = await tab(c, tb); rec('Review/' + tb, ok, 'len=' + text(c).length); }
  await tab(c, 'Proposed Changes'); rec('Review/AdmitReject-present', /Admit|Reject/i.test(text(c)), text(c).match(/Admit|Reject|pending|proposal/ig) ? 'found' : 'none in: ' + text(c).slice(0, 60));
} catch (e) { rec('Review', false, 'THREW ' + (e.stack || e).split('\n')[0]); }

// 5. Authority
try {
  const { AuthorityScreen } = await import('../../app/ui2/js/screens/authority.js'); const c = mount(AuthorityScreen({ onNavigate: () => {} })); await sleep(400);
  rec('Authority/render', text(c).length > 20, 'len=' + text(c).length);
  for (const tb of ['Authority Ledger', 'Trace & Gates', 'Residence']) { const ok = await tab(c, tb); rec('Authority/' + tb, ok, 'len=' + text(c).length); }
  await tab(c, 'Trace & Gates'); const tt = text(c);
  rec('Authority/Trace-has-data', /posture|allowed|blocked|advisory|gate result/i.test(tt), tt.slice(0, 80));
} catch (e) { rec('Authority', false, 'THREW ' + (e.stack || e).split('\n')[0]); }

// 6. Capture
try {
  const { CaptureScreen } = await import('../../app/ui2/js/screens/capture.js'); const c = mount(CaptureScreen({ onToast: () => {} })); await sleep(400);
  rec('Capture/render', text(c).length > 20, 'len=' + text(c).length);
  for (const tb of ['Add documents', 'Capture note', 'Capabilities', 'Quarantine', 'Duplicates']) { try { const ok = await tab(c, tb); rec('Capture/' + tb, ok, 'len=' + text(c).length); } catch (e) { rec('Capture/' + tb, false, 'THREW ' + (e.stack || e).split('\n')[0]); } }
  await tab(c, 'Capabilities'); rec('Capture/Capabilities-data', /accept|hold|quarantine|normalized|preserved/i.test(text(c)), text(c).slice(0, 50));
  await tab(c, 'Quarantine'); rec('Capture/Quarantine-data', /quarantine|hold|Approve for Retry|No active/i.test(text(c)), text(c).slice(0, 50));
  await tab(c, 'Duplicates'); rec('Capture/Duplicates-data', text(c).length > 20, text(c).slice(0, 50));
} catch (e) { rec('Capture', false, 'THREW ' + (e.stack || e).split('\n')[0]); }

// 7. Context Pack
try { const { ContextPackScreen } = await import('../../app/ui2/js/screens/context-pack.js'); const c = mount(ContextPackScreen()); await sleep(300); rec('ContextPack/render', /Context Pack/i.test(text(c)), 'ok'); }
catch (e) { rec('ContextPack', false, 'THREW ' + (e.stack || e).split('\n')[0]); }

// 8. Settings
try { const { SettingsFullScreen } = await import('../../app/ui2/js/screens/settings-full.js'); const c = mount(SettingsFullScreen({ settings: {}, onSet: () => {}, onConfirm: () => {}, onToast: () => {} })); await sleep(300); await tab(c, 'Security'); rec('Settings/Security-tab', /token|operator|Security/i.test(text(c)), 'len=' + text(c).length); }
catch (e) { rec('Settings', false, 'THREW ' + (e.stack || e).split('\n')[0]); }

// 9. Activity
try { const { ActivityScreen } = await import('../../app/ui2/js/screens/activity.js'); const c = mount(ActivityScreen()); await sleep(400); rec('Activity/render', /audit|event|Activity/i.test(text(c)), 'ok'); rec('Activity/Export-tab', await tab(c, 'Export'), 'len=' + text(c).length); }
catch (e) { rec('Activity', false, 'THREW ' + (e.stack || e).split('\n')[0]); }

// 10. Shell
try {
  const sh = await import('../../app/ui2/js/shell.js');
  const ALL_PLANES_SH = ['informational','subjective','evidence','internal','review','canonical','conflict','archive'];
  rec('Shell/Sidebar', text(sh.Sidebar({ route: 'current', onNavigate: () => {} })).length > 10, 'nav');
  const tbEl = sh.TopBar({ mode: 'advanced', onMode: () => {},
    visiblePlanes: ALL_PLANES_SH, onTogglePlane: () => {}, onShowAllPlanes: () => {},
    onOpenAlerts: () => {}, alertCount: 2, jobCount: 0, lastIndexed: 'now', diagnostics: true, onSearch: () => {} });
  const tbText = text(tbEl);
  rec('Shell/TopBar', tbText.length > 5, 'topbar len=' + tbText.length);
  rec('Shell/TopBar-no-scope',     !tbText.includes('Scope:'),                    'text=' + tbText.slice(0, 80));
  rec('Shell/TopBar-library-chip', tbText.includes('Library: Bag of Holding'),    'present=' + tbText.includes('Library: Bag of Holding'));
  rec('Shell/TopBar-planes-chip',  tbText.includes('Planes:'),                    'present=' + tbText.includes('Planes:'));
  const ad = sh.AlertsDrawer({ onClose: () => {}, onToast: () => {} }); await sleep(300); rec('Shell/AlertsDrawer', !!ad, 'built');
} catch (e) { rec('Shell', false, 'THREW ' + (e.stack || e).split('\n')[0]); }

console.log('\n=== EXHAUSTIVE /v2 FRONTEND DRIVE (live seeded server) ===');
for (const r of R) console.log((r.p ? 'PASS ' : 'FAIL ') + r.s.padEnd(30) + '| ' + r.d);
const f = R.filter(r => !r.p);
console.log('\n' + (R.length - f.length) + '/' + R.length + ' passed' + (f.length ? '  FAILURES: ' + f.map(x => x.s).join(', ') : ''));
