import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
const PublicShare = React.lazy(() => import("./components/PublicShare"));
import "./styles.css";
import "./design.css";
import "./commands.css";
if ("serviceWorker" in navigator && import.meta.env.PROD && !location.pathname.startsWith("/share/")) {
  window.addEventListener("load", () => { void navigator.serviceWorker.register("/service-worker.js").catch(() => {}); }, { once: true });
}
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <React.Suspense fallback={<div className="loading-area">Loading…</div>}>{location.pathname.startsWith("/share/") ? <PublicShare /> : <App />}</React.Suspense>
  </React.StrictMode>,
);
