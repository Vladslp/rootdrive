import { useEffect, useState } from "react";
import { ArrowLeft, Download, FolderArchive, Loader2 } from "lucide-react";
import { api, bytes, saveURL, type Entry } from "../services/api";
import { Art, kindOf } from "./Art";
import { Dialog } from "./Dialog";

type Member = Entry;
type ArchivePage = { items: Member[]; total: number; prefix: string };
export function ArchiveDialog({ entry, close, extracted }: { entry: Entry; close: () => void; extracted: (entry: Entry) => void }) {
  const [prefix, setPrefix] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ArchivePage>({ items: [], total: 0, prefix: "" });
  const [selected, setSelected] = useState<string[]>([]);
  const [name, setName] = useState(entry.name.replace(/\.zip$/i, "") + " extracted");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setSelected([]);
    api<ArchivePage>("/archives?" + new URLSearchParams({ path: entry.path, prefix, offset: String(offset), limit: "100" }), "GET", undefined, controller.signal)
      .then(setPage).catch((error) => { if (!controller.signal.aborted) setError(error.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [entry.path, prefix, offset]);
  async function extract() {
    setBusy(true); setError("");
    try {
      const result = await api<Entry>("/archives/extract", "POST", { path: entry.path, destination: entry.path.split("/").slice(0, -1).join("/"), name, members: selected.length ? selected : undefined });
      extracted(result);
    } catch (error) { setError((error as Error).message); }
    finally { setBusy(false); }
  }
  return <Dialog title={entry.name} close={() => { if (!busy) close(); }} className="archive-dialog" wide>
    <div className="archive-path"><button className="icon-button" aria-label="Parent archive folder" disabled={!prefix || loading || busy} onClick={() => { setPrefix(prefix.split("/").slice(0, -1).join("/")); setOffset(0); }}><ArrowLeft size={18} /></button><FolderArchive size={18} /><span>/{prefix}</span><small>{page.total} items</small></div>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {loading ? <div className="loading-area"><Loader2 className="spin" /></div> : <div className="archive-members">
      {!page.items.length && !error && <p className="muted">This archive folder is empty</p>}
      {page.items.map((item) => <div className="archive-member" key={item.path}>
        <input type="checkbox" aria-label={"Select archive member " + item.name} checked={selected.includes(item.path)} disabled={busy} onChange={(event) => setSelected((values) => event.target.checked ? [...values, item.path] : values.filter((value) => value !== item.path))} />
        <button className="archive-member-name" disabled={busy} onClick={() => item.type === "folder" ? (setPrefix(item.path), setOffset(0)) : saveURL("/api/archives/member?" + new URLSearchParams({ path: entry.path, member: item.path }))}><Art kind={kindOf(item)} /><span>{item.name}</span></button>
        <small>{bytes(item.size)}</small>
        {item.type === "file" && <button className="icon-button" aria-label={"Download " + item.name} onClick={() => saveURL("/api/archives/member?" + new URLSearchParams({ path: entry.path, member: item.path }))}><Download size={16} /></button>}
      </div>)}
    </div>}
    {page.total > 100 && <div className="pagination"><button disabled={!offset || loading || busy} onClick={() => setOffset(offset - 100)}>Previous</button><span>{offset + 1}–{Math.min(offset + 100, page.total)}</span><button disabled={offset + 100 >= page.total || loading || busy} onClick={() => setOffset(offset + 100)}>Next</button></div>}
    <label className="field-label">Extract into new folder<input value={name} maxLength={240} disabled={busy} onChange={(event) => setName(event.target.value)} /></label>
    <div className="dialog-actions"><button className="button secondary" disabled={busy} onClick={close}>Close</button><button className="button primary" disabled={busy || loading || !name.trim()} onClick={() => void extract()}>{busy ? <Loader2 size={16} className="spin" /> : <FolderArchive size={16} />}{selected.length ? `Extract ${selected.length} selected` : "Extract all"}</button></div>
  </Dialog>;
}
