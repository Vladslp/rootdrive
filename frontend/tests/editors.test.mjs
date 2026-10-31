import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { createRequire } from "node:module";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";
import { JSDOM } from "jsdom";
import { createElement as h, act, useState } from "react";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  HTMLElement: dom.window.HTMLElement,
  Element: dom.window.Element,
  MutationObserver: dom.window.MutationObserver,
  Window: dom.window.Window,
  getComputedStyle: dom.window.getComputedStyle,
  IS_REACT_ACT_ENVIRONMENT: true,
  requestAnimationFrame: (callback) => { callback(0); return 1; },
  cancelAnimationFrame: () => {},
  ResizeObserver: class { observe() {} disconnect() {} },
});
dom.window.requestAnimationFrame = (callback) => setTimeout(() => callback(0), 16);
dom.window.cancelAnimationFrame = clearTimeout;
dom.window.Range.prototype.getClientRects = () => [];
dom.window.Range.prototype.getBoundingClientRect = () => ({ left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 });
Object.defineProperty(dom.window.HTMLElement.prototype, "clientWidth", { get: () => 600 });
Object.defineProperty(dom.window.HTMLElement.prototype, "clientHeight", { get: () => 400 });
let drawCount = 0;
dom.window.HTMLElement.prototype.setPointerCapture = function () {};
dom.window.HTMLCanvasElement.prototype.getContext = function () {
  return { translate() {}, scale() {}, rotate() {}, drawImage() { drawCount++; }, set filter(value) { throw new Error("Canvas filters are unavailable"); } };
};
globalThis.Image = class {
  naturalWidth = 1200;
  naturalHeight = 800;
  set src(value) { queueMicrotask(() => this.onload?.()); }
};
const require = createRequire(import.meta.url);
const components = fileURLToPath(new URL("../src/components/", import.meta.url));
const bundle = await build({
  stdin: { contents: 'export { MarkdownPreview } from "./MarkdownPreview"; export { PhotoEditor } from "./PhotoEditor"; export { PhotoViewport } from "./PhotoViewport"; export { NewFileDialog, ShareDialog } from "./FileDialogs"; export { TagDeleteDialog } from "./TagDeleteDialog"; export { default as EditorDialog } from "./EditorDialog"; export { default as CodeEditor } from "./CodeEditor"; export { EditorView } from "@codemirror/view"; export { undo, redo } from "@codemirror/commands";', resolveDir: components, loader: "tsx" },
  bundle: true,
  format: "esm",
  platform: "node",
  mainFields: ["module", "main"],
  jsx: "automatic",
  write: false,
  plugins: [{ name: "shared-react", setup(builder) {
    builder.onResolve({ filter: /^react(?:\/.*)?$/ }, ({ path }) => ({ path: pathToFileURL(require.resolve(path)).href, external: true }));
    builder.onResolve({ filter: /\/PDFEditor$/ }, () => ({ path: "unused-pdf-editor", external: true }));
  } }],
});
const compiledDirectory = await mkdtemp(join(tmpdir(), "rootdrive-editor-tests-"));
const compiledPath = join(compiledDirectory, "components.mjs");
await writeFile(compiledPath, bundle.outputFiles[0].text);
let compiled;
try {
  compiled = await import(pathToFileURL(compiledPath).href);
} finally {
  await rm(compiledDirectory, { recursive: true, force: true });
}
const { PhotoEditor, PhotoViewport, NewFileDialog, ShareDialog, TagDeleteDialog, EditorDialog, CodeEditor, EditorView, undo, redo } = compiled;
const { createRoot } = await import("react-dom/client");
let root, host, requests, saved;
const defaults = { rotation: 0, flip: false, crop: [0, 0, 1, 1], brightness: 1, contrast: 1, saturation: 1 };
const entry = { name: "note.txt", path: "note.txt", type: "file", size: 3, modified: 0 };
function Harness() {
  const [edits, change] = useState(defaults);
  return h(PhotoEditor, { path: "photo.jpg", revision: "a".repeat(64), edits, change });
}
async function render(component) {
  await act(async () => { root.render(component); });
}
function click(label) {
  const button = [...host.querySelectorAll("button")].find((node) => (node.getAttribute("aria-label") || node.textContent.trim()) === label);
  assert.ok(button, label);
  act(() => button.click());
}
function adjustment(label, value) {
  const input = host.querySelector(`input[aria-label="${label}"]`);
  act(() => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set.call(input, value);
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
}
beforeEach(() => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  requests = [];
  saved = [];
  drawCount = 0;
  globalThis.fetch = async (url, options = {}) => {
    const body = options.body ? JSON.parse(options.body) : null;
    requests.push({ url, body, method: options.method });
    return { ok: true, json: async () => body ? { kind: "text", revision: "b".repeat(64), text: body.text, entry: { ...entry, path: body.mode === "copy" ? "note (edited).txt" : entry.path } } : { kind: "text", revision: "a".repeat(64), text: "old", format: "txt" } };
  };
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
});
test("photo adjustments work without Canvas filter support and keep the image geometry", async () => {
  await render(h(Harness));
  const canvas = host.querySelector("canvas");
  assert.ok(canvas);
  const draws = drawCount;
  adjustment("Brightness", "50");
  adjustment("Contrast", "150");
  adjustment("Saturation", "0");
  assert.equal(canvas.style.filter, "brightness(0.5) contrast(1.5) saturate(0)");
  assert.equal(drawCount, draws);
  assert.equal(canvas.width, 1200);
  click("Rotate");
  assert.equal(canvas.width, 800);
  assert.equal(canvas.height, 1200);
  assert.equal(canvas.style.filter, "brightness(0.5) contrast(1.5) saturate(0)");
});
test("photo zoom changes only the viewport and fit resets it", async () => {
  await render(h(Harness));
  const canvas = host.querySelector("canvas");
  click("Zoom in");
  assert.equal(host.querySelector(".photo-zoom-controls output").textContent, "125%");
  assert.match(host.querySelector(".photo-viewport-content").style.transform, /scale\(1.25\)/);
  assert.equal(canvas.width, 1200);
  click("Fit photo");
  assert.equal(host.querySelector(".photo-zoom-controls output").textContent, "100%");
  click("Crop");
  assert.equal(host.querySelector('[aria-label="Zoom in"]').disabled, true);
});
test("photo zoom respects its bounds", async () => {
  await render(h(PhotoViewport, { width: 1200, height: 800 }, h("img", { alt: "Test" })));
  for (let index = 0; index < 25; index++) click("Zoom in");
  assert.equal(host.querySelector("output").textContent, "800%");
  for (let index = 0; index < 35; index++) click("Zoom out");
  assert.equal(host.querySelector("output").textContent, "25%");
});
test("photo wheel zoom leaves ordinary scrolling alone and enlarged photos can pan", async () => {
  await render(h(PhotoViewport, { width: 1200, height: 800 }, h("img", { alt: "Test" })));
  const viewport = host.querySelector(".photo-viewport");
  const scroll = new window.WheelEvent("wheel", { deltaY: -100, bubbles: true, cancelable: true });
  act(() => viewport.dispatchEvent(scroll));
  assert.equal(scroll.defaultPrevented, false);
  assert.equal(host.querySelector("output").textContent, "100%");
  const zoom = new window.WheelEvent("wheel", { deltaY: -100, ctrlKey: true, bubbles: true, cancelable: true });
  act(() => viewport.dispatchEvent(zoom));
  assert.equal(zoom.defaultPrevented, true);
  assert.equal(host.querySelector("output").textContent, "272%");
  for (const [type, x, y] of [["pointerdown", 200, 200], ["pointermove", 300, 260], ["pointerup", 300, 260]]) {
    act(() => viewport.dispatchEvent(new window.MouseEvent(type, { bubbles: true, clientX: x, clientY: y, button: 0 })));
  }
  assert.match(host.querySelector(".photo-viewport-content").style.transform, /translate\(100px, 60px\)/);
});
test("file types use labelled native radio tiles", async () => {
  await render(h(NewFileDialog, { path: "", close() {}, created() {} }));
  assert.equal(host.querySelectorAll('input[type="radio"]').length, 10);
  assert.equal(host.querySelector("select"), null);
  const python = host.querySelector('input[value="py"]');
  act(() => python.click());
  assert.equal(python.checked, true);
  assert.match(python.closest("label").className, /selected/);
  assert.equal(host.querySelector('input[value="txt"]').checked, false);
});
for (const [label, mode] of [["Save", "original"], ["Save copy", "copy"]]) {
  test(`${label} sends its explicit save mode`, async () => {
    await render(h(EditorDialog, { entry, close() {}, saved: (...value) => saved.push(value) }));
    const editor = EditorView.findFromDOM(host.querySelector(".cm-editor"));
    act(() => editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: "changed" } }));
    await act(async () => click(label));
    assert.equal(requests.at(-1).body.mode, mode);
    assert.equal(requests.at(-1).body.text, "changed");
    assert.equal(saved[0][1], mode);
  });
}
test("created share links can be copied on HTTP without the Clipboard API", async () => {
  globalThis.location = window.location;
  Object.defineProperty(globalThis, "navigator", { configurable: true, value: {} });
  let copied = false;
  document.execCommand = (command) => { copied = command === "copy"; return copied; };
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ url: "/api/public/test-link" }) });
  await render(h(ShareDialog, { entry, close() {} }));
  await act(async () => click("Create link"));
  assert.equal(host.querySelector("input").value, "http://localhost/api/public/test-link");
  await act(async () => click("Copy link"));
  assert.equal(copied, true);
  assert.ok(host.textContent.includes("Copied"));
});
test("tag deletion requires confirmation and only calls the tag endpoint", async () => {
  let removed = false;
  await render(h(TagDeleteDialog, { tag: { id: "tag-123", name: "Travel", color: "blue" }, close() {}, removed: () => { removed = true; } }));
  assert.equal(requests.length, 0);
  await act(async () => click("Delete tag"));
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/tags/tag-123");
  assert.equal(requests[0].method, "DELETE");
  assert.equal(removed, true);
});
test("a failed tag deletion keeps the dialog open with an error", async () => {
  let removed = false;
  globalThis.fetch = async () => ({ ok: false, status: 503, json: async () => ({ error: { message: "Storage unavailable" } }) });
  await render(h(TagDeleteDialog, { tag: { id: "tag-123", name: "Travel", color: "blue" }, close() {}, removed: () => { removed = true; } }));
  await act(async () => click("Delete tag"));
  assert.equal(removed, false);
  assert.equal(host.querySelector('[role="alert"]').textContent, "Storage unavailable");
  assert.equal([...host.querySelectorAll("button")].find((node) => node.textContent === "Delete tag").disabled, false);
});

