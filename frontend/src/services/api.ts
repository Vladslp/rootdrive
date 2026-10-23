export type Entry = {
  name: string;
  path: string;
  type: "file" | "folder";
  size: number;
  modified: number;
  mime?: string;
  id?: string;
};
export type Listing = { items: Entry[]; total: number };
export type Account = {
  auth_enabled: boolean;
  shares_enabled: boolean;
  max_upload_size_mb: number;
  csrf_token: string | null;
  user: { username: string; role: string } | null;
};
export type Stats = {
  file_count: number;
  stored_bytes: number;
  disk_free: number;
  disk_total: number;
  disk_used: number;
  disk_percent: number;
  categories: Record<string, number>;
};
export type Shared = {
  id: string;
  path: string;
  name: string;
  expires_at: number | null;
  created_at: number;
};
let csrf = "";
export function setCSRF(value: string | null) {
  csrf = value || "";
}
export async function api<T>(
  url: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch("/api" + url, {
    method,
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401)
      window.dispatchEvent(new Event("rootdrive:unauthorized"));
    throw new Error(data.error?.message || "Something went wrong");
  }
  return data;
}
export function upload(
  file: File,
  path: string,
  progress: (percent: number) => void,
) {
  return new Promise<void>((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("POST", "/api/files/upload?path=" + encodeURIComponent(path));
    if (csrf) request.setRequestHeader("X-CSRF-Token", csrf);
    request.upload.onprogress = (event) => {
      if (event.lengthComputable)
        progress(Math.round((event.loaded / event.total) * 100));
    };
    request.onload = () => {
      if (request.status >= 200 && request.status < 300) resolve();
      else {
        let message = "Upload failed";
        try {
          message = JSON.parse(request.responseText).error.message;
        } catch {}
        reject(new Error(message));
      }
    };
    request.onerror = () => reject(new Error("Connection lost. Try again"));
    const body = new FormData();
    body.append("files", file);
    request.send(body);
  });
}
export const fileURL = (entry: Entry, preview = false) =>
  "/api/files/" +
  (preview ? "preview" : "download") +
  "?path=" +
  encodeURIComponent(entry.path);
export function bytes(value: number) {
  if (!value) return "0 B";
  const unit = Math.min(Math.floor(Math.log(value) / Math.log(1024)), 4);
  return (
    (value / 1024 ** unit).toLocaleString("en", {
      maximumFractionDigits: unit ? 1 : 0,
    }) +
    " " +
    ["B", "KB", "MB", "GB", "TB"][unit]
  );
}
