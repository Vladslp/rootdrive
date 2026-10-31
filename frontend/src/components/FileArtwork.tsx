import { memo, useEffect, useState } from "react";
import { workspaceURL, type Entry } from "../services/api";
import { Art, kindOf } from "./Art";

export function isPhoto(entry: Entry) {
  return (
    entry.type === "file" &&
    (/^image\/(jpeg|png|webp|gif|heic|heif|avif)$/.test(entry.mime || "") ||
      /\.(heic|heif|avif|cr2|cr3|nef|arw|dng|orf|rw2|raf)$/i.test(entry.name))
  );
}

export const FileArtwork = memo(function FileArtwork({
  entry,
  disabled = false,
}: {
  entry: Entry;
  disabled?: boolean;
}) {
  const [failed, setFailed] = useState(false);
  const image = isPhoto(entry);
  useEffect(() => setFailed(false), [entry.path, entry.modified]);
  if (image && !disabled && !failed)
    return (
      <img
        className="file-thumbnail"
        src={workspaceURL(
          "/api/files/thumbnail?path=" +
          encodeURIComponent(entry.path) +
          "&modified=" +
          entry.modified
        )}
        alt=""
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
      />
    );
  return <Art kind={kindOf(entry)} emptyFolder={entry.type === "folder" && entry.child_count === 0} />;
});
