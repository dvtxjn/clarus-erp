import { useEffect, useState } from "react";
import { getMailbox, syncMailbox, type MailboxStatus } from "./api";
import { istTime } from "./customsMail";

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Something went wrong — try again.";
}

/**
 * Customs mail → "Check mail now" next to the mails it brings in (client, 2026-09-30: every button sits
 * near its task). BE status, queries and challans are checked on ICEGATE by hand — the ERP never logs in.
 */
export default function CustomsReadBar({ isAdmin, onRead }: { isAdmin: boolean; onRead: () => void }) {
  const [mail, setMail] = useState<MailboxStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (isAdmin) getMailbox().then(setMail).catch(() => setMail(null));
  }, [isAdmin]);

  async function check() {
    setBusy(true);
    setMsg(null);
    try {
      const m = await syncMailbox();
      setMail(m);
      setMsg(m.last_error ? { ok: false, text: m.last_error } : { ok: true, text: `Mailbox checked — ${m.last_new ?? 0} new.` });
      onRead();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  if (!isAdmin || !mail?.connected) return null;
  return (
    <div className="customs-readbar">
      <span className="customs-read">
        <button type="button" className="btn-secondary" disabled={busy} onClick={check}>
          {busy ? "Checking…" : "Check mail now"}
        </button>
        <span className="field-note">{mail.last_run ? `last ${istTime(mail.last_run)}` : "not checked yet"}</span>
      </span>
      {msg && (
        <span role="status" aria-live="polite" className={msg.ok ? "field-note" : "auth-error"}>
          {msg.text}
        </span>
      )}
    </div>
  );
}
