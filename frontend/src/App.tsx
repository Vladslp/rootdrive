import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  ArrowDown,
  ArrowUp,
  Check,
  CheckSquare,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Download,
  FolderInput,
  FolderPlus,
  HardDrive,
  History,
  Info,
  LayoutGrid,
  Link,
  List,
  Loader2,
  LogOut,
  Menu,
  Moon,
  MoreHorizontal,
  Pencil,
  Plus,
  Search,
  Settings,
  ShieldCheck,
  Star,
  Sun,
  Tag as TagIcon,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import {
  api,
  bytes,
  date,
  fileURL,
  saveURL,
  setCSRF,
  type Account,
  type Entry,
  type Listing,
  type Shared,
  type Stats,
  type Tag,
} from "./services/api";
import { Art, kindOf } from "./components/Art";
import { canEdit, editorKind } from "./services/editor";
import { StorageArtwork } from "./components/StorageArtwork";
import { FileArtwork } from "./components/FileArtwork";
import { Dialog } from "./components/Dialog";
import {
  MoveDialog,
  NameDialog,
  PreviewDialog,
  PropertiesDialog,
  ShareDialog,
  TagsDialog,
  VersionsDialog,
  type Modal,
} from "./components/FileDialogs";
import { UsersSettings } from "./components/UsersSettings";
import { UploadLimitSettings } from "./components/UploadLimitSettings";
import { UploadQueue } from "./components/UploadQueue";
import { droppedFiles, useUploads } from "./hooks/useUploads";

const EditorDialog = lazy(() => import("./components/EditorDialog"));

type View =
  | "files"
  | "favorites"
  | "tag"
  | "shares"
  | "trash"
  | "storage"
  | "settings";
type Theme = "light" | "dark";
const pageSize = 60;

function readPreference(name: string, fallback: string) {
  try {
    return localStorage.getItem(name) || fallback;
  } catch {
    return fallback;
  }
}
function writePreference(name: string, value: string) {
  try {
    localStorage.setItem(name, value);
  } catch {}
}

