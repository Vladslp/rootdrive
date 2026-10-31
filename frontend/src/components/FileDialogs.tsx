import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowLeft,
  Check,
  ChevronRight,
  Copy,
  Download,
  Folder,
  FolderInput,
  History,
  Info,
  Link2,
  Loader2,
  Pencil,
  Plus,
  RotateCcw,
  Tag as TagIcon,
  Trash2,
} from "lucide-react";
import {
  api,
  bytes,
  date,
  fileURL,
  workspaceURL,
  saveURL,
  type Entry,
  type Listing,
  type Tag,
} from "../services/api";
import { canEdit } from "../services/editor";
import { Dialog } from "./Dialog";
import { Art, kindOf } from "./Art";
import { FileArtwork, isPhoto } from "./FileArtwork";
import { ImageDetails } from "./ImageDetails";
import { PhotoViewport } from "./PhotoViewport";

export type FileAction =
  | "export"
  | "archive"
  | "compress"
  | "edit"
  | "rename"
  | "newfile"
  | "newfolder"
  | "move"
  | "tags"
  | "delete"
  | "properties"
  | "preview"
  | "versions"
  | "share"
  | "purge"
  | "emptytrash";
export type Modal = {
  action: FileAction;
  entries: Entry[];
  trashRevision?: string;
  total?: number;
};
const colors = ["blue", "green", "amber", "rose", "violet", "slate"];

