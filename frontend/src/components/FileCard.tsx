import { memo, useState, type HTMLAttributes } from "react";
import { Check, History, MoreHorizontal, Star, Trash2 } from "lucide-react";
import { bytes, date, type Entry, type Tag } from "../services/api";
import { FileArtwork } from "./FileArtwork";
import { SurfaceAction } from "./SurfaceAction";
import type { Modal } from "./FileDialogs";

export type FileCardActions = {
  open: (entry: Entry) => void;
  drag: (entry: Entry, data: DataTransfer) => void;
  drop: (destination: string, data: DataTransfer) => void;
  chooseAction: (action: Modal["action"], entries: Entry[]) => void;
  favorite: (entry: Entry) => void;
  select: (key: string, checked: boolean) => void;
  restore: (entry: Entry) => void;
  clearTagContext: () => void;
  context: (value: { entry: Entry; x: number; y: number }) => void;
  navigate: (view: "tag", path: string, tag: string) => void;
  tagMenuProps: (tag: Tag) => HTMLAttributes<HTMLButtonElement>;
};
type FileCardProps = {
  entry: Entry;
  selected: boolean;
  trash: boolean;
  showPath: boolean;
  busy: boolean;
  readOnly?: boolean;
  actions: FileCardActions;
};
export const FileCard = memo(function FileCard({
  entry, selected, trash, showPath, busy, actions, readOnly = false,
}: FileCardProps) {
  const [dropOver, setDropOver] = useState(false);
  const entryKey = trash ? entry.id! : entry.path;
  return (
    <article
      draggable={!trash && !readOnly}
      onDragStart={(event) => { if (!trash && !readOnly) actions.drag(entry, event.dataTransfer); }}
      onDragOver={(event) => { if (!trash && !readOnly && entry.type === "folder" && event.dataTransfer.types.includes("application/x-rootdrive-files")) { event.preventDefault(); event.stopPropagation(); setDropOver(true); event.dataTransfer.dropEffect = "move"; } }}
      onDragLeave={() => setDropOver(false)}
      onDrop={(event) => { setDropOver(false); if (!trash && !readOnly && entry.type === "folder" && event.dataTransfer.types.includes("application/x-rootdrive-files")) { event.preventDefault(); event.stopPropagation(); actions.drop(entry.path, event.dataTransfer); } }}
      data-selection-path={entryKey}
      className={"file-card " + (entry.type === "folder" ? "folder-card " : "") + (selected ? "selected " : "") + (dropOver ? "folder-drop-target" : "")}
      onContextMenu={(event) => {
        if (trash) return;
        event.preventDefault();
        actions.clearTagContext();
        actions.context({
          entry,
          x: Math.min(event.clientX, window.innerWidth - 240),
          y: Math.max(8, Math.min(event.clientY, window.innerHeight - 470)),
        });
      }}
    >
      <SurfaceAction
        label={"Open " + entry.name}
        activate={() => trash ? actions.chooseAction("properties", [entry]) : actions.open(entry)}
      />
      <div className="card-art">
        <div className="card-open">
          <FileArtwork entry={entry} disabled={trash} />
        </div>
        <label className={"selection-check " + (selected ? "checked" : "")}>
          <input
            type="checkbox"
            checked={selected}
            aria-label={"Select " + entry.name}
            onChange={(event) => actions.select(entryKey, event.target.checked)}
          />
          <Check size={13} />
        </label>
        {!trash && !readOnly && (
          <button
            className={"favorite-toggle " + (entry.favorite ? "is-favorite" : "")}
            aria-label={(entry.favorite ? "Unfavorite " : "Favorite ") + entry.name}
            onClick={() => actions.favorite(entry)}
          >
            <Star size={16} fill={entry.favorite ? "currentColor" : "none"} />
          </button>
        )}
        <button
          className="card-more icon-button"
          aria-label={"Actions for " + entry.name}
          onClick={(event) => {
            event.stopPropagation();
            if (trash) {
              actions.chooseAction("properties", [entry]);
              return;
            }
            const rect = event.currentTarget.getBoundingClientRect();
            actions.clearTagContext();
            actions.context({
              entry,
              x: Math.max(8, Math.min(rect.right - 220, window.innerWidth - 240)),
              y: Math.max(8, Math.min(rect.bottom + 6, window.innerHeight - 470)),
            });
          }}
        >
          <MoreHorizontal size={19} />
        </button>
      </div>
      <div className="card-info">
        <span className="file-name" title={entry.name}>{entry.name}</span>
        <div className="card-meta">
          <span>{bytes(entry.size)}</span>
          <time>{date(entry.modified)}</time>
        </div>
        {Boolean(entry.tags?.length) && (
          <div className="file-tags">
            {entry.tags?.slice(0, 3).map((tag) => (
              <button
                className={"tag-pill " + tag.color}
                key={tag.id}
                {...actions.tagMenuProps(tag)}
                onClick={() => actions.navigate("tag", "", tag.id)}
              >
                {tag.name}
              </button>
            ))}
            {(entry.tags?.length || 0) > 3 && (
              <span className="more-tags">+{entry.tags!.length - 3}</span>
            )}
          </div>
        )}
        {showPath && <span className="entry-path">/{entry.path.split("/").slice(0, -1).join("/")}</span>}
        {trash && !readOnly && (
          <div className="trash-actions">
            <button className="text-button" disabled={busy} onClick={() => actions.restore(entry)}>
              <History size={14} />
              Restore
            </button>
            <button
              className="icon-button danger-text"
              aria-label={"Permanently delete " + entry.name}
              onClick={() => actions.chooseAction("purge", [entry])}
            >
              <Trash2 size={16} />
            </button>
          </div>
        )}
      </div>
      <span className="list-size">{bytes(entry.size)}</span>
      <span className="list-date">{date(entry.modified)}</span>
    </article>
  );
});
