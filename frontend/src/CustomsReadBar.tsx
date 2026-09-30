import { useEffect, useState } from "react";
import { getIcegateLogin, getMailbox, runIcegateLookup, syncMailbox, type IcegateLogin, type MailboxStatus } from "./api";
import { istTime } from "./customsMail";

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Something went wrong — try again.";
}

/**
 * Customs mail → "read now" buttons next to the mails they bring in (client, 2026-09-30: every button sits
 * near its task). Setup — the ICEGATE login and connecting the mailbox — stays where it is set up.
 */
export default function CustomsReadBar({ isAdmin, onRead }: { isAdmin: boolean; onRead: () => void }) {
  const [login, setLogin] = useState<IcegateLogin | null>(null);
  const [mail, setMail] = useState<MailboxStatus | null>(null);
  const [busy, setBusy] = useState<"mail" | "be" | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    getIcegateLogin().then(setLogin).catch(() => setLogin(null));
    if (isAdmin) getMailbox().then(setMail).catch(() => setMail(null));
  }, [isAdmin]);

  async function go(key: "mail" | "be") {
    setBusy(key);
    setMsg(null);
    try {
      if (key === "mail") {
        const m = await syncMailbox();
        setMail(m);
        setMsg(m.last_error ? { ok: false, text: m.last_error } : { ok: true, text: `Mailbox checked — ${m.last_new ?? 0} new.` });
      } else {
        const l = await runIcegateLookup("status");
        setLogin(l);
        const s = l.last_status;
        setMsg(l.last_error ? { ok: false, text: l.last_error } : { ok: true, text: `BE status read — ${s?.checked ?? 0} BEs, ${s?.changed ?? 0} changed.` });
      }
      onRead();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  const showMail = isAdmin && mail?.connected;
  if (!showMail && !login) return null;
  return (
    <div className="customs-readbar">
      {showMail && (
        <span className="customs-read">
          <button type="button" className="btn-secondary" disabled={!!busy} onClick={() => go("mail")}>
            {busy === "mail" ? "Checking…" : "Check mail now"}
          </button>
          <span className="field-note">{mail?.last_run ? `last ${istTime(mail.last_run)}` : "not checked yet"}</span>
        </span>
      )}
      {login && (
        <span className="customs-read">
          <button
            type="button"
            className="btn-secondary"
            disabled={!!busy || !login.ready}
            title={login.ready ? undefined : "Save the ICEGATE login above first"}
            onClick={() => go("be")}
          >
            {busy === "be" ? "Reading ICEGATE (a login waits up to 3 min for the OTP)…" : "Read BE status now"}
          </button>
          <span className="field-note">
            {login.last_status ? `last ${istTime(login.last_status.at)}` : login.ready ? "not read yet" : "ICEGATE login not saved"}
          </span>
        </span>
      )}
      {msg && (
        <span role="status" aria-live="polite" className={msg.ok ? "field-note" : "auth-error"}>
          {msg.text}
        </span>
      )}
    </div>
  );
}
