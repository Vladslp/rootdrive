import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import {
  AlignLeft,
  Code2,
  Copy,
  FileText,
  Image as ImageIcon,
  Loader2,
  RotateCcw,
  Save,
  WrapText,
} from "lucide-react";
import { api, type Entry } from "../services/api";
import {
  defaultPhotoEdits,
  type EditorData,
  type Paragraph,
  type PDFPage,
  type PhotoEdits,
} from "../services/editor";
import { Dialog } from "./Dialog";
import { PhotoEditor } from "./PhotoEditor";

const PDFEditor = lazy(() => import("./PDFEditor"));
function ParagraphInput({
  paragraph,
  change,
}: {
  paragraph: Paragraph;
  change: (text: string) => void;
}) {
  const input = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const node = input.current;
    if (!node) return;
    const resize = () => {
      node.style.height = "0px";
      node.style.height = node.scrollHeight + "px";
    };
    resize();
    let width = node.clientWidth;
    const observer = new ResizeObserver(() => {
      if (node.clientWidth !== width) {
        width = node.clientWidth;
        resize();
      }
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [paragraph.text]);
  return (
    <textarea
      ref={input}
      aria-label={"Paragraph " + (paragraph.id + 1)}
      value={paragraph.text}
      rows={1}
      onChange={(event) => change(event.target.value)}
    />
  );
}
export default function EditorDialog({
  entry,
  close,
  saved,
}: {
  entry: Entry;
  close: () => void;
  saved: (entry: Entry, mode: "copy" | "original") => void;
}) {
  const [data, setData] = useState<EditorData | null>(null);
  const [text, setText] = useState("");
  const [photo, setPhoto] = useState<PhotoEdits>(defaultPhotoEdits);
  const [paragraphs, setParagraphs] = useState<Paragraph[]>([]);
  const [pages, setPages] = useState<PDFPage[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [wrap, setWrap] = useState(true);
  const initial = useRef("");
  const textBox = useRef<HTMLTextAreaElement>(null);
  const loadData = useCallback((value: EditorData) => {
    const next = {
      text: value.text || "",
      photo: defaultPhotoEdits,
      paragraphs: value.paragraphs || [],
      pages: Array.from({ length: value.pages || 0 }, (_, index) => ({
        index,
        rotation: 0,
      })),
    };
    setData(value);
    setText(next.text);
    setPhoto(next.photo);
    setParagraphs(next.paragraphs);
    setPages(next.pages);
    initial.current = JSON.stringify(next);
  }, []);
  useEffect(() => {
    let active = true;
    api<EditorData>("/editor?path=" + encodeURIComponent(entry.path))
      .then((value) => {
        if (active) loadData(value);
      })
      .catch((error) => {
        if (active) setError((error as Error).message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [entry.path, loadData]);
  const dirty =
    !!data &&
    JSON.stringify({ text, photo, paragraphs, pages }) !== initial.current;
  useEffect(() => {
    if (!dirty) return;
    const guard = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
  const save = useCallback(async (mode: "copy" | "original" = "original") => {
    if (!data || !dirty || busy) return;
    setBusy(true);
    setError("");
    try {
      const changes =
        data.kind === "text"
          ? { text }
          : data.kind === "photo"
            ? { photo }
            : data.kind === "pdf"
              ? { pages }
              : {
                  paragraphs: paragraphs
                    .filter(
                      (item) =>
                        item.editable &&
                        item.text !==
                          data.paragraphs?.find(
                            (original) => original.id === item.id,
                          )?.text,
                    )
                    .map(({ id, text }) => ({ id, text })),
                };
      const result = await api<EditorData & { entry: Entry }>(
        "/editor",
        "POST",
        {
          path: entry.path,
          revision: data.revision,
          kind: data.kind,
          mode,
          ...changes,
        },
      );
      saved(result.entry, mode);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }, [
    data,
    dirty,
    busy,
    text,
    photo,
    paragraphs,
    pages,
    entry.path,
    loadData,
    saved,
  ]);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void save(event.shiftKey ? "copy" : "original");
      }
    };
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, [save]);
  function requestClose() {
    if (!busy && (!dirty || window.confirm("Discard unsaved changes?")))
      close();
  }
  return (
    <Dialog
      title={entry.name}
      close={requestClose}
      className={"editor-dialog editor-" + (data?.kind || "loading")}
    >
      {loading ? (
        <div className="loading-area">
          <Loader2 className="spin" />
        </div>
      ) : (
        <>
          {data && (
            <div className="editor-toolbar">
              <span className="editor-mode">
                {data.kind === "photo" ? (
                  <ImageIcon size={17} />
                ) : data.kind === "text" ? (
                  <Code2 size={17} />
                ) : (
                  <FileText size={17} />
                )}
                {data.kind === "photo"
                  ? "Photo studio"
                  : data.kind === "text"
                    ? "Text editor"
                    : data.kind === "pdf"
                      ? "PDF pages"
                      : "Document text"}
              </span>
              <span className="editor-format">
                {data.format?.toUpperCase()}
                {data.kind === "text" && " · UTF-8"}
              </span>
              {data.kind === "text" && (
                <button
                  className={"icon-button " + (wrap ? "active" : "")}
                  aria-label="Toggle line wrapping"
                  aria-pressed={wrap}
                  onClick={() => setWrap(!wrap)}
                >
                  <WrapText size={18} />
                </button>
              )}
            </div>
          )}
          {error && (
            <p className="editor-error error-banner" role="alert">
              {error}
            </p>
          )}
          {data && (
            <fieldset disabled={busy} className="editor-workspace">
              {data.kind === "text" && (
                <div className="text-editor">
                  <textarea
                    ref={textBox}
                    aria-label="File contents"
                    spellCheck={false}
                    wrap={wrap ? "soft" : "off"}
                    value={text}
                    onChange={(event) => {
                      setText(event.target.value);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Tab") {
                        event.preventDefault();
                        const node = event.currentTarget;
                        const start = node.selectionStart;
                        document.execCommand("insertText", false, "  ");
                        if (node.value === text) {
                          setText(
                            text.slice(0, start) +
                              "  " +
                              text.slice(node.selectionEnd),
                          );
                          requestAnimationFrame(() => {
                            node.selectionStart = node.selectionEnd = start + 2;
                          });
                        }
                      }
                    }}
                  />
                </div>
              )}
              {data.kind === "photo" && (
                <PhotoEditor
                  path={entry.path}
                  revision={data.revision}
                  edits={photo}
                  change={(value) => {
                    setPhoto(value);
                  }}
                />
              )}
              {data.kind === "document" && (
                <div className="document-editor">
                  <div className="document-note">
                    <AlignLeft size={16} />
                    Edit paragraph text. Layout and embedded objects stay in the
                    document.
                  </div>
                  <div className="document-paper">
                    {paragraphs.map((item) => (
                      <div
                        className={
                          "document-paragraph " +
                          (item.heading ? "document-heading" : "")
                        }
                        key={item.id}
                      >
                        {item.editable ? (
                          <ParagraphInput
                            paragraph={item}
                            change={(text) => {
                              setParagraphs((current) =>
                                current.map((paragraph) =>
                                  paragraph.id === item.id
                                    ? { ...paragraph, text }
                                    : paragraph,
                                ),
                              );
                            }}
                          />
                        ) : (
                          <div className="document-locked">
                            <p>{item.text || "Embedded content"}</p>
                            <span>Preserved</span>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {data.kind === "pdf" && (
                <Suspense
                  fallback={
                    <div className="loading-area">
                      <Loader2 className="spin" />
                    </div>
                  }
                >
                  <PDFEditor
                    path={entry.path}
                    revision={data.revision}
                    pages={pages}
                    change={(value) => {
                      setPages(value);
                    }}
                  />
                </Suspense>
              )}
            </fieldset>
          )}
          <div className="editor-footer">
            <span className="editor-save-state" aria-live="polite">
              {busy ? (
                <>
                  <Loader2 size={14} className="spin" />
                  Saving…
                </>
              ) : dirty ? (
                <>
                  <i />
                  Unsaved changes
                </>
              ) : data?.kind === "text" ? (
                `${text.split("\n").length.toLocaleString()} lines · ${text.length.toLocaleString()} characters`
              ) : (
                "Ready to edit"
              )}
            </span>
            {data && dirty && (
              <button
                className="button secondary editor-reset"
                disabled={busy}
                onClick={() => {
                  if (window.confirm("Reset all unsaved changes?"))
                    loadData(data);
                }}
              >
                <RotateCcw size={15} />
                Reset
              </button>
            )}
            <button
              className="button secondary"
              disabled={busy}
              onClick={requestClose}
            >
              Close
            </button>
            {data && (
              <button
                className="button secondary"
                disabled={busy || !dirty}
                onClick={() => void save("copy")}
                title="Save a separate copy · Ctrl/Cmd+Shift+S"
              >
                <Copy size={16} />
                Save copy
              </button>
            )}
            {data && (
              <button
                className="button primary"
                disabled={busy || !dirty}
                onClick={() => void save("original")}
                title="Save original with version history · Ctrl/Cmd+S"
              >
                <Save size={16} />
                Save
              </button>
            )}
          </div>
        </>
      )}
    </Dialog>
  );
}
