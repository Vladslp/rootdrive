export type ConnectionState = "running" | "checking" | "offline" | "unavailable";

export function watchServerConnection(change: (state: ConnectionState) => void) {
  let stopped = false;
  let status: ConnectionState = navigator.onLine === false ? "offline" : "running";
  let failed = status === "offline";
  let timer: number | undefined;
  let deadline: number | undefined;
  let controller: AbortController | null = null;

  function publish(next: ConnectionState) {
    if (stopped) return;
    if (next === "offline" || next === "unavailable") failed = true;
    const recovered = next === "running" && failed;
    if (next === "running") failed = false;
    status = next;
    change(next);
    if (recovered) window.dispatchEvent(new window.Event("rootdrive:reconnected"));
  }
  function schedule(delay = status === "unavailable" ? 5000 : 45000) {
    window.clearTimeout(timer);
    if (!stopped && !document.hidden && navigator.onLine !== false) timer = window.setTimeout(() => void check(), delay);
  }
  async function check(manual = false) {
    if (stopped || controller || document.hidden) return;
    if (navigator.onLine === false) { publish("offline"); return; }
    window.clearTimeout(timer);
    const active = new AbortController();
    controller = active;
    let timedOut = false;
    if (manual || status !== "running") publish("checking");
    deadline = window.setTimeout(() => { timedOut = true; active.abort(); }, 8000);
    try {
      const response = await fetch("/api/health", { signal: active.signal, cache: "no-store" });
      const result = await response.json();
      if (!active.signal.aborted) publish(response.ok && result.status === "ok" ? "running" : "unavailable");
    } catch {
      if (!active.signal.aborted || timedOut) publish("unavailable");
    } finally {
      window.clearTimeout(deadline);
      if (controller === active) controller = null;
      schedule();
    }
  }
  const connected = () => { publish(navigator.onLine === false ? "offline" : "running"); schedule(); };
  const lost = () => { publish(navigator.onLine === false ? "offline" : "unavailable"); schedule(5000); };
  const online = () => void check();
  const offline = () => { window.clearTimeout(timer); controller?.abort(); publish("offline"); };
  const visibility = () => {
    if (document.hidden) { window.clearTimeout(timer); controller?.abort(); }
    else void check();
  };
  window.addEventListener("rootdrive:connection-ok", connected);
  window.addEventListener("rootdrive:connection-lost", lost);
  window.addEventListener("online", online);
  window.addEventListener("offline", offline);
  window.addEventListener("focus", online);
  document.addEventListener("visibilitychange", visibility);
  publish(status);
  schedule();
  return {
    check: () => void check(true),
    stop: () => {
      stopped = true;
      window.clearTimeout(timer); window.clearTimeout(deadline); controller?.abort();
      window.removeEventListener("rootdrive:connection-ok", connected);
      window.removeEventListener("rootdrive:connection-lost", lost);
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
      window.removeEventListener("focus", online);
      document.removeEventListener("visibilitychange", visibility);
    },
  };
}
