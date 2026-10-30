import { useRef, useState } from "react";
import { Copy, Loader2, Search } from "lucide-react";
import { api, bytes, type Entry } from "../services/api";
import { Art, kindOf } from "./Art";

type Match = { entry: Entry; line: number; excerpt: string };
type Scan = { groups: { size: number; items: Entry[] }[]; scanned: number; hashed: number; incomplete: boolean };
export default function Discovery({ open, locate }: { open: (entry: Entry) => void; locate: (entry: Entry) => void }) {
  const [mode, setMode] = useState("content");
  const [query, setQuery] = useState("");
  const [path, setPath] = useState("");
  const [matches, setMatches] = useState<{ items: Match[]; scanned: number; skipped: number; incomplete: boolean } | null>(null);
  const [scan, setScan] = useState<Scan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const controller = useRef<AbortController | null>(null);
  async function run() { setBusy(true); setError(""); controller.current?.abort(); controller.current = new AbortController(); try { if (mode === "content") setMatches(await api("/discovery/content?" + new URLSearchParams({ q: query, path }), "GET", undefined, controller.current.signal)); else setScan(await api<Scan>("/discovery/duplicates", "POST", undefined, controller.current.signal)); } catch (error) { if (!controller.current?.signal.aborted) setError((error as Error).message); } finally { setBusy(false); } }
  return <section className="library-page"><div className="library-toolbar" role="tablist" aria-label="Discovery mode"><button role="tab" aria-selected={mode === "content"} className={"button " + (mode === "content" ? "primary" : "secondary")} disabled={busy} onClick={() => setMode("content")}><Search size={16} />Inside files</button><button role="tab" aria-selected={mode === "duplicates"} className={"button " + (mode === "duplicates" ? "primary" : "secondary")} disabled={busy} onClick={() => setMode("duplicates")}><Copy size={16} />Duplicates</button></div>
    <form className="discovery-form" onSubmit={(event) => { event.preventDefault(); void run(); }}>{mode === "content" ? <><label className="field-label">Find text<input required minLength={2} maxLength={200} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search notes, code, DOCX and ODT" /></label><label className="field-label">Within folder<input value={path} onChange={(event) => setPath(event.target.value)} placeholder="All files" /></label></> : <p className="muted">Compare file contents. Originals are kept.</p>}<button className="button primary" disabled={busy || (mode === "content" && query.trim().length < 2)}>{busy && <Loader2 size={16} className="spin" />}{mode === "content" ? "Search" : "Scan for duplicates"}</button></form>
    {error && <p className="error-banner" role="alert">{error}</p>}
    {mode === "content" && matches && <><p className="muted">{matches.items.length} matches · {matches.scanned} files checked{matches.skipped > 0 ? ` · ${matches.skipped} unsupported or oversized files skipped` : ""}{matches.incomplete ? " · Partial results; narrow the folder or query" : ""}</p>{matches.items.map((match) => <article className="discovery-result" key={match.entry.path}><Art kind={kindOf(match.entry)} /><div><button onClick={() => open(match.entry)}><strong>{match.entry.name}</strong></button><small>/{match.entry.path} · line {match.line}</small><p>{match.excerpt}</p></div><button className="button secondary" onClick={() => locate(match.entry)}>Open location</button></article>)}{!matches.items.length && <p className="empty-state">No matching text</p>}</>}
    {mode === "duplicates" && scan && <><p className="muted">{scan.groups.length} groups · {scan.scanned} files checked · {scan.hashed} newly hashed{scan.incomplete ? " · Partial scan: 30-second / 100,000-file budget reached" : ""}</p>{scan.groups.map((group, index) => <section className="duplicate-group" key={index}><h3>{group.items.length} copies · {bytes(group.size * (group.items.length - 1))} extra</h3>{group.items.map((item) => <article className="discovery-result" key={item.path}><Art kind={kindOf(item)} /><div><button onClick={() => open(item)}><strong>{item.name}</strong></button><small>/{item.path}</small></div><button className="button secondary" onClick={() => locate(item)}>Open location</button></article>)}</section>)}{!scan.groups.length && <p className="empty-state">No duplicates found</p>}</>}
  </section>;
}