test("code editing shows a gutter and tracks clean state through undo and redo", async () => {
  const dirty = [];
  await render(h(CodeEditor, { text: "first\nsecond", format: "txt", wrap: true, disabled: false, changed: (value) => dirty.push(value) }));
  const editor = EditorView.findFromDOM(host.querySelector(".cm-editor"));
  assert.ok(host.querySelector(".cm-lineNumbers"));
  act(() => editor.dispatch({ changes: { from: 5, insert: "!" } }));
  assert.deepEqual(dirty, [true]);
  act(() => undo(editor));
  assert.deepEqual(dirty, [true, false]);
  assert.equal(editor.state.doc.toString(), "first\nsecond");
  act(() => redo(editor));
  assert.deepEqual(dirty, [true, false, true]);
  assert.ok(host.textContent.includes("Ln 1, Col"));
});
test("large code documents render a viewport and keep changes in the editor", async () => {
  const dirty = [];
  const text = "value = 123456789\n".repeat(110000);
  await render(h(CodeEditor, { text, format: "txt", wrap: false, disabled: false, changed: (value) => dirty.push(value) }));
  const editor = EditorView.findFromDOM(host.querySelector(".cm-editor"));
  assert.equal(editor.state.doc.lines, 110001);
  assert.ok(host.querySelectorAll(".cm-line").length < 100);
  for (let index = 0; index < 20; index++) act(() => editor.dispatch({ changes: { from: 0, insert: "x" } }));
  assert.deepEqual(dirty, [true]);
  assert.equal(editor.state.doc.length, text.length + 20);
});
test("code editor supports search and becomes read-only during saving", async () => {
  const props = { text: "alpha\nbeta", format: "txt", wrap: true, disabled: false, changed() {} };
  await render(h(CodeEditor, props));
  click("Find in file");
  assert.ok(host.querySelector(".cm-search"));
  await render(h(CodeEditor, { ...props, disabled: true }));
  assert.equal(host.querySelector(".cm-content").getAttribute("contenteditable"), "false");
});

