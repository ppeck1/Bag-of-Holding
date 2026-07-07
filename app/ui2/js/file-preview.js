import { h } from "./dom.js";
import { api } from "./api.js";

const PREVIEW_CHAR_LIMIT = 6000;
const JSON_PARSE_LIMIT = 200000;
const JSON_FIELD_LIMIT = 160;
const JSONL_RECORD_LIMIT = 20;

const MARKDOWN_EXTS = new Set(["md", "markdown", "mdx", "rst"]);
const JSON_EXTS = new Set(["json", "jsonc", "ipynb"]);
const JSONL_EXTS = new Set(["jsonl", "ndjson"]);
const TEXT_EXTS = new Set([
  "txt", "csv", "log", "xml", "yaml", "yml", "ini", "toml", "cfg",
  "conf", "properties", "env", "example", "tex", "bib", "html", "htm",
  "eml", "py", "js", "ts", "tsx", "jsx", "css", "scss", "sql", "sh",
  "ps1", "bat", "cmd", "java", "cs", "go", "rs", "rb", "php", "dart",
]);
const EXTERNAL_ONLY_EXTS = new Set([
  "pdf", "doc", "docx", "rtf", "zip", "7z", "rar", "gz", "tar", "exe",
  "dll", "png", "jpg", "jpeg", "gif", "webp", "bmp", "ico", "svg",
]);

const contentCache = new Map();

function extensionOf(path) {
  const name = String(path || "").split(/[\\/]/).pop() || "";
  if (name.toLowerCase().endsWith(".env.example")) return "example";
  const m = name.match(/\.([^.]+)$/);
  return m ? m[1].toLowerCase() : "";
}

