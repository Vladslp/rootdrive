import assert from "node:assert/strict";
import { test } from "node:test";
import { api, apiBlob, fileURL, setSpace, workspaceURL } from "../src/services/api.ts";
const events = new EventTarget();
globalThis.window = { location: { origin: "https://rootdrive.test" }, dispatchEvent: (event) => events.dispatchEvent(event), Event };

test("file URLs bind to their workspace and public URLs retain their explicit space", () => {
  setSpace("personal-space");
  assert.equal(new URL(fileURL({ path: "photo.png" }), window.location.origin).searchParams.get("workspace"), "personal-space");
  assert.equal(workspaceURL("/api/public/token?space=other"), "/api/public/token?space=other");
  assert.equal(workspaceURL("/api/files/media?path=one.mp3&workspace=old"), "/api/files/media?path=one.mp3&workspace=old");
});

test("JSON mutations and photo previews carry the workspace binding", async () => {
  const requests = [];
  globalThis.fetch = async (url, options) => { requests.push({ url, options }); return { ok: true, json: async () => ({ ok: true }), blob: async () => new Blob(["image"]) }; };
  setSpace("team-space");
  await api("/folders", "POST", { name: "New" });
  await apiBlob("/studio/preview", { paths: ["image.jpg"] });
  assert.ok(requests.every((request) => request.options.headers["X-RootDrive-Space"] === "team-space"));
});


test("responses from a previous account are discarded after the account changes", async () => {
  let finish;
  globalThis.fetch = () => new Promise((resolve) => { finish = resolve; });
  setSpace("shared", true);
  const pending = api("/files");
  setSpace("shared", true);
  finish({ ok: true, json: async () => ({ items: [{ name: "previous-account-private.txt" }] }) });
  await assert.rejects(pending, (error) => error.name === "AbortError");
});