test("Escape in the code field stays in the editor and the save shortcut saves current contents", async () => {
  let closed = 0;
  await render(h(EditorDialog, { entry, close: () => { closed++; }, saved: (...value) => saved.push(value) }));
  const editor = EditorView.findFromDOM(host.querySelector(".cm-editor"));
  act(() => editor.dispatch({ changes: { from: 0, to: editor.state.doc.length, insert: "keyboard save" } }));
  act(() => editor.contentDOM.dispatchEvent(new window.KeyboardEvent("keydown", { key: "Escape", keyCode: 27, bubbles: true, cancelable: true })));
  assert.equal(closed, 0);
  await act(async () => editor.contentDOM.dispatchEvent(new window.KeyboardEvent("keydown", { key: "s", ctrlKey: true, bubbles: true, cancelable: true })));
  assert.equal(requests.at(-1).body.text, "keyboard save");
  assert.equal(requests.at(-1).body.mode, "original");
  assert.equal(saved.length, 1);
});


test("Markdown preview renders structure and keeps uploaded HTML and unsafe links inert", async () => {
  await render(h(compiled.MarkdownPreview, { text: '# Heading\n\n**Bold** and *italic*\n\n- One\n- Two\n\n```js\nconst value = 1;\n```\n\n<script>alert(1)</script>\n\n[bad](javascript:alert(1)) [good](https://example.com)' }));
  assert.equal(host.querySelector('h1').textContent, 'Heading');
  assert.equal(host.querySelector('strong').textContent, 'Bold');
  assert.equal(host.querySelectorAll('li').length, 2);
  assert.ok(host.querySelector('pre code').textContent.includes('const value'));
  assert.equal(host.querySelector('script'), null);
  assert.equal(host.querySelectorAll('a').length, 1);
  assert.equal(host.querySelector('a').getAttribute('href'), 'https://example.com');
  assert.ok(host.textContent.includes('<script>'));
});


test("read-only code remains viewable and cannot submit a save", async () => {
  await render(h(EditorDialog, { entry, readOnly: true, close() {}, saved() {} }));
  assert.equal(host.querySelector('.cm-content').getAttribute('contenteditable'), 'false');
  const buttons = [...host.querySelectorAll('button')];
  assert.equal(buttons.find((button) => button.textContent.trim() === 'Save').disabled, true);
  assert.equal(buttons.find((button) => button.textContent.trim() === 'Save copy').disabled, true);
  assert.ok(host.textContent.includes('Read only'));
  assert.equal(requests.some((request) => request.method === 'POST'), false);
});
