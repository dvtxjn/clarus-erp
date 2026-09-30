import { useEffect, useState } from "react";
import { getIcegateLogin, setIcegateLoginIds, setIcegatePassword, type IcegateLogin } from "./api";
import { istTime } from "./customsMail";

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg); // field check from the server
  return "Something went wrong — try again.";
}

/**
 * The ICEGATE login the ERP uses to read BE status, queries and challans by itself (client, 2026-09-30).
 * ICEGATE resets the password periodically: when it's refused, the ERP stops trying (so the account isn't
 * locked) until the admin or an import manager enters the new one here. The password is never shown.
 */
export default function IcegateLoginPanel({ isAdmin }: { isAdmin: boolean }) {
  const [l, setL] = useState<IcegateLogin | null>(null);
  const [pw, setPw] = useState("");
  const [ids, setIds] = useState<{ id: string; cha: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    getIcegateLogin().then(setL).catch(() => setL(null));
  }, []);

  async function act(key: string, fn: () => Promise<IcegateLogin>, ok: string) {
    setBusy(key);
    setMsg(null);
    try {
      setL(await fn());
      setMsg({ ok: true, text: ok });
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  if (!l) return null;
  return (
    <section className={`icegate-login${l.password_bad ? " is-bad" : ""}`} aria-labelledby="icegate-login-head">
      <div className="icegate-login-head">
        <h2 id="icegate-login-head">ICEGATE login (automatic lookups)</h2>
        <span className={`icegate-login-state ${l.ready ? "ok" : "bad"}`}>
          {l.password_bad ? "Password needs updating" : l.ready ? "Working" : "Not set up"}
        </span>
      </div>
      {l.password_bad && (
        <p className="auth-error" role="alert">
          ICEGATE didn't accept the saved password{l.bad_since ? ` (${istTime(l.bad_since)})` : ""} — it has probably been reset. Enter the
          new one below; the ERP won't try again until then, so the account isn't locked.
        </p>
      )}
      <div className="settings-grid">
        <span>ICEGATE ID · CHA code</span>
        <span translate="no">
          {l.icegate_id || "—"} · {l.cha_code || "—"}
          {isAdmin && (
            <button type="button" className="link-button" onClick={() => setIds({ id: l.icegate_id ?? "", cha: l.cha_code ?? "" })}>
              {" "}Change…
            </button>
          )}
        </span>
        <span>Password</span>
        <span>{l.password_set ? `Saved${l.password_set_at ? ` ${istTime(l.password_set_at)}` : ""}${l.password_set_by ? ` by ${l.password_set_by}` : ""}` : "Not entered"}</span>
        <span>BE status &amp; queries</span>
        <span>
          Every 30 minutes, 8 am – 10 pm
          {l.last_status ? ` · last ${istTime(l.last_status.at)}: ${l.last_status.checked ?? 0} BEs read, ${l.last_status.changed ?? 0} changed` : ""}
        </span>
        <span>Duty challans</span>
        <span>
          Every morning
          {l.last_challans ? ` · last ${istTime(l.last_challans.at)}: ${l.last_challans.pending ?? 0} pending, ${l.last_challans.added ?? 0} new` : ""}
        </span>
        {l.last_error && !l.password_bad && (
          <>
            <span>Problem</span>
            <span className="auth-error">{l.last_error}</span>
          </>
        )}
      </div>
      {ids && (
        <form
          className="settings-save"
          onSubmit={(e) => {
            e.preventDefault();
            act("ids", () => setIcegateLoginIds(ids.id.trim(), ids.cha.trim()), "Saved.").then(() => setIds(null));
          }}
        >
          <input aria-label="ICEGATE ID" placeholder="ICEGATE ID…" value={ids.id} onChange={(e) => setIds({ ...ids, id: e.target.value })} spellCheck={false} autoComplete="off" />
          <input aria-label="CHA code" placeholder="CHA code, e.g. ACGFA8615DCH001…" value={ids.cha} onChange={(e) => setIds({ ...ids, cha: e.target.value })} spellCheck={false} autoComplete="off" />
          <button type="submit" disabled={busy === "ids"}>{busy === "ids" ? "Saving…" : "Save"}</button>
        </form>
      )}
      <form
        className="settings-save"
        onSubmit={(e) => {
          e.preventDefault();
          if (!pw.trim()) return;
          act("pw", () => setIcegatePassword(pw), "New password saved — the next lookup logs in with it.").then(() => setPw(""));
        }}
      >
        <input
          type="password"
          name="icegate-password"
          aria-label="New ICEGATE password"
          placeholder={l.password_set ? "New ICEGATE password (after a reset)…" : "ICEGATE password…"}
          value={pw}
          onChange={(e) => setPw(e.target.value)}
          autoComplete="new-password"
          style={{ flex: 1, minWidth: 0, maxWidth: 320 }}
        />
        <button type="submit" disabled={busy === "pw" || !pw.trim()}>{busy === "pw" ? "Saving…" : l.password_set ? "Update password" : "Save password"}</button>
      </form>
      {msg && (
        <div role="status" aria-live="polite" className={`grid-toast ${msg.ok ? "grid-toast-ok" : "grid-toast-error"}`}>
          {msg.text}
        </div>
      )}
    </section>
  );
}
