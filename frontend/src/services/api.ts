export type Tag = { id: string; name: string; color: string };
export type Entry = {
  name: string;
  path: string;
  type: "file" | "folder";
  size: number;
  modified: number;
  mime?: string;
  id?: string;
  favorite?: boolean;
  tags?: Tag[];
  color?: string | null;
  version_count?: number;
  child_count?: number | null;
};
export type Listing = { items: Entry[]; total: number; revision?: string };
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
  system_bytes: number;
  trash_bytes: number;
  versions_bytes: number;
  uploads_bytes: number;
  cache_bytes: number;
  exports_bytes: number;
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
export class APIError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
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
    throw new APIError(
      data.error?.message || "Something went wrong",
      response.status,
    );
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

export function sendChunk(
  url: string,
  body: Blob,
  signal?: AbortSignal,
  progress?: (loaded: number) => void,
  method = "PUT",
) {
  return new Promise<UploadJob>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, "/api" + url);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    if (csrf) xhr.setRequestHeader("X-CSRF-Token", csrf);
    const abort = () => xhr.abort();
    signal?.addEventListener("abort", abort, { once: true });
    const cleanup = () => signal?.removeEventListener("abort", abort);
    xhr.upload.onprogress = (event) => progress?.(event.loaded);
    xhr.onload = () => {
      cleanup();
      let data;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        reject(new Error("Invalid server response"));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else
        reject(
          new APIError(data.error?.message || "Upload failed", xhr.status),
        );
    };
    xhr.onerror = () => {
      cleanup();
      reject(new Error("Connection lost"));
    };
    xhr.onabort = () => {
      cleanup();
      reject(new DOMException("Paused", "AbortError"));
    };
    if (signal?.aborted) {
      cleanup();
      reject(new DOMException("Paused", "AbortError"));
      return;
    }
    xhr.send(body);
  });
}
export type UploadJob = {
  id: string;
  path: string;
  name: string;
  size: number;
  received: number;
  last_modified: number;
  status: string;
  overwrite: boolean;
  source_name: string;
};
export const date = (value: number) =>
  new Date(value * 1000).toLocaleDateString("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
export function saveURL(url: string) {
  const link = document.createElement("a");
  link.href = url;
  link.download = "";
  document.body.appendChild(link);
  link.click();
  link.remove();
}
