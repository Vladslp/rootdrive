import { useCallback, useEffect, useRef } from "react";
import { api, APIError, sendChunk, type UploadJob } from "../services/api";

export type UploadSource = { file: File; relative: string };
export type Transfer = {
  key: string;
  file?: File;
  relative: string;
  base: string;
  size: number;
  modified: number;
  sourceName?: string;
  received: number;
  progress: number;
  state:
    | "queued"
    | "uploading"
    | "paused"
    | "waiting"
    | "missing"
    | "error"
    | "done";
  job?: UploadJob;
  error?: string;
  conflict?: boolean;
  overwrite?: boolean;
  verify?: boolean;
  paused?: boolean;
  retries?: number;
};

export function useUploads(ready: boolean, completed: () => void, scope = "workspace") {
  const scheduleRetry = useRef<() => void>(() => {});
  const listeners = useRef(new Set<() => void>());
  const snapshot = useRef<Transfer[]>([]);
  const runRef = useRef<() => Promise<void>>(async () => {});
  const setTransfers = useCallback((items: Transfer[]) => {
    snapshot.current = items;
    scheduleRetry.current();
    listeners.current.forEach((listener) => listener());
    queueMicrotask(() => { void runRef.current(); });
  }, []);
  const subscribe = useCallback((listener: () => void) => {
    listeners.current.add(listener);
    return () => { listeners.current.delete(listener); };
  }, []);
  const getSnapshot = useCallback(() => snapshot.current, []);
  const ref = useRef<Transfer[]>([]);
  const running = useRef(false);
  const activeKey = useRef<string | null>(null);
  const mounted = useRef(true);
  const abort = useRef<AbortController | null>(null);
  const publication = useRef<ReturnType<typeof setTimeout> | null>(null);
  const completionTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reset = useCallback(() => {
    abort.current?.abort();
    ref.current = [];
    if (publication.current !== null) clearTimeout(publication.current);
    if (completionTimer.current !== null) clearTimeout(completionTimer.current);
    publication.current = null;
    completionTimer.current = null;
    setTransfers([]);
  }, [setTransfers]);
  const completedRef = useRef(completed);
  completedRef.current = completed;
  const update = useCallback((key: string, values: Partial<Transfer>) => {
    ref.current = ref.current.map((item) =>
      item.key === key ? { ...item, ...values } : item,
    );
    if (!mounted.current) return;
    if (Object.keys(values).length === 1 && values.progress !== undefined) {
      if (publication.current === null) publication.current = setTimeout(() => {
        publication.current = null;
        if (mounted.current) setTransfers(ref.current);
      }, 100);
    } else {
      if (publication.current !== null) clearTimeout(publication.current);
      publication.current = null;
      setTransfers(ref.current);
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      abort.current?.abort();
      if (publication.current !== null) clearTimeout(publication.current);
      if (completionTimer.current !== null) clearTimeout(completionTimer.current);
    };
  }, []);
  useEffect(() => {
    if (!ready) return;
    let active = true;
    api<{ items: UploadJob[] }>("/uploads")
      .then(({ items }) => {
        if (!active) return;
        const known = new Set(ref.current.map((item) => item.job?.id));
        const recovered: Transfer[] = items
          .filter((job) => !known.has(job.id))
          .map((job) => ({
            key: job.id,
            relative: job.path,
            base: "",
            size: job.size,
            modified: job.last_modified,
            sourceName: job.source_name,
            received: job.received,
            progress: job.size ? (job.received / job.size) * 100 : 0,
            state: "missing",
            job,
          }));
        ref.current = [...ref.current, ...recovered];
        setTransfers(ref.current);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [ready, scope]);
  const reportCompleted = useCallback(() => {
    if (completionTimer.current !== null) clearTimeout(completionTimer.current);
    completionTimer.current = setTimeout(() => {
      completionTimer.current = null;
      if (mounted.current) completedRef.current();
    }, 200);
  }, []);
  const run = useCallback(async () => {
    if (running.current || !ready) return;
    running.current = true;
    try {
      while (mounted.current) {
        const next = ref.current.find(
          (item) => item.state === "queued" && item.file && !item.paused,
        );
        if (!next || !next.file) break;
        activeKey.current = next.key;
        const file = next.file;
        const control = new AbortController();
        abort.current = control;
        update(next.key, {
          state: "uploading",
          error: undefined,
          conflict: false,
        });
        try {
          let job = next.job
            ? await api<UploadJob>("/uploads/" + next.job.id)
            : await api<UploadJob>("/uploads", "POST", {
                path: next.base,
                relative_path: next.relative,
                size: file.size,
                last_modified: file.lastModified,
                source_name: file.name,
                overwrite: Boolean(next.overwrite),
              });
          update(next.key, { job, received: job.received });
          if (job.status === "completed") {
            update(next.key, { state: "done", progress: 100 });
            reportCompleted();
            activeKey.current = null;
            continue;
          }
          if (next.verify) {
            job = await sendChunk(
              "/uploads/" + job.id + "/verify",
              file.slice(0, Math.min(job.received, 65536)),
              control.signal,
              undefined,
              "POST",
            );
            update(next.key, { verify: false });
          }
          while (job.received < file.size) {
            if (
              control.signal.aborted ||
              ref.current.find((item) => item.key === next.key)?.paused
            )
              throw new DOMException("Paused", "AbortError");
            const offset = job.received;
            const chunk = file.slice(offset, offset + 4 * 1024 * 1024);
            try {
              job = await sendChunk(
                "/uploads/" + job.id + "?offset=" + offset,
                chunk,
                control.signal,
                (loaded) =>
                  update(next.key, {
                    progress: Math.min(
                      99,
                      ((offset + loaded) / file.size) * 100,
                    ),
                  }),
              );
            } catch (error) {
              if (!(error instanceof APIError) || error.status !== 409)
                throw error;
              const latest = await api<UploadJob>("/uploads/" + job.id);
              if (latest.status !== "open" || latest.received === offset)
                throw error;
              job = latest;
            }
            update(next.key, {
              job,
              received: job.received,
              progress: file.size
                ? Math.min(99, (job.received / file.size) * 100)
                : 99,
            });
          }
          if (
            control.signal.aborted ||
            ref.current.find((item) => item.key === next.key)?.paused
          )
            throw new DOMException("Paused", "AbortError");
          await api("/uploads/" + job.id + "/complete", "POST");
          update(next.key, {
            state: "done",
            progress: 100,
            received: file.size,
            file: undefined,
          });
          reportCompleted();
        } catch (error) {
          const current = ref.current.find((item) => item.key === next.key);
          if (!current) {
            activeKey.current = null;
            continue;
          }
          if ((error as Error).name === "AbortError")
            update(next.key, { state: "paused" });
          else if (!(error instanceof APIError))
            update(next.key, {
              state: "waiting",
              error: "Connection lost. Your progress is saved.",
              retries: (current.retries || 0) + 1,
            });
          else
            update(next.key, {
              state: "error",
              error: error.message,
              conflict: error.status === 409,
            });
        }
        activeKey.current = null;
      }
    } finally {
      activeKey.current = null;
      running.current = false;
      abort.current = null;
    }
  }, [ready, update, reportCompleted]);
  runRef.current = run;
  useEffect(() => {
    void run();
  }, [run]);
  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const waiting = () => ref.current.some((item) => item.state === "waiting" && item.file && (item.retries || 0) <= 3);
    const schedule = () => {
      if (!ready || document.hidden || !navigator.onLine || !waiting()) {
        if (timer !== null) clearTimeout(timer);
        timer = null;
        return;
      }
      if (timer === null) timer = setTimeout(retry, 15000);
    };
    const retry = () => {
      timer = null;
      if (!ready || document.hidden || !navigator.onLine || !waiting()) { schedule(); return; }
      ref.current = ref.current.map((item) => item.state === "waiting" && item.file && (item.retries || 0) <= 3 ? { ...item, state: "queued" } : item);
      setTransfers(ref.current);
    };
    scheduleRetry.current = schedule;
    window.addEventListener("online", retry);
    window.addEventListener("offline", schedule);
    document.addEventListener("visibilitychange", schedule);
    schedule();
    return () => {
      scheduleRetry.current = () => {};
      if (timer !== null) clearTimeout(timer);
      window.removeEventListener("online", retry);
      window.removeEventListener("offline", schedule);
      document.removeEventListener("visibilitychange", schedule);
    };
  }, [ready, setTransfers]);
  const add = (sources: UploadSource[], base: string, replacement?: string) => {
    const fresh: Transfer[] = sources.map(({ file, relative }) => ({
      key:
        "transfer-" +
        Date.now().toString(36) +
        Math.random().toString(36).slice(2),
      file,
      relative: replacement || relative,
      base: replacement ? "" : base,
      size: file.size,
      modified: file.lastModified,
      sourceName: file.name,
      received: 0,
      progress: 0,
      state: "queued",
      overwrite: Boolean(replacement),
    }));
    ref.current = [...ref.current, ...fresh];
    setTransfers(ref.current);
  };
  const pause = (item: Transfer) => {
    update(item.key, { paused: true, state: "paused" });
    if (item.state === "uploading") abort.current?.abort();
  };
  const resume = (item: Transfer) =>
    update(item.key, {
      state: item.file ? "queued" : "missing",
      paused: false,
      retries: 0,
      error: undefined,
    });
  const cancel = async (item: Transfer) => {
    pause(item);
    const wait = () => new Promise((resolve) => setTimeout(resolve, 80));
    if (item.state === "uploading")
      while (activeKey.current === item.key) await wait();
    const latest = ref.current.find((current) => current.key === item.key);
    if (latest?.job) await api("/uploads/" + latest.job.id, "DELETE");
    ref.current = ref.current.filter((current) => current.key !== item.key);
    setTransfers(ref.current);
  };
  const replace = async (item: Transfer) => {
    if (item.job) await api("/uploads/" + item.job.id, "DELETE");
    update(item.key, {
      job: undefined,
      received: 0,
      progress: 0,
      overwrite: true,
      state: "queued",
      conflict: false,
      paused: false,
    });
  };
  const reselect = (item: Transfer, file: File) => {
    if (
      file.name !== (item.sourceName || item.relative.split("/").pop()) ||
      file.size !== item.size ||
      file.lastModified !== item.modified
    )
      throw new Error(
        "Choose the same original file, with matching name, size and modification time.",
      );
    update(item.key, {
      file,
      verify: true,
      paused: false,
      state: "queued",
      error: undefined,
    });
  };
  const clearDone = () => {
    ref.current = ref.current.filter((item) => item.state !== "done");
    setTransfers(ref.current);
  };
  return {
    subscribe,
    getSnapshot,
    add,
    pause,
    resume,
    cancel,
    replace,
    reselect,
    clearDone,
    reset,
  };
}

type DroppedEntry = {
  name: string;
  isFile: boolean;
  isDirectory: boolean;
  file: (
    ok: (file: File) => void,
    error: (error: DOMException) => void,
  ) => void;
  createReader: () => {
    readEntries: (
      ok: (entries: DroppedEntry[]) => void,
      error: (error: DOMException) => void,
    ) => void;
  };
};
export async function droppedFiles(
  data: DataTransfer,
): Promise<UploadSource[]> {
  const entries = [...data.items]
    .filter((item) => item.kind === "file")
    .map((item) => item.webkitGetAsEntry() as unknown as DroppedEntry | null);
  if (!entries.some(Boolean))
    return [...data.files].map((file) => ({ file, relative: file.name }));
  const result: UploadSource[] = [];
  async function visit(entry: DroppedEntry, prefix = "") {
    const relative = prefix + entry.name;
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) =>
        entry.file(resolve, reject),
      );
      result.push({ file, relative });
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      while (true) {
        const batch = await new Promise<DroppedEntry[]>((resolve, reject) =>
          reader.readEntries(resolve, reject),
        );
        if (!batch.length) break;
        for (const child of batch) await visit(child, relative + "/");
      }
    }
  }
  for (const entry of entries) if (entry) await visit(entry);
  return result;
}
