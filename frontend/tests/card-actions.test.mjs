import assert from "node:assert/strict";
import { after, afterEach, beforeEach, test } from "node:test";
import { createRequire } from "node:module";
import { mkdtemp, writeFile, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";
import { JSDOM } from "jsdom";
import { createElement as h, act } from "react";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://localhost", pretendToBeVisual: true });
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, Element: dom.window.Element, IS_REACT_ACT_ENVIRONMENT: true, requestAnimationFrame: (callback) => setTimeout(callback, 0), cancelAnimationFrame: clearTimeout });
Object.defineProperty(globalThis, "localStorage", { value: window.localStorage, configurable: true });
window.scrollTo = () => {};
globalThis.ResizeObserver = class { observe() {} disconnect() {} };
window.setInterval = (...args) => { const timer = setInterval(...args); timer.unref(); return timer; };
window.setTimeout = (...args) => { const timer = setTimeout(...args); timer.unref(); return timer; };
const require = createRequire(import.meta.url);
const result = await build({
  entryPoints: [fileURLToPath(new URL("../src/App.tsx", import.meta.url))], bundle: true, format: "esm", platform: "node", mainFields: ["module", "main"], jsx: "automatic", write: false,
  plugins: [{ name: "shared-react", setup(builder) {
    builder.onLoad({ filter: /(?:App|FileCard)\.tsx$/ }, async ({ path }) => {
      const text = await readFile(path, "utf8");
      return { contents: text.replace(/<article\s/g, '<article data-render-probe={(globalThis.cardRenders.push(entry.path), undefined)} '), loader: "tsx" };
    });
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
let host, root, requests, delayListing, additionalFiles, runtimeErrors = [];
window.addEventListener("error", (event) => runtimeErrors.push(event.error?.stack || event.message));
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
  runtimeErrors = [];
  globalThis.cardRenders = [];
  delayListing = null;
  additionalFiles = [];
  globalThis.fetch = async (value, options = {}) => {
    const url = new URL(value, "http://localhost");
    requests.push({ url, method: options.method || "GET", body: options.body && JSON.parse(options.body) });
    let data = {};
    if (url.pathname === "/api/auth/me") data = { auth_enabled: false, shares_enabled: true, max_upload_size_mb: 2048, csrf_token: null, user: null };
    else if (url.pathname === "/api/tags") data = { items: [tag] };
    else if (url.pathname === "/api/uploads") data = { items: [] };
    else if (url.pathname === "/api/storage/stats") data = { file_count: 1, stored_bytes: 12, disk_total: 1000, disk_free: 800, disk_used: 200, disk_percent: 20, system_bytes: 188, trash_bytes: 0, versions_bytes: 0, uploads_bytes: 0, cache_bytes: 0, exports_bytes: 0, categories: { images: 12, videos: 0, documents: 0, other: 0 } };
    else if (url.pathname === "/api/files") { if (delayListing) await delayListing; data = { items: url.searchParams.get("path") ? [] : [folder, photo, ...additionalFiles], total: url.searchParams.get("path") ? 0 : 2 + additionalFiles.length }; }
    else if (url.pathname === "/api/files/location") data = { path: "", offset: 0 };
    else if (url.pathname === "/api/files/compress") data = { ...photo, name: requests.at(-1).body.name, path: requests.at(-1).body.name, mime: "application/zip" };
    else if (url.pathname === "/api/smart-files") data = { items: [photo], total: 1 };
    else if (url.pathname === "/api/search") data = { items: [{ ...photo, path: "Nested/photo.png" }], total: 1 };
    else if (url.pathname === "/api/collection") data = { items: [], total: 0 };
    else if (url.pathname === "/api/trash") data = { items: [{ ...folder, id: "trash-1" }], total: 1, revision: "revision" };
    return { ok: true, json: async () => data };
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(h(App)));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); assert.deepEqual(runtimeErrors, []); });
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


test("opening a menu does not rerender the file cards", async () => {
  globalThis.cardRenders = [];
  await click("Actions for Folder");
  assert.deepEqual(globalThis.cardRenders, []);
});

test("changing selection rerenders only the changed card", async () => {
  globalThis.cardRenders = [];
  await act(async () => host.querySelector('input[aria-label="Select Folder"]').click());
  assert.deepEqual(globalThis.cardRenders, ["Folder"]);
});

test("typing in search leaves the existing cards alone until results change", async () => {
  globalThis.cardRenders = [];
  const input = host.querySelector('input[aria-label="Search files"]');
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
  await act(async () => {
    setter.call(input, "photo");
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
  assert.equal(input.value, "photo");
  assert.deepEqual(globalThis.cardRenders, []);
});

test("returning to a cached folder shows its files while revalidating them", async () => {
  await click("Open Folder");
  let release;
  delayListing = new Promise((resolve) => { release = resolve; });
  await click("My files");
  try {
    assert.ok(host.querySelector('[data-selection-path="Folder"]'));
    assert.equal(host.querySelector(".loading-area"), null);
    globalThis.cardRenders = [];
    await act(async () => release());
    assert.deepEqual(globalThis.cardRenders, []);
  } finally { release(); }
});

test("mutations invalidate the folder cache", async () => {
  await click("Open Folder");
  await click("New folder");
  const name = host.querySelector('input');
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    setter.call(name, "New child");
    name.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
  await act(async () => host.querySelector("form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));
  let release;
  delayListing = new Promise((resolve) => { release = resolve; });
  await click("My files");
  try {
    assert.equal(host.querySelector('[data-selection-path="Folder"]'), null);
    assert.ok(host.querySelector(".loading-area"));
  } finally { await act(async () => release()); }
});


test("sixty cards remain untouched by menus and only one rerenders on selection", async () => {
  additionalFiles = Array.from({ length: 58 }, (_, index) => ({ ...photo, name: `Extra ${index}.txt`, path: `Extra ${index}.txt`, mime: "text/plain" }));
  await click("Favorites");
  await click("My files");
  assert.equal(host.querySelectorAll(".file-card").length, 60);
  globalThis.cardRenders = [];
  await click("Actions for Folder");
  assert.deepEqual(globalThis.cardRenders, []);
  await act(async () => window.dispatchEvent(new window.Event("click")));
  await act(async () => host.querySelector('input[aria-label="Select Folder"]').click());
  assert.deepEqual(globalThis.cardRenders, ["Folder"]);
});

test("cached listings expire and do not replace fresh server validation", async () => {
  await click("Open Folder");
  const originalNow = Date.now;
  let release;
  delayListing = new Promise((resolve) => { release = resolve; });
  Date.now = () => originalNow() + 16000;
  try {
    await click("My files");
    assert.equal(host.querySelector('[data-selection-path="Folder"]'), null);
    assert.ok(host.querySelector(".loading-area"));
  } finally {
    await act(async () => release());
    Date.now = originalNow;
  }
});

test("leaving Storage does not request another disk inventory", async () => {
  await click("Storage");
  const count = requests.filter(({ url }) => url.pathname === "/api/storage/stats").length;
  await click("My files");
  assert.equal(requests.filter(({ url }) => url.pathname === "/api/storage/stats").length, count);
});


test("Create ZIP saves a folder archive through the backend without downloading it", async () => {
  await click("Actions for Folder");
  const action = [...host.querySelectorAll('[role="menuitem"]')].find((node) => node.textContent.trim() === "Create ZIP");
  assert.ok(action.querySelector("svg.lucide-folder-archive"));
  await act(async () => action.click());
  const dialog = host.querySelector('[role="dialog"][aria-label="Create ZIP"]');
  assert.ok(dialog);
  assert.equal(dialog.querySelector("input").value, "Folder.zip");
  await act(async () => dialog.querySelector("form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));
  const request = requests.find(({ url }) => url.pathname === "/api/files/compress");
  assert.equal(request.method, "POST");
  assert.deepEqual(request.body, { path: "Folder", name: "Folder.zip" });
  assert.equal(requests.some(({ url }) => url.pathname === "/api/files/archive"), false);
  assert.equal(host.querySelector('[role="dialog"]'), null);
  assert.match(host.querySelector(".toast-stack").textContent, /ZIP created/);
});

test("Create ZIP is offered only for folders", async () => {
  await click("Actions for photo.png");
  assert.equal([...host.querySelectorAll('[role="menuitem"]')].some((node) => node.textContent.trim() === "Create ZIP"), false);
});

test("ZIP creation shows pending state and keeps errors in the dialog", async () => {
  const originalFetch = globalThis.fetch;
  let complete;
  globalThis.fetch = async (url, options) => url === "/api/files/compress" ? new Promise((resolve) => { complete = resolve; }) : originalFetch(url, options);
  await click("Actions for Folder");
  await act(async () => [...host.querySelectorAll('[role="menuitem"]')].find((node) => node.textContent.trim() === "Create ZIP").click());
  const dialog = host.querySelector('[role="dialog"]');
  await act(async () => dialog.querySelector("form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));
  assert.equal(dialog.querySelector("input").disabled, true);
  assert.equal(button("Creating ZIP…").disabled, true);
  assert.equal(button("Cancel").disabled, true);
  await click("Close dialog");
  assert.equal(host.querySelector('[role="dialog"]'), dialog);
  await act(async () => complete({ ok: false, status: 409, json: async () => ({ error: { message: "A file with this name already exists" } }) }));
  assert.equal(dialog.querySelector("input").disabled, false);
  assert.match(dialog.querySelector('[role="alert"]').textContent, /already exists/);
  await click("Cancel");
  assert.equal(host.querySelector('[role="dialog"]'), null);
});

async function typeIn(input, value) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set.call(input, value);
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
  });
}
async function keyOn(target, key, modifiers = {}) {
  await act(async () => target.dispatchEvent(new window.KeyboardEvent("keydown", { key, bubbles: true, cancelable: true, ...modifiers })));
}
async function waitForSearch() { await act(async () => new Promise((resolve) => setTimeout(resolve, 230))); }
const commandInput = () => host.querySelector('input[aria-label="Search commands and files"]');

for (const [label, kind, sort, direction] of [["Recent files", "recent", "modified", "desc"], ["All photos", "photos", "name", "asc"], ["Documents", "documents", "name", "asc"], ["Large files", "large", "size", "desc"]]) {
  test(`${label} is a virtual collection with its own default sort`, async () => {
    await click(label);
    assert.equal(heading(), label);
    const request = requests.findLast(({ url }) => url.pathname === "/api/smart-files");
    assert.equal(request.url.searchParams.get("kind"), kind);
    assert.equal(request.url.searchParams.get("sort"), sort);
    assert.equal(request.url.searchParams.get("direction"), direction);
    assert.ok(host.querySelector(".entry-path"));
    assert.equal(host.querySelector(".file-actions"), null);
    assert.equal(host.querySelector(".loading-area"), null);
    await click(label);
    assert.equal(host.querySelector(".loading-area"), null);
  });
}

test("smart folders preserve file selection and real actions", async () => {
  await click("All photos");
  await act(async () => host.querySelector('input[aria-label="Select photo.png"]').click());
  assert.match(host.querySelector(".selection-bar").textContent, /1 selected/);
  await click("Actions for photo.png");
  await act(async () => [...host.querySelectorAll('[role="menuitem"]')].find((node) => node.textContent.trim() === "Rename").click());
  assert.equal(host.querySelector('[role="dialog"]').getAttribute("aria-label"), "Rename");
});

for (const modifier of ["metaKey", "ctrlKey"]) {
  test(`${modifier} K opens quick commands from Settings and Escape restores focus`, async () => {
    await click("Settings");
    button("Quick commands").focus();
    await keyOn(window, "k", { [modifier]: true });
    await act(async () => new Promise((resolve) => setTimeout(resolve, 10)));
    assert.ok(commandInput());
    assert.equal(document.activeElement, commandInput());
    assert.equal(host.querySelectorAll('[role="listbox"]').length, 1);
    await keyOn(commandInput(), "Escape");
    assert.equal(host.querySelector('[role="dialog"]'), null);
    assert.equal(document.activeElement, button("Quick commands"));
  });
}

test("quick commands filter actions and support arrow navigation and Enter", async () => {
  await click("Quick commands");
  const input = commandInput();
  await typeIn(input, "smart");
  assert.equal(host.querySelectorAll('[role="option"]').length, 4);
  await keyOn(input, "ArrowDown");
  assert.match(host.querySelector('[role="option"][aria-selected="true"]').textContent, /All photos/);
  assert.equal(input.getAttribute("aria-activedescendant"), host.querySelector('[aria-selected="true"]').id);
  await keyOn(input, "Enter");
  assert.equal(host.querySelector('[role="dialog"]'), null);
  assert.equal(heading(), "All photos");
});

test("quick commands search files recursively only after typing and open the result", async () => {
  await click("Storage");
  await click("Quick commands");
  assert.equal(requests.some(({ url }) => url.pathname === "/api/search"), false);
  await typeIn(commandInput(), "photo");
  assert.ok(host.querySelector('[aria-label="Searching files"]'));
  await waitForSearch();
  const request = requests.find(({ url }) => url.pathname === "/api/search");
  assert.equal(request.url.searchParams.get("q"), "photo");
  assert.equal(request.url.searchParams.get("recursive"), "true");
  assert.equal(request.url.searchParams.get("limit"), "8");
  const result = host.querySelector(".command-file");
  assert.match(result.textContent, /Nested\/photo.png/);
  await act(async () => result.click());
  assert.equal(host.querySelector('[role="dialog"]').getAttribute("aria-label"), "photo.png");
  assert.equal(host.querySelector(".command-palette"), null);
});

test("quick commands abort obsolete searches and never show stale file results", async () => {
  const originalFetch = globalThis.fetch;
  const pending = [];
  globalThis.fetch = (url, options) => String(url).startsWith("/api/search?") ? new Promise((resolve) => pending.push({ resolve, signal: options.signal, url })) : originalFetch(url, options);
  await click("Quick commands");
  await typeIn(commandInput(), "first");
  await waitForSearch();
  await typeIn(commandInput(), "second");
  assert.equal(pending[0].signal.aborted, true);
  await waitForSearch();
  await act(async () => pending[1].resolve({ ok: true, json: async () => ({ items: [{ ...photo, name: "second.png", path: "second.png" }] }) }));
  await act(async () => pending[0].resolve({ ok: true, json: async () => ({ items: [{ ...photo, name: "first.png", path: "first.png" }] }) }));
  assert.match(host.querySelector(".command-file").textContent, /second.png/);
  assert.doesNotMatch(host.querySelector(".command-results").textContent, /first.png/);
});

test("quick command search errors can be retried", async () => {
  const originalFetch = globalThis.fetch;
  let failed = false;
  globalThis.fetch = async (url, options) => {
    if (String(url).startsWith("/api/search?") && !failed) {
      failed = true;
      return { ok: false, status: 503, json: async () => ({ error: { message: "Storage unavailable" } }) };
    }
    return originalFetch(url, options);
  };
  await click("Quick commands");
  await typeIn(commandInput(), "photo");
  await waitForSearch();
  assert.match(host.querySelector('[role="status"]').textContent, /Storage unavailable/);
  await click("Try again");
  await waitForSearch();
  assert.ok(host.querySelector(".command-file"));
});

test("creation commands use the current folder and root from a smart folder", async () => {
  await click("Open Folder");
  await click("Quick commands");
  await typeIn(commandInput(), "new folder");
  await keyOn(commandInput(), "Enter");
  assert.equal(host.querySelector('[role="dialog"]').getAttribute("aria-label"), "New folder");
  const name = host.querySelector('[role="dialog"] input');
  await typeIn(name, "Child");
  await act(async () => host.querySelector("form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));
  assert.deepEqual(requests.findLast(({ url }) => url.pathname === "/api/folders").body, { path: "Folder", name: "Child" });
  await click("All photos");
  await click("Quick commands");
  await typeIn(commandInput(), "new folder");
  await keyOn(commandInput(), "Enter");
  await typeIn(host.querySelector('[role="dialog"] input'), "Root child");
  await act(async () => host.querySelector("form").dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));
  assert.deepEqual(requests.findLast(({ url }) => url.pathname === "/api/folders").body, { path: "", name: "Root child" });
  assert.equal(heading(), "My files");
});

test("quick commands can change theme and stay out of active editor dialogs", async () => {
  const previous = document.documentElement.dataset.theme;
  await click("Quick commands");
  await typeIn(commandInput(), "theme");
  await keyOn(commandInput(), "Enter");
  assert.notEqual(document.documentElement.dataset.theme, previous);
  await click("New file");
  await keyOn(window, "k", { metaKey: true });
  assert.equal(host.querySelector(".command-palette"), null);
  assert.equal(host.querySelectorAll('[role="dialog"]').length, 1);
});

test("F2 renames one selected item and Delete asks before moving files to Trash", async () => {
  const checkbox = host.querySelector('input[aria-label="Select Folder"]');
  await act(async () => checkbox.click());
  await keyOn(checkbox, "F2");
  assert.equal(host.querySelector('[role="dialog"]').getAttribute("aria-label"), "Rename");
  await click("Close dialog");
  await keyOn(checkbox, "Delete");
  assert.ok(host.querySelector('[role="dialog"]'));
  assert.match(host.querySelector('[role="dialog"]').textContent, /trash/i);
  assert.equal(requests.some(({ method }) => method === "DELETE"), false);
});

test("file shortcuts ignore text entry, repeated events and multi-selection rename", async () => {
  await act(async () => host.querySelector('input[aria-label="Select Folder"]').click());
  await keyOn(host.querySelector('input[aria-label="Search files"]'), "Delete");
  assert.equal(host.querySelector('[role="dialog"]'), null);
  await keyOn(window, "F2", { repeat: true });
  assert.equal(host.querySelector('[role="dialog"]'), null);
  await act(async () => host.querySelector('input[aria-label="Select photo.png"]').click());
  await keyOn(window, "F2");
  assert.equal(host.querySelector('[role="dialog"]'), null);
  await click("Trash");
  await act(async () => host.querySelector('input[aria-label="Select Folder"]').click());
  await keyOn(window, "Delete");
  assert.equal(host.querySelector('[role="dialog"]'), null);
});

test("Open file location leaves a smart view and selects the original file", async () => {
  await click("All photos");
  await click("Actions for photo.png");
  await act(async () => [...host.querySelectorAll('[role="menuitem"]')].find((node) => node.textContent.trim() === "Open file location").click());
  assert.equal(heading(), "My files");
  assert.equal(host.querySelector('input[aria-label="Select photo.png"]').checked, true);
  assert.ok(requests.some(({ url }) => url.pathname === "/api/files/location" && url.searchParams.get("path") === "photo.png"));
});

test("Open file location jumps directly to the target page", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    const parsed = new URL(url, "http://localhost");
    if (parsed.pathname === "/api/files/location") return { ok: true, json: async () => ({ path: "", offset: 60 }) };
    if (parsed.pathname === "/api/files" && parsed.searchParams.get("offset") === "60") return { ok: true, json: async () => ({ items: [photo], total: 61 }) };
    return originalFetch(url, options);
  };
  await click("All photos");
  await click("Actions for photo.png");
  await act(async () => [...host.querySelectorAll('[role="menuitem"]')].find((node) => node.textContent.trim() === "Open file location").click());
  assert.equal(host.querySelector('input[aria-label="Select photo.png"]').checked, true);
});

test("file sorting survives remount and smart folders keep independent preferences", async () => {
  await act(async () => {
    const select = host.querySelector('select[aria-label="Sort files"]');
    select.value = "size";
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
  });
  await click("Sort descending");
  await click("All photos");
  assert.equal(host.querySelector('select[aria-label="Sort files"]').value, "name");
  await click("My files");
  assert.equal(host.querySelector('select[aria-label="Sort files"]').value, "size");
  assert.ok(button("Sort ascending"));
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(h(App)));
  assert.equal(host.querySelector('select[aria-label="Sort files"]').value, "size");
  assert.equal(requests.at(-1).url.searchParams.get("sort"), "size");
});

test("invalid saved sorting falls back to safe values", async () => {
  window.localStorage.setItem("rootdrive-sort:files", "invalid");
  window.localStorage.setItem("rootdrive-direction:files", "invalid");
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => root.render(h(App)));
  assert.equal(host.querySelector('select[aria-label="Sort files"]').value, "name");
  assert.ok(button("Sort descending"));
});

test("the selection bar shows the actual combined size", async () => {
  await act(async () => {
    host.querySelector('input[aria-label="Select Folder"]').click();
    host.querySelector('input[aria-label="Select photo.png"]').click();
  });
  assert.equal(host.querySelector(".selection-size").textContent, "24 B");
});

test("smart folder controls send real filter parameters and remember their values", async () => {
  await click("Recent files");
  await act(async () => {
    const select = host.querySelector('select[aria-label="Recent period"]');
    select.value = "30";
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
  });
  assert.equal(requests.findLast(({ url }) => url.pathname === "/api/smart-files").url.searchParams.get("recent_days"), "30");
  await click("Large files");
  await act(async () => {
    const select = host.querySelector('select[aria-label="Minimum file size"]');
    select.value = "10";
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
  });
  assert.equal(requests.findLast(({ url }) => url.pathname === "/api/smart-files").url.searchParams.get("min_size_mb"), "10");
  await click("Recent files");
  assert.equal(host.querySelector('select[aria-label="Recent period"]').value, "30");
});

test("quick commands remember command IDs and can clear their recent history", async () => {
  await click("Quick commands");
  await typeIn(commandInput(), "storage");
  await keyOn(commandInput(), "Enter");
  await click("Quick commands");
  assert.match(host.querySelector(".command-group").textContent, /Recently used/);
  assert.match(host.querySelector('[role="option"]').textContent, /Storage/);
  assert.deepEqual(JSON.parse(window.localStorage.getItem("rootdrive-commands:workspace")), ["storage"]);
  await click("Clear history");
  assert.equal(window.localStorage.getItem("rootdrive-commands:workspace"), null);
  assert.equal(host.querySelector(".command-group").textContent, "Jump to or create");
});

test("corrupt recent-command preferences do not prevent opening the palette", async () => {
  window.localStorage.setItem("rootdrive-commands:workspace", '{bad');
  await click("Quick commands");
  assert.ok(commandInput());
  assert.ok(host.querySelectorAll('[role="option"]').length > 0);
});

test("Trash restores its selected IDs through the bulk endpoint", async () => {
  await click("Trash");
  await act(async () => host.querySelector('input[aria-label="Select Folder"]').click());
  await click("Restore selected");
  const request = requests.find(({ url }) => url.pathname === "/api/trash/restore/batch");
  assert.equal(request.method, "POST");
  assert.deepEqual(request.body, { ids: ["trash-1"] });
  assert.match(host.querySelector(".toast-stack").textContent, /Restored selected/);
});

test("Trash search and sorting reach the backend and disable Remove all while filtering", async () => {
  await click("Trash");
  await typeIn(host.querySelector('input[aria-label="Search Trash"]'), "Folder");
  assert.equal(button("Remove all").disabled, true);
  await waitForSearch();
  await act(async () => {
    const select = host.querySelector('select[aria-label="Sort Trash"]');
    select.value = "size";
    select.dispatchEvent(new window.Event("change", { bubbles: true }));
  });
  const request = requests.findLast(({ url }) => url.pathname === "/api/trash");
  assert.equal(request.url.searchParams.get("q"), "Folder");
  assert.equal(request.url.searchParams.get("sort"), "size");
});

test("password settings verify confirmation before submitting and rotate CSRF after success", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => url === "/api/auth/me" ? { ok: true, json: async () => ({ auth_enabled: true, shares_enabled: false, max_upload_size_mb: 2048, csrf_token: "old-csrf", user: { username: "member", role: "user" } }) } : String(url) === "/api/auth/password" ? (requests.push({ url: new URL(url, "http://localhost"), method: options.method, body: JSON.parse(options.body) }), { ok: true, json: async () => ({ csrf_token: "new-csrf" }) }) : originalFetch(url, options);
  await act(async () => window.dispatchEvent(new window.Event("rootdrive:unauthorized")));
  await click("Settings");
  await click("Change password");
  await typeIn(host.querySelector('input[name="currentPassword"]'), "old-password");
  await typeIn(host.querySelector('input[name="newPassword"]'), "new-password-123");
  await typeIn(host.querySelector('input[name="confirmPassword"]'), "different-password");
  const form = host.querySelector('form[aria-label="Change password"]');
  await act(async () => form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));
  assert.match(host.querySelector('[role="alert"]').textContent, /do not match/);
  assert.equal(requests.some(({ url }) => url.pathname === "/api/auth/password"), false);
  await typeIn(host.querySelector('input[name="confirmPassword"]'), "new-password-123");
  await act(async () => form.dispatchEvent(new window.Event("submit", { bubbles: true, cancelable: true })));
  assert.deepEqual(requests.find(({ url }) => url.pathname === "/api/auth/password").body, { current_password: "old-password", new_password: "new-password-123" });
  assert.equal(host.querySelector('form[aria-label="Change password"]'), null);
  assert.match(host.querySelector(".toast-stack").textContent, /Password changed/);
});

test("server status reports transport loss and refreshes files after a successful retry", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (url, options) => url === "/api/health" ? { ok: true, json: async () => ({ status: "ok" }) } : originalFetch(url, options);
  const count = requests.filter(({ url }) => url.pathname === "/api/files").length;
  await act(async () => window.dispatchEvent(new window.Event("rootdrive:connection-lost")));
  assert.ok(button("Retry connection"));
  await click("Retry connection");
  assert.ok(button("Check server connection"));
  assert.ok(requests.filter(({ url }) => url.pathname === "/api/files").length > count);
});
