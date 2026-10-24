import { useRef, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  FileUp,
  Pause,
  Play,
  RotateCcw,
  Upload,
  X,
} from "lucide-react";
import { bytes } from "../services/api";
import type { useUploads, Transfer } from "../hooks/useUploads";

export function UploadQueue({
  queue,
  notify,
}: {
  queue: ReturnType<typeof useUploads>;
  notify: (text: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [reselecting, setReselecting] = useState<Transfer | null>(null);
  const input = useRef<HTMLInputElement>(null);
  if (!queue.transfers.length) return null;
  const active = queue.transfers.filter((item) => item.state !== "done").length;
  const safe = (action: Promise<unknown>) =>
    action.catch((error) => notify(error.message));
  return (
    <section className="upload-queue" aria-label="Transfers">
      <header>
        <button onClick={() => setCollapsed(!collapsed)}>
          <Upload size={17} />
          <strong>
            {active
              ? `${active} upload${active === 1 ? "" : "s"}`
              : "Uploads complete"}
          </strong>
          {collapsed ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
        {queue.transfers.some((item) => item.state === "done") && (
          <button
            className="icon-button"
            aria-label="Clear completed uploads"
            onClick={queue.clearDone}
          >
            <X size={17} />
          </button>
        )}
      </header>
      {!collapsed && (
        <div className="transfers">
          {queue.transfers.map((item) => (
            <div className={"transfer " + item.state} key={item.key}>
              <div className="transfer-icon">
                {item.state === "done" ? (
                  <Check size={20} />
                ) : (
                  <FileUp size={20} />
                )}
              </div>
              <div className="transfer-body">
                <strong title={item.relative}>{item.relative}</strong>
                <span>
                  {item.state === "done"
                    ? "Complete"
                    : item.state === "missing"
                      ? "Select original file to resume"
                      : item.state === "paused"
                        ? "Paused"
                        : item.error ||
                          `${bytes(item.received)} / ${bytes(item.size)}`}
                </span>
                {item.state !== "done" && (
                  <div className="progress-track">
                    <i style={{ width: item.progress + "%" }} />
                  </div>
                )}
                {item.conflict && (
                  <button
                    className="text-button"
                    onClick={() => safe(queue.replace(item))}
                  >
                    Replace & keep previous version
                  </button>
                )}
              </div>
              <div className="transfer-actions">
                {item.state === "uploading" || item.state === "queued" ? (
                  <button
                    className="icon-button"
                    onClick={() => queue.pause(item)}
                    aria-label={"Pause " + item.relative}
                  >
                    <Pause size={16} />
                  </button>
                ) : item.state === "missing" ? (
                  <button
                    className="icon-button"
                    onClick={() => {
                      setReselecting(item);
                      input.current?.click();
                    }}
                    aria-label={"Select original " + item.relative}
                  >
                    <FileUp size={17} />
                  </button>
                ) : (
                  item.state !== "done" &&
                  !item.conflict && (
                    <button
                      className="icon-button"
                      onClick={() => queue.resume(item)}
                      aria-label={"Resume " + item.relative}
                    >
                      {item.state === "error" ? (
                        <RotateCcw size={16} />
                      ) : (
                        <Play size={16} />
                      )}
                    </button>
                  )
                )}
                {item.state !== "done" && (
                  <button
                    className="icon-button"
                    onClick={() => safe(queue.cancel(item))}
                    aria-label={"Cancel " + item.relative}
                  >
                    <X size={16} />
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
      <input
        ref={input}
        type="file"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file && reselecting) {
            try {
              queue.reselect(reselecting, file);
            } catch (error) {
              notify((error as Error).message);
            }
          }
          event.target.value = "";
        }}
      />
    </section>
  );
}
