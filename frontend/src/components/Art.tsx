import { Braces, File, FileSpreadsheet, Presentation } from "lucide-react";
import type { Entry } from "../services/api";
export function Art({
  kind,
  className = "",
}: {
  kind: string;
  className?: string;
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
  return (
    <div
      aria-hidden="true"
      className={"art " + className}
      style={{
        backgroundImage: `url(/assets/${icon[0]}.png)`,
        backgroundSize: icon[0] === "extra" ? "200% 200%" : "300% 200%",
        backgroundPosition: `${icon[1] * (icon[0] === "extra" ? 100 : 50)}% ${icon[2] * 100}%`,
      }}
    />
  );
}
export function kindOf(entry: Entry) {
  if (entry.type === "folder") {
    const index = [...entry.name].reduce((a, b) => a + b.charCodeAt(0), 0) % 4;
    return ["folder", "lavender", "yellow", "mint"][index];
  }
  const ext = entry.name.split(".").pop()?.toLowerCase() || "";
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
