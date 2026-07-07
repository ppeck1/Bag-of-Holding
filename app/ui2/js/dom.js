/* BOH new UI (Phase A) — tiny hyperscript helper.
   Vanilla port of the React prototype: components are functions returning real
   DOM nodes. No framework, no build. `h(tag, props, ...children)`.
   - tag may be a string or a component function (props.children is passed through).
   - props: className/class, style (object), on<Event> handlers, html (trusted innerHTML
     for inline SVG icons only), aria- / data- / hyphenated keys -> setAttribute, else property. */

export function h(tag, props, ...children) {
  if (typeof tag === "function") return tag({ ...(props || {}), children });
  const el = document.createElement(tag);
  const p = props || {};
  for (const k in p) {
    const v = p[k];
    if (v == null || v === false) continue;
    if (k === "class" || k === "className") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "dataset" && typeof v === "object") Object.assign(el.dataset, v);
    else if (k === "html") el.innerHTML = v; // trusted (icon SVG paths only)
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k.startsWith("aria-") || k.startsWith("data-") || k.includes("-")) el.setAttribute(k, v);
    else { try { el[k] = v; } catch (_) { el.setAttribute(k, v); } }
  }
  appendChildren(el, children);
  return el;
}

export function appendChildren(el, children) {
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false || c === true) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

/** Replace all children of `el` with `node` (node may be a Node or array of Nodes). */
export function mount(el, node) {
  el.replaceChildren();
  if (Array.isArray(node)) appendChildren(el, node);
  else if (node != null) el.appendChild(node instanceof Node ? node : document.createTextNode(String(node)));
  return el;
}

/** Convenience: a document fragment from a list of nodes. */
export function frag(...children) {
  const f = document.createDocumentFragment();
  appendChildren(f, children);
  return f;
}

const SVG_NS = "http://www.w3.org/2000/svg";

/** SVG-namespaced hyperscript (for the Fold graph). Same prop rules as h(), but
 *  every attribute is set via setAttribute (SVG props are not plain DOM props). */
export function hs(tag, props, ...children) {
  if (typeof tag === "function") return tag({ ...(props || {}), children });
  const el = document.createElementNS(SVG_NS, tag);
  const p = props || {};
  for (const k in p) {
    const v = p[k];
    if (v == null || v === false) continue;
    if (k === "class" || k === "className") el.setAttribute("class", v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false || c === true) continue;
    el.appendChild(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}
