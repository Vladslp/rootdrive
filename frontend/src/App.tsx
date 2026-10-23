import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  ArrowDown,
  ArrowDownToLine,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  CloudUpload,
  Ellipsis,
  FolderClosed,
  FolderPlus,
  HardDrive,
  Image,
  LayoutGrid,
  Link2,
  List,
  Loader2,
  LogOut,
  Menu,
  MoveRight,
  Music2,
  Pencil,
  Search,
  Server,
  Settings,
  ShieldCheck,
  Trash2,
  Undo2,
  Video,
  X,
} from "lucide-react";
import {
  api,
  bytes,
  fileURL,
  setCSRF,
  upload,
  type Account,
  type Entry,
  type Listing,
  type Shared,
  type Stats,
} from "./services/api";
import { Art, kindOf } from "./components/Art";

type View = "files" | "shares" | "trash" | "storage" | "settings";
type Dialog = {
  kind: "folder" | "rename" | "delete" | "move" | "share" | "permanent";
  entry?: Entry;
};
const date = (value: number) =>
  new Date(value * 1000).toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
function Modal({
  title,
  children,
  close,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
  wide?: boolean;
}) {
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const focusable = () =>
      Array.from(
        panel.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input, select, a[href], iframe, [tabindex="0"]',
        ) || [],
      );
    const preferred = panel.current?.querySelector<HTMLInputElement>(
      "input:not([readonly])",
    );
    (preferred || focusable()[0])?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
      if (event.key === "Tab") {
        const nodes = focusable();
        const first = nodes[0];
        const last = nodes[nodes.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", key);
    const old = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", key);
      document.body.style.overflow = old;
      previous?.focus();
    };
  }, [close]);
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        ref={panel}
        className={"modal " + (wide ? "modal-wide" : "")}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-heading">
          <h2>{title}</h2>
          <button className="icon-button" onClick={close} aria-label="Close">
            <X size={20} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
