import assert from "node:assert/strict";
import { test } from "node:test";
import { createRequire } from "node:module";
import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { build } from "esbuild";
import { JSDOM } from "jsdom";
import { createElement as h, act, useSyncExternalStore } from "react";

const dom = new JSDOM("<!doctype html><html><body></body></html>");
Object.assign(globalThis, { window: dom.window, document: dom.window.document, HTMLElement: dom.window.HTMLElement, IS_REACT_ACT_ENVIRONMENT: true });
Object.defineProperty(globalThis, "navigator", { value: { onLine: true, userAgent: "node" }, configurable: true });
let retry;
window.setInterval = (callback) => { retry = callback; return 1; };
const require = createRequire(import.meta.url);
const compiled = await build({
  stdin: { contents: 'export { useUploads } from "./useUploads";', resolveDir: fileURLToPath(new URL("../src/hooks/", import.meta.url)), loader: "tsx" },
  bundle: true, format: "esm", platform: "node", mainFields: ["module", "main"], write: false,
  plugins: [{ name: "dependencies", setup(builder) {
    builder.onResolve({ filter: /^react$/ }, ({ path }) => ({ path: pathToFileURL(require.resolve(path)).href, external: true }));
    builder.onResolve({ filter: /services\/api$/ }, () => ({ path: "api", namespace: "mock" }));
    builder.onLoad({ filter: /.*/, namespace: "mock" }, () => ({ contents: 'export class APIError extends Error {} export const api = (...args) => globalThis.uploadTestAPI(...args); export const sendChunk = (...args) => globalThis.uploadTestChunk(...args);' }));
  } }],
});
const directory = await mkdtemp(join(tmpdir(), "rootdrive-upload-tests-"));
const path = join(directory, "uploads.mjs");
await writeFile(path, compiled.outputFiles[0].text);
let useUploads;
try { ({ useUploads } = await import(pathToFileURL(path).href)); }
finally { await rm(directory, { recursive: true, force: true }); }
const { createRoot } = await import("react-dom/client");

test("upload progress is isolated from the file manager, throttled, and does not render on idle retries", async () => {
  let queue, parentRenders = 0, queueRenders = 0, progress, finish, completed = 0;
  const job = { id: "job-1", size: 1000, received: 0, status: "open" };
  globalThis.uploadTestAPI = async (url, method = "GET") => url === "/uploads" && method === "GET" ? { items: [] } : job;
  globalThis.uploadTestChunk = (_url, _chunk, _signal, callback) => new Promise((resolve) => { progress = callback; finish = () => resolve({ ...job, received: 1000 }); });
  function Queue({ value }) {
    const transfers = useSyncExternalStore(value.subscribe, value.getSnapshot);
    queueRenders++;
    return h("output", null, transfers.map((item) => item.progress).join(","));
  }
  function Parent() {
    queue = useUploads(true, () => { completed++; });
    parentRenders++;
    return h(Queue, { value: queue });
  }
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(h(Parent)));
    const initialRenders = queueRenders;
    act(() => retry());
    assert.equal(queueRenders, initialRenders);
    await act(async () => queue.add([{ file: new dom.window.File(["x".repeat(1000)], "test.txt"), relative: "test.txt" }], ""));
    const beforeProgress = queueRenders;
    act(() => { for (let index = 1; index <= 100; index++) progress(index * 9); });
    assert.equal(queueRenders, beforeProgress);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 125)); });
    assert.equal(queueRenders, beforeProgress + 1);
    assert.equal(parentRenders, 1);
    assert.equal(host.textContent, "90");
    await act(async () => finish());
    assert.equal(host.textContent, "100");
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 225)); });
    assert.equal(completed, 1);
    assert.equal(parentRenders, 1);
    const doneRenders = queueRenders;
    act(() => retry());
    assert.equal(queueRenders, doneRenders);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    window.close();
  }
});
