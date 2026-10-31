import { useEffect, useState } from "react";
import {
  ArrowLeft,
  Download,
  Folder,
  Link2,
  Loader2,
  LockKeyhole,
} from "lucide-react";
import { api, bytes, saveURL, type Listing } from "../services/api";

type Info = {
  name: string;
  type: string;
  locked: boolean;
  expires_at: number | null;
};
export default function PublicShare() {
  const token = location.pathname.split("/")[2] || "";
  const base = "/public/" + encodeURIComponent(token);
  const space = new URLSearchParams(location.search).get("space");
  function scoped(value: string) {
    const url = new URL(value, location.origin);
    if (space) url.searchParams.set("space", space);
    return url.pathname + url.search;
  }
  const [info, setInfo] = useState<Info | null>(null);
  const [listing, setListing] = useState<Listing>({ items: [], total: 0 });
  const [path, setPath] = useState("");
  const [offset, setOffset] = useState(0);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  async function load() {
    try {
      setInfo(await api<Info>(scoped(base + "/info")));
      setError("");
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, [base]);
  useEffect(() => {
    if (!info || info.locked || info.type !== "folder") return;
    const controller = new AbortController();
    setLoading(true);
    api<Listing>(
      scoped(
        base + "/list?" + new URLSearchParams({ path, offset: String(offset) }),
      ),
      "GET",
      undefined,
      controller.signal,
    )
      .then((value) => {
        setListing(value);
        setError("");
      })
      .catch((error) => {
        if (!controller.signal.aborted) setError(error.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [base, info, path, offset]);
  return (
    <main className="public-share">
      <a className="public-brand" href="/">
        <img src="/assets/icons/app.webp" alt="" />
        RootDrive
      </a>
      <section className="public-share-card">
        <Link2 size={26} />
        <h1>{info?.name || "Shared with you"}</h1>
        {error && (
          <p role="alert" className="error-banner">
            {error}
          </p>
        )}
        {loading ? (
          <div className="loading-area">
            <Loader2 className="spin" />
          </div>
        ) : info?.locked ? (
          <form
            onSubmit={async (event) => {
              event.preventDefault();
              setBusy(true);
              try {
                await api(scoped(base + "/unlock"), "POST", { password });
                setPassword("");
                await load();
              } catch (error) {
                setError((error as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            <label className="field-label">
              <LockKeyhole size={16} />
              Link password
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>
            <button className="button primary" disabled={busy}>
              Unlock
            </button>
          </form>
        ) : info?.type === "file" ? (
          <button
            className="button primary"
            onClick={() => saveURL("/api" + scoped(base))}
          >
            <Download size={16} />
            Download file
          </button>
        ) : (
          info && (
            <>
              <div className="library-toolbar">
                <button
                  className="icon-button"
                  aria-label="Parent shared folder"
                  disabled={!path}
                  onClick={() => {
                    setPath(path.split("/").slice(0, -1).join("/"));
                    setOffset(0);
                  }}
                >
                  <ArrowLeft size={18} />
                </button>
                <span>/{path}</span>
              </div>
              {listing.items.map((item) => (
                <button
                  className="public-file-row"
                  key={item.path}
                  onClick={() =>
                    item.type === "folder"
                      ? (setPath(item.path), setOffset(0))
                      : saveURL(
                          "/api" +
                            scoped(
                              base +
                                "?" +
                                new URLSearchParams({ path: item.path }),
                            ),
                        )
                  }
                >
                  {item.type === "folder" ? (
                    <Folder size={19} />
                  ) : (
                    <Download size={19} />
                  )}
                  <span>{item.name}</span>
                  <small>{bytes(item.size)}</small>
                </button>
              ))}
              {listing.total === 0 && <p className="muted">Empty folder</p>}
              {listing.total > 60 && (
                <div className="pagination">
                  <button
                    disabled={!offset}
                    onClick={() => setOffset(offset - 60)}
                  >
                    Previous
                  </button>
                  <span>
                    {offset + 1}–{Math.min(offset + 60, listing.total)}
                  </span>
                  <button
                    disabled={offset + 60 >= listing.total}
                    onClick={() => setOffset(offset + 60)}
                  >
                    Next
                  </button>
                </div>
              )}
            </>
          )
        )}
        {info?.expires_at && (
          <p className="muted share-expiry">
            Expires {new Date(info.expires_at * 1000).toLocaleString()}
          </p>
        )}
      </section>
    </main>
  );
}