function previewKind(path, text) {
  const ext = extensionOf(path);
  const trimmed = String(text || "").trimStart();
  if (JSONL_EXTS.has(ext)) return "jsonl";
  if (JSON_EXTS.has(ext) || trimmed.startsWith("{") || trimmed.startsWith("[")) return "json";
  if (MARKDOWN_EXTS.has(ext) || /^#{1,6}\s/m.test(text) || /\[[^\]]+\]\([^)]+\)/.test(text)) return "markdown";
  if (TEXT_EXTS.has(ext) || !ext) return "text";
  return "unsupported";
}

function isExternalOnly(path) {
  return EXTERNAL_ONLY_EXTS.has(extensionOf(path));
}

function boundedText(raw) {
  const text = String(raw == null ? "" : raw);
  if (text.length <= PREVIEW_CHAR_LIMIT) return { text, truncated: false, originalLength: text.length };
  return { text: text.slice(0, PREVIEW_CHAR_LIMIT), truncated: true, originalLength: text.length };
}

function getContent(docId) {
  const key = String(docId || "");
  if (!contentCache.has(key)) {
    const entry = { status: "loading", value: "", error: "", promise: null };
    entry.promise = api(`/api/docs/${encodeURIComponent(key)}/content`).then((result) => {
      if (typeof result === "string") {
        entry.status = "ready";
        entry.value = result;
      } else {
        entry.status = "error";
        entry.error = (result && result.error) || "Preview unavailable.";
      }
      return entry;
    });
    contentCache.set(key, entry);
  }
  return contentCache.get(key);
}

export function AssociatedFilePreview({ docId, path, title = "Associated file" }) {
  const body = h("div", { class: "file-preview-body" });
  const root = h("section", { class: "file-preview" },
    h("div", { class: "file-preview-head" },
      h("div", null,
        h("div", { class: "t-micro muted" }, "Associated files"),
        h("div", { class: "file-preview-title" }, title)),
      extensionOf(path) && h("span", { class: "file-preview-ext" }, extensionOf(path))),
    path && h("div", { class: "file-preview-path t-mono" }, path),
    body);

  if (!docId) {
    body.replaceChildren(statusBlock("No document id is available for this file association."));
    return root;
  }
  if (isExternalOnly(path)) {
    body.replaceChildren(statusBlock("In-app preview is not available for this file type.", "Metadata is still shown above."));
    return root;
  }

  const entry = getContent(docId);
  renderEntry(body, entry, path);
  if (entry.status === "loading" && entry.promise) {
    entry.promise.then((next) => {
      if (body.isConnected) renderEntry(body, next, path);
    });
  }
  return root;
}

function renderEntry(target, entry, path) {
  if (entry.status === "loading") {
    target.replaceChildren(statusBlock("Loading preview..."));
    return;
  }
  if (entry.status === "error") {
    target.replaceChildren(statusBlock(entry.error || "Preview unavailable."));
    return;
  }
  target.replaceChildren(renderContent(path, entry.value));
}

function renderContent(path, raw) {
  const { text, truncated, originalLength } = boundedText(raw);
  if (!String(raw || "").trim()) return statusBlock("No readable content is available.");

  const kind = previewKind(path, raw);
  let rendered;
  if (kind === "json") {
    rendered = renderJsonPreview(raw, path) || codeBlock(text, "JSON-like text");
  } else if (kind === "jsonl") {
    rendered = renderJsonlPreview(raw) || codeBlock(text, "JSON Lines");
  } else if (kind === "markdown") {
    rendered = markdownBlock(text);
  } else if (kind === "text") {
    rendered = codeBlock(text, "Text preview");
  } else {
    rendered = statusBlock("No friendly preview is available for this file type.");
  }

  if (!truncated) return rendered;
  return h("div", { class: "col gap-2" },
    rendered,
    h("div", { class: "file-preview-note" }, `Preview truncated at ${PREVIEW_CHAR_LIMIT.toLocaleString()} of ${originalLength.toLocaleString()} characters.`));
}

function renderJsonPreview(raw, path) {
  if (String(raw).length > JSON_PARSE_LIMIT) return null;
  try {
    const parsed = JSON.parse(stripJsonCommentsIfNeeded(raw, path));
    return renderJsonRows(parsed, "Structured JSON");
  } catch (_) {
    return null;
  }
}

function renderJsonlPreview(raw) {
  const rows = [];
  const lines = String(raw).split(/\r?\n/).filter(line => line.trim()).slice(0, JSONL_RECORD_LIMIT);
  try {
    lines.forEach((line, i) => collectJsonRows(JSON.parse(line), `record ${i + 1}`, rows));
  } catch (_) {
    return null;
  }
  return jsonRowsBlock("Structured JSON Lines", rows, lines.length >= JSONL_RECORD_LIMIT);
}

function stripJsonCommentsIfNeeded(raw, path) {
  if (extensionOf(path) !== "jsonc") return raw;
  return String(raw).replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

function renderJsonRows(value, label) {
  const rows = [];
  collectJsonRows(value, "", rows);
  return jsonRowsBlock(label, rows, rows.length >= JSON_FIELD_LIMIT);
}

function collectJsonRows(value, prefix, rows) {
  if (rows.length >= JSON_FIELD_LIMIT) return;
  if (value == null || typeof value !== "object") {
    rows.push([prefix || "value", scalarText(value)]);
    return;
  }
  if (Array.isArray(value)) {
    if (!value.length) rows.push([prefix || "value", "[empty list]"]);
    value.slice(0, 40).forEach((item, i) => collectJsonRows(item, `${prefix || "items"}[${i}]`, rows));
    if (value.length > 40 && rows.length < JSON_FIELD_LIMIT) rows.push([prefix || "items", `${value.length - 40} more items not shown`]);
    return;
  }
  const entries = Object.entries(value);
  if (!entries.length) rows.push([prefix || "value", "{empty object}"]);
  for (const [key, child] of entries) {
    const next = prefix ? `${prefix}.${key}` : key;
    if (child != null && typeof child === "object") collectJsonRows(child, next, rows);
    else rows.push([next, scalarText(child)]);
    if (rows.length >= JSON_FIELD_LIMIT) break;
  }
}

function scalarText(value) {
  if (value == null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  const text = String(value);
  return text.length > 220 ? `${text.slice(0, 220)}...` : text;
}

function jsonRowsBlock(label, rows, capped) {
  return h("div", { class: "file-preview-json" },
    h("div", { class: "file-preview-kind" }, label),
    h("div", { class: "file-json-table" },
      rows.map(([key, value]) => h("div", { class: "file-json-row" },
        h("span", { class: "file-json-key" }, key),
        h("span", { class: "file-json-value" }, value)))),
    capped && h("div", { class: "file-preview-note" }, `Showing the first ${JSON_FIELD_LIMIT} fields.`));
}

function markdownBlock(text) {
  const lines = String(text).split(/\r?\n/).slice(0, 180);
  return h("div", { class: "file-preview-markdown" },
    lines.map((line) => {
      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      if (heading) return h("div", { class: `file-md-heading h${heading[1].length}` }, heading[2]);
      if (!line.trim()) return h("div", { class: "file-md-space" });
      const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
      if (bullet) return h("div", { class: "file-md-bullet" }, bullet[1]);
      return h("div", { class: "file-md-line" }, line);
    }));
}

function codeBlock(text, label) {
  return h("div", { class: "file-preview-code-wrap" },
    h("div", { class: "file-preview-kind" }, label),
    h("pre", { class: "file-preview-code" }, text));
}

function statusBlock(primary, secondary) {
  return h("div", { class: "file-preview-status" },
    h("div", null, primary),
    secondary && h("div", { class: "muted" }, secondary));
}
