import { useEffect, useState } from "react";
import { Pin, X } from "lucide-react";
import { api } from "../services/api";
export function PinnedFolders({ revision, navigate }: { revision: number; navigate: (path: string) => void }) {
  const [items, setItems] = useState<{ path: string; name: string }[]>([]);
  const [error, setError] = useState("");
  useEffect(() => { const controller = new AbortController(); api<{ items: { path: string; name: string }[] }>("/library/pins", "GET", undefined, controller.signal).then((value) => { setItems(value.items); setError(""); }).catch((error) => { if (!controller.signal.aborted) setError(error.message); }); return () => controller.abort(); }, [revision]);
  if (!items.length && !error) return null;
  return <section className="sidebar-pins" aria-label="Pinned folders"><div className="sidebar-label">Pinned</div>{items.map((item) => <div key={item.path} className="pinned-row"><button className="nav-link" title={item.path} onClick={() => navigate(item.path)}><Pin size={16} /><span>{item.name}</span></button><button className="icon-button" aria-label={"Unpin " + item.name} onClick={async () => { try { await api("/library/pins", "DELETE", { path: item.path }); setItems((values) => values.filter((value) => value.path !== item.path)); } catch (error) { setError((error as Error).message); } }}><X size={12} /></button></div>)}{error && <small className="error-text">{error}</small>}</section>;
}
