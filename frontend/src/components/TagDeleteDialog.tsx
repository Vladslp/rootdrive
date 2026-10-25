import { useState } from "react";
import { Loader2, Trash2 } from "lucide-react";
import { api, type Tag } from "../services/api";
import { Dialog } from "./Dialog";

export function TagDeleteDialog({ tag, close, removed }: {
  tag: Tag;
  close: () => void;
  removed: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function remove() {
    setBusy(true);
    setError("");
    try {
      await api("/tags/" + encodeURIComponent(tag.id), "DELETE");
      removed();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title="Delete tag?" close={() => { if (!busy) close(); }}>
      <p className="confirm-name">{tag.name}</p>
      <p className="muted">Removes this tag from all files.</p>
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="dialog-actions">
        <button className="button secondary" disabled={busy} onClick={close}>Cancel</button>
        <button className="button danger" disabled={busy} onClick={() => void remove()}>
          {busy ? <Loader2 size={16} className="spin" /> : <Trash2 size={16} />}
          Delete tag
        </button>
      </div>
    </Dialog>
  );
}
