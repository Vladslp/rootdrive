import type { Entry } from "./api";

export const textExtensions = new Set(
  "txt md markdown csv tsv json jsonl yaml yml toml ini cfg conf log xml html htm css scss js jsx ts tsx py sh bash zsh sql c h cpp hpp rs go java kt swift rb php vue svelte tex bib svg srt vtt".split(
    " ",
  ),
);
export function editorKind(entry: Entry) {
  if (entry.type !== "file") return null;
  const name = entry.name.replace(/ \(edited(?: \d+)?\)(?=\.|$)/g, "");
  const extension = name.split(".").pop()?.toLowerCase() || "";
  if (
    textExtensions.has(extension) ||
    ["Dockerfile", "Makefile", ".gitignore", ".env.example"].includes(name)
  )
    return "text";
  if (
    ["jpg", "jpeg", "png", "webp", "heic", "heif", "avif"].includes(extension)
  )
    return "photo";
  if (["docx", "odt"].includes(extension)) return "document";
  if (extension === "pdf") return "pdf";
  return null;
}
export function canEdit(entry: Entry) {
  return editorKind(entry) !== null;
}
export type Paragraph = {
  id: number;
  text: string;
  editable: boolean;
  heading: boolean;
};
export type EditorData = {
  kind: "text" | "photo" | "document" | "pdf";
  revision: string;
  text?: string;
  encoding?: string;
  format?: string;
  width?: number;
  height?: number;
  paragraphs?: Paragraph[];
  pages?: number;
};
export type PhotoEdits = {
  rotation: number;
  flip: boolean;
  crop: [number, number, number, number];
  brightness: number;
  contrast: number;
  saturation: number;
};
export const defaultPhotoEdits: PhotoEdits = {
  rotation: 0,
  flip: false,
  crop: [0, 0, 1, 1],
  brightness: 1,
  contrast: 1,
  saturation: 1,
};
export type PDFPage = { index: number; rotation: number };
