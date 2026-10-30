import { useState, type FormEvent } from "react";
import { KeyRound, Loader2 } from "lucide-react";
import { api, setCSRF, type Account } from "../services/api";

export function PasswordSettings({ account, changed, notify }: { account: Account; changed: () => Promise<void>; notify: (message: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [current, setCurrent] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  if (!account.auth_enabled || !account.user) return null;
  function clear() { setCurrent(""); setPassword(""); setConfirmation(""); setError(""); setExpanded(false); }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    if (password !== confirmation) { setError("Passwords do not match"); return; }
    setPending(true); setError("");
    try {
      const result = await api<{ csrf_token: string }>("/auth/password", "POST", { current_password: current, new_password: password });
      setCSRF(result.csrf_token);
      await changed();
      clear();
      notify("Password changed. Other sessions were signed out");
    } catch (error) { setError((error as Error).message); }
    finally { setPending(false); }
  }
  return <section className="settings-section" aria-label="Account security">
    <h3><KeyRound size={18} />Account security</h3>
    {!expanded ? <button className="button secondary" onClick={() => setExpanded(true)}>Change password</button> :
      <form className="password-form" aria-label="Change password" onSubmit={submit}>
        <label className="field-label">Current password<input name="currentPassword" type="password" autoComplete="current-password" required maxLength={1024} disabled={pending} value={current} onChange={(event) => setCurrent(event.target.value)} /></label>
        <label className="field-label">New password<input name="newPassword" type="password" autoComplete="new-password" required minLength={10} maxLength={1024} disabled={pending} value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        <label className="field-label">Confirm new password<input name="confirmPassword" type="password" autoComplete="new-password" required minLength={10} maxLength={1024} disabled={pending} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} /></label>
        <p className="muted">At least 10 characters. Other sessions will be signed out.</p>
        {error && <p className="error-text" role="alert">{error}</p>}
        <div className="dialog-actions"><button className="button secondary" type="button" disabled={pending} onClick={clear}>Cancel</button><button className="button primary" disabled={pending}>{pending && <Loader2 size={16} className="spin" />}Save password</button></div>
      </form>}
  </section>;
}
