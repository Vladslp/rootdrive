import { useCallback, useEffect, useState, type FormEvent } from "react";
import {
  ChevronDown,
  Loader2,
  Plus,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import { api, type Account } from "../services/api";

type User = { id: number; username: string; role: string; created_at: number };
type UserPage = { items: User[]; total: number };

export function UsersSettings({
  account,
  notify,
}: {
  account: Account | null;
  notify: (message: string) => void;
}) {
  const [page, setPage] = useState<UserPage>({ items: [], total: 0 });
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [formError, setFormError] = useState("");
  const admin = Boolean(
    account?.auth_enabled && account.user?.role === "admin",
  );
  const load = useCallback(
    async (start: number) => {
      if (!admin) return;
      setLoading(true);
      setError("");
      try {
        setPage(await api<UserPage>(`/auth/users?offset=${start}&limit=20`));
      } catch (error) {
        setError((error as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [admin],
  );
  useEffect(() => {
    load(offset);
  }, [load, offset]);
  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaving(true);
    setFormError("");
    try {
      await api("/auth/users", "POST", {
        username: form.get("username"),
        password: form.get("password"),
        role: form.get("role"),
      });
      setCreating(false);
      setOffset(0);
      await load(0);
      notify("User created");
    } catch (error) {
      setFormError((error as Error).message);
    } finally {
      setSaving(false);
    }
  };
  return (
    <section className="users-settings" aria-label="Users">
      <div className="users-heading">
        <div>
          <h3>
            <Users size={18} />
            Users
          </h3>
          <p>Personal and shared spaces.</p>
        </div>
        {admin && (
          <button
            className="button secondary"
            onClick={() => {
              setCreating(true);
              setFormError("");
            }}
            disabled={creating}
          >
            <Plus size={16} />
            Add user
          </button>
        )}
      </div>
      {!account?.auth_enabled ? (
        <div className="users-locked">
          <span className="badge">Sign-in is off</span>
          <details>
            <summary>
              Set up users <ChevronDown size={14} />
            </summary>
            <p>Create the first administrator in your terminal:</p>
            <code>python run.py create-admin --username admin</code>
            <p>
              Set <code>AUTH_ENABLED=true</code> in <code>.env</code>, restart,
              then sign in.
            </p>
          </details>
        </div>
      ) : !admin ? (
        <p className="muted users-note">
          <ShieldCheck size={16} />
          Only administrators can manage users.
        </p>
      ) : (
        <>
          {creating && (
            <form
              className="user-form"
              onSubmit={create}
              aria-label="Create user"
            >
              <div className="user-form-heading">
                <strong>New user</strong>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Cancel new user"
                  disabled={saving}
                  onClick={() => setCreating(false)}
                >
                  <X size={16} />
                </button>
              </div>
              <div className="user-form-grid">
                <label className="field-label">
                  Username
                  <input
                    name="username"
                    required
                    minLength={1}
                    maxLength={80}
                    autoComplete="off"
                    autoFocus
                  />
                </label>
                <label className="field-label">
                  Role
                  <select name="role" defaultValue="user">
                    <option value="user">Member</option>
                    <option value="admin">Administrator</option>
                  </select>
                </label>
              </div>
              <label className="field-label">
                Password
                <input
                  name="password"
                  type="password"
                  required
                  minLength={10}
                  maxLength={1024}
                  autoComplete="new-password"
                  placeholder="At least 10 characters"
                />
              </label>
              {formError && (
                <p className="error-text" role="alert">
                  {formError}
                </p>
              )}
              <div className="dialog-actions">
                <button
                  type="button"
                  className="button secondary"
                  disabled={saving}
                  onClick={() => setCreating(false)}
                >
                  Cancel
                </button>
                <button className="button primary" disabled={saving}>
                  {saving && <Loader2 size={15} className="spin" />}Create user
                </button>
              </div>
            </form>
          )}
          {loading ? (
            <p className="users-note muted">
              <Loader2 size={17} className="spin" />
              Loading users…
            </p>
          ) : error ? (
            <div className="error-banner" role="alert">
              <span>{error}</span>
              <button onClick={() => load(offset)}>Try again</button>
            </div>
          ) : (
            <div className="users-list">
              {page.items.map((user) => (
                <div key={user.id} className="user-row">
                  <span className="user-avatar">
                    {user.username.slice(0, 1).toUpperCase()}
                  </span>
                  <div>
                    <strong>
                      {user.username}
                      {user.username === account?.user?.username && (
                        <small>You</small>
                      )}
                    </strong>
                    <span>
                      Joined{" "}
                      {new Date(user.created_at * 1000).toLocaleDateString(
                        "en",
                        { month: "short", day: "numeric", year: "numeric" },
                      )}
                    </span>
                  </div>
                  <span className="badge">
                    {user.role === "admin" ? "Administrator" : "Member"}
                  </span>
                </div>
              ))}
            </div>
          )}
          <div className="users-list-footer">
            <span>
              {page.total} {page.total === 1 ? "user" : "users"}
            </span>
            {page.total > 20 && (
              <div className="pagination">
                <button
                  disabled={!offset || loading}
                  onClick={() => setOffset(Math.max(0, offset - 20))}
                >
                  Previous
                </button>
                <button
                  disabled={offset + 20 >= page.total || loading}
                  onClick={() => setOffset(offset + 20)}
                >
                  Next
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </section>
  );
}
