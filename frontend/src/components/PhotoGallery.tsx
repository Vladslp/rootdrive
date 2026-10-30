import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Images, Loader2, Pause, Play, Plus, Trash2 } from "lucide-react";
import { api, fileURL, type Entry, type Listing } from "../services/api";
import { Dialog } from "./Dialog";
import { PhotoViewport } from "./PhotoViewport";

type Album = { id: string; name: string };
export default function PhotoGallery() {
  const [albums, setAlbums] = useState<Album[]>([]);
  const [album, setAlbum] = useState("");
  const [page, setPage] = useState<Listing>({ items: [], total: 0 });
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [target, setTarget] = useState("");
  const [name, setName] = useState<string | null>(null);
  const [active, setActive] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [size, setSize] = useState({ width: 1, height: 1 });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { const controller = new AbortController(); api<{ items: Album[] }>("/albums", "GET", undefined, controller.signal).then((data) => setAlbums(data.items)).catch((error) => { if (!controller.signal.aborted) setError(error.message); }); return () => controller.abort(); }, [revision]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setSelected([]); setError("");
    api<Listing>("/gallery?" + new URLSearchParams({ album, offset: String(offset), limit: "60" }), "GET", undefined, controller.signal).then(setPage).catch((error) => { if (!controller.signal.aborted) setError(error.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [album, offset, revision]);
  function step(direction: number) {
    if (active === null) return;
    const next = active + direction;
    if (next >= 0 && next < page.items.length) { setActive(next); setSize({ width: 1, height: 1 }); }
    else { setPlaying(false); if (direction > 0 && offset + 60 < page.total) { setOffset(offset + 60); setActive(0); } else if (direction < 0 && offset > 0) { setOffset(offset - 60); setActive(59); } }
  }
  useEffect(() => {
    if (active === null) return;
    function key(event: KeyboardEvent) { if (event.key === "ArrowRight") { event.preventDefault(); step(1); } if (event.key === "ArrowLeft") { event.preventDefault(); step(-1); } }
    window.addEventListener("keydown", key); return () => window.removeEventListener("keydown", key);
  }, [active, page, offset]);
  useEffect(() => {
    if (!playing || active === null || loading) return;
    const timer = window.setInterval(() => { if (document.visibilityState === "visible") step(1); }, 3500);
    return () => window.clearInterval(timer);
  }, [playing, active, page, offset, loading]);
  async function mutate(action: () => Promise<unknown>) { setBusy(true); setError(""); try { await action(); setSelected([]); setRevision((value) => value + 1); } catch (error) { setError((error as Error).message); } finally { setBusy(false); } }
  const photo = active === null ? null : page.items[active];
  const groups = new Map<string, Entry[]>();
  for (const item of page.items) { const day = new Date(item.modified * 1000).toLocaleDateString("en", { year: "numeric", month: "long", day: "numeric" }); groups.set(day, [...(groups.get(day) || []), item]); }
  return <section className="library-page" aria-label="Photo gallery">
    <div className="library-toolbar"><label>Album<select value={album} onChange={(event) => { setAlbum(event.target.value); setOffset(0); setActive(null); }}><option value="">All photos</option>{albums.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><span className="muted">{page.total} photos · by modification date</span><button className="button secondary" onClick={() => setName("")}><Plus size={16} />New album</button>{album && <button className="button secondary danger" disabled={busy} onClick={() => void mutate(async () => { await api("/albums/" + album, "DELETE"); setAlbum(""); setOffset(0); })}><Trash2 size={16} />Delete album</button>}</div>
    {selected.length > 0 && <div className="library-toolbar"><strong>{selected.length} selected</strong><select aria-label="Destination album" value={target} onChange={(event) => setTarget(event.target.value)}><option value="">Choose album</option>{albums.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><button className="button primary" disabled={!target || busy} onClick={() => void mutate(() => api("/albums/" + target + "/items", "POST", { paths: selected }))}>Add to album</button>{album && <button className="button secondary" disabled={busy} onClick={() => void mutate(() => api("/albums/" + album + "/items", "DELETE", { paths: selected }))}>Remove from album</button>}<button className="button secondary" onClick={() => setSelected([])}>Clear</button></div>}
    {error && <p className="error-banner" role="alert">{error}</p>}
    {loading ? <div className="loading-area"><Loader2 className="spin" /></div> : page.total === 0 ? <div className="empty-state"><Images size={42} /><h3>No photos yet</h3></div> : Array.from(groups, ([day, items]) => <section key={day} className="gallery-day"><h3>{day}</h3><div className="gallery-grid">{items.map((item) => <article key={item.path} className={"gallery-photo" + (selected.includes(item.path) ? " selected" : "")}><button className="gallery-open" aria-label={"Open " + item.name} onClick={() => { setActive(page.items.indexOf(item)); setSize({ width: 1, height: 1 }); }}><img loading="lazy" decoding="async" src={"/api/files/thumbnail?path=" + encodeURIComponent(item.path)} alt={item.name} /><span>{item.name}</span></button><input type="checkbox" aria-label={"Select " + item.name} checked={selected.includes(item.path)} onChange={(event) => setSelected((values) => event.target.checked ? [...values, item.path] : values.filter((value) => value !== item.path))} /></article>)}</div></section>)}
    {page.total > 60 && <div className="pagination"><button disabled={!offset || loading} onClick={() => setOffset(offset - 60)}>Previous</button><span>{offset + 1}–{Math.min(offset + 60, page.total)}</span><button disabled={offset + 60 >= page.total || loading} onClick={() => setOffset(offset + 60)}>Next</button></div>}
    {name !== null && <Dialog title="New album" close={() => { if (!busy) setName(null); }}><form onSubmit={(event) => { event.preventDefault(); void mutate(async () => { const result = await api<Album>("/albums", "POST", { name }); setAlbum(result.id); setOffset(0); setName(null); }); }}><label className="field-label">Name<input autoFocus required maxLength={80} value={name} onChange={(event) => setName(event.target.value)} /></label><p className="muted">Original files stay in their folders.</p>{error && <p role="alert" className="error-text">{error}</p>}<div className="dialog-actions"><button className="button primary" disabled={busy || !name.trim()}>Create album</button></div></form></Dialog>}
    {photo && !loading && <Dialog title={photo.name} wide close={() => { setActive(null); setPlaying(false); }}><div className="preview-content photos"><PhotoViewport key={photo.path} width={size.width} height={size.height}><img src={fileURL(photo, true)} alt={photo.name} onLoad={(event) => setSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })} /></PhotoViewport></div><div className="dialog-actions"><button className="button secondary" aria-label="Previous photo" disabled={offset === 0 && active === 0} onClick={() => step(-1)}><ChevronLeft size={18} /></button><span>{offset + (active || 0) + 1} / {page.total}</span><button className="button secondary" aria-label="Next photo" disabled={offset + (active || 0) + 1 >= page.total} onClick={() => step(1)}><ChevronRight size={18} /></button><button className="button primary" onClick={() => setPlaying(!playing)}>{playing ? <Pause size={16} /> : <Play size={16} />}{playing ? "Pause" : "Slideshow"}</button></div></Dialog>}
  </section>;
}
