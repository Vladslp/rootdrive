import assert from "node:assert/strict";
import { beforeEach, afterEach, test } from "node:test";
import { watchServerConnection } from "../src/services/connection.ts";
import { api } from "../src/services/api.ts";

let jobs, now, sequence, calls, states, monitor, recoveries, navigatorDescriptor;
const flush = () => new Promise((resolve) => setImmediate(resolve));
async function advance(duration) {
  const end = now + duration;
  for (;;) {
    const next = [...jobs.entries()].filter(([, task]) => task.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
    if (!next) break;
    jobs.delete(next[0]); now = next[1].at; next[1].run(); await flush();
  }
  now = end; await flush();
}
beforeEach(() => {
  jobs = new Map(); now = 0; sequence = 0; calls = []; states = []; recoveries = 0;
  globalThis.window = new EventTarget();
  window.Event = Event;
  window.setTimeout = (run, delay) => { const id = ++sequence; jobs.set(id, { run, at: now + delay }); return id; };
  window.clearTimeout = (id) => jobs.delete(id);
  globalThis.document = new EventTarget(); document.hidden = false;
  navigatorDescriptor = Object.getOwnPropertyDescriptor(globalThis, "navigator");
  Object.defineProperty(globalThis, "navigator", { value: { onLine: true }, configurable: true });
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => ({ status: "ok" }) }; };
  window.addEventListener("rootdrive:reconnected", () => recoveries++);
  monitor = watchServerConnection((state) => states.push(state));
});
afterEach(() => {
  monitor.stop();
  if (navigatorDescriptor) Object.defineProperty(globalThis, "navigator", navigatorDescriptor);
  else delete globalThis.navigator;
});

test("server heartbeats are infrequent and stop on cleanup", async () => {
  assert.equal(states.at(-1), "running");
  await advance(44999); assert.equal(calls.length, 0);
  await advance(1); assert.equal(calls.length, 1);
  assert.equal(calls[0].options.cache, "no-store");
  assert.deepEqual(states, ["running", "running"]);
  monitor.stop(); await advance(100000); assert.equal(calls.length, 1);
});

test("hidden and offline pages pause checks and resume when visible and online", async () => {
  document.hidden = true; document.dispatchEvent(new Event("visibilitychange"));
  await advance(90000); assert.equal(calls.length, 0);
  document.hidden = false; document.dispatchEvent(new Event("visibilitychange")); await flush();
  assert.equal(calls.length, 1);
  navigator.onLine = false; window.dispatchEvent(new Event("offline"));
  assert.equal(states.at(-1), "offline");
  window.dispatchEvent(new Event("rootdrive:connection-ok"));
  assert.equal(states.at(-1), "offline");
  await advance(90000); assert.equal(calls.length, 1);
  navigator.onLine = true; window.dispatchEvent(new Event("online")); await flush();
  assert.equal(states.at(-1), "running"); assert.equal(recoveries, 1);
});

test("transport errors trigger a bounded retry and recovery notification", async () => {
  globalThis.fetch = async () => { throw new TypeError("network failed"); };
  await assert.rejects(api("/files"));
  assert.equal(states.at(-1), "unavailable");
  globalThis.fetch = async () => { calls.push({}); return { ok: true, json: async () => ({ status: "ok" }) }; };
  await advance(4999); assert.equal(calls.length, 0);
  await advance(1); assert.equal(states.at(-1), "running"); assert.equal(recoveries, 1);
});

test("stalled checks time out and cleanup aborts in-flight requests", async () => {
  let signal;
  globalThis.fetch = (url, options) => new Promise((resolve, reject) => {
    signal = options.signal;
    signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
  });
  monitor.check(); assert.equal(states.at(-1), "checking");
  await advance(8000); assert.equal(signal.aborted, true); assert.equal(states.at(-1), "unavailable");
  monitor.check(); const before = states.length;
  monitor.stop(); await flush();
  assert.equal(signal.aborted, true); assert.equal(states.length, before); assert.equal(jobs.size, 0);
});

test("intentional API cancellation does not report a lost server", async () => {
  const controller = new AbortController(); controller.abort();
  globalThis.fetch = async () => { throw new Error("cancelled"); };
  await assert.rejects(api("/files", "GET", undefined, controller.signal));
  assert.deepEqual(states, ["running"]);
});