export default function App() {
  const [account, setAccount] = useState<Account | null>(null);
  const [view, setView] = useState<View>("files");
  const [path, setPath] = useState("");
  const [listing, setListing] = useState<Listing>({ items: [], total: 0 });
  const [stats, setStats] = useState<Stats | null>(null);
  const [shares, setShares] = useState<Shared[]>([]);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [recursive, setRecursive] = useState(false);
  const [sort, setSort] = useState("name");
  const [direction, setDirection] = useState("asc");
  const [offset, setOffset] = useState(0);
  const [layout, setLayout] = useState<"grid" | "list">("grid");
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [sidebar, setSidebar] = useState(false);
  const [menu, setMenu] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const [value, setValue] = useState("");
  const [dialogError, setDialogError] = useState("");
  const [preview, setPreview] = useState<Entry | null>(null);
  const [movePath, setMovePath] = useState("");
  const [moveFolders, setMoveFolders] = useState<Entry[]>([]);
  const [shareLink, setShareLink] = useState("");
  const [progress, setProgress] = useState<{
    name: string;
    percent: number;
    index: number;
    total: number;
  } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [loginError, setLoginError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const requestId = useRef(0);
  const notify = (message: string) => {
    setToast(message);
  };
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(""), 4500);
    return () => clearTimeout(timer);
  }, [toast]);
  const loadAccount = useCallback(async () => {
    const data = await api<Account>("/auth/me");
    setAccount(data);
    setCSRF(data.csrf_token);
    return data;
  }, []);
  useEffect(() => {
    loadAccount().catch((e) => {
      setError(e.message);
      setLoading(false);
    });
    const unauthorized = () => {
      setAccount((a) => (a ? { ...a, user: null } : a));
    };
    window.addEventListener("rootdrive:unauthorized", unauthorized);
    return () =>
      window.removeEventListener("rootdrive:unauthorized", unauthorized);
  }, [loadAccount]);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search);
      setOffset(0);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);
  const refresh = useCallback(async () => {
    if (!account || (account.auth_enabled && !account.user)) return;
    const id = ++requestId.current;
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        path,
        q: query,
        recursive: String(recursive),
        sort,
        direction,
        offset: String(offset),
        limit: "80",
      });
      const [data, space] = await Promise.all([
        view === "trash"
          ? api<Listing>("/trash?offset=" + offset)
          : view === "shares"
            ? api<{ items: Shared[]; total: number }>(
                "/shares?offset=" + offset,
              )
            : api<Listing>("/files?" + params),
        api<Stats>("/storage/stats"),
      ]);
      if (id !== requestId.current) return;
      setStats(space);
      if (view === "shares") {
        setShares(data.items as Shared[]);
        setListing({ items: [], total: data.total });
      } else setListing(data as Listing);
    } catch (e) {
      if (id === requestId.current) setError((e as Error).message);
    } finally {
      if (id === requestId.current) setLoading(false);
    }
  }, [account, view, path, query, recursive, sort, direction, offset]);
  useEffect(() => {
    refresh();
  }, [refresh]);
  useEffect(() => {
    if (!menu) return;
    const close = () => setMenu(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [menu]);
  useEffect(() => {
    if (dialog?.kind === "move")
      api<Listing>(
        "/files?" + new URLSearchParams({ path: movePath, limit: "200" }),
      )
        .then((result) =>
          setMoveFolders(result.items.filter((item) => item.type === "folder")),
        )
        .catch((e) => setDialogError(e.message));
  }, [dialog, movePath]);
  const navigate = (next: string) => {
    setPath(next);
    setView("files");
    setSearch("");
    setQuery("");
    setOffset(0);
    setFilter("all");
    setSelected(null);
  };
  const changeView = (next: View) => {
    setView(next);
    setSidebar(false);
    setOffset(0);
    setSearch("");
    setSelected(null);
    setFilter("all");
  };
  const openDialog = (kind: Dialog["kind"], entry?: Entry) => {
    setMenu(null);
    setDialog({ kind, entry });
    setValue(
      kind === "rename" ? entry?.name || "" : kind === "share" ? "24" : "",
    );
    setDialogError("");
    setShareLink("");
    setMovePath("");
  };
  const closeDialog = useCallback(() => {
    setDialog(null);
    setDialogError("");
  }, []);
  const closePreview = useCallback(() => setPreview(null), []);
  const perform = async (event: FormEvent) => {
    event.preventDefault();
    if (!dialog) return;
    setBusy(true);
    setDialogError("");
    try {
      const entry = dialog.entry;
      if (dialog.kind === "folder")
        await api("/folders", "POST", { path, name: value });
      if (dialog.kind === "rename")
        await api("/files/rename", "PATCH", { path: entry?.path, name: value });
      if (dialog.kind === "delete")
        await api("/files", "DELETE", { path: entry?.path });
      if (dialog.kind === "move")
        await api("/files/move", "POST", {
          path: entry?.path,
          destination: movePath,
        });
      if (dialog.kind === "permanent")
        await api("/trash", "DELETE", { id: entry?.id });
      if (dialog.kind === "share") {
        const result = await api<{ url: string }>("/shares", "POST", {
          path: entry?.path,
          expires_hours: Number(value) || null,
        });
        setShareLink(window.location.origin + result.url);
        await refresh();
        return;
      }
      closeDialog();
      notify(
        dialog.kind === "delete"
          ? "Moved to trash"
          : dialog.kind === "folder"
            ? "Folder created"
            : "All done",
      );
      await refresh();
    } catch (e) {
      setDialogError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const doUpload = async (files: FileList | File[] | null) => {
    if (!files?.length || progress) return;
    const batch = Array.from(files);
    let successes = 0;
    for (let i = 0; i < batch.length; i++) {
      const file = batch[i];
      if (file.size > (account?.max_upload_size_mb || 2048) * 1024 * 1024) {
        notify(file.name + " exceeds the upload limit");
        continue;
      }
      setProgress({
        name: file.name,
        percent: 0,
        index: i + 1,
        total: batch.length,
      });
      try {
        await upload(file, path, (percent) =>
          setProgress({
            name: file.name,
            percent,
            index: i + 1,
            total: batch.length,
          }),
        );
        successes++;
      } catch (e) {
        notify(file.name + ": " + (e as Error).message);
      }
    }
    setProgress(null);
    if (input.current) input.current.value = "";
    if (successes === batch.length)
      notify(successes === 1 ? "File uploaded" : `${successes} files uploaded`);
    await refresh();
  };
  const openEntry = (entry: Entry) => {
    if (entry.type === "folder") navigate(entry.path);
    else if (
      /^(image\/(jpeg|png|webp|gif)|application\/pdf)$/.test(entry.mime || "")
    )
      setPreview(entry);
    else window.location.assign(fileURL(entry));
  };
  const restore = async (entry: Entry) => {
    try {
      await api("/trash/restore", "POST", { id: entry.id });
      notify(
        "Restored to " +
          (entry.path.includes("/")
            ? entry.path.split("/").slice(0, -1).join("/")
            : "My files"),
      );
      refresh();
    } catch (e) {
      notify((e as Error).message);
    }
  };
  const revoke = async (id: string) => {
    try {
      await api("/shares/" + id, "DELETE");
      notify("Link revoked");
      refresh();
    } catch (e) {
      notify((e as Error).message);
    }
  };
  const login = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true);
    setLoginError("");
    const data = new FormData(event.currentTarget);
    try {
      await api("/auth/login", "POST", {
        username: data.get("username"),
        password: data.get("password"),
      });
      await loadAccount();
    } catch (e) {
      setLoginError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const logout = async () => {
    try {
      await api("/auth/logout", "POST");
      await loadAccount();
    } catch (e) {
      notify((e as Error).message);
    }
  };
  if (account?.auth_enabled && !account.user)
    return (
      <main className="login-page">
        <div className="login-card">
          <div className="brand">
            <span className="brand-icon">
              <img src="/assets/app-icon.png" alt="" />
            </span>
            RootDrive<span className="brand-dot">.</span>
          </div>
          <Art kind="drive" className="login-art" />
          <h1>Welcome to your space.</h1>
          <p>Your files, right where you left them.</p>
          <form onSubmit={login}>
            <label>
              Username
              <input
                name="username"
                autoComplete="username"
                required
                autoFocus
              />
            </label>
            <label>
              Password
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                required
              />
            </label>
            {loginError && (
              <div className="error-text" role="alert">
                {loginError}
              </div>
            )}
            <button className="button primary" disabled={busy}>
              {busy ? (
                <Loader2 className="spin" size={18} />
              ) : (
                <ArrowRight size={18} />
              )}{" "}
              Sign in
            </button>
          </form>
          <span className="login-foot">
            <ShieldCheck size={14} /> One shared workspace. Hosted by you.
          </span>
        </div>
      </main>
    );
  const title = {
    files: "My files",
    shares: "Shared links",
    trash: "Trash",
    storage: "Storage",
    settings: "Settings",
  }[view];
  const entries = listing.items.filter(
    (entry) =>
      filter === "all" ||
      kindOf(entry) === filter ||
      (filter === "documents" &&
        ["pdf", "sheets", "slides", "code"].includes(kindOf(entry))),
  );
  const folders = entries.filter((entry) => entry.type === "folder");
  const documents = entries.filter((entry) => entry.type !== "folder");
  const canUpload = view === "files";
  const breadcrumbs = path ? path.split("/") : [];
  const menuActions = (entry: Entry) => (
    <div
      className="context-menu"
      onClick={(e) => e.stopPropagation()}
      role="menu"
    >
      <button
        role="menuitem"
        onClick={() => {
          setMenu(null);
          openEntry(entry);
        }}
      >
        <FolderClosed size={16} />
        {entry.type === "folder" ? "Open folder" : "Open file"}
      </button>
      {entry.type === "file" && (
        <a role="menuitem" href={fileURL(entry)} onClick={() => setMenu(null)}>
          <ArrowDownToLine size={16} />
          Download
        </a>
      )}
      <button role="menuitem" onClick={() => openDialog("rename", entry)}>
        <Pencil size={16} />
        Rename
      </button>
      <button role="menuitem" onClick={() => openDialog("move", entry)}>
        <MoveRight size={16} />
        Move to…
      </button>
      {account?.shares_enabled && entry.type === "file" && (
        <button role="menuitem" onClick={() => openDialog("share", entry)}>
          <Link2 size={16} />
          Share link
        </button>
      )}
      <hr />
      <button
        role="menuitem"
        className="danger-text"
        onClick={() => openDialog("delete", entry)}
      >
        <Trash2 size={16} />
        Move to trash
      </button>
    </div>
  );
  const entryCard = (entry: Entry) => (
    <div
      key={entry.path}
      className={
        "file-card " +
        (entry.type === "folder" ? "folder-card " : "") +
        (selected === entry.path ? "selected" : "")
      }
      onClick={() => setSelected(entry.path)}
      onDoubleClick={() => view === "files" && openEntry(entry)}
      onContextMenu={(e) => {
        if (view === "files") {
          e.preventDefault();
          setMenu(entry.path);
        }
      }}
    >
      <div className="card-art-wrap">
        <button
          className="card-open"
          onClick={() => view === "files" && openEntry(entry)}
          aria-label={"Open " + entry.name}
        >
          <Art kind={kindOf(entry)} />
        </button>
        {view === "files" && (
          <div className="card-menu">
            <button
              className="icon-button"
              aria-label={"Actions for " + entry.name}
              aria-expanded={menu === entry.path}
              onClick={(e) => {
                e.stopPropagation();
                setMenu(menu === entry.path ? null : entry.path);
              }}
            >
              <Ellipsis size={19} />
            </button>
            {menu === entry.path && menuActions(entry)}
          </div>
        )}
      </div>
      <div className="file-card-bottom">
        <button
          className="file-name"
          title={entry.name}
          onClick={() => view === "files" && openEntry(entry)}
        >
          {entry.name}
        </button>
        <div className="file-meta">
          <span>{entry.type === "folder" ? "Folder" : bytes(entry.size)}</span>
          <span>{date(entry.modified)}</span>
        </div>
        {query && <small className="result-path">{entry.path}</small>}
        {view === "trash" && (
          <div className="trash-actions">
            <button onClick={() => restore(entry)}>
              <Undo2 size={15} />
              Restore
            </button>
            <button
              className="danger-text"
              onClick={() => openDialog("permanent", entry)}
              aria-label={"Delete permanently " + entry.name}
            >
              <Trash2 size={15} />
            </button>
          </div>
        )}
      </div>
    </div>
  );
  return (
    <div
      className="app-shell"
      onDragOver={(e) => {
        e.preventDefault();
        if (canUpload && e.dataTransfer.types.includes("Files"))
          setDragging(true);
      }}
    >
      <input
        ref={input}
        type="file"
        multiple
        className="hidden"
        onChange={(e) => doUpload(e.target.files)}
      />
      {sidebar && (
        <div className="sidebar-scrim" onClick={() => setSidebar(false)} />
      )}
      <aside className={"sidebar " + (sidebar ? "sidebar-open" : "")}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            navigate("");
            setSidebar(false);
          }}
        >
          <span className="brand-icon">
            <img src="/assets/app-icon.png" alt="" />
          </span>
          RootDrive<span className="brand-dot">.</span>
        </a>
        <div className="workspace-label">PERSONAL WORKSPACE</div>
        <nav aria-label="Main navigation">
          <button
            className={view === "files" ? "active" : ""}
            onClick={() => {
              changeView("files");
              navigate("");
            }}
          >
            <FolderClosed size={19} />
            My files
            <ChevronRight className="nav-chevron" size={15} />
          </button>
          {account?.shares_enabled && (
            <button
              className={view === "shares" ? "active" : ""}
              onClick={() => changeView("shares")}
            >
              <Link2 size={19} />
              Shared links
            </button>
          )}
          <button
            className={view === "trash" ? "active" : ""}
            onClick={() => changeView("trash")}
          >
            <Trash2 size={19} />
            Trash
          </button>
        </nav>
        <div className="sidebar-divider" />
        <div className="workspace-label">YOUR SPACE</div>
        <nav>
          <button
            className={view === "storage" ? "active" : ""}
            onClick={() => changeView("storage")}
          >
            <HardDrive size={19} />
            Storage
          </button>
          <button
            className={view === "settings" ? "active" : ""}
            onClick={() => changeView("settings")}
          >
            <Settings size={19} />
            Settings
          </button>
        </nav>
        <div className="sidebar-bottom">
          <div className="storage-mini">
            <div className="storage-mini-label">
              <span>
                <HardDrive size={15} />
                Local storage
              </span>
              <span>{stats?.disk_percent || 0}%</span>
            </div>
            <div className="usage-track">
              <span style={{ width: (stats?.disk_percent || 0) + "%" }} />
            </div>
            <p>{bytes(stats?.disk_free || 0)} available</p>
            <button onClick={() => changeView("storage")}>
              View storage <ArrowRight size={14} />
            </button>
          </div>
          <div className="server-status">
            <span className="status-dot" />
            <div>
              <strong>Your personal cloud</strong>
              <span>Hosted by you. Always yours.</span>
            </div>
            <ShieldCheck size={18} />
          </div>
          {account?.user && (
            <button className="logout" onClick={logout}>
              <LogOut size={16} />
              Sign out · {account.user.username}
            </button>
          )}
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            aria-label="Open navigation"
            onClick={() => setSidebar(true)}
          >
            <Menu size={22} />
          </button>
          <div className="searchbox">
            <Search size={19} />
            <input
              aria-label="Search files"
              placeholder="Search your files…"
              value={search}
              onChange={(e) => {
                if (view !== "files") changeView("files");
                setSearch(e.target.value);
              }}
            />
            {search ? (
              <button aria-label="Clear search" onClick={() => setSearch("")}>
                <X size={16} />
              </button>
            ) : (
              <kbd>⌕</kbd>
            )}
          </div>
          <div className="topbar-right">
            <span className="connection">
              <span className="status-dot" />
              Local workspace
            </span>
            <button
              className="icon-button help-button"
              aria-label="About RootDrive"
              onClick={() => changeView("settings")}
            >
              <CircleHelp size={20} />
            </button>
            <button
              className="avatar"
              aria-label="Workspace settings"
              onClick={() => changeView("settings")}
            >
              {account?.user?.username.slice(0, 1).toUpperCase() || "R"}
            </button>
          </div>
        </header>
        <main className="content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">YOUR PERSONAL CLOUD</div>
              <h1>
                {title}
                <span className="heading-dot">.</span>
              </h1>
              <p>
                {view === "files"
                  ? "A home for everything that matters."
                  : view === "trash"
                    ? "A second chance for your files."
                    : view === "shares"
                      ? "A little sharing goes a long way."
                      : view === "storage"
                        ? "Know your space."
                        : "Make yourself at home."}
              </p>
            </div>
            {canUpload && (
              <div className="page-actions">
                <button
                  className="button secondary"
                  aria-label="New folder"
                  onClick={() => openDialog("folder")}
                >
                  <FolderPlus size={18} />
                  <span>New folder</span>
                </button>
                <button
                  className="button primary"
                  aria-label="Upload files"
                  disabled={!!progress}
                  onClick={() => input.current?.click()}
                >
                  <CloudUpload size={18} />
                  <span>Upload files</span>
                </button>
              </div>
            )}
          </div>
          {view === "files" && (
            <>
              <section className="welcome-banner">
                <div>
                  <span className="banner-label">
                    <span className="tiny-spark">✦</span> YOUR FILES, YOUR RULES
                  </span>
                  <h2>
                    A little space.
                    <br />
                    For everything.
                  </h2>
                  <p>All your files. One place. Entirely yours.</p>
                  <button onClick={() => input.current?.click()}>
                    Drop something good <ArrowRight size={16} />
                  </button>
                </div>
                <Art kind="cloud" className="banner-art" />
                <div className="banner-orbit orbit-one" />
                <div className="banner-orbit orbit-two" />
                <span className="banner-star star-one">✦</span>
                <span className="banner-star star-two">✧</span>
              </section>
              <section
                className="category-grid"
                aria-label="Filter by file type"
              >
                {[
                  { id: "images", label: "Photos", color: "green" },
                  { id: "documents", label: "Documents", color: "blue" },
                  { id: "videos", label: "Videos", color: "purple" },
                  { id: "audio", label: "Audio", color: "orange" },
                ].map((category) => (
                  <button
                    key={category.id}
                    className={
                      "category-card " +
                      category.color +
                      (filter === category.id ? " category-active" : "")
                    }
                    onClick={() => {
                      setFilter(filter === category.id ? "all" : category.id);
                    }}
                  >
                    <Art kind={category.id} />
                    <div>
                      <strong>{category.label}</strong>
                      <span>
                        {category.id === "audio"
                          ? "Find your rhythm"
                          : bytes(stats?.categories[category.id] || 0) +
                            " in your drive"}
                      </span>
                    </div>
                    <ChevronRight size={16} />
                  </button>
                ))}
              </section>
            </>
          )}
          {error && (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button
                onClick={() => {
                  loadAccount()
                    .then(refresh)
                    .catch((e) => setError(e.message));
                }}
              >
                Try again
              </button>
            </div>
          )}
          {(view === "files" || view === "trash") && (
            <section className="files-section">
              <div className="files-toolbar">
                <div className="breadcrumbs">
                  <button onClick={() => navigate("")}>
                    <FolderClosed size={17} />
                    {view === "trash" ? "Deleted files" : "My files"}
                  </button>
                  {view === "files" &&
                    breadcrumbs.map((part, index) => (
                      <span key={index}>
                        <ChevronRight size={15} />
                        <button
                          onClick={() =>
                            navigate(breadcrumbs.slice(0, index + 1).join("/"))
                          }
                        >
                          {part}
                        </button>
                      </span>
                    ))}
                  {filter !== "all" && (
                    <button
                      className="filter-pill"
                      onClick={() => setFilter("all")}
                    >
                      {filter}
                      <X size={12} />
                    </button>
                  )}
                </div>
                <div className="toolbar-options">
                  {view === "files" && query && (
                    <label className="recursive">
                      <input
                        type="checkbox"
                        checked={recursive}
                        onChange={(e) => setRecursive(e.target.checked)}
                      />
                      Subfolders
                    </label>
                  )}
                  {view === "files" && (
                    <>
                      <label className="sort-select">
                        <span className="sr-only">Sort files</span>
                        <select
                          value={sort}
                          onChange={(e) => {
                            setSort(e.target.value);
                            setOffset(0);
                          }}
                        >
                          <option value="name">Name</option>
                          <option value="modified">Date modified</option>
                          <option value="size">Size</option>
                          <option value="type">Type</option>
                        </select>
                        <ChevronDown size={14} />
                      </label>
                      <button
                        className="icon-button sort-direction"
                        aria-label="Reverse sort order"
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
                    </>
                  )}
                  <div className="view-toggle">
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
              </div>
              {loading ? (
                <div className="loading-state">
                  <Loader2 className="spin" size={25} />
                  <span>Getting your space ready…</span>
                </div>
              ) : entries.length === 0 ? (
                <div
                  className="empty-state"
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={(e) => {
                    e.preventDefault();
                    if (canUpload) doUpload(e.dataTransfer.files);
                  }}
                >
                  <Art
                    kind={
                      view === "trash"
                        ? "mint"
                        : query || filter !== "all"
                          ? "folder"
                          : "cloud"
                    }
                  />
                  <h3>
                    {view === "trash"
                      ? "Nothing to leave behind."
                      : query || filter !== "all"
                        ? "No files found."
                        : "Room for your next big thing."}
                  </h3>
                  <p>
                    {view === "trash"
                      ? "Deleted files will appear here."
                      : query || filter !== "all"
                        ? "Try another search or file type."
                        : "Drop files here, or make yourself a folder."}
                  </p>
                  {view === "files" && !query && filter === "all" && (
                    <button
                      className="text-button"
                      onClick={() => input.current?.click()}
                    >
                      Choose files <ArrowRight size={15} />
                    </button>
                  )}
                </div>
              ) : layout === "grid" ? (
                <>
                  {folders.length > 0 && (
                    <>
                      <div className="section-label">
                        Folders <span>{folders.length}</span>
                      </div>
                      <div className="file-grid folder-grid">
                        {folders.map(entryCard)}
                      </div>
                    </>
                  )}
                  {documents.length > 0 && (
                    <>
                      <div className="section-label">
                        {query
                          ? "Search results"
                          : view === "trash"
                            ? "Files in trash"
                            : "Files"}{" "}
                        <span>{documents.length}</span>
                      </div>
                      <div className="file-grid">
                        {documents.map(entryCard)}
                      </div>
                    </>
                  )}
                </>
              ) : (
                <div className="file-table" role="table" aria-label="Files">
                  <div className="table-head" role="row">
                    <span>Name</span>
                    <span>File size</span>
                    <span>Date modified</span>
                    <span />
                  </div>
                  {entries.map((entry) => (
                    <div
                      key={entry.path}
                      className={
                        "table-row " +
                        (selected === entry.path ? "selected" : "")
                      }
                      role="row"
                      onClick={() => setSelected(entry.path)}
                    >
                      <button
                        className="table-name"
                        onClick={() => view === "files" && openEntry(entry)}
                      >
                        <Art kind={kindOf(entry)} />
                        <span>
                          {entry.name}
                          {query && <small>{entry.path}</small>}
                        </span>
                      </button>
                      <span className="table-size">
                        {entry.type === "folder" ? "—" : bytes(entry.size)}
                      </span>
                      <span className="table-date">{date(entry.modified)}</span>
                      <div className="table-actions">
                        {view === "trash" ? (
                          <>
                            <button
                              className="icon-button"
                              aria-label={"Restore " + entry.name}
                              onClick={() => restore(entry)}
                            >
                              <Undo2 size={17} />
                            </button>
                            <button
                              className="icon-button danger-text"
                              aria-label={"Delete permanently " + entry.name}
                              onClick={() => openDialog("permanent", entry)}
                            >
                              <Trash2 size={16} />
                            </button>
                          </>
                        ) : (
                          <>
                            <button
                              className="icon-button"
                              aria-label={"Actions for " + entry.name}
                              onClick={(e) => {
                                e.stopPropagation();
                                setMenu(
                                  menu === entry.path ? null : entry.path,
                                );
                              }}
                            >
                              <Ellipsis size={19} />
                            </button>
                            {menu === entry.path && menuActions(entry)}
                          </>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <div className="files-footer">
                <span>
                  {listing.total} {listing.total === 1 ? "item" : "items"}
                  {filter !== "all" ? " · filtered on this page" : ""}
                </span>
                {listing.total > 80 && (
                  <div className="pagination">
                    <button
                      disabled={offset === 0}
                      onClick={() => setOffset(Math.max(0, offset - 80))}
                    >
                      <ArrowLeft size={15} />
                      Previous
                    </button>
                    <span>{Math.floor(offset / 80) + 1}</span>
                    <button
                      disabled={offset + 80 >= listing.total}
                      onClick={() => setOffset(offset + 80)}
                    >
                      Next
                      <ArrowRight size={15} />
                    </button>
                  </div>
                )}
                <span className="footer-security">
                  <ShieldCheck size={14} />
                  Safe in your own space
                </span>
              </div>
            </section>
          )}
          {view === "shares" && (
            <section className="panel">
              <div className="panel-title">
                <h2>Your shared links</h2>
                <Link2 size={21} />
              </div>
              <p className="muted">Anyone with a link can download its file.</p>
              {!shares.length && (
                <div className="empty-state">
                  <Art kind="folder" />
                  <h3>Good things are worth sharing.</h3>
                  <p>Create a link from a file’s action menu.</p>
                </div>
              )}
              {shares.map((share) => (
                <div className="share-row" key={share.id}>
                  <span className="share-icon">
                    <Link2 size={20} />
                  </span>
                  <div>
                    <strong>{share.name}</strong>
                    <p>
                      {share.expires_at
                        ? "Expires " + date(share.expires_at)
                        : "No expiration"}{" "}
                      · {share.path}
                    </p>
                  </div>
                  <button
                    className="button secondary"
                    onClick={() => revoke(share.id)}
                  >
                    Revoke
                  </button>
                </div>
              ))}
              {listing.total > 80 && (
                <div className="pagination">
                  <button
                    disabled={!offset}
                    onClick={() => setOffset(Math.max(0, offset - 80))}
                  >
                    Previous
                  </button>
                  <button
                    disabled={offset + 80 >= listing.total}
                    onClick={() => setOffset(offset + 80)}
                  >
                    Next
                  </button>
                </div>
              )}
            </section>
          )}
          {view === "storage" && stats && (
            <>
              <section className="storage-dashboard panel">
                <div>
                  <span className="eyebrow">ON YOUR DEVICE</span>
                  <h2>Your space, at a glance.</h2>
                  <p className="muted">
                    {stats.file_count} files · {bytes(stats.stored_bytes)} in
                    RootDrive
                  </p>
                  <div className="big-storage-number">
                    {bytes(stats.disk_free)}
                    <span>available</span>
                  </div>
                  <div className="usage-track big">
                    <span style={{ width: stats.disk_percent + "%" }} />
                  </div>
                  <div className="disk-labels">
                    <span>{bytes(stats.disk_used)} used on device</span>
                    <span>{bytes(stats.disk_total)} total</span>
                  </div>
                </div>
                <Art kind="drive" />
              </section>
              <div className="storage-categories">
                {Object.entries(stats.categories).map(([kind, amount]) => (
                  <div className="panel" key={kind}>
                    <Art kind={kind === "other" ? "archives" : kind} />
                    <strong>
                      {kind === "images"
                        ? "Photos"
                        : kind[0].toUpperCase() + kind.slice(1)}
                    </strong>
                    <span>{bytes(amount)}</span>
                  </div>
                ))}
              </div>
              <p className="storage-note">
                Device usage includes other applications and trash. RootDrive
                totals include active files only. Updates every 30 seconds.
              </p>
            </>
          )}
          {view === "settings" && (
            <section className="panel settings-panel">
              <div className="settings-brand">
                <span className="brand-icon">
                  <img src="/assets/app-icon.png" alt="RootDrive icon" />
                </span>
                <div>
                  <h2>RootDrive</h2>
                  <p>Your files. Your hardware. Your space.</p>
                </div>
                <span className="version">1.0.0</span>
              </div>
              <div className="setting-row">
                <div>
                  <strong>
                    <Server size={17} />
                    Workspace
                  </strong>
                  <p>One shared space for everyone on this server.</p>
                </div>
                <span className="badge">Self-hosted</span>
              </div>
              <div className="setting-row">
                <div>
                  <strong>
                    <ShieldCheck size={17} />
                    Authentication
                  </strong>
                  <p>
                    {account?.auth_enabled
                      ? "Sign-in required. Sessions stay in secure cookies."
                      : "Open workspace for your trusted local network."}
                  </p>
                </div>
                <span className="badge">
                  {account?.auth_enabled ? "Enabled" : "Disabled"}
                </span>
              </div>
              <div className="setting-row">
                <div>
                  <strong>
                    <Link2 size={17} />
                    Public links
                  </strong>
                  <p>
                    {account?.shares_enabled
                      ? "Anyone with a link can download a shared file."
                      : "File sharing is turned off on this server."}
                  </p>
                </div>
                <span className="badge">
                  {account?.shares_enabled ? "Enabled" : "Disabled"}
                </span>
              </div>
              <div className="setting-row">
                <div>
                  <strong>
                    <CloudUpload size={17} />
                    Upload limit
                  </strong>
                  <p>Multiple files, streamed to your device.</p>
                </div>
                <span className="badge">
                  {bytes((account?.max_upload_size_mb || 2048) * 1024 * 1024)} /
                  file
                </span>
              </div>
              <div className="settings-foot">
                <ShieldCheck size={18} />
                Configuration is managed by the server owner in .env.
              </div>
            </section>
          )}
          <footer className="page-footer">
            <span>Rooted in your hardware. Free in your hands.</span>
            <span>
              <span className="status-dot" />
              RootDrive
            </span>
          </footer>
        </main>
      </div>
      {dragging && (
        <div
          className="drop-overlay"
          onDragOver={(e) => e.preventDefault()}
          onDragLeave={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node))
              setDragging(false);
          }}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            doUpload(e.dataTransfer.files);
          }}
        >
          <div>
            <Art kind="cloud" />
            <h2>Make room for good things.</h2>
            <p>Drop your files to upload to {path || "My files"}</p>
          </div>
        </div>
      )}
      {progress && (
        <div className="upload-progress" role="status">
          <div>
            <span className="upload-icon">
              <CloudUpload size={21} />
            </span>
            <div>
              <strong>
                Uploading {progress.index} of {progress.total}
              </strong>
              <p>{progress.name}</p>
            </div>
            <span>{progress.percent}%</span>
          </div>
          <div className="usage-track">
            <span style={{ width: progress.percent + "%" }} />
          </div>
          <small>
            {progress.percent === 100
              ? "Saving to your drive…"
              : "Finding a home on your drive…"}
          </small>
        </div>
      )}
      {toast && (
        <div className="toast" role="status">
          <CheckCircle2 size={19} />
          <span>{toast}</span>
          <button
            aria-label="Dismiss notification"
            onClick={() => setToast("")}
          >
            <X size={16} />
          </button>
        </div>
      )}
      {dialog && (
        <Modal
          title={
            {
              folder: "A new folder",
              rename: "Rename",
              delete: "Move to trash?",
              move: "Move to…",
              share: "Share a little",
              permanent: "Delete forever?",
            }[dialog.kind]
          }
          close={closeDialog}
        >
          <form onSubmit={perform}>
            {["folder", "rename"].includes(dialog.kind) && (
              <>
                <Art
                  kind={
                    dialog.kind === "folder" ? "folder" : kindOf(dialog.entry!)
                  }
                  className="dialog-art"
                />
                <label className="field-label">
                  {dialog.kind === "folder" ? "Folder name" : "Name"}
                  <input
                    autoFocus
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    required
                    maxLength={240}
                    placeholder="Something wonderful"
                  />
                </label>
              </>
            )}
            {dialog.kind === "delete" && (
              <p className="dialog-copy">
                <strong>{dialog.entry?.name}</strong> will move to trash. You
                can bring it back anytime.
              </p>
            )}
            {dialog.kind === "permanent" && (
              <p className="dialog-copy">
                <strong>{dialog.entry?.name}</strong> will be permanently
                deleted. This cannot be undone.
              </p>
            )}
            {dialog.kind === "move" && (
              <>
                <div className="move-breadcrumb">
                  <button
                    type="button"
                    onClick={() =>
                      setMovePath(movePath.split("/").slice(0, -1).join("/"))
                    }
                    disabled={!movePath}
                  >
                    <ArrowLeft size={16} />
                  </button>
                  <span>{movePath || "My files"}</span>
                </div>
                <div className="move-folders">
                  {moveFolders
                    .filter(
                      (folder) =>
                        folder.path !== dialog.entry?.path &&
                        !folder.path.startsWith(dialog.entry?.path + "/"),
                    )
                    .map((folder) => (
                      <button
                        type="button"
                        key={folder.path}
                        onClick={() => setMovePath(folder.path)}
                      >
                        <Art kind={kindOf(folder)} />
                        <span>{folder.name}</span>
                        <ChevronRight size={16} />
                      </button>
                    ))}
                  {!moveFolders.length && (
                    <p className="muted">No subfolders here</p>
                  )}
                </div>
              </>
            )}
            {dialog.kind === "share" && (
              <>
                <p className="dialog-copy">
                  Anyone with this link can download{" "}
                  <strong>{dialog.entry?.name}</strong>.
                </p>
                {shareLink ? (
                  <div className="share-result">
                    <input
                      aria-label="Share URL"
                      value={shareLink}
                      readOnly
                      onFocus={(e) => e.target.select()}
                    />
                    <button
                      className="button primary"
                      type="button"
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(shareLink);
                          notify("Link copied");
                        } catch {
                          notify("Select and copy the link above");
                        }
                      }}
                    >
                      <Link2 size={16} />
                      Copy link
                    </button>
                  </div>
                ) : (
                  <label className="field-label">
                    Link expires
                    <select
                      value={value}
                      onChange={(e) => setValue(e.target.value)}
                    >
                      <option value="1">In 1 hour</option>
                      <option value="24">In 24 hours</option>
                      <option value="168">In 7 days</option>
                      <option value="0">Never</option>
                    </select>
                  </label>
                )}
              </>
            )}
            {dialogError && (
              <p className="error-text" role="alert">
                {dialogError}
              </p>
            )}
            <div className="dialog-actions">
              <button
                type="button"
                className="button secondary"
                onClick={closeDialog}
              >
                {shareLink ? "Done" : "Cancel"}
              </button>
              {!shareLink && (
                <button
                  className={
                    "button " +
                    (["delete", "permanent"].includes(dialog.kind)
                      ? "danger"
                      : "primary")
                  }
                  disabled={busy}
                >
                  {busy && <Loader2 className="spin" size={16} />}
                  {
                    {
                      folder: "Create folder",
                      rename: "Save name",
                      delete: "Move to trash",
                      move: "Move here",
                      share: "Create link",
                      permanent: "Delete forever",
                    }[dialog.kind]
                  }
                </button>
              )}
            </div>
          </form>
        </Modal>
      )}
      {preview && (
        <Modal title={preview.name} close={closePreview} wide>
          <div className="preview-content">
            {preview.mime === "application/pdf" ? (
              <iframe src={fileURL(preview, true)} title={preview.name} />
            ) : (
              <img src={fileURL(preview, true)} alt={preview.name} />
            )}
          </div>
          <div className="preview-footer">
            <span>
              {bytes(preview.size)} · {date(preview.modified)}
            </span>
            <a className="button primary" href={fileURL(preview)}>
              <ArrowDownToLine size={17} />
              Download
            </a>
          </div>
        </Modal>
      )}
    </div>
  );
}
