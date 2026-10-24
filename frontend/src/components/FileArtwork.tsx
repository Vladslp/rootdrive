import { useEffect, useState } from "react";
import { type Entry } from "../services/api";
import { Art, kindOf } from "./Art";

export function isPhoto(entry: Entry) {
  return (
    entry.type === "file" &&
    (/^image\/(jpeg|png|webp|gif|heic|heif|avif)$/.test(entry.mime || "") ||
      /\.(heic|heif|avif)$/i.test(entry.name))
  );
}

export function FileArtwork({
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
        src={
          "/api/files/thumbnail?path=" +
          encodeURIComponent(entry.path) +
          "&modified=" +
          entry.modified
        }
        alt=""
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
      />
    );
  return <Art kind={kindOf(entry)} />;
}