export default function App() {
  const [account, setAccount] = useState<Account | null>(null);
  const [accountError, setAccountError] = useState("");
  const [view, setView] = useState<View>("files");
  const [path, setPath] = useState("");
  const [activeTag, setActiveTag] = useState("");
  const [tags, setTags] = useState<Tag[]>([]);
  const [tagManager, setTagManager] = useState(false);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [recursive, setRecursive] = useState(false);
  const [sort, setSort] = useState("name");
  const [direction, setDirection] = useState("asc");
  const [offset, setOffset] = useState(0);
  const [listing, setListing] = useState<Listing>({ items: [], total: 0 });
  const [shares, setShares] = useState<{ items: Shared[]; total: number }>({
    items: [],
    total: 0,
  });
  const [stats, setStats] = useState<Stats | null>(null);
  const [statsError, setStatsError] = useState("");
  const [revision, setRevision] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selection, setSelection] = useState<string[]>([]);
  const [layout, setLayout] = useState(
    readPreference("rootdrive-layout", "grid"),
  );
  const [theme, setTheme] = useState<Theme>(
    document.documentElement.dataset.theme === "dark" ? "dark" : "light",
  );
  const [sidebar, setSidebar] = useState(false);
  const [modal, setModal] = useState<Modal | null>(null);
  const [context, setContext] = useState<{
    entry: Entry;
    x: number;
    y: number;
  } | null>(null);
  const [toasts, setToasts] = useState<{ id: number; text: string }[]>([]);
  const [dragging, setDragging] = useState(false);
  const dragDepth = useRef(0);
  const filesInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const replacePath = useRef<string | undefined>(undefined);
  const mainSearch = useRef<HTMLInputElement>(null);
  const ready = Boolean(account && (!account.auth_enabled || account.user));
  const fileView = ["files", "favorites", "tag"].includes(view);
  const selected = listing.items.filter((item) =>
    selection.includes(item.path),
  );
  const refresh = useCallback(() => setRevision((value) => value + 1), []);
  const notify = useCallback((text: string) => {
    const id = Date.now() + Math.random();
    setToasts((current) => [...current.slice(-2), { id, text }]);
    window.setTimeout(
      () => setToasts((current) => current.filter((item) => item.id !== id)),
      5500,
    );
  }, []);
  const queue = useUploads(ready, refresh);
  const loadAccount = useCallback(async () => {
    try {
      const value = await api<Account>("/auth/me");
      setCSRF(value.csrf_token);
      setAccount(value);
      setAccountError("");
    } catch (error) {
      setAccountError((error as Error).message);
    }
  }, []);
  const loadTags = useCallback(async () => {
    const result = await api<{ items: Tag[] }>("/tags");
    setTags(result.items);
  }, []);
  useEffect(() => {
    void loadAccount();
    const invalid = () => void loadAccount();
    window.addEventListener("rootdrive:unauthorized", invalid);
    return () => window.removeEventListener("rootdrive:unauthorized", invalid);
  }, [loadAccount]);
  useEffect(() => {
    if (ready) void loadTags().catch((error) => notify(error.message));
  }, [ready, loadTags, notify]);
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(query);
      setOffset(0);
    }, 220);
    return () => clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    writePreference("rootdrive-theme", theme);
    document
      .querySelector("meta[name=theme-color]")
      ?.setAttribute("content", theme === "dark" ? "#101319" : "#f7f8fb");
  }, [theme]);
  useEffect(() => {
    writePreference("rootdrive-layout", layout);
  }, [layout]);
  useEffect(() => {
    if (!ready) return;
    let active = true;
    api<Stats>("/storage/stats")
      .then((result) => {
        if (active) {
          setStats(result);
          setStatsError("");
        }
      })
      .catch((error) => {
        if (active) setStatsError(error.message);
      });
    return () => {
      active = false;
    };
  }, [ready, revision, view === "storage"]);
  useEffect(() => {
    if (!ready || (!fileView && view !== "trash" && view !== "shares")) {
      setLoading(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError("");
    setSelection([]);
    const params = new URLSearchParams({
      path,
      q: search,
      recursive: String(recursive),
      sort,
      direction,
      offset: String(offset),
      limit: String(pageSize),
    });
    if (view === "favorites") params.set("favorite", "true");
    if (view === "tag") params.set("tag", activeTag);
    const endpoint =
      view === "trash"
        ? "/trash"
        : view === "shares"
          ? "/shares"
          : view === "files"
            ? "/files"
            : "/collection";
    api<Listing & { items: Shared[] }>(endpoint + "?" + params)
      .then((result) => {
        if (active) {
          if (view === "shares") setShares(result);
          else setListing(result);
          if (!result.items.length && offset && result.total <= offset)
            setOffset(Math.max(0, offset - pageSize));
        }
      })
      .catch((error) => {
        if (active) setError(error.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [
    ready,
    view,
    path,
    search,
    recursive,
    sort,
    direction,
    offset,
    activeTag,
    revision,
  ]);
  useEffect(() => {
    folderInput.current?.setAttribute("webkitdirectory", "");
  }, [ready]);
  useEffect(() => {
    if (!context) return;
    const close = () => setContext(null);
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    window.addEventListener("click", close);
    window.addEventListener("resize", close);
    window.addEventListener("scroll", close, true);
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("click", close);
      window.removeEventListener("resize", close);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("keydown", key);
    };
  }, [context]);
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (
        modal ||
        tagManager ||
        (event.target as HTMLElement)?.closest(
          "input,textarea,select,[contenteditable]",
        )
      )
        return;
      if (
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === "a" &&
        fileView
      ) {
        event.preventDefault();
        setSelection(listing.items.map((item) => item.path));
      }
      if (
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === "k" &&
        fileView
      ) {
        event.preventDefault();
        mainSearch.current?.focus();
      }
      if (event.key === "Escape") {
        setSelection([]);
        setSidebar(false);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [modal, tagManager, fileView, listing.items]);
  function navigate(next: View, destination = "", tag = "") {
    window.scrollTo({ top: 0, behavior: "instant" });
    setView(next);
    setPath(destination);
    setActiveTag(tag);
    setOffset(0);
    setQuery("");
    setSearch("");
    setSelection([]);
    setSidebar(false);
    setContext(null);
  }
  function done(message = "Saved") {
    setModal(null);
    setSelection([]);
    refresh();
    notify(message);
  }
  async function perform(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    try {
      await action();
      done(message);
    } catch (error) {
      notify((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function open(entry: Entry) {
    if (entry.type === "folder") navigate("files", entry.path);
    else
      setModal({
        action: ["text", "document"].includes(editorKind(entry) || "")
          ? "edit"
          : "preview",
        entries: [entry],
      });
  }
  async function download(entries: Entry[]) {
    if (entries.length === 1 && entries[0].type === "file") {
      saveURL(fileURL(entries[0]));
      return;
    }
    setBusy(true);
    notify("Preparing ZIP…");
    try {
      const result = await api<{ url: string }>("/files/archive", "POST", {
        paths: entries.map((item) => item.path),
      });
      saveURL(result.url);
    } catch (error) {
      notify((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function favorite(entry: Entry) {
    try {
      await api("/favorites", "POST", {
        paths: [entry.path],
        favorite: !entry.favorite,
      });
      refresh();
    } catch (error) {
      notify((error as Error).message);
    }
  }
  function chooseUpload(folder = false, replacement?: string) {
    replacePath.current = replacement;
    if (folder) folderInput.current?.click();
    else filesInput.current?.click();
  }
  function chooseAction(action: Modal["action"], entries: Entry[]) {
    setContext(null);
    setModal({ action, entries });
  }
  const title =
    view === "tag"
      ? tags.find((tag) => tag.id === activeTag)?.name || "Tag"
      : (
          {
            files: "My files",
            favorites: "Favorites",
            shares: "Shared links",
            trash: "Trash",
            storage: "Storage",
            settings: "Settings",
          } as Record<string, string>
        )[view];
  if (!account)
    return (
      <div className="connection-screen">
        <img src="/assets/app-icon.png?v=flat-roots-2" alt="RootDrive" />
        <h1>RootDrive</h1>
        {accountError ? (
          <>
            <p className="error-text">{accountError}</p>
            <button className="button primary" onClick={loadAccount}>
              Try again
            </button>
          </>
        ) : (
          <Loader2 className="spin" />
        )}
      </div>
    );
  if (account.auth_enabled && !account.user)
    return <Login connected={loadAccount} theme={theme} setTheme={setTheme} />;
  const nav = (target: View, label: string, icon: ReactNode) => (
    <button
      key={target}
      className={"nav-link " + (view === target ? "active" : "")}
      onClick={() => navigate(target)}
    >
      {icon}
      <span>{label}</span>
      {view === target && <i />}
    </button>
  );
  const contextEntry = context?.entry;
  return (
    <div className="app-shell">
      <aside className={"sidebar " + (sidebar ? "sidebar-open" : "")}>
        <button
          className="brand"
          onClick={() => navigate("files")}
          aria-label="RootDrive home"
        >
          <img
            className="brand-logo"
            src="/assets/app-icon.png?v=flat-roots-2"
            alt=""
          />
          <span>
            RootDrive<span className="brand-dot">.</span>
          </span>
        </button>
        <button
          className="button primary sidebar-upload"
          onClick={() => chooseUpload()}
        >
          <Plus size={20} />
          Upload files
        </button>
        <nav aria-label="Main navigation">
          {nav("files", "My files", <HardDrive size={19} />)}
          {nav("favorites", "Favorites", <Star size={19} />)}
          {account.shares_enabled &&
            nav("shares", "Shared links", <Link size={19} />)}
          {nav("trash", "Trash", <Trash2 size={19} />)}
        </nav>
        <div className="sidebar-tags">
          <div className="sidebar-label">
            <span>Tags</span>
            <button
              className="icon-button"
              aria-label="Manage tags"
              onClick={() => {
                setTagManager(true);
                setSidebar(false);
              }}
            >
              <Plus size={15} />
            </button>
          </div>
          {tags.slice(0, 12).map((tag) => (
            <button
              key={tag.id}
              className={
                "nav-link tag-link " +
                (view === "tag" && activeTag === tag.id ? "active" : "")
              }
              onClick={() => navigate("tag", "", tag.id)}
            >
              <i className={"tag-dot " + tag.color} />
              <span>{tag.name}</span>
            </button>
          ))}
          {!tags.length && (
            <button
              className="add-first-tag"
              onClick={() => setTagManager(true)}
            >
              <TagIcon size={15} />
              Create tag
            </button>
          )}
          {tags.length > 12 && (
            <button className="text-button" onClick={() => setTagManager(true)}>
              Manage all tags
            </button>
          )}
        </div>
        <div className="sidebar-bottom">
          {nav("storage", "Storage", <HardDrive size={19} />)}
          {stats && (
            <button
              className="sidebar-storage"
              onClick={() => navigate("storage")}
            >
              <div className="disk-meter">
                <i style={{ width: stats.disk_percent + "%" }} />
              </div>
              <span>
                <strong>{bytes(stats.disk_free)}</strong> free of{" "}
                {bytes(stats.disk_total)}
              </span>
            </button>
          )}
          {nav("settings", "Settings", <Settings size={19} />)}
          <div className="sidebar-version">
            <span className="status-dot" />
            RootDrive <span>MVP 1.0.0</span>
          </div>
        </div>
      </aside>
      {sidebar && (
        <button
          className="sidebar-scrim"
          aria-label="Close navigation"
          onClick={() => setSidebar(false)}
        />
      )}
      <main
        className={"main " + (dragging ? "is-dragging" : "")}
        onDragEnter={(event) => {
          if (view === "files" && event.dataTransfer.types.includes("Files")) {
            event.preventDefault();
            dragDepth.current++;
            setDragging(true);
          }
        }}
        onDragOver={(event) => {
          if (view === "files" && event.dataTransfer.types.includes("Files")) {
            event.preventDefault();
            event.dataTransfer.dropEffect = "copy";
          }
        }}
        onDragLeave={(event) => {
          if (view === "files") {
            event.preventDefault();
            dragDepth.current--;
            if (dragDepth.current <= 0) setDragging(false);
          }
        }}
        onDrop={async (event) => {
          event.preventDefault();
          dragDepth.current = 0;
          setDragging(false);
          if (view !== "files") return;
          try {
            const sources = await droppedFiles(event.dataTransfer);
            if (sources.length) queue.add(sources, path);
            else notify("No files found. Empty folders are not uploaded.");
          } catch (error) {
            notify((error as Error).message);
          }
        }}
      >
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="icon-button mobile-menu"
              aria-label="Open navigation"
              onClick={() => setSidebar(true)}
            >
              <Menu size={22} />
            </button>
          </div>
          <div className="topbar-right">
            <button
              className="icon-button theme-toggle"
              aria-label={
                "Switch to " + (theme === "light" ? "dark" : "light") + " theme"
              }
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            >
              {theme === "light" ? <Moon size={19} /> : <Sun size={19} />}
            </button>
            {account.user && (
              <button
                className="account-avatar"
                aria-label={"Settings for " + account.user.username}
                onClick={() => navigate("settings")}
              >
                {account.user.username[0].toUpperCase()}
              </button>
            )}
            <span className="connection-state">
              <i />
              Running
            </span>
          </div>
        </header>
        <div className="page-content" key={`${view}:${path}:${activeTag}`}>
          <div className="page-heading">
            <div>
              <span className="eyebrow">ROOTDRIVE</span>
              <h1>
                {view === "files" && path ? path.split("/").pop() : title}
              </h1>
            </div>
            {view === "files" && (
              <div className="heading-actions">
                <button
                  className="button secondary"
                  aria-label="New folder"
                  onClick={() => chooseAction("newfolder", [])}
                >
                  <FolderPlus size={17} />
                  <span>New folder</span>
                </button>
                <button
                  className="button primary"
                  onClick={() => chooseUpload()}
                >
                  <Upload size={17} />
                  Upload
                </button>
              </div>
            )}
            {view === "storage" && (
              <button className="button secondary" onClick={refresh}>
                <History size={16} />
                Refresh
              </button>
            )}
            {view === "settings" && account.user && (
              <button
                className="button secondary"
                onClick={() =>
                  perform(async () => {
                    await api("/auth/logout", "POST");
                    await loadAccount();
                  }, "Signed out")
                }
              >
                <LogOut size={16} />
                Sign out
              </button>
            )}
          </div>
          {view === "files" && (
            <section className="dropzone" aria-label="Upload drop area">
              <div className="dropzone-symbol">
                <Upload size={24} strokeWidth={1.6} />
                <span>+</span>
              </div>
              <div>
                <strong>Drag & drop files</strong>
                <p>
                  or{" "}
                  <button onClick={() => chooseUpload()}>browse files</button> ·{" "}
                  <button onClick={() => chooseUpload(true)}>
                    upload folder
                  </button>
                </p>
              </div>
              <span className="dropzone-limit">
                Up to {bytes(account.max_upload_size_mb * 1024 * 1024)} per file
              </span>
            </section>
          )}
          {fileView && (
            <>
              <section className="file-toolbar">
                <div className="breadcrumbs" aria-label="Breadcrumbs">
                  <button
                    onClick={() => navigate("files")}
                    aria-label="My files"
                  >
                    <HardDrive size={17} />
                    {!path && view === "files" && <span>All files</span>}
                  </button>
                  {view === "files" &&
                    path
                      .split("/")
                      .filter(Boolean)
                      .map((part, index, parts) => (
                        <span key={index}>
                          <ChevronRight size={13} />
                          <button
                            onClick={() =>
                              navigate(
                                "files",
                                parts.slice(0, index + 1).join("/"),
                              )
                            }
                          >
                            {part}
                          </button>
                        </span>
                      ))}
                  {view !== "files" && (
                    <span>
                      <ChevronRight size={13} />
                      {title}
                    </span>
                  )}
                </div>
                <div className="search-field">
                  <Search size={17} />
                  <input
                    ref={mainSearch}
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="Search files"
                    aria-label="Search files"
                  />
                  {query && (
                    <button
                      className="icon-button"
                      aria-label="Clear search"
                      onClick={() => setQuery("")}
                    >
                      <X size={14} />
                    </button>
                  )}
                </div>
                <div className="view-controls">
                  <select
                    aria-label="Sort files"
                    value={sort}
                    onChange={(event) => {
                      setSort(event.target.value);
                      setOffset(0);
                    }}
                  >
                    <option value="name">Name</option>
                    <option value="modified">Modified</option>
                    <option value="size">Size</option>
                    <option value="type">Type</option>
                  </select>
                  <button
                    className="icon-button"
                    aria-label={
                      direction === "asc" ? "Sort descending" : "Sort ascending"
                    }
                    onClick={() =>
                      setDirection(direction === "asc" ? "desc" : "asc")
                    }
                  >
                    {direction === "asc" ? (
                      <ArrowUp size={16} />
                    ) : (
                      <ArrowDown size={16} />
                    )}
                  </button>
                  <div className="layout-toggle">
                    <button
                      className={layout === "grid" ? "active" : ""}
                      aria-label="Grid view"
                      onClick={() => setLayout("grid")}
                    >
                      <LayoutGrid size={17} />
                    </button>
                    <button
                      className={layout === "list" ? "active" : ""}
                      aria-label="List view"
                      onClick={() => setLayout("list")}
                    >
                      <List size={18} />
                    </button>
                  </div>
                </div>
              </section>
              {query && view === "files" && (
                <label className="recursive-toggle">
                  <input
                    type="checkbox"
                    checked={recursive}
                    onChange={(e) => {
                      setRecursive(e.target.checked);
                      setOffset(0);
                    }}
                  />
                  Include subfolders
                </label>
              )}
              <div className="listing-caption">
                <span>
                  {search ? "Results" : "Files"}
                  <small>{listing.total}</small>
                </span>
                <button
                  className="text-button"
                  disabled={!listing.items.length}
                  onClick={() =>
                    setSelection(
                      selection.length === listing.items.length
                        ? []
                        : listing.items.map((item) => item.path),
                    )
                  }
                >
                  <CheckSquare size={14} />
                  {selection.length === listing.items.length &&
                  listing.items.length
                    ? "Deselect page"
                    : "Select page"}
                </button>
              </div>
            </>
          )}
          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button onClick={refresh}>Try again</button>
            </div>
          )}
          {(fileView || view === "trash") &&
            (loading ? (
              <div className="loading-area">
                <Loader2 className="spin" size={26} />
              </div>
            ) : !error && !listing.items.length ? (
              <div className="empty-state">
                <Art kind={view === "trash" ? "folder" : "drive"} />
                <h2>
                  {search
                    ? "No matches"
                    : view === "trash"
                      ? "Trash is empty"
                      : view === "favorites"
                        ? "No favorites yet"
                        : view === "tag"
                          ? "No files with this tag"
                          : "This folder is empty"}
                </h2>
                {view === "files" && !search && (
                  <button
                    className="button secondary"
                    onClick={() => chooseUpload()}
                  >
                    <Upload size={16} />
                    Upload files
                  </button>
                )}
              </div>
            ) : (
              !error && (
                <div
                  className={
                    "file-collection " +
                    layout +
                    (view === "trash" ? " trash-collection" : "")
                  }
                >
                  {layout === "list" && (
                    <div className="list-head">
                      <span>Name</span>
                      <span>Size</span>
                      <span>Modified</span>
                      <span />
                    </div>
                  )}
                  {listing.items.map((entry, index) => (
                    <article
                      key={entry.id || entry.path}
                      style={{
                        animationDelay: Math.min(index, 10) * 24 + "ms",
                      }}
                      className={
                        "file-card " +
                        (entry.type === "folder" ? "folder-card " : "") +
                        (selection.includes(entry.path) ? "selected" : "")
                      }
                      onContextMenu={(event) => {
                        if (view === "trash") return;
                        event.preventDefault();
                        setContext({
                          entry,
                          x: Math.min(event.clientX, window.innerWidth - 240),
                          y: Math.max(
                            8,
                            Math.min(event.clientY, window.innerHeight - 470),
                          ),
                        });
                      }}
                    >
                      <div className="card-art">
                        <button
                          className="card-open"
                          aria-label={"Open " + entry.name}
                          onClick={() =>
                            view === "trash"
                              ? chooseAction("properties", [entry])
                              : open(entry)
                          }
                        >
                          <FileArtwork
                            entry={entry}
                            disabled={view === "trash"}
                          />
                        </button>
                        {view !== "trash" && (
                          <label
                            className={
                              "selection-check " +
                              (selection.includes(entry.path) ? "checked" : "")
                            }
                          >
                            <input
                              type="checkbox"
                              checked={selection.includes(entry.path)}
                              aria-label={"Select " + entry.name}
                              onChange={(event) =>
                                setSelection((current) =>
                                  event.target.checked
                                    ? [...current, entry.path]
                                    : current.filter(
                                        (item) => item !== entry.path,
                                      ),
                                )
                              }
                            />
                            <Check size={13} />
                          </label>
                        )}
                        {view !== "trash" && (
                          <button
                            className={
                              "favorite-toggle " +
                              (entry.favorite ? "is-favorite" : "")
                            }
                            aria-label={
                              (entry.favorite ? "Unfavorite " : "Favorite ") +
                              entry.name
                            }
                            onClick={() => favorite(entry)}
                          >
                            <Star
                              size={16}
                              fill={entry.favorite ? "currentColor" : "none"}
                            />
                          </button>
                        )}
                        <button
                          className="card-more icon-button"
                          aria-label={"Actions for " + entry.name}
                          onClick={(event) => {
                            event.stopPropagation();
                            if (view === "trash") {
                              chooseAction("properties", [entry]);
                              return;
                            }
                            const rect =
                              event.currentTarget.getBoundingClientRect();
                            setContext({
                              entry,
                              x: Math.max(
                                8,
                                Math.min(
                                  rect.right - 220,
                                  window.innerWidth - 240,
                                ),
                              ),
                              y: Math.max(
                                8,
                                Math.min(
                                  rect.bottom + 6,
                                  window.innerHeight - 470,
                                ),
                              ),
                            });
                          }}
                        >
                          <MoreHorizontal size={19} />
                        </button>
                      </div>
                      <div className="card-info">
                        <button
                          className="file-name"
                          title={entry.name}
                          onClick={() =>
                            view === "trash"
                              ? chooseAction("properties", [entry])
                              : open(entry)
                          }
                        >
                          {entry.name}
                        </button>
                        <div className="card-meta">
                          <span>
                            {entry.type === "folder"
                              ? "Folder"
                              : bytes(entry.size)}
                          </span>
                          <time>{date(entry.modified)}</time>
                        </div>
                        {Boolean(entry.tags?.length) && (
                          <div className="file-tags">
                            {entry.tags?.slice(0, 3).map((tag) => (
                              <button
                                className={"tag-pill " + tag.color}
                                key={tag.id}
                                onClick={() => navigate("tag", "", tag.id)}
                              >
                                {tag.name}
                              </button>
                            ))}
                            {(entry.tags?.length || 0) > 3 && (
                              <span className="more-tags">
                                +{entry.tags!.length - 3}
                              </span>
                            )}
                          </div>
                        )}
                        {(view === "favorites" ||
                          view === "tag" ||
                          (recursive && search)) && (
                          <span className="entry-path">
                            /{entry.path.split("/").slice(0, -1).join("/")}
                          </span>
                        )}
                        {view === "trash" && (
                          <div className="trash-actions">
                            <button
                              className="text-button"
                              disabled={busy}
                              onClick={() =>
                                perform(
                                  () =>
                                    api("/trash/restore", "POST", {
                                      id: entry.id,
                                    }),
                                  "Restored",
                                )
                              }
                            >
                              <History size={14} />
                              Restore
                            </button>
                            <button
                              className="icon-button danger-text"
                              aria-label={"Permanently delete " + entry.name}
                              onClick={() => chooseAction("purge", [entry])}
                            >
                              <Trash2 size={16} />
                            </button>
                          </div>
                        )}
                      </div>
                      <span className="list-size">
                        {entry.type === "folder" ? "—" : bytes(entry.size)}
                      </span>
                      <span className="list-date">{date(entry.modified)}</span>
                    </article>
                  ))}
                </div>
              )
            ))}
          {fileView && selected.length > 0 && (
            <div className="selection-bar">
              <button
                className="icon-button"
                onClick={() => setSelection([])}
                aria-label="Clear selection"
              >
                <X size={17} />
              </button>
              <strong>{selected.length} selected</strong>
              <div />
              <button
                onClick={() => chooseAction("move", selected)}
                title="Move"
              >
                <FolderInput size={18} />
                <span>Move</span>
              </button>
              <button
                onClick={() => download(selected)}
                disabled={busy}
                title="Download ZIP"
              >
                <Download size={18} />
                <span>Download</span>
              </button>
              <button
                onClick={() => chooseAction("tags", selected)}
                title="Tags"
              >
                <TagIcon size={18} />
                <span>Tags</span>
              </button>
              <button
                className="danger-text"
                onClick={() => chooseAction("delete", selected)}
                title="Move to trash"
              >
                <Trash2 size={18} />
                <span>Trash</span>
              </button>
            </div>
          )}
          {view === "shares" &&
            !error &&
            (loading ? (
              <div className="loading-area">
                <Loader2 className="spin" />
              </div>
            ) : !shares.items.length ? (
              <div className="empty-state">
                <Link size={40} />
                <h2>No shared links</h2>
              </div>
            ) : (
              <div className="shared-list">
                {shares.items.map((share) => (
                  <div className="shared-row" key={share.id}>
                    <div className="shared-icon">
                      <Link size={20} />
                    </div>
                    <div>
                      <strong>{share.name}</strong>
                      <span>
                        Expires{" "}
                        {share.expires_at ? date(share.expires_at) : "never"}
                      </span>
                      <small>/{share.path}</small>
                    </div>
                    <button
                      className="button secondary"
                      disabled={busy}
                      onClick={() => {
                        if (window.confirm("Revoke this link?"))
                          void perform(
                            () => api("/shares/" + share.id, "DELETE"),
                            "Link revoked",
                          );
                      }}
                    >
                      Revoke
                    </button>
                  </div>
                ))}
              </div>
            ))}
          {["files", "favorites", "tag", "trash", "shares"].includes(view) &&
            (view === "shares" ? shares.total : listing.total) > pageSize && (
              <div className="pagination page-pagination">
                <button
                  disabled={!offset || loading}
                  onClick={() => setOffset(offset - pageSize)}
                >
                  <ChevronLeft size={16} />
                  Previous
                </button>
                <span>
                  {offset + 1}–
                  {Math.min(
                    offset + pageSize,
                    view === "shares" ? shares.total : listing.total,
                  )}{" "}
                  of {view === "shares" ? shares.total : listing.total}
                </span>
                <button
                  disabled={
                    offset + pageSize >=
                      (view === "shares" ? shares.total : listing.total) ||
                    loading
                  }
                  onClick={() => setOffset(offset + pageSize)}
                >
                  Next
                  <ChevronRight size={16} />
                </button>
              </div>
            )}
          {view === "storage" && (
            <Storage stats={stats} error={statsError} navigate={navigate} />
          )}
          {view === "settings" && (
            <div className="settings-stack">
              <section className="settings-section">
                <div className="section-heading">
                  <h3>Appearance</h3>
                </div>
                <div className="theme-options">
                  {(["light", "dark"] as Theme[]).map((value) => (
                    <button
                      key={value}
                      className={
                        "theme-card " +
                        value +
                        (theme === value ? " chosen" : "")
                      }
                      onClick={() => setTheme(value)}
                    >
                      <div className="theme-mini">
                        <i />
                        <div>
                          <span />
                          <span />
                          <span />
                        </div>
                      </div>
                      <span>
                        {value === "light" ? (
                          <Sun size={17} />
                        ) : (
                          <Moon size={17} />
                        )}
                        {value === "light" ? "Light" : "Dark"}
                        {theme === value && <Check size={17} />}
                      </span>
                    </button>
                  ))}
                </div>
              </section>
              <UploadLimitSettings
                account={account}
                saved={(limit) => {
                  setAccount((current) =>
                    current
                      ? { ...current, max_upload_size_mb: limit }
                      : current,
                  );
                  notify("Upload limit updated");
                }}
              />
              <UsersSettings account={account} notify={notify} />
              <section className="settings-section">
                <h3>Server</h3>
                <dl className="properties-list">
                  <div>
                    <dt>Version</dt>
                    <dd>MVP 1.0.0</dd>
                  </div>
                  <div>
                    <dt>Public links</dt>
                    <dd>{account.shares_enabled ? "Enabled" : "Disabled"}</dd>
                  </div>
                  <div>
                    <dt>Workspace</dt>
                    <dd>Shared</dd>
                  </div>
                </dl>
              </section>
            </div>
          )}
        </div>
        {dragging && (
          <div className="drop-overlay">
            <Upload size={48} />
            <h2>Drop files here</h2>
            <span>{path || "My files"}</span>
          </div>
        )}
      </main>
      <input
        type="file"
        hidden
        multiple
        ref={filesInput}
        onChange={(event) => {
          const files = [...(event.target.files || [])];
          if (files.length)
            queue.add(
              files.map((file) => ({ file, relative: file.name })),
              path,
              replacePath.current,
            );
          event.target.value = "";
          replacePath.current = undefined;
        }}
      />
      <input
        type="file"
        hidden
        multiple
        ref={folderInput}
        onChange={(event) => {
          const files = [...(event.target.files || [])];
          if (files.length)
            queue.add(
              files.map((file) => ({
                file,
                relative: file.webkitRelativePath || file.name,
              })),
              path,
            );
          event.target.value = "";
        }}
      />
      <UploadQueue queue={queue} notify={notify} />
      <div className="toast-stack" aria-live="polite">
        {toasts.map((toast) => (
          <div className="toast" key={toast.id}>
            <Info size={17} />
            <span>{toast.text}</span>
            <button
              aria-label="Dismiss notification"
              onClick={() =>
                setToasts((current) =>
                  current.filter((item) => item.id !== toast.id),
                )
              }
            >
              <X size={15} />
            </button>
          </div>
        ))}
      </div>
      {context && contextEntry && (
        <div
          role="menu"
          className="context-menu"
          style={{ left: context.x, top: context.y }}
          onClick={(event) => event.stopPropagation()}
        >
          <button
            role="menuitem"
            onClick={() => {
              setContext(null);
              open(contextEntry);
            }}
          >
            <HardDrive size={16} />
            Open
          </button>
          {canEdit(contextEntry) && (
            <button
              role="menuitem"
              onClick={() => chooseAction("edit", [contextEntry])}
            >
              <Pencil size={16} />
              Edit
            </button>
          )}
          <button
            role="menuitem"
            onClick={() => {
              setContext(null);
              void download([contextEntry]);
            }}
          >
            <Download size={16} />
            {contextEntry.type === "folder" ? "Download ZIP" : "Download"}
          </button>
          <button
            role="menuitem"
            onClick={() => {
              setContext(null);
              void favorite(contextEntry);
            }}
          >
            <Star size={16} />
            {contextEntry.favorite ? "Remove favorite" : "Add to favorites"}
          </button>
          <hr />
          <button
            role="menuitem"
            onClick={() => chooseAction("rename", [contextEntry])}
          >
            <Info size={16} />
            Rename
          </button>
          <button
            role="menuitem"
            onClick={() => chooseAction("move", [contextEntry])}
          >
            <FolderInput size={16} />
            Move
          </button>
          <button
            role="menuitem"
            onClick={() => chooseAction("tags", [contextEntry])}
          >
            <TagIcon size={16} />
            Tags & color
          </button>
          {contextEntry.type === "file" && (
            <button
              role="menuitem"
              onClick={() => chooseAction("versions", [contextEntry])}
            >
              <History size={16} />
              Version history
            </button>
          )}
          {contextEntry.type === "file" && account.shares_enabled && (
            <button
              role="menuitem"
              onClick={() => chooseAction("share", [contextEntry])}
            >
              <Link size={16} />
              Share link
            </button>
          )}
          <button
            role="menuitem"
            onClick={() => chooseAction("properties", [contextEntry])}
          >
            <CircleHelp size={16} />
            Properties
          </button>
          <hr />
          <button
            role="menuitem"
            className="danger-text"
            onClick={() => chooseAction("delete", [contextEntry])}
          >
            <Trash2 size={16} />
            Move to trash
          </button>
        </div>
      )}
      {modal?.action === "newfolder" && (
        <NameDialog
          path={path}
          close={() => setModal(null)}
          done={() => done("Folder created")}
        />
      )}
      {modal?.action === "rename" && (
        <NameDialog
          entry={modal.entries[0]}
          path={path}
          close={() => setModal(null)}
          done={() => done("Renamed")}
        />
      )}
      {modal?.action === "move" && (
        <MoveDialog
          entries={modal.entries}
          close={() => setModal(null)}
          done={() => done("Moved")}
        />
      )}
      {modal?.action === "tags" && (
        <TagsDialog
          entries={modal.entries}
          tags={tags}
          close={() => setModal(null)}
          done={() => done("Tags updated")}
          reloadTags={loadTags}
        />
      )}
      {tagManager && (
        <TagsDialog
          entries={[]}
          tags={tags}
          manager
          close={() => {
            setTagManager(false);
            refresh();
          }}
          done={() => setTagManager(false)}
          reloadTags={loadTags}
        />
      )}
      {modal?.action === "properties" && (
        <PropertiesDialog
          entry={modal.entries[0]}
          close={() => setModal(null)}
        />
      )}
      {modal?.action === "preview" && (
        <PreviewDialog
          entry={modal.entries[0]}
          close={() => setModal(null)}
          properties={() => setModal({ ...modal, action: "properties" })}
          edit={() => setModal({ ...modal, action: "edit" })}
        />
      )}
      {modal?.action === "edit" && (
        <Suspense
          fallback={
            <Dialog title={modal.entries[0].name} close={() => setModal(null)}>
              <div className="loading-area">
                <Loader2 className="spin" />
              </div>
            </Dialog>
          }
        >
          <EditorDialog
            entry={modal.entries[0]}
            close={() => setModal(null)}
            saved={() => {
              refresh();
              notify("Saved · previous version kept");
            }}
          />
        </Suspense>
      )}
      {modal?.action === "versions" && (
        <VersionsDialog
          entry={modal.entries[0]}
          close={() => setModal(null)}
          done={() => done("Version restored")}
          replace={() => {
            const file = modal.entries[0];
            setModal(null);
            chooseUpload(false, file.path);
          }}
        />
      )}
      {modal?.action === "share" && (
        <ShareDialog
          entry={modal.entries[0]}
          close={() => {
            setModal(null);
            refresh();
          }}
        />
      )}
      {(modal?.action === "delete" || modal?.action === "purge") && (
        <Dialog
          title={
            modal.action === "purge" ? "Delete permanently?" : "Move to trash?"
          }
          close={() => {
            if (!busy) setModal(null);
          }}
        >
          <p className="confirm-name">
            {modal.entries.length === 1
              ? modal.entries[0].name
              : modal.entries.length + " selected items"}
          </p>
          <p className="muted">
            {modal.action === "purge"
              ? "This also removes saved versions. This cannot be undone."
              : "You can restore these files from Trash."}
          </p>
          <div className="dialog-actions">
            <button
              className="button secondary"
              disabled={busy}
              onClick={() => setModal(null)}
            >
              Cancel
            </button>
            <button
              className="button danger"
              disabled={busy}
              onClick={() =>
                perform(
                  () =>
                    modal.action === "purge"
                      ? api("/trash", "DELETE", { id: modal.entries[0].id })
                      : api("/files/batch/trash", "POST", {
                          paths: modal.entries.map((item) => item.path),
                        }),
                  modal.action === "purge"
                    ? "Deleted permanently"
                    : "Moved to trash",
                )
              }
            >
              {busy ? (
                <Loader2 size={16} className="spin" />
              ) : (
                <Trash2 size={16} />
              )}
              {modal.action === "purge" ? "Delete forever" : "Move to trash"}
            </button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

function Storage({
  stats,
  error,
  navigate,
}: {
  stats: Stats | null;
  error: string;
  navigate: (view: View) => void;
}) {
  if (error)
    return (
      <div className="error-banner" role="alert">
        {error}
      </div>
    );
  if (!stats)
    return (
      <div className="loading-area">
        <Loader2 className="spin" />
      </div>
    );
  const temporary =
    stats.uploads_bytes + stats.cache_bytes + stats.exports_bytes;
  const parts = [
    {
      name: "RootDrive files",
      size: stats.stored_bytes,
      color: "storage-blue",
      detail:
        stats.file_count.toLocaleString("en") +
        (stats.file_count === 1 ? " file" : " files"),
      action: "files" as View,
    },
    {
      name: "Trash",
      size: stats.trash_bytes,
      color: "storage-rose",
      detail: "Deleted files",
      action: "trash" as View,
    },
    {
      name: "Versions",
      size: stats.versions_bytes,
      color: "storage-violet",
      detail: "Previous file versions",
    },
    {
      name: "Temporary",
      size: temporary,
      color: "storage-amber",
      detail: "Uploads, previews & ZIPs",
    },
    {
      name: "System",
      size: stats.system_bytes,
      color: "storage-slate",
      detail: "OS, apps & other files",
    },
    {
      name: "Free",
      size: stats.disk_free,
      color: "storage-free",
      detail: "Available space",
    },
  ];
  return (
    <div className="storage-page">
      <section className="storage-overview">
        <div className="storage-overview-top">
          <div>
            <span className="muted">Disk usage</span>
            <h2>
              {bytes(stats.disk_used)}
              <small> / {bytes(stats.disk_total)}</small>
            </h2>
          </div>
          <span className="disk-percentage">
            {stats.disk_percent}
            <small>%</small>
          </span>
        </div>
        <div
          className="storage-bar"
          aria-label={"Disk " + stats.disk_percent + "% used"}
        >
          {parts.map((part) => (
            <i
              key={part.name}
              className={part.color}
              style={{ width: (part.size / stats.disk_total) * 100 + "%" }}
              title={part.name + ": " + bytes(part.size)}
            />
          ))}
        </div>
        <div className="storage-legend">
          {parts.map((part) => (
            <span key={part.name}>
              <i className={part.color} />
              {part.name}
            </span>
          ))}
        </div>
      </section>
      <div className="storage-breakdown">
        {parts.map((part, index) => (
          <section
            className="storage-part"
            key={part.name}
            style={{ animationDelay: index * 45 + "ms" }}
          >
            <div className="storage-part-icon">
              <StorageArtwork index={index} />
            </div>
            <div>
              <h3>{part.name}</h3>
              <p>{part.detail}</p>
            </div>
            <strong>{bytes(part.size)}</strong>
            {part.action && (
              <button
                className="icon-button"
                aria-label={"Open " + part.name}
                onClick={() => navigate(part.action!)}
              >
                <ChevronRight size={18} />
              </button>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}

function Login({
  connected,
  theme,
  setTheme,
}: {
  connected: () => Promise<void>;
  theme: Theme;
  setTheme: (theme: Theme) => void;
}) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true);
    setError("");
    try {
      const result = await api<{ csrf_token: string }>("/auth/login", "POST", {
        username: data.get("username"),
        password: data.get("password"),
      });
      setCSRF(result.csrf_token);
      await connected();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-screen">
      <button
        className="icon-button login-theme"
        aria-label="Toggle theme"
        onClick={() => setTheme(theme === "light" ? "dark" : "light")}
      >
        {theme === "light" ? <Moon /> : <Sun />}
      </button>
      <form className="login-card" onSubmit={submit}>
        <img
          className="login-logo"
          src="/assets/app-icon.png?v=flat-roots-2"
          alt=""
        />
        <h1>RootDrive</h1>
        <label className="field-label">
          Username
          <input name="username" autoComplete="username" autoFocus required />
        </label>
        <label className="field-label">
          Password
          <input
            type="password"
            name="password"
            autoComplete="current-password"
            required
          />
        </label>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <button className="button primary full-width" disabled={busy}>
          {busy ? (
            <Loader2 className="spin" size={17} />
          ) : (
            <ShieldCheck size={17} />
          )}
          Sign in
        </button>
      </form>
    </div>
  );
}
