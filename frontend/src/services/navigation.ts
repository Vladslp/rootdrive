import { Clock3, Files, Images, Weight } from "lucide-react";

export const smartFolders = [
  { id: "recent", label: "Recent files", detail: "Modified in the last 7 days", icon: Clock3, sort: "modified", direction: "desc" },
  { id: "photos", label: "All photos", detail: "Photos from every folder", icon: Images, sort: "name", direction: "asc" },
  { id: "documents", label: "Documents", detail: "Documents from every folder", icon: Files, sort: "name", direction: "asc" },
  { id: "large", label: "Large files", detail: "100 MB and larger", icon: Weight, sort: "size", direction: "desc" },
] as const;

export type SmartFolder = typeof smartFolders[number]["id"];
export type View = "gallery" | "files" | "favorites" | "tag" | "smart" | "shares" | "trash" | "storage" | "settings";
