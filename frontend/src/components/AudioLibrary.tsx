import { useEffect, useRef, useState } from "react";
import { Loader2, Music2, Play, Plus, SkipBack, SkipForward, Trash2, X } from "lucide-react";
import { api, bytes, type Entry, type Listing } from "../services/api";
import { Dialog } from "./Dialog";
type Playlist = { id: string; name: string };
export default function AudioLibrary({ visible }: { visible: boolean }) {
  const [playlists, setPlaylists] = useState<Playlist[]>([]);
  const [playlist, setPlaylist] = useState("");
  const [page, setPage] = useState<Listing>({ items: [], total: 0 });
  const [offset, setOffset] = useState(0);
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState<string[]>([]);
  const [target, setTarget] = useState("");
  const [name, setName] = useState<string | null>(null);
  const [queue, setQueue] = useState<Entry[]>([]);
  const [index, setIndex] = useState(0);
  const [scope, setScope] = useState({ playlist: "", offset: 0, total: 0 });
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const audio = useRef<HTMLAudioElement>(null);
  const track = queue[index];
  useEffect(() => { if (!visible) return; const controller = new AbortController(); api<{ items: Playlist[] }>("/library/playlists", "GET", undefined, controller.signal).then((value) => setPlaylists(value.items)).catch((error) => { if (!controller.signal.aborted) setError(error.message); }); return () => controller.abort(); }, [visible, revision]);
  useEffect(() => { if (!visible) return; const controller = new AbortController(); setLoading(true); setSelected([]); api<Listing>("/library/audio?" + new URLSearchParams({ playlist, offset: String(offset) }), "GET", undefined, controller.signal).then(setPage).catch((error) => { if (!controller.signal.aborted) setError(error.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); }); return () => controller.abort(); }, [visible, playlist, offset, revision]);
  async function mutate(action: () => Promise<unknown>) { setBusy(true); setError(""); try { await action(); setSelected([]); setRevision((value) => value + 1); } catch (error) { setError((error as Error).message); } finally { setBusy(false); } }
  async function play(item: Entry) { setError(""); if (queue[index]?.path === item.path) { await audio.current?.play().catch(() => setError("Playback is unavailable for this format")); return; } setScope({ playlist, offset, total: page.total }); setQueue(page.items); setIndex(page.items.indexOf(item)); }
  async function advance(direction: number) {
    const next = index + direction;
    if (next >= 0 && next < queue.length) { setIndex(next); return; }
    const nextOffset = scope.offset + direction * 60;
    if (nextOffset < 0 || nextOffset >= scope.total) return;
    try { const nextPage = await api<Listing>("/library/audio?" + new URLSearchParams({ playlist: scope.playlist, offset: String(nextOffset) })); if (!nextPage.items.length) return; setQueue(nextPage.items); setIndex(direction > 0 ? 0 : nextPage.items.length - 1); setScope({ ...scope, offset: nextOffset, total: nextPage.total }); } catch (error) { setError((error as Error).message); }
  }
  return <><section hidden={!visible} className="library-page audio-library"><div className="library-toolbar"><select aria-label="Playlist" value={playlist} onChange={(event) => { setPlaylist(event.target.value); setOffset(0); }}><option value="">All audio</option>{playlists.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><button className="button secondary" onClick={() => setName("")}><Plus size={16} />New playlist</button>{playlist && <button className="button secondary danger" disabled={busy} onClick={() => void mutate(async () => { await api("/library/playlists/" + playlist, "DELETE"); setPlaylist(""); setOffset(0); })}><Trash2 size={16} />Delete playlist</button>}</div>{selected.length > 0 && <div className="library-toolbar"><strong>{selected.length} selected</strong><select aria-label="Add to playlist" value={target} onChange={(event) => setTarget(event.target.value)}><option value="">Choose playlist</option>{playlists.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><button className="button primary" disabled={!target || busy} onClick={() => void mutate(() => api("/library/playlists/" + target + "/items", "POST", { paths: selected }))}>Add tracks</button>{playlist && <button className="button secondary" disabled={busy} onClick={() => void mutate(() => api("/library/playlists/" + playlist + "/items", "DELETE", { paths: selected }))}>Remove tracks</button>}</div>}{error && <p className="error-banner" role="alert">{error}</p>}{loading ? <div className="loading-area"><Loader2 className="spin" /></div> : page.items.map((item) => <article className="audio-row" key={item.path}><input type="checkbox" aria-label={"Select " + item.name} checked={selected.includes(item.path)} onChange={(event) => setSelected((values) => event.target.checked ? [...values, item.path] : values.filter((value) => value !== item.path))} /><button className="audio-track" onClick={() => void play(item)}><Music2 size={22} /><span><strong>{item.name}</strong><small>/{item.path}</small></span><small>{bytes(item.size)}</small><Play size={16} /></button></article>)}{!loading && !page.total && <p className="empty-state">No audio yet</p>}{page.total > 60 && <div className="pagination"><button disabled={!offset || loading} onClick={() => setOffset(offset - 60)}>Previous</button><span>{offset + 1}–{Math.min(offset + 60, page.total)}</span><button disabled={offset + 60 >= page.total || loading} onClick={() => setOffset(offset + 60)}>Next</button></div>}</section>
    {name !== null && <Dialog title="New playlist" close={() => { if (!busy) setName(null); }}><form onSubmit={(event) => { event.preventDefault(); void mutate(async () => { const item = await api<Playlist>("/library/playlists", "POST", { name }); setPlaylist(item.id); setOffset(0); setName(null); }); }}><label className="field-label">Name<input autoFocus required maxLength={80} value={name} onChange={(event) => setName(event.target.value)} /></label>{error && <p className="error-text">{error}</p>}<div className="dialog-actions"><button className="button primary" disabled={busy || !name.trim()}>Create</button></div></form></Dialog>}
    {track && <aside className="persistent-player" aria-label="Audio player"><Music2 size={21} /><strong title={track.path}>{track.name}{error && <small className="error-text" role="alert">{error}</small>}</strong><button className="icon-button" aria-label="Previous track" disabled={index === 0 && scope.offset === 0} onClick={() => void advance(-1)}><SkipBack size={17} /></button><audio key={track.path} ref={audio} controls autoPlay preload="metadata" src={"/api/files/media?path=" + encodeURIComponent(track.path)} onEnded={() => void advance(1)} onError={() => setError("Your browser cannot play this audio format")} /><button className="icon-button" aria-label="Next track" disabled={scope.offset + index + 1 >= scope.total} onClick={() => void advance(1)}><SkipForward size={17} /></button><button className="icon-button" aria-label="Close player" onClick={() => setQueue([])}><X size={17} /></button></aside>}
  </>;
}
