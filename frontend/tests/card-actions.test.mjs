import assert from "node:assert/strict";
import { after, afterEach, beforeEach, test } from "node:test";
import { createRequire } from "node:module";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";
import { JSDOM } from "jsdom";
import { createElement as h, act } from "react";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost" });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Element: dom.window.Element, IS_REACT_ACT_ENVIRONMENT: true, requestAnimationFrame: (callback) => setTimeout(callback, 0), cancelAnimationFrame: clearTimeout });
Object.defineProperty(globalThis, "localStorage", { value: window.localStorage, configurable: true });
window.scrollTo = () => {};
window.setInterval = (...args) => { const timer = setInterval(...args); timer.unref(); return timer; };
window.setTimeout = (...args) => { const timer = setTimeout(...args); timer.unref(); return timer; };
const require = createRequire(import.meta.url);
const result = await build({
  entryPoints: [fileURLToPath(new URL("../src/App.tsx", import.meta.url))], bundle: true, format: "esm", platform: "node", mainFields: ["module", "main"], jsx: "automatic", write: false,
  plugins: [{ name: "shared-react", setup(builder) {
    builder.onResolve({ filter: /^(?:react|react-dom)(?:\/.*)?$/ }, ({ path }) => ({ path: pathToFileURL(require.resolve(path)).href, external: true }));
    builder.onResolve({ filter: /\/EditorDialog$/ }, () => ({ path: "unused-editor", external: true }));
  } }],
});
const directory = await mkdtemp(join(tmpdir(), "rootdrive-card-tests-"));
const compiled = join(directory, "app.mjs");
await writeFile(compiled, result.outputFiles[0].text);
let App;
try { App = (await import(pathToFileURL(compiled).href)).default; }
finally { await rm(directory, { recursive: true, force: true }); }
const { createRoot } = await import("react-dom/client");
const tag = { id: "tag-1", name: "Travel", color: "blue" };
const folder = { name: "Folder", path: "Folder", type: "folder", size: 12, modified: 1, child_count: 1, tags: [tag] };
const photo = { name: "photo.png", path: "photo.png", type: "file", size: 12, modified: 1, mime: "image/png" };
let host, root, requests;
function button(label) {
  const found = [...host.querySelectorAll("button")].find((node) => (node.getAttribute("aria-label") || node.textContent.trim()) === label);
  assert.ok(found, label);
  return found;
}
async function click(label) { await act(async () => button(label).click()); }
function heading() { return host.querySelector("h1")?.textContent; }
beforeEach(async () => {
  window.localStorage.clear();
  requests = [];
  globalThis.fetch = async (value, options = {}) => {
    const url = new URL(value, "http://localhost");
    requests.push({ url, method: options.method || "GET", body: options.body && JSON.parse(options.body) });
    let data = {};
    if (url.pathname === "/api/auth/me") data = { auth_enabled: false, shares_enabled: true, max_upload_size_mb: 2048, csrf_token: null, user: null };
    else if (url.pathname === "/api/tags") data = { items: [tag] };
    else if (url.pathname === "/api/uploads") data = { items: [] };
    else if (url.pathname === "/api/storage/stats") data = { file_count: 1, stored_bytes: 12, disk_total: 1000, disk_free: 800, disk_used: 200, disk_percent: 20, system_bytes: 188, trash_bytes: 0, versions_bytes: 0, uploads_bytes: 0, cache_bytes: 0, exports_bytes: 0, categories: { images: 12, videos: 0, documents: 0, other: 0 } };
    else if (url.pathname === "/api/files") data = { items: url.searchParams.get("path") ? [] : [folder, photo], total: url.searchParams.get("path") ? 0 : 2 };
    else if (url.pathname === "/api/collection") data = { items: [], total: 0 };
    else if (url.pathname === "/api/trash") data = { items: [{ ...folder, id: "trash-1" }], total: 1, revision: "revision" };
    return { ok: true, json: async () => data };
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(h(App)));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); });
after(() => window.close());
for (const layout of ["Grid view", "List view"]) {
  test(`one native open control navigates the folder in ${layout}`, async () => {
    await click(layout);
    const card = host.querySelector('[data-selection-path="Folder"]');
    assert.equal(card.querySelectorAll('button[aria-label="Open Folder"]').length, 1);
    assert.equal(card.querySelectorAll(".card-open button, .file-name button").length, 0);
    assert.equal(button("Open Folder").className, "surface-action");
    await click("Open Folder");
    assert.equal(heading(), "Folder");
    assert.ok(requests.some(({ url }) => url.pathname === "/api/files" && url.searchParams.get("path") === "Folder"));
  });
}
test("selection, favorite and context-menu controls do not open the folder", async () => {
  await act(async () => host.querySelector('input[aria-label="Select Folder"]').click());
  assert.ok(host.querySelector('[data-selection-path="Folder"]').classList.contains("selected"));
  assert.equal(heading(), "My files");
  await click("Favorite Folder");
  assert.equal(heading(), "My files");
  assert.ok(requests.some(({ url, method, body }) => url.pathname === "/api/favorites" && method === "POST" && body.paths[0] === "Folder"));
  await click("Actions for Folder");
  const rename = [...host.querySelectorAll('[role="menuitem"]')].find((node) => node.textContent.trim() === "Rename");
  assert.ok(rename.querySelector("svg.lucide-pencil"));
  assert.equal(heading(), "My files");
  assert.equal(requests.some(({ url }) => url.pathname === "/api/files" && url.searchParams.get("path") === "Folder"), false);
});
test("file tags navigate to their collection without opening the folder", async () => {
  await act(async () => host.querySelector(".file-card .tag-pill").click());
  assert.equal(heading(), "Travel");
  assert.ok(requests.some(({ url }) => url.pathname === "/api/collection" && url.searchParams.get("tag") === "tag-1"));
});
test("Storage cards expose their whole-card actions without adding fake actions", async () => {
  await click("Storage");
  assert.equal(heading(), "Storage");
  assert.equal(host.querySelectorAll(".storage-part .surface-action").length, 2);
  await click("Open Trash");
  assert.equal(heading(), "Trash");
  await click("Storage");
  await click("Open RootDrive files");
  assert.equal(heading(), "My files");
});
test("trash restore and selection stay independent of the card open action", async () => {
  await click("Trash");
  await act(async () => host.querySelector('input[aria-label="Select Folder"]').click());
  assert.ok(host.querySelector('[data-selection-path="trash-1"]').classList.contains("selected"));
  await click("Restore");
  assert.equal(heading(), "Trash");
  assert.ok(requests.some(({ url, method, body }) => url.pathname === "/api/trash/restore" && method === "POST" && body.id === "trash-1"));
  assert.equal(host.querySelector('[role="dialog"]'), null);
});
