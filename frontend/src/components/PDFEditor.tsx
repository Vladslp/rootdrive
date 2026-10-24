import { useEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Loader2, RotateCw, Trash2 } from "lucide-react";
import {
  getDocument,
  GlobalWorkerOptions,
  type PDFDocumentProxy,
  type RenderTask,
} from "pdfjs-dist";
import workerURL from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import type { PDFPage } from "../services/editor";

GlobalWorkerOptions.workerSrc = workerURL;
function PageThumbnail({
  document,
  page,
  position,
  count,
  rotate,
  move,
  remove,
}: {
  document: PDFDocumentProxy;
  page: PDFPage;
  position: number;
  count: number;
  rotate: () => void;
  move: (delta: number) => void;
  remove: () => void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [visible, setVisible] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "150px" },
    );
    if (box.current) observer.observe(box.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!visible) return;
    let active = true;
    let task: RenderTask | undefined;
    const target = window.document.createElement("canvas");
    void document
      .getPage(page.index + 1)
      .then(async (source) => {
        if (!active) return;
        const rotation = (source.rotate + page.rotation) % 360;
        const base = source.getViewport({ scale: 1, rotation });
        const viewport = source.getViewport({
          scale: Math.min(440 / base.width, 560 / base.height),
          rotation,
        });
        target.width = Math.ceil(viewport.width);
        target.height = Math.ceil(viewport.height);
        task = source.render({ canvas: target, viewport });
        await task.promise;
        if (active && canvas.current) {
          canvas.current.width = target.width;
          canvas.current.height = target.height;
          canvas.current.getContext("2d")?.drawImage(target, 0, 0);
          setError("");
        }
      })
      .catch((error) => {
        if (active && (error as Error).name !== "RenderingCancelledException")
          setError("Preview unavailable");
      });
    return () => {
      active = false;
      task?.cancel();
    };
  }, [document, page.index, page.rotation, visible]);
  return (
    <div className="pdf-page-card" ref={box}>
      <div className="pdf-page-preview">
        {error ? (
          <span>{error}</span>
        ) : (
          <canvas
            ref={canvas}
            aria-label={"Preview of original page " + (page.index + 1)}
          />
        )}
      </div>
      <div className="pdf-page-caption">
        <span>
          Page {position + 1}
          <small>Original {page.index + 1}</small>
        </span>
        <div>
          <button
            className="icon-button"
            aria-label={"Move page " + (position + 1) + " up"}
            disabled={position === 0}
            onClick={() => move(-1)}
          >
            <ArrowUp size={16} />
          </button>
          <button
            className="icon-button"
            aria-label={"Move page " + (position + 1) + " down"}
            disabled={position === count - 1}
            onClick={() => move(1)}
          >
            <ArrowDown size={16} />
          </button>
          <button
            className="icon-button"
            aria-label={"Rotate page " + (position + 1)}
            onClick={rotate}
          >
            <RotateCw size={16} />
          </button>
          <button
            className="icon-button danger-text"
            aria-label={"Remove page " + (position + 1)}
            disabled={count === 1}
            onClick={remove}
          >
            <Trash2 size={16} />
          </button>
        </div>
      </div>
    </div>
  );
}
export default function PDFEditor({
  path,
  revision,
  pages,
  change,
}: {
  path: string;
  revision: string;
  pages: PDFPage[];
  change: (value: PDFPage[]) => void;
}) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setDocument(null);
    setError("");
    const task = getDocument({
      url:
        "/api/files/media?path=" +
        encodeURIComponent(path) +
        "&revision=" +
        revision,
      useSystemFonts: true,
      cMapUrl: "/assets/pdfjs/cmaps/",
      cMapPacked: true,
      standardFontDataUrl: "/assets/pdfjs/standard_fonts/",
      wasmUrl: "/assets/pdfjs/wasm/",
      disableAutoFetch: true,
    });
    task.promise
      .then((value) => {
        if (active) setDocument(value);
      })
      .catch((error) => {
        if (active) setError((error as Error).message);
      });
    return () => {
      active = false;
      void task.destroy();
    };
  }, [path, revision]);
  function move(position: number, delta: number) {
    const next = [...pages];
    [next[position], next[position + delta]] = [
      next[position + delta],
      next[position],
    ];
    change(next);
  }
  return (
    <div className="pdf-editor">
      <p className="document-note">Reorder, rotate or remove pages.</p>
      {error ? (
        <p role="alert" className="error-banner">
          {error}
        </p>
      ) : !document ? (
        <div className="loading-area">
          <Loader2 className="spin" />
        </div>
      ) : (
        <div className="pdf-page-grid">
          {pages.map((page, position) => (
            <PageThumbnail
              document={document}
              page={page}
              key={revision + ":" + page.index}
              position={position}
              count={pages.length}
              rotate={() =>
                change(
                  pages.map((item, index) =>
                    index === position
                      ? { ...item, rotation: (item.rotation + 90) % 360 }
                      : item,
                  ),
                )
              }
              move={(delta) => move(position, delta)}
              remove={() =>
                change(pages.filter((_, index) => index !== position))
              }
            />
          ))}
        </div>
      )}
    </div>
  );
}
