// DOM stub + real fetch to the live seeded server. Exercises real UI modules + real data.
const BASE = process.env.BOH_BASE || "http://127.0.0.1:8141";
class Node {}
export function mkEl(tag){
  const el=new Node(); el.tagName=tag; el.children=[]; el.style={}; el.dataset={}; el._handlers={}; el.value='';
  const cs=new Set();
  el.classList={add:(...c)=>c.forEach(x=>cs.add(x)),remove:(...c)=>c.forEach(x=>cs.delete(x)),toggle:()=>{},contains:(c)=>cs.has(c)};
  el.setAttribute=(k,v)=>{el['_attr_'+k]=v}; el.getAttribute=(k)=>el['_attr_'+k]??null; el.removeAttribute=()=>{};
  el.appendChild=(c)=>{el.children.push(c); if(c&&typeof c==='object')c._parent=el; return c;};
  el.append=(...c)=>c.forEach(x=>el.appendChild(x));
  el.replaceChildren=(...c)=>{el.children.forEach(x=>{if(x&&typeof x==='object')x._parent=null}); el.children=[]; c.forEach(x=>el.appendChild(x));};
  el.replaceWith=(n)=>{ const p=el._parent; if(p){ const i=p.children.indexOf(el); if(i>=0){p.children[i]=n; n._parent=p;} } };
  el.remove=()=>{}; el.focus=()=>{};
  el.addEventListener=(t,fn)=>{(el._handlers[t]=el._handlers[t]||[]).push(fn);};
  el.removeEventListener=()=>{};
  el.querySelector=()=>null; el.querySelectorAll=()=>[];
  el.closest=(sel)=>{ const cls=sel.replace('.',''); let n=el; while(n){ const c=[n.className,n._attr_class].filter(Boolean).join(' '); if(c.split(' ').includes(cls)) return n; n=n._parent;} return null; };
  el.insertBefore=(c)=>{el.appendChild(c);return c;};
  el.getBoundingClientRect=()=>({left:0,top:0,width:1000,height:680,right:1000,bottom:680});
  Object.defineProperty(el,'firstChild',{get(){return el.children[0]||null;}});
  Object.defineProperty(el,'innerHTML',{get(){return el._h||"";},set(v){el._h=v; if(el.content) el.content.children=[mkEl('svg')]; else el.children=[mkEl('parsed')];}});
  Object.defineProperty(el,'textContent',{get(){return el._t||"";},set(v){el._t=v; el.children=[];}});
  if(tag==='template') el.content=mkEl('#frag');
  return el;
}
globalThis.Node=Node;
globalThis.__root=mkEl('div');
globalThis.document={createElement:mkEl,createElementNS:(_n,t)=>mkEl(t),createTextNode:(t)=>{const n=new Node();n._t=t;return n;},createDocumentFragment:()=>mkEl('#frag'),getElementById:()=>globalThis.__root,querySelector:()=>null,querySelectorAll:()=>[],documentElement:mkEl('html'),body:mkEl('body'),addEventListener:()=>{},removeEventListener:()=>{}};
globalThis.window=globalThis; globalThis.addEventListener=()=>{}; globalThis.removeEventListener=()=>{};
globalThis.location={hash:'',href:BASE+'/',replace(){},assign(){}}; globalThis.history={replaceState(){},pushState(){}};
const _store={}; globalThis.sessionStorage={getItem:(k)=>_store[k]??null,setItem:(k,v)=>{_store[k]=String(v)},removeItem:(k)=>{delete _store[k]}}; globalThis.localStorage={getItem:()=>null,setItem(){},removeItem(){}};
globalThis.getComputedStyle=()=>({getPropertyValue:()=>"#888"});
globalThis.matchMedia=()=>({matches:false,addEventListener(){},removeEventListener(){},addListener(){},removeListener(){}});
globalThis.ResizeObserver=class{observe(){}unobserve(){}disconnect(){}};
globalThis.requestAnimationFrame=(f)=>setTimeout(f,0); globalThis.cancelAnimationFrame=()=>{};
const realFetch=globalThis.fetch;
// Request trace: every fetch records {method, path} so interaction tests can assert which
// endpoints were hit and FAIL if a read-only interaction emits a mutating verb.
globalThis.__reqlog=[];
globalThis.fetch=(url,opts)=>{
  const u=String(url); const path=u.startsWith('http')?u.replace(BASE,''):u;
  const method=((opts&&opts.method)||'GET').toUpperCase();
  globalThis.__reqlog.push({method,path});
  return realFetch(u.startsWith('http')?u:BASE+u, opts);
};
globalThis.Blob=class{constructor(){}}; globalThis.URL.createObjectURL=()=>"blob:x"; globalThis.URL.revokeObjectURL=()=>{};
// helpers
export function walk(el,fn){ if(!el||typeof el!=='object')return; fn(el); (el.children||[]).forEach(c=>walk(c,fn)); }
export function text(el){ const a=[]; walk(el,e=>{ if(e._t) a.push(e._t); }); return a.join(' '); }
export function byClass(el,cls){ const o=[]; walk(el,e=>{ const c=[e.className,e._attr_class].filter(Boolean).join(' '); if(c.split(' ').includes(cls)) o.push(e); }); return o; }
export function clickHandlers(el){ const o=[]; walk(el,e=>{ if(e._handlers&&e._handlers.click) o.push(e); }); return o; }
export const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
