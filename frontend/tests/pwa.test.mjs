import assert from "node:assert/strict";
import { test } from "node:test";
import { readFile } from "node:fs/promises";
import vm from "node:vm";
const source = await readFile(new URL("../public/service-worker.js", import.meta.url), "utf8");

test("service worker ignores API data, public links, uploads and unknown assets", async () => {
  const handlers = {};
  const context = vm.createContext({ self: { location: { origin: "https://rootdrive.test" }, addEventListener: (name, callback) => { handlers[name] = callback; } }, URL, Response });
  vm.runInContext(source, context);
  for (const [path, method, mode] of [["/api/files/preview?path=private.jpg", "GET", "cors"], ["/api/files/download?path=private.txt", "GET", "navigate"], ["/share/secret", "GET", "navigate"], ["/api/files/upload", "POST", "cors"], ["/assets/user.txt", "GET", "cors"], ["https://other.test/assets/index-12345678.js", "GET", "cors"]]) {
    let intercepted = false;
    handlers.fetch({ request: { url: path.startsWith("https") ? path : "https://rootdrive.test" + path, method, mode }, respondWith: () => { intercepted = true; } });
    assert.equal(intercepted, false, path);
  }
});

test("manifest offers a scoped standalone app with correctly sized icons", async () => {
  const manifest = JSON.parse(await readFile(new URL("../public/manifest.webmanifest", import.meta.url), "utf8"));
  assert.equal(manifest.start_url, "/");
  assert.equal(manifest.display, "standalone");
  assert.deepEqual(manifest.icons.map((icon) => icon.sizes), ["192x192", "512x512"]);
  for (const icon of manifest.icons) {
    const png = await readFile(new URL("../public" + icon.src, import.meta.url));
    const expected = Number(icon.sizes.split("x")[0]);
    assert.equal(png.readUInt32BE(16), expected);
    assert.equal(png.readUInt32BE(20), expected);
  }
});
