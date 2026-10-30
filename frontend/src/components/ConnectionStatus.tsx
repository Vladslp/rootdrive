import { useEffect, useRef, useState } from "react";
import { watchServerConnection, type ConnectionState } from "../services/connection";

export function ConnectionStatus() {
  const [state, setState] = useState<ConnectionState>(navigator.onLine === false ? "offline" : "running");
  const monitor = useRef<ReturnType<typeof watchServerConnection> | null>(null);
  useEffect(() => {
    monitor.current = watchServerConnection(setState);
    return () => { monitor.current?.stop(); monitor.current = null; };
  }, []);
  const label = state === "running" ? "Running" : state === "checking" ? "Checking…" : state === "offline" ? "Offline" : "Retry connection";
  return <button className={"connection-state connection-" + state} disabled={state === "checking"}
    title={state === "running" ? "Check server connection" : state === "offline" ? "Your device is offline" : "Reconnect to the server"}
    aria-label={state === "running" ? "Check server connection" : state === "checking" ? "Checking server connection" : "Retry connection"}
    onClick={() => monitor.current?.check()}><i /><span aria-live="polite">{label}</span></button>;
}
