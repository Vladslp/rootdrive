import { useEffect, useState, useSyncExternalStore } from "react";
import { Check, MonitorDown } from "lucide-react";
import { installation } from "../services/install";
export function InstallSettings() {
  const prompt = useSyncExternalStore(installation.subscribe, installation.get);
  const [installed, setInstalled] = useState(
    () => window.matchMedia?.("(display-mode: standalone)").matches || false,
  );
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const done = () => setInstalled(true);
    window.addEventListener("appinstalled", done);
    return () => window.removeEventListener("appinstalled", done);
  }, []);
  return (
    <section className="settings-section">
      <div className="section-heading">
        <h3>
          <MonitorDown size={19} />
          Install RootDrive
        </h3>
        {installed && (
          <span className="status-pill">
            <Check size={13} />
            Installed
          </span>
        )}
      </div>
      {!installed && (
        <p className="muted">
          {!window.isSecureContext
            ? "Open over HTTPS or localhost to install the app."
            : prompt
              ? "Open RootDrive in its own window."
              : "Use your browser’s Install app or Add to Home Screen action."}
        </p>
      )}
      {prompt && !installed && (
        <button
          className="button primary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await prompt.prompt();
              await prompt.userChoice;
              installation.clear();
            } finally {
              setBusy(false);
            }
          }}
        >
          <MonitorDown size={16} />
          Install app
        </button>
      )}
    </section>
  );
}
