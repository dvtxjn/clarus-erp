import { useCallback, useEffect, useState, type FormEvent } from "react";
import axios from "axios";
import { createUser, listUsers, setUserPassword, updateUser } from "./api";
import { useAuth } from "./AuthContext";
import type { User, UserRole } from "./types";

const ROLES: Record<UserRole, string> = {
  admin: "Admin",
  import_manager: "Import Manager",
  export_manager: "Export Manager",
  accountant: "Accountant",
};

function errorText(e: unknown): string {
  const d = axios.isAxiosError(e) ? e.response?.data?.detail : null;
  if (Array.isArray(d)) return "Password must be at least 12 characters, and the name can't be empty.";
  return typeof d === "string" ? d : "Something went wrong — please try again.";
}

/** Suggest a strong password the admin can hand over (the user can't change it themselves). */
function newPassword(): string {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";
  const bytes = crypto.getRandomValues(new Uint8Array(14));
  return Array.from(bytes, (b) => chars[b % chars.length]).join("");
}

/**
 * Admin only (client, 2026-09-29): the admin creates logins and sets every password; users
 * can't change their own. "Forgot password" on the login page shows up here as a request.
 */
export default function UsersPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[] | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ email: "", full_name: "", role: "import_manager" as UserRole, password: newPassword() });
  const [resetting, setResetting] = useState<{ id: number; password: string } | null>(null);

  const load = useCallback(() => listUsers().then(setUsers), []);
  useEffect(() => {
    load().catch(() => setMsg({ kind: "error", text: "Couldn't load users." }));
  }, [load]);

  async function add(e: FormEvent) {
    e.preventDefault();
    try {
      const u = await createUser(form);
      setMsg({ kind: "ok", text: `Login created for ${u.email} — give them the password: ${form.password}` });
      setAdding(false);
      setForm({ email: "", full_name: "", role: "import_manager", password: newPassword() });
      load();
    } catch (err) {
      setMsg({ kind: "error", text: errorText(err) });
    }
  }

  async function change(u: User, patch: Partial<Pick<User, "role" | "is_active">>) {
    try {
      await updateUser(u.id, patch);
      load();
    } catch (err) {
      setMsg({ kind: "error", text: errorText(err) });
    }
  }

  async function savePassword() {
    if (!resetting) return;
    try {
      const u = await setUserPassword(resetting.id, resetting.password);
      setMsg({ kind: "ok", text: `New password for ${u.email}: ${resetting.password} — give it to them.` });
      setResetting(null);
      load();
    } catch (err) {
      setMsg({ kind: "error", text: errorText(err) });
    }
  }

  const requests = users?.filter((u) => u.password_reset_requested_at && u.is_active) ?? [];
  return (
    <div className="rates-page">
      <div className="rates-head">
        <div>
          <h1>Users</h1>
          <p className="field-note">
            You set every password; users can't change their own. "Forgot password" on the login page appears here as
            a request. Passwords: at least 12 characters.
          </p>
        </div>
        <button onClick={() => setAdding((a) => !a)}>{adding ? "Cancel" : "+ Add user"}</button>
      </div>
      {msg && <div role="status" className={`grid-toast grid-toast-${msg.kind}`}>{msg.text}</div>}
      {requests.length > 0 && (
        <div className="backup-banner">
          <strong>Password reset requested:</strong> {requests.map((u) => u.email).join(", ")}
        </div>
      )}
      {adding && (
        <form className="org-form" onSubmit={add}>
          <label>
            <span>Email *</span>
            <input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </label>
          <label>
            <span>Name *</span>
            <input required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          </label>
          <label>
            <span>Role</span>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as UserRole })}>
              {Object.entries(ROLES).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Password (give it to them)</span>
            <input required minLength={12} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </label>
          <div className="org-form-actions wide">
            <button type="submit">Create login</button>
          </div>
        </form>
      )}
      {users === null ? (
        <div className="tracker-empty">Loading…</div>
      ) : (
        <div className="tracker-grid-wrap">
        <table className="rates-table">
          <thead>
            <tr><th>Name</th><th>Email</th><th>Role</th><th>Last login</th><th>Status</th><th /></tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className={u.is_active ? undefined : "row-inactive"}>
                <td>{u.full_name}{u.id === me?.id && <span className="tracker-subtitle"> (you)</span>}</td>
                <td>{u.email}</td>
                <td>
                  <select value={u.role} disabled={u.id === me?.id} onChange={(e) => change(u, { role: e.target.value as UserRole })}>
                    {Object.entries(ROLES).map(([k, v]) => (
                      <option key={k} value={k}>{v}</option>
                    ))}
                  </select>
                </td>
                <td>{u.last_login_at ? new Date(u.last_login_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "—"}</td>
                <td>
                  {!u.is_active ? "Switched off" : u.password_reset_requested_at ? <span className="exception-badge">Reset requested</span> : "Active"}
                </td>
                <td className="num">
                  {resetting?.id === u.id ? (
                    <>
                      <input value={resetting.password} minLength={12} onChange={(e) => setResetting({ id: u.id, password: e.target.value })} />{" "}
                      <button onClick={savePassword}>Save</button>{" "}
                      <button className="btn-secondary" onClick={() => setResetting(null)}>Cancel</button>
                    </>
                  ) : (
                    <>
                      <button className="btn-secondary" onClick={() => setResetting({ id: u.id, password: newPassword() })}>
                        Set password
                      </button>{" "}
                      {u.id !== me?.id && (
                        <button className="btn-secondary" onClick={() => change(u, { is_active: !u.is_active })}>
                          {u.is_active ? "Switch off" : "Switch on"}
                        </button>
                      )}
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
    </div>
  );
}
