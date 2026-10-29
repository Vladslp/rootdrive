import type { Entry } from "./api";

export function selectionSize(entries: Entry[], trash = false): number {
  if (trash) return entries.reduce((total, entry) => total + entry.size, 0);
  const folders = entries.filter((entry) => entry.type === "folder").map((entry) => entry.path + "/");
  return entries.reduce((total, entry) => folders.some((folder) => entry.path.startsWith(folder)) ? total : total + entry.size, 0);
}
