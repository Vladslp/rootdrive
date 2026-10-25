import { useEffect, useRef, useState, type PointerEvent } from "react";
import {
  Crop,
  FlipHorizontal2,
  Loader2,
  RotateCw,
  SlidersHorizontal,
} from "lucide-react";
import { type PhotoEdits } from "../services/editor";
import { PhotoViewport } from "./PhotoViewport";

export function PhotoEditor({
  path,
  revision,
  edits,
  change,
}: {
  path: string;
  revision: string;
  edits: PhotoEdits;
  change: (value: PhotoEdits) => void;
}) {
  const [image, setImage] = useState<HTMLImageElement | null>(null);
  const [error, setError] = useState("");
  const [cropping, setCropping] = useState(false);
  const [draft, setDraft] = useState<PhotoEdits["crop"] | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const start = useRef<[number, number] | null>(null);
  useEffect(() => {
    let active = true;
    setImage(null);
    setError("");
    const source = new Image();
    source.onload = () => {
      if (active) setImage(source);
    };
    source.onerror = () => {
      if (active) setError("The photo preview could not be loaded");
    };
    source.src =
      "/api/editor/image?path=" +
      encodeURIComponent(path) +
      "&revision=" +
      revision;
    return () => {
      active = false;
      source.onload = null;
      source.onerror = null;
    };
  }, [path, revision]);
  useEffect(() => {
    if (!image || !canvas.current) return;
    const rotated = document.createElement("canvas");
    const quarter = edits.rotation % 180 !== 0;
    rotated.width = quarter ? image.naturalHeight : image.naturalWidth;
    rotated.height = quarter ? image.naturalWidth : image.naturalHeight;
    const context = rotated.getContext("2d")!;
    context.translate(rotated.width / 2, rotated.height / 2);
    context.scale(edits.flip ? -1 : 1, 1);
    context.rotate((edits.rotation * Math.PI) / 180);
    context.drawImage(image, -image.naturalWidth / 2, -image.naturalHeight / 2);
    const crop = cropping ? [0, 0, 1, 1] : edits.crop;
    const left = crop[0] * rotated.width,
      top = crop[1] * rotated.height;
    const width = Math.max(1, (crop[2] - crop[0]) * rotated.width),
      height = Math.max(1, (crop[3] - crop[1]) * rotated.height);
    const target = canvas.current;
    target.width = Math.round(width);
    target.height = Math.round(height);
    const output = target.getContext("2d")!;
    output.drawImage(
      rotated,
      left,
      top,
      width,
      height,
      0,
      0,
      target.width,
      target.height,
    );
  }, [image, edits.rotation, edits.flip, edits.crop, cropping]);
  function point(event: PointerEvent<HTMLDivElement>): [number, number] {
    const box = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)),
      Math.max(0, Math.min(1, (event.clientY - box.top) / box.height)),
    ];
  }
  const selection = draft || edits.crop;
  const quarter = edits.rotation % 180 !== 0;
  const crop = cropping ? [0, 0, 1, 1] : edits.crop;
  const width = (quarter ? image?.naturalHeight || 1 : image?.naturalWidth || 1) * (crop[2] - crop[0]);
  const height = (quarter ? image?.naturalWidth || 1 : image?.naturalHeight || 1) * (crop[3] - crop[1]);
  function setCropEdge(index: number, percent: number) {
    const crop = [...edits.crop] as PhotoEdits["crop"];
    const value = percent / 100;
    crop[index] =
      index < 2
        ? Math.min(value, crop[index + 2] - 0.01)
        : Math.max(value, crop[index - 2] + 0.01);
    change({ ...edits, crop });
  }
  return (
    <div className="photo-editor">
      <div className="photo-stage">
        {error ? (
          <p role="alert">{error}</p>
        ) : !image ? (
          <Loader2 className="spin" />
        ) : (
          <PhotoViewport width={width} height={height} cropping={cropping}>
          <div
            className={"photo-canvas-wrap " + (cropping ? "cropping" : "")}
            onPointerDown={(event) => {
              if (!cropping) return;
              event.preventDefault();
              event.currentTarget.setPointerCapture(event.pointerId);
              start.current = point(event);
              setDraft([
                start.current[0],
                start.current[1],
                start.current[0],
                start.current[1],
              ]);
            }}
            onPointerMove={(event) => {
              if (!start.current) return;
              const current = point(event);
              setDraft([
                Math.min(start.current[0], current[0]),
                Math.min(start.current[1], current[1]),
                Math.max(start.current[0], current[0]),
                Math.max(start.current[1], current[1]),
              ]);
            }}
            onPointerUp={(event) => {
              if (!start.current) return;
              const current = point(event);
              const crop: PhotoEdits["crop"] = [
                Math.min(start.current[0], current[0]),
                Math.min(start.current[1], current[1]),
                Math.max(start.current[0], current[0]),
                Math.max(start.current[1], current[1]),
              ];
              if (crop[2] - crop[0] > 0.01 && crop[3] - crop[1] > 0.01)
                change({ ...edits, crop });
              start.current = null;
              setDraft(null);
            }}
            onPointerCancel={() => {
              start.current = null;
              setDraft(null);
            }}
          >
            <canvas
              ref={canvas}
              aria-label="Photo edit preview"
              style={{
                filter: `brightness(${edits.brightness}) contrast(${edits.contrast}) saturate(${edits.saturation})`,
              }}
            />
            {cropping && (
              <div
                className="crop-selection"
                style={{
                  left: selection[0] * 100 + "%",
                  top: selection[1] * 100 + "%",
                  width: (selection[2] - selection[0]) * 100 + "%",
                  height: (selection[3] - selection[1]) * 100 + "%",
                }}
              >
                <i />
                <i />
              </div>
            )}
          </div>
          </PhotoViewport>
        )}
      </div>
      <aside className="photo-tools">
        <span className="editor-tool-label">
          <Crop size={15} />
          Transform
        </span>
        <div className="photo-transform-buttons">
          <button
            className="button secondary"
            onClick={() =>
              change({
                ...edits,
                rotation: (edits.rotation + 90) % 360,
                crop: [0, 0, 1, 1],
              })
            }
          >
            <RotateCw size={17} />
            Rotate
          </button>
          <button
            className={"button secondary " + (edits.flip ? "active" : "")}
            aria-pressed={edits.flip}
            onClick={() =>
              change({ ...edits, flip: !edits.flip, crop: [0, 0, 1, 1] })
            }
          >
            <FlipHorizontal2 size={17} />
            Flip
          </button>
        </div>
        <button
          className={
            "button secondary crop-toggle " + (cropping ? "active" : "")
          }
          onClick={() => setCropping(!cropping)}
        >
          <Crop size={17} />
          {cropping ? "Apply crop view" : "Crop"}
        </button>
        {cropping && (
          <div className="crop-controls">
            <p>Drag on the photo or adjust the edges.</p>
            {["Left", "Top", "Right", "Bottom"].map((label, index) => (
              <label key={label}>
                {label}
                <input
                  type="range"
                  aria-label={label + " crop edge"}
                  min={index < 2 ? 0 : 1}
                  max={index < 2 ? 99 : 100}
                  value={Math.round(edits.crop[index] * 100)}
                  onChange={(event) =>
                    setCropEdge(index, Number(event.target.value))
                  }
                />
                <output>{Math.round(edits.crop[index] * 100)}%</output>
              </label>
            ))}
            <button
              className="text-button"
              onClick={() => change({ ...edits, crop: [0, 0, 1, 1] })}
            >
              Reset crop
            </button>
          </div>
        )}
        <span className="editor-tool-label">
          <SlidersHorizontal size={15} />
          Adjustments
        </span>
        {(
          [
            ["Brightness", "brightness", 20],
            ["Contrast", "contrast", 20],
            ["Saturation", "saturation", 0],
          ] as const
        ).map(([label, key, min]) => (
          <label className="photo-adjustment" key={key}>
            <span>
              {label}
              <output>{Math.round(edits[key] * 100)}%</output>
            </span>
            <input
              aria-label={label}
              type="range"
              min={min}
              max={200}
              value={Math.round(edits[key] * 100)}
              onChange={(event) =>
                change({ ...edits, [key]: Number(event.target.value) / 100 })
              }
            />
          </label>
        ))}
        <p className="editor-hint">
          Preview is scaled. Saved at original resolution.
        </p>
      </aside>
    </div>
  );
}
