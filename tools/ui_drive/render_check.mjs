// Server-free render guard: import the real app/ui2 entry (app.js) under a DOM stub and
// confirm the module graph evaluates AND the synchronous initial render() does not throw.
//
// Catches the class of failure that blanks the SPA but passes `node --check` and the Python
// suite: a runtime error during module evaluation or the boot render (undefined access,
// bad call, etc.). No server needed — fetch is stubbed to a benign empty response, since the
// initial render paints the shell + loading states synchronously before any fetch resolves.
//
// Usage:  node render_check.mjs <path-to-app/ui2/js>
// Prints "RENDER_OK" and exits 0 on success; prints the error + exits 1 on any throw.

import { pathToFileURL } from "node:url";
import path from "node:path";

const jsDir = process.argv[2];
if (!jsDir) { console.error("usage: node render_check.mjs <ui2/js dir>"); process.exit(2); }

class Node {}
function mkEl(tag) {
  const el = new Node();
  el.tagName = tag; el.children = []; el.style = {}; el.dataset = {}; el._handlers = {}; el.value = "";
  const cs = new Set();
  el.classList = { add: (...c) => c.forEach(x => cs.add(x)), remove: (...c) => c.forEach(x => cs.delete(x)), toggle: () => {}, contains: (c) => cs.has(c) };
  el.setAttribute = (k, v) => { el["_attr_" + k] = v; };
  el.getAttribute = (k) => (el["_attr_" + k] ?? null);
  el.removeAttribute = () => {};
  el.appendChild = (c) => { el.children.push(c); if (c && typeof c === "object") c._parent = el; return c; };
  el.append = (...c) => c.forEach(x => el.appendChild(x));
  el.replaceChildren = (...c) => { el.children = []; c.forEach(x => el.appendChild(x)); };
  el.replaceWith = () => {}; el.remove = () => {}; el.focus = () => {};
  el.addEventListener = (t, fn) => { (el._handlers[t] = el._handlers[t] || []).push(fn); };
  el.removeEventListener = () => {};
  el.querySelector = () => null; el.querySelectorAll = () => [];
  el.closest = () => null; el.insertBefore = (c) => { el.appendChild(c); return c; };
  el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 1000, height: 680, right: 1000, bottom: 680 });
  Object.defineProperty(el, "firstChild", { get() { return el.children[0] || null; } });
  Object.defineProperty(el, "innerHTML", { get() { return el._h || ""; }, set(v) { el._h = v; if (el.content) el.content.children = [mkEl("svg")]; else el.children = [mkEl("parsed")]; } });
  Object.defineProperty(el, "textContent", { get() { return el._t || ""; }, set(v) { el._t = v; el.children = []; } });
  if (tag === "template") el.content = mkEl("#frag");
  return el;
}
globalThis.Node = Node;
globalThis.__root = mkEl("div");
globalThis.document = { createElement: mkEl, createElementNS: (_n, t) => mkEl(t), createTextNode: (t) => { const n = new Node(); n._t = t; return n; }, createDocumentFragment: () => mkEl("#frag"), getElementById: () => globalThis.__root, querySelector: () => null, querySelectorAll: () => [], documentElement: mkEl("html"), body: mkEl("body"), addEventListener: () => {}, removeEventListener: () => {} };
globalThis.window = globalThis; globalThis.addEventListener = () => {}; globalThis.removeEventListener = () => {};
globalThis.location = { hash: "", href: "http://localhost/", replace() {}, assign() {} };
globalThis.history = { replaceState() {}, pushState() {} };
const _store = {};
globalThis.sessionStorage = { getItem: (k) => _store[k] ?? null, setItem: (k, v) => { _store[k] = String(v); }, removeItem: (k) => { delete _store[k]; } };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };
globalThis.getComputedStyle = () => ({ getPropertyValue: () => "#888" });
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} });
globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
globalThis.requestAnimationFrame = (f) => setTimeout(f, 0); globalThis.cancelAnimationFrame = () => {};
// Benign empty fetch — initial render must not depend on it resolving.
globalThis.fetch = async () => ({ ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => ({}), text: async () => "" });
globalThis.URL.createObjectURL = () => "blob:x"; globalThis.URL.revokeObjectURL = () => {};

const entry = pathToFileURL(path.join(jsDir, "app.js")).href;
try {
  await import(entry);
  console.log("RENDER_OK");
  process.exit(0);
} catch (e) {
  console.error("RENDER_THREW:\n" + (e && e.stack ? e.stack : String(e)));
  process.exit(1);
}
