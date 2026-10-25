import { Braces, File, FileSpreadsheet, Presentation } from "lucide-react";
import type { Entry } from "../services/api";
export function Art({
  kind,
  className = "",
  emptyFolder = false,
}: {
  kind: string;
  className?: string;
  emptyFolder?: boolean;
}) {
  const icons: Record<string, [string, number, number]> = {
    folder: ["folders", 0, 0],
    lavender: ["folders", 1, 0],
    yellow: ["folders", 2, 0],
    mint: ["folders", 0, 1],
    cloud: ["folders", 1, 1],
    drive: ["folders", 2, 1],
    images: ["files", 0, 0],
    videos: ["files", 1, 0],
    audio: ["files", 2, 0],
    documents: ["files", 0, 1],
    archives: ["files", 1, 1],
    pdf: ["files", 2, 1],
    sheets: ["extra", 0, 0],
    slides: ["extra", 1, 0],
    code: ["extra", 0, 1],
    file: ["extra", 1, 1],
    text: ["file-types", 0, 0],
    markdown: ["file-types", 1, 0],
    word: ["file-types", 2, 0],
    opendocument: ["file-types", 3, 0],
    json: ["file-types", 0, 1],
    csv: ["file-types", 1, 1],
    python: ["file-types", 2, 1],
    javascript: ["file-types", 3, 1],
    html: ["file-types", 0, 2],
    css: ["file-types", 1, 2],
    typescript: ["file-types", 2, 2],
    sql: ["file-types", 3, 2],
  };
  const icon = icons[kind];
  if (!icon) {
    const Icon =
      kind === "code"
        ? Braces
        : kind === "sheets"
          ? FileSpreadsheet
          : kind === "slides"
            ? Presentation
            : File;
    return (
      <div className={"art fallback-art " + kind + " " + className}>
        <Icon strokeWidth={1.5} />
      </div>
    );
  }
  const columns = icon[0] === "file-types" ? 4 : icon[0] === "extra" ? 2 : 3;
  const rows = icon[0] === "file-types" ? 3 : 2;
  return (
    <div
      aria-hidden="true"
      className={"art " + className}
      style={{
        backgroundImage: `url(/assets/${emptyFolder && icon[0] === "folders" ? "empty-folders" : icon[0]}.png${icon[0] === "file-types" ? "?v=clean-2" : ""})`,
        backgroundSize: icon[0] === "file-types" ? `${1448 / 320 * 100}% ${1086 / 342 * 100}%` : `${columns * 100}% ${rows * 100}%`,
        backgroundPosition: icon[0] === "file-types"
          ? `${(68 + icon[1] * 342) / (1448 - 320) * 100}% ${(34 + icon[2] * 335) / (1086 - 342) * 100}%`
          : `${icon[1] * 100 / (columns - 1)}% ${icon[2] * 100 / (rows - 1)}%`,
      }}
    />
  );
}
export function kindOf(entry: Entry) {
  if (entry.type === "folder") {
    if (entry.color) return entry.color;
    const colors: Record<string, string> = {
      photos: "mint",
      documents: "folder",
      videos: "lavender",
      audio: "yellow",
    };
    if (colors[entry.name.toLowerCase()])
      return colors[entry.name.toLowerCase()];
    const index = [...entry.name].reduce((a, b) => a + b.charCodeAt(0), 0) % 4;
    return ["folder", "lavender", "yellow", "mint"][index];
  }
  const ext = entry.name.split(".").pop()?.toLowerCase() || "";
  const fileTypes: Record<string, string> = {
    txt: "text", log: "text", md: "markdown", markdown: "markdown",
    docx: "word", odt: "opendocument", json: "json", jsonl: "json",
    csv: "csv", tsv: "csv", py: "python", js: "javascript", jsx: "javascript",
    html: "html", htm: "html", css: "css", scss: "css", ts: "typescript",
    tsx: "typescript", sql: "sql",
  };
  if (fileTypes[ext]) return fileTypes[ext];
  if (
    entry.mime?.startsWith("image/") ||
    /^(jpg|jpeg|png|webp|gif|svg|heic|avif|raw)$/.test(ext)
  )
    return "images";
  if (entry.mime?.startsWith("video/") || /^(mp4|mov|mkv|avi|webm)$/.test(ext))
    return "videos";
  if (entry.mime?.startsWith("audio/") || /^(mp3|wav|flac|m4a|ogg)$/.test(ext))
    return "audio";
  if (ext === "pdf") return "pdf";
  if (/^(zip|rar|7z|gz|tar|bz2)$/.test(ext)) return "archives";
  if (
    /^(py|js|ts|tsx|jsx|html|css|json|yaml|yml|sh|rs|go|java|cpp|c|sql)$/.test(
      ext,
    )
  )
    return "code";
  if (/^(csv|xlsx|xls|ods)$/.test(ext)) return "sheets";
  if (/^(pptx|ppt|odp|key)$/.test(ext)) return "slides";
  if (/^(txt|md|doc|docx|rtf|odt)$/.test(ext)) return "documents";
  return "file";
}
