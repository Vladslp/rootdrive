import { useEffect, useState } from "react";
import { Download, Eye, Loader2 } from "lucide-react";
import { api, apiBlob, type Entry } from "../services/api";
import { Dialog } from "./Dialog";
export default function PhotoStudio({
  entries,
  close,
  saved,
}: {
  entries: Entry[];
  close: () => void;
  saved: () => void;
}) {
  const [settings, setSettings] = useState({
    format: "jpeg",
    quality: 88,
    width: 2560,
    height: 2560,
    strip_metadata: true,
    watermark: "",
    logo: "",
    opacity: 0.65,
    position: "bottom-right",
  });
  const [preview, setPreview] = useState("");
  const [stale, setStale] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [logos, setLogos] = useState<Entry[]>([]);
  const [logoQuery, setLogoQuery] = useState("");
  useEffect(() => {
    if (logoQuery.length < 2) {
      setLogos([]);
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      api<{ items: Entry[] }>(
        "/search?" +
          new URLSearchParams({ q: logoQuery, recursive: "true", limit: "20" }),
        "GET",
        undefined,
        controller.signal,
      )
        .then((data) =>
          setLogos(
            data.items.filter((entry) =>
              /\.(png|webp|jpe?g)$/i.test(entry.name),
            ),
          ),
        )
        .catch(() => {});
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [logoQuery]);
  useEffect(() => {
    setStale(true);
  }, [settings]);
  useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview);
    },
    [preview],
  );
  function change(
    key: keyof typeof settings,
    value: string | number | boolean,
  ) {
    setSettings((current) => ({ ...current, [key]: value }));
  }
  async function run(save: boolean) {
    setBusy(true);
    setError("");
    try {
      const body = { ...settings, paths: entries.map((entry) => entry.path) };
      if (save) {
        await api("/studio/export", "POST", body);
        saved();
      } else {
        const blob = await apiBlob("/studio/preview", body);
        setPreview(URL.createObjectURL(blob));
        setStale(false);
      }
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={
        entries.length === 1
          ? "Export photo"
          : `Export ${entries.length} photos`
      }
      wide
      close={() => {
        if (!busy) close();
      }}
      className="studio-dialog"
    >
      <div className="studio-layout">
        <div className="studio-preview">
          {preview ? (
            <img src={preview} alt="Export preview" />
          ) : (
            <p className="muted">Preview your export</p>
          )}
          {preview && stale && <span>Settings changed · refresh preview</span>}
        </div>
        <fieldset className="studio-controls" disabled={busy}>
          <label className="field-label">
            Format
            <select
              value={settings.format}
              onChange={(event) => change("format", event.target.value)}
            >
              <option value="jpeg">JPEG</option>
              <option value="png">PNG</option>
              <option value="webp">WebP</option>
            </select>
          </label>
          {settings.format !== "png" && (
            <label className="field-label">
              Quality · {settings.quality}%
              <input
                type="range"
                min={10}
                max={100}
                value={settings.quality}
                onChange={(event) =>
                  change("quality", Number(event.target.value))
                }
              />
            </label>
          )}
          <div className="studio-dimensions">
            <label className="field-label">
              Max width
              <input
                type="number"
                min={1}
                max={20000}
                value={settings.width}
                onChange={(event) =>
                  change("width", Number(event.target.value))
                }
              />
            </label>
            <label className="field-label">
              Max height
              <input
                type="number"
                min={1}
                max={20000}
                value={settings.height}
                onChange={(event) =>
                  change("height", Number(event.target.value))
                }
              />
            </label>
          </div>
          <label className="studio-check">
            <input
              type="checkbox"
              checked={settings.strip_metadata}
              onChange={(event) =>
                change("strip_metadata", event.target.checked)
              }
            />
            Remove EXIF and GPS
          </label>
          <label className="field-label">
            Watermark text
            <input
              maxLength={120}
              value={settings.watermark}
              onChange={(event) => {
                change("watermark", event.target.value);
                change("logo", "");
              }}
              placeholder="Optional"
            />
          </label>
          <label className="field-label">
            Or use a logo
            <input
              value={logoQuery}
              onChange={(event) => setLogoQuery(event.target.value)}
              placeholder="Find an uploaded image"
            />
            <select
              aria-label="Watermark logo"
              value={settings.logo}
              onChange={(event) => change("logo", event.target.value)}
            >
              <option value="">No logo</option>
              {settings.logo &&
                !logos.some((item) => item.path === settings.logo) && (
                  <option value={settings.logo}>{settings.logo}</option>
                )}
              {logos.map((item) => (
                <option key={item.path} value={item.path}>
                  {item.path}
                </option>
              ))}
            </select>
          </label>
          {(settings.watermark || settings.logo) && (
            <>
              <label className="field-label">
                Opacity · {Math.round(settings.opacity * 100)}%
                <input
                  type="range"
                  min={0.05}
                  max={1}
                  step={0.05}
                  value={settings.opacity}
                  onChange={(event) =>
                    change("opacity", Number(event.target.value))
                  }
                />
              </label>
              <label className="field-label">
                Position
                <select
                  value={settings.position}
                  onChange={(event) => change("position", event.target.value)}
                >
                  {[
                    "bottom-right",
                    "bottom-left",
                    "top-right",
                    "top-left",
                    "center",
                  ].map((value) => (
                    <option key={value} value={value}>
                      {value.replace("-", " ")}
                    </option>
                  ))}
                </select>
              </label>
            </>
          )}
        </fieldset>
      </div>
      <p className="muted">
        Copies are saved beside the originals. Aspect ratio stays unchanged.
      </p>
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}
      <div className="dialog-actions">
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => void run(false)}
        >
          <Eye size={16} />
          Preview
        </button>
        <button
          className="button primary"
          disabled={
            busy ||
            settings.width < 1 ||
            settings.height < 1 ||
            entries.length > 20
          }
          onClick={() => void run(true)}
        >
          {busy ? (
            <Loader2 className="spin" size={16} />
          ) : (
            <Download size={16} />
          )}
          Save {entries.length === 1 ? "copy" : "copies"}
        </button>
      </div>
    </Dialog>
  );
}
