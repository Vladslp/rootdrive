import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Check, Loader2, Upload } from "lucide-react";
import { api, bytes, type Account } from "../services/api";

export function UploadLimitSettings({
  account,
  saved,
}: {
  account: Account;
  saved: (limit: number) => void;
}) {
  const [limit, setLimit] = useState(account.max_upload_size_mb);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const editable = !account.auth_enabled || account.user?.role === "admin";
  const values = useMemo(
    () =>
      [
        ...new Set([
          ...Array.from({ length: 17 }, (_, index) => 2 ** index),
          account.max_upload_size_mb,
        ]),
      ].sort((left, right) => left - right),
    [account.max_upload_size_mb],
  );
  const position = Math.max(0, values.indexOf(limit));
  const changed = limit !== account.max_upload_size_mb;
  useEffect(() => {
    setLimit(account.max_upload_size_mb);
    setError("");
  }, [account.max_upload_size_mb]);
  async function save() {
    setBusy(true);
    setError("");
    try {
      const response = await api<{ max_upload_size_mb: number }>(
        "/settings",
        "PATCH",
        { max_upload_size_mb: limit },
      );
      saved(response.max_upload_size_mb);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section
      className="settings-section upload-limit-settings"
      aria-label="Uploads"
    >
      <div className="section-heading">
        <h3>
          <Upload size={18} />
          Uploads
        </h3>
        <output htmlFor="upload-limit">{bytes(limit * 1024 * 1024)}</output>
      </div>
      <label htmlFor="upload-limit" className="upload-limit-label">
        Upload limit<span>per file</span>
      </label>
      <input
        id="upload-limit"
        className="upload-range"
        type="range"
        min={0}
        max={values.length - 1}
        step={1}
        value={position}
        aria-valuetext={bytes(limit * 1024 * 1024) + " per file"}
        disabled={!editable || busy}
        style={
          {
            "--range-progress": (position / (values.length - 1)) * 100 + "%",
          } as CSSProperties
        }
        onChange={(event) => setLimit(values[Number(event.target.value)])}
      />
      <div className="range-labels">
        <span>{bytes(values[0] * 1024 * 1024)}</span>
        <span>{bytes(values[values.length - 1] * 1024 * 1024)}</span>
      </div>
      <div className="upload-limit-footer">
        <span>
          {editable
            ? "Saved on this server"
            : "Only administrators can change this"}
        </span>
        {editable && (
          <button
            className="button primary"
            disabled={!changed || busy}
            onClick={save}
          >
            {busy ? (
              <Loader2 size={15} className="spin" />
            ) : (
              <Check size={15} />
            )}
            Save
          </button>
        )}
      </div>
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
