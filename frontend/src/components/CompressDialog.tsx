import { useState, type FormEvent } from "react";
import { FolderArchive, Loader2 } from "lucide-react";
import { api, type Entry } from "../services/api";
import { Dialog } from "./Dialog";

function archiveName(name: string) {
  const parts = [...name];
  while (new TextEncoder().encode(parts.join("") + ".zip").length > 240) parts.pop();
  return parts.join("") + ".zip";
}
export function CompressDialog({ entry, close, created }: {
  entry: Entry;
  close: () => void;
  created: (entry: Entry) => void;
}) {
  const [name, setName] = useState(() => archiveName(entry.name));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Entry>("/files/compress", "POST", { path: entry.path, name });
      created(result);
    } catch (error) {
      setError((error as Error).message);
      setBusy(false);
    }
  }
  return (
    <Dialog title="Create ZIP" close={() => { if (!busy) close(); }}>
      <form onSubmit={submit}>
        <label className="field-label">
          Name
          <input value={name} onChange={(event) => setName(event.target.value)} autoFocus required maxLength={240} disabled={busy} />
        </label>
        <p className="muted">Saved beside this folder.</p>
        {error && <p className="error-text" role="alert">{error}</p>}
        <div className="dialog-actions">
          <button type="button" className="button secondary" disabled={busy} onClick={close}>Cancel</button>
          <button type="submit" className="button primary" disabled={busy || !name.trim()}>
            {busy ? <Loader2 className="spin" size={16} /> : <FolderArchive size={16} />}
            {busy ? "Creating ZIP…" : "Create ZIP"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}