export function NameDialog({
  entry,
  path,
  close,
  done,
}: {
  entry?: Entry;
  path: string;
  close: () => void;
  done: () => void;
}) {
  const [name, setName] = useState(entry?.name || "");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(
        entry ? "/files/rename" : "/folders",
        entry ? "PATCH" : "POST",
        entry ? { path: entry.path, name } : { path, name },
      );
      done();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title={entry ? "Rename" : "New folder"} close={close}>
      <form onSubmit={submit}>
        <label className="field-label">
          Name
          <input
            autoFocus
            value={name}
            maxLength={240}
            required
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button type="button" className="button secondary" onClick={close}>
            Cancel
          </button>
          <button
            className="button primary"
            disabled={busy || name === entry?.name}
          >
            {busy && <Loader2 size={16} className="spin" />}
            {entry ? "Save" : "Create folder"}
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function NewFileDialog({
  path,
  close,
  created,
}: {
  path: string;
  close: () => void;
  created: (entry: Entry) => void;
}) {
  const [name, setName] = useState("Untitled");
  const [extension, setExtension] = useState("txt");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const filename = name.toLowerCase().endsWith("." + extension)
        ? name
        : name + "." + extension;
      const result = await api<Entry>("/files", "POST", {
        path,
        name: filename,
      });
      created(result);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="New file"
      className="new-file-dialog"
      close={() => {
        if (!busy) close();
      }}
    >
      <form onSubmit={submit}>
        <label className="field-label">
          Name
          <input
            autoFocus
            value={name}
            maxLength={230}
            required
            disabled={busy}
            onChange={(event) => setName(event.target.value)}
            onFocus={(event) => event.target.select()}
          />
        </label>
        <fieldset className="file-type-picker" disabled={busy}>
          <legend>File type</legend>
          <div className="file-type-grid">
            {[
              ["txt", "Text", "text", "slate"],
              ["md", "Markdown", "markdown", "violet"],
              ["docx", "Document", "word", "blue"],
              ["odt", "OpenDocument", "opendocument", "green"],
              ["json", "JSON", "json", "amber"],
              ["csv", "CSV", "csv", "green"],
              ["py", "Python", "python", "blue"],
              ["js", "JavaScript", "javascript", "amber"],
              ["html", "HTML", "html", "rose"],
              ["css", "CSS", "css", "violet"],
            ].map(([value, label, art, color]) => (
              <label
                key={value}
                className={"file-type-option " + color + (extension === value ? " selected" : "")}
              >
                <input
                  type="radio"
                  name="file-type"
                  value={value}
                  checked={extension === value}
                  onChange={() => setExtension(value)}
                  aria-label={label + " (." + value + ")"}
                />
                <Art kind={art} />
                <span><strong>{label}</strong><small>.{value}</small></span>
                {extension === value && <Check size={13} className="file-type-check" />}
              </label>
            ))}
          </div>
        </fieldset>
        {error && (
          <p className="error-text" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <button
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={close}
          >
            Cancel
          </button>
          <button className="button primary" disabled={busy || !name}>
            {busy && <Loader2 size={16} className="spin" />}Create & edit
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function MoveDialog({
  entries,
  close,
  done,
}: {
  entries: Entry[];
  close: () => void;
  done: () => void;
}) {
  const [path, setPath] = useState("");
  const [listing, setListing] = useState<Listing>({ items: [], total: 0 });
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    setLoading(true);
    api<Listing>(
      "/files?" +
        new URLSearchParams({ path, limit: "80", offset: String(offset) }),
    )
      .then((result) => {
        if (active) setListing(result);
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
  }, [path, offset]);
  function navigate(value: string) {
    setPath(value);
    setOffset(0);
    setError("");
  }
  async function move() {
    setBusy(true);
    setError("");
    try {
      await api("/files/batch/move", "POST", {
        paths: entries.map((entry) => entry.path),
        destination: path,
      });
      done();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={
        "Move " +
        (entries.length === 1 ? entries[0].name : entries.length + " items")
      }
      close={close}
    >
      <div className="picker-path">
        <button
          className="icon-button"
          disabled={!path}
          aria-label="Parent folder"
          onClick={() => navigate(path.split("/").slice(0, -1).join("/"))}
        >
          <ArrowLeft size={17} />
        </button>
        <button onClick={() => navigate("")}>My files</button>
        <ChevronRight size={14} />
        <span>{path || "Root"}</span>
      </div>
      <div className="folder-picker">
        {loading ? (
          <Loader2 className="spin" />
        ) : (
          listing.items
            .filter((item) => item.type === "folder")
            .map((item) => (
              <button
                key={item.path}
                onClick={() => navigate(item.path)}
                disabled={entries.some(
                  (entry) =>
                    entry.type === "folder" &&
                    (item.path === entry.path ||
                      item.path.startsWith(entry.path + "/")),
                )}
              >
                <Art kind={kindOf(item)} />
                <span>{item.name}</span>
                <ChevronRight size={17} />
              </button>
            ))
        )}
        {!loading && !listing.items.some((item) => item.type === "folder") && (
          <p className="muted">No folders on this page.</p>
        )}
      </div>
      {listing.total > 80 && (
        <div className="pagination">
          <button disabled={!offset} onClick={() => setOffset(offset - 80)}>
            Previous
          </button>
          <span>
            {offset + 1}to{Math.min(offset + 80, listing.total)}
          </span>
          <button
            disabled={offset + 80 >= listing.total}
            onClick={() => setOffset(offset + 80)}
          >
            Next
          </button>
        </div>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="dialog-actions">
        <button className="button secondary" onClick={close}>
          Cancel
        </button>
        <button className="button primary" disabled={busy} onClick={move}>
          <FolderInput size={16} />
          Move here
        </button>
      </div>
    </Dialog>
  );
}

export function TagsDialog({
  entries,
  tags,
  close,
  done,
  reloadTags,
  manager = false,
}: {
  entries: Entry[];
  tags: Tag[];
  close: () => void;
  done: () => void;
  reloadTags: () => Promise<void>;
  manager?: boolean;
}) {
  const [selected, setSelected] = useState<string[]>(
    entries.length === 1 ? (entries[0].tags || []).map((tag) => tag.id) : [],
  );
  const [folderColor, setFolderColor] = useState(
    entries.length === 1 ? entries[0].color || "" : "",
  );
  const [name, setName] = useState("");
  const [color, setColor] = useState("blue");
  const [editing, setEditing] = useState<Tag | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function create(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const tag = await api<Tag>(
        editing ? "/tags/" + editing.id : "/tags",
        editing ? "PATCH" : "POST",
        { name, color },
      );
      if (!editing) setSelected((current) => [...current, tag.id]);
      setName("");
      setEditing(null);
      await reloadTags();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function remove(tag: Tag) {
    setBusy(true);
    setError("");
    try {
      await api("/tags/" + tag.id, "DELETE");
      setSelected((current) => current.filter((id) => id !== tag.id));
      await reloadTags();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function apply() {
    setBusy(true);
    setError("");
    try {
      await api("/files/tags", "POST", {
        paths: entries.map((item) => item.path),
        tag_ids: selected,
        mode: entries.length === 1 ? "replace" : "add",
        ...(folderColor ? { color: folderColor } : {}),
      });
      done();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title={manager ? "Manage tags" : "Tags & color"} close={close}>
      {!manager && entries.length > 1 && (
        <p className="muted">Add tags to {entries.length} items.</p>
      )}
      <div className="tag-options">
        {tags.map((tag) => (
          <div className="tag-option" key={tag.id}>
            {manager ? (
              <button
                onClick={() => {
                  setEditing(tag);
                  setName(tag.name);
                  setColor(tag.color);
                }}
              >
                <i className={"tag-dot " + tag.color} />
                {tag.name}
              </button>
            ) : (
              <button
                className={selected.includes(tag.id) ? "chosen" : ""}
                onClick={() =>
                  setSelected((current) =>
                    current.includes(tag.id)
                      ? current.filter((id) => id !== tag.id)
                      : [...current, tag.id],
                  )
                }
              >
                <i className={"tag-dot " + tag.color} />
                <span>{tag.name}</span>
                {selected.includes(tag.id) && <Check size={16} />}
              </button>
            )}
            {manager && (
              <button
                className="icon-button danger-text"
                disabled={busy}
                onClick={() => {
                  if (
                    window.confirm(
                      "Delete tag “" + tag.name + "” from all files?",
                    )
                  )
                    void remove(tag);
                }}
                aria-label={"Delete tag " + tag.name}
              >
                <Trash2 size={15} />
              </button>
            )}
          </div>
        ))}
      </div>
      {!manager && entries.length === 1 && entries[0].type === "folder" && (
        <div className="folder-colors">
          <label>Folder color</label>
          <div>
            {["folder", "lavender", "yellow", "mint"].map((value) => (
              <button
                key={value}
                className={folderColor === value ? "chosen" : ""}
                onClick={() => setFolderColor(value)}
                aria-label={value + " folder"}
              >
                <Art kind={value} />
              </button>
            ))}
          </div>
        </div>
      )}
      <form className="create-tag" onSubmit={create}>
        <label className="field-label">
          {editing ? "Edit tag" : "New tag"}
          <input
            value={name}
            maxLength={40}
            placeholder="Tag name"
            required
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <div className="color-options">
          {colors.map((value) => (
            <button
              type="button"
              key={value}
              className={
                "color-choice " + value + (color === value ? " chosen" : "")
              }
              aria-label={value}
              onClick={() => setColor(value)}
            >
              {color === value && <Check size={14} />}
            </button>
          ))}
          <button className="button secondary" disabled={busy || !name.trim()}>
            {editing ? <Check size={16} /> : <Plus size={16} />}
            {editing ? "Save" : "Add"}
          </button>
        </div>
      </form>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      <div className="dialog-actions">
        <button className="button secondary" onClick={close}>
          {manager ? "Done" : "Cancel"}
        </button>
        {!manager && (
          <button className="button primary" disabled={busy} onClick={apply}>
            <TagIcon size={16} />
            Apply
          </button>
        )}
      </div>
    </Dialog>
  );
}

type Version = {
  id: string;
  size: number;
  modified: number;
  created_at: number;
};
export function VersionsDialog({
  entry,
  close,
  done,
  replace,
}: {
  entry: Entry;
  close: () => void;
  done: () => void;
  replace: () => void;
}) {
  const [versions, setVersions] = useState<Version[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api<{ items: Version[] }>(
      "/files/versions?path=" + encodeURIComponent(entry.path),
    )
      .then((result) => setVersions(result.items))
      .catch((error) => setError(error.message))
      .finally(() => setLoading(false));
  }, [entry.path]);
  async function restore(version: Version) {
    if (
      !window.confirm(
        "Restore this version? The current file will be kept in history.",
      )
    )
      return;
    setBusy(true);
    try {
      await api("/versions/" + version.id + "/restore", "POST");
      done();
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title="Version history" close={close}>
      <div className="version-current">
        <Art kind={kindOf(entry)} />
        <div>
          <strong>{entry.name}</strong>
          <span>{bytes(entry.size)} · Current version</span>
        </div>
      </div>
      <button className="button secondary full-width" onClick={replace}>
        <Plus size={16} />
        Upload new version
      </button>
      <div className="version-list">
        {loading ? (
          <Loader2 className="spin" />
        ) : !versions.length ? (
          <div className="empty-small">
            <History size={28} />
            <p>No previous versions.</p>
          </div>
        ) : (
          versions.map((version, index) => (
            <div className="version-row" key={version.id}>
              <History size={18} />
              <div>
                <strong>{date(version.modified)}</strong>
                <span>
                  {bytes(version.size)} · Saved{" "}
                  {new Date(version.created_at * 1000).toLocaleString("en")}
                </span>
              </div>
              <button
                className="icon-button"
                aria-label={"Download version " + (index + 1)}
                onClick={() =>
                  saveURL("/api/versions/" + version.id + "/download")
                }
              >
                <Download size={17} />
              </button>
              <button
                className="icon-button"
                aria-label={"Restore version " + (index + 1)}
                disabled={busy}
                onClick={() => restore(version)}
              >
                <RotateCcw size={17} />
              </button>
            </div>
          ))
        )}
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </Dialog>
  );
}

export function PropertiesDialog({
  entry,
  close,
}: {
  entry: Entry;
  close: () => void;
}) {
  return (
    <Dialog title="Properties" close={close}>
      <div className={"properties-art " + (isPhoto(entry) ? "photo-art" : "")}>
        <FileArtwork entry={entry} disabled={Boolean(entry.id)} />
      </div>
      <h3 className="properties-name">{entry.name}</h3>
      <dl className="properties-list">
        {[
          [
            "Type",
            entry.type === "folder"
              ? "Folder"
              : entry.mime ||
                entry.name.split(".").pop()?.toUpperCase() ||
                "File",
          ],
          ["Size", bytes(entry.size)],
          ...(entry.type === "folder" && entry.child_count != null ? [["Items", String(entry.child_count)]] : []),
          ["Modified", new Date(entry.modified * 1000).toLocaleString("en")],
          ["Path", "/" + entry.path],
          ["Versions", String(entry.version_count || 0)],
        ].map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {Boolean(entry.tags?.length) && (
        <div className="file-tags">
          {entry.tags?.map((tag) => (
            <span key={tag.id} className={"tag-pill " + tag.color}>
              {tag.name}
            </span>
          ))}
        </div>
      )}
      {isPhoto(entry) && !entry.id && <ImageDetails entry={entry} />}
    </Dialog>
  );
}

export function PreviewDialog({
  entry,
  close,
  properties,
  edit,
  share,
  readOnly = false,
}: {
  readOnly?: boolean;
  entry: Entry;
  close: () => void;
  properties: () => void;
  edit: () => void;
  share?: () => void;
}) {
  const [failed, setFailed] = useState(false);
  const [size, setSize] = useState({ width: 1, height: 1 });
  const kind = kindOf(entry);
  const url = workspaceURL("/api/files/media?path=" + encodeURIComponent(entry.path));
  return (
    <Dialog title={entry.name} close={close} wide>
      <div className={"preview-content " + kind}>
        {failed ? (
          <p className="muted">
            Your browser cannot preview this format. Download the original file.
          </p>
        ) : isPhoto(entry) ? (
          <PhotoViewport width={size.width} height={size.height}>
          <img
            src={fileURL(entry, true)}
            alt={entry.name}
            onError={() => setFailed(true)}
            onLoad={(event) => setSize({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
          />
          </PhotoViewport>
        ) : kind === "pdf" ? (
          <iframe src={fileURL(entry, true)} title={entry.name} />
        ) : kind === "videos" ? (
          <video
            src={url}
            controls
            playsInline
            onError={() => setFailed(true)}
          />
        ) : kind === "audio" ? (
          <div className="audio-preview">
            <Art kind="audio" />
            <audio
              src={url}
              controls
              autoPlay
              onError={() => setFailed(true)}
            />
          </div>
        ) : (
          <div className="unsupported-preview">
            <Art kind={kind} />
            <p>No preview for this file.</p>
          </div>
        )}
      </div>
      <div className="preview-actions">
        <span>{bytes(entry.size)}</span>
        {share && (
          <button className="button secondary" onClick={share}>
            <Link2 size={16} />
            Share link
          </button>
        )}
        {canEdit(entry) && !readOnly && (
          <button className="button secondary" onClick={edit}>
            <Pencil size={16} />
            Edit
          </button>
        )}
        <button className="button secondary" onClick={properties}>
          <Info size={16} />
          Properties
        </button>
        <button
          className="button primary"
          onClick={() => saveURL(fileURL(entry))}
        >
          <Download size={16} />
          Download
        </button>
      </div>
    </Dialog>
  );
}

export function ShareDialog({
  entry,
  close,
}: {
  entry: Entry;
  close: () => void;
}) {
  const [hours, setHours] = useState("24");
  const [password, setPassword] = useState("");
  const [link, setLink] = useState("");
  const [copied, setCopied] = useState(false);
  const linkInput = useRef<HTMLInputElement>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function create() {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ url: string }>("/shares", "POST", {
        path: entry.path,
        expires_hours: hours ? Number(hours) : null,
        password: password || undefined,
      });
      setLink(location.origin + result.url);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog title={entry.type === "folder" ? "Share folder" : "Share file"} close={() => { if (!busy) close(); }}>
      <p className="share-warning">
        {password ? "Anyone with the link and password can download shared files." : "Anyone with the link can download shared files."}
      </p>
      <strong className="break-word">{entry.name}</strong>
      {link ? (
        <label className="field-label">
          Share link
          <input ref={linkInput} readOnly value={link} onFocus={(e) => e.target.select()} />
        </label>
      ) : (
        <label className="field-label">
          Expires
          <select value={hours} onChange={(e) => setHours(e.target.value)}>
            <option value="1">1 hour</option>
            <option value="24">1 day</option>
            <option value="168">1 week</option>
            <option value="">Never</option>
          </select>
        </label>
      )}
      {!link && <label className="field-label">Password <span className="muted">Optional · 8 characters minimum</span><input type="password" autoComplete="new-password" minLength={8} maxLength={1024} value={password} onChange={(event) => setPassword(event.target.value)} /></label>}
      {error && <p className="error-text" role="alert">{error}</p>}
      <div className="dialog-actions">
        <button className="button secondary" onClick={close} disabled={busy}>
          Close
        </button>
        {!link && (
          <button className="button primary" onClick={create} disabled={busy || (password.length > 0 && password.length < 8)}>
            Create link
          </button>
        )}
        {link && (
          <button
            className="button primary"
            onClick={async () => {
              try {
                if (navigator.clipboard?.writeText) {
                  await navigator.clipboard.writeText(link);
                } else {
                  linkInput.current?.select();
                  if (!document.execCommand("copy")) throw new Error("Copy unavailable");
                }
                setCopied(true);
                setError("");
              } catch {
                setError("Select and copy the link above");
              }
            }}
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
            {copied ? "Copied" : "Copy link"}
          </button>
        )}
      </div>
    </Dialog>
  );
}
