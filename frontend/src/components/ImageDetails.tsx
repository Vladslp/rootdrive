import { useEffect, useState } from "react";
import { Camera, ChevronDown, Loader2 } from "lucide-react";
import { api, type Entry } from "../services/api";

type Metadata = {
  width: number;
  height: number;
  format: string;
  exif: { label: string; value: string }[];
};
export function ImageDetails({ entry }: { entry: Entry }) {
  const [metadata, setMetadata] = useState<Metadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    setMetadata(null);
    setLoading(true);
    setError("");
    api<Metadata>("/files/metadata?path=" + encodeURIComponent(entry.path))
      .then((result) => {
        if (active) setMetadata(result);
      })
      .catch((error) => {
        if (active) setError(error.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [entry.path, entry.modified]);
  return (
    <div className="image-details">
      {metadata && (
        <dl className="properties-list image-dimensions">
          <div>
            <dt>Dimensions</dt>
            <dd>
              {metadata.width.toLocaleString("en")} ×{" "}
              {metadata.height.toLocaleString("en")} px
            </dd>
          </div>
        </dl>
      )}
      <details className="exif-section">
        <summary>
          <Camera size={16} />
          <span>EXIF</span>
          {metadata && <small>{metadata.exif.length}</small>}
          <ChevronDown size={15} />
        </summary>
        <div className="exif-content">
          {loading ? (
            <p className="muted exif-loading">
              <Loader2 className="spin" size={15} />
              Reading metadata…
            </p>
          ) : error ? (
            <p className="muted">{error}</p>
          ) : metadata?.exif.length ? (
            <dl className="exif-list">
              {metadata.exif.map((field) => (
                <div key={field.label}>
                  <dt>{field.label}</dt>
                  <dd>{field.value}</dd>
                </div>
              ))}
            </dl>
          ) : (
            <p className="muted">No EXIF metadata in this file.</p>
          )}
        </div>
      </details>
    </div>
  );
}
