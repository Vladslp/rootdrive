import { useEffect, useState } from "react";
import { FolderLock, Loader2, Users } from "lucide-react";
import { api, type Account, type Space } from "../services/api";
export function SpaceSelector({
  account,
  canSwitch,
}: {
  account: Account;
  canSwitch: () => boolean;
}) {
  const [items, setItems] = useState<Space[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!account.auth_enabled || !account.user) return;
    const controller = new AbortController();
    const load = () => {
      void api<{ items: Space[] }>(
        "/spaces",
        "GET",
        undefined,
        controller.signal,
      )
        .then((value) => setItems(value.items))
        .catch((error) => {
          if (!controller.signal.aborted) setError(error.message);
        });
    };
    load();
    window.addEventListener("rootdrive:spaces-changed", load);
    return () => {
      controller.abort();
      window.removeEventListener("rootdrive:spaces-changed", load);
    };
  }, [account.auth_enabled, account.user?.username]);
  if (!account.auth_enabled || !account.user) return null;
  return (
    <section className="space-selector">
      <label>
        <span>
          {account.space?.kind === "personal" ? (
            <FolderLock size={16} />
          ) : (
            <Users size={16} />
          )}
          {busy ? <Loader2 className="spin" size={14} /> : "Workspace"}
        </span>
        <select
          aria-label="Workspace"
          disabled={busy}
          value={account.space?.id || "shared"}
          onChange={async (event) => {
            if (!canSwitch()) {
              setError("Finish editing and finish or cancel uploads first");
              return;
            }
            setBusy(true);
            setError("");
            try {
              await api("/spaces/select", "POST", { id: event.target.value });
              window.location.assign("/");
            } catch (error) {
              setError((error as Error).message);
              setBusy(false);
            }
          }}
        >
          {!items.some((item) => item.id === account.space?.id) &&
            account.space && (
              <option value={account.space.id}>{account.space.name}</option>
            )}
          {items.map((item) => (
            <option value={item.id} key={item.id}>
              {item.name}
              {item.role === "reader" ? " · Read only" : ""}
            </option>
          ))}
        </select>
      </label>
      {account.space?.role === "reader" && <small>Read only</small>}
      {error && (
        <small role="alert" className="error-text">
          {error}
        </small>
      )}
    </section>
  );
}
