import { useEffect, useState } from "react";
import { Plus, Users, X } from "lucide-react";
import { api, type Space } from "../services/api";
type Member = { id: number; username: string; role: string };
export function SpaceSettings() {
  const [spaces, setSpaces] = useState<Space[]>([]);
  const [name, setName] = useState("");
  const [active, setActive] = useState<Space | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [username, setUsername] = useState("");
  const [role, setRole] = useState("reader");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    const data = await api<{ items: Space[] }>("/spaces");
    setSpaces(data.items);
  }
  useEffect(() => {
    void load().catch((error) => setError(error.message));
  }, []);
  async function manage(space: Space) {
    setActive(space);
    setError("");
    try {
      setMembers(
        (await api<{ items: Member[] }>("/spaces/" + space.id + "/members"))
          .items,
      );
    } catch (error) {
      setError((error as Error).message);
    }
  }
  async function mutate(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
      await load();
      window.dispatchEvent(new window.Event("rootdrive:spaces-changed"));
      if (active) await manage(active);
    } catch (error) {
      setError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="settings-section">
      <h3>
        <Users size={19} />
        Spaces
      </h3>
      <p className="muted">
        Personal files stay private. Invite existing accounts to a shared space.
      </p>
      <form
        className="space-create"
        onSubmit={(event) => {
          event.preventDefault();
          void mutate(async () => {
            await api("/spaces", "POST", { name });
            setName("");
          });
        }}
      >
        <input
          aria-label="New shared space name"
          placeholder="New shared space"
          maxLength={80}
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
        />
        <button className="button secondary" disabled={busy || !name.trim()}>
          <Plus size={16} />
          Create
        </button>
      </form>
      <div className="spaces-list">
        {spaces.map((space) => (
          <div className="space-row" key={space.id}>
            <div>
              <strong>{space.name}</strong>
              <small>
                {space.kind === "personal"
                  ? "Only you"
                  : space.kind === "legacy"
                    ? "All signed-in accounts"
                    : space.role === "reader"
                      ? "Read only"
                      : space.owner
                        ? "Owner"
                        : "Can edit"}
              </small>
            </div>
            {space.kind === "shared" && space.owner && (
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => void manage(space)}
              >
                Members
              </button>
            )}
          </div>
        ))}
      </div>
      {active && (
        <div className="space-members">
          <div className="section-heading">
            <strong>{active.name}</strong>
            <button
              className="icon-button"
              aria-label="Close members"
              onClick={() => setActive(null)}
            >
              <X size={16} />
            </button>
          </div>
          {members.map((member) => (
            <div className="space-row" key={member.id}>
              <span>{member.username}</span>
              <small>
                {member.role === "owner"
                  ? "Owner"
                  : member.role === "reader"
                    ? "Read only"
                    : "Can edit"}
              </small>
              {member.role !== "owner" && (
                <button
                  className="icon-button danger-text"
                  aria-label={"Remove " + member.username}
                  disabled={busy}
                  onClick={() =>
                    void mutate(() =>
                      api(
                        "/spaces/" + active.id + "/members/" + member.id,
                        "DELETE",
                      ),
                    )
                  }
                >
                  <X size={15} />
                </button>
              )}
            </div>
          ))}
          <form
            className="space-create"
            onSubmit={(event) => {
              event.preventDefault();
              void mutate(async () => {
                await api("/spaces/" + active.id + "/members", "POST", {
                  username,
                  role,
                });
                setUsername("");
              });
            }}
          >
            <input
              aria-label="Member username"
              placeholder="Existing username"
              required
              maxLength={80}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
            <select
              aria-label="Member access"
              value={role}
              onChange={(event) => setRole(event.target.value)}
            >
              <option value="reader">Read only</option>
              <option value="editor">Can edit</option>
            </select>
            <button className="button primary" disabled={busy || !username}>
              Save access
            </button>
          </form>
        </div>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
