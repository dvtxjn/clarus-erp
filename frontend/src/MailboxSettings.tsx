import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { disconnectMailbox, getMailbox, mailboxConnectUrl, setMailboxPush, type MailboxStatus } from "./api";
import { istTime } from "./customsMail";

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Something went wrong — try again.";
}

const RETURN: Record<string, { ok: boolean; text: string }> = {
  connected: { ok: true, text: "Mailbox connected — ICEGATE mails from the last 30 days were read." },
  cancelled: { ok: false, text: "Google sign-in was cancelled." },
  expired: { ok: false, text: "The sign-in link expired — press Connect again." },
  failed: { ok: false, text: "Google didn't give read access — try Connect again." },
};

/**
 * Settings → ICEGATE mailbox (client, 2026-09-30): the ERP reads the company mailbox the ICEGATE mails are
 * forwarded to — every new mail instantly (Gmail push), with a 15-minute catch-up. Read-only: Google refuses
 * any send, delete or mark-as-read.
 */
export default function MailboxSettings() {
  const [m, setM] = useState<MailboxStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [params] = useSearchParams();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(RETURN[params.get("mailbox") ?? ""] ?? null);
  const [hint, setHint] = useState("");

  useEffect(() => {
    getMailbox().then(setM).catch(() => setM(null));
  }, []);

  async function run(fn: () => Promise<MailboxStatus>) {
    setBusy(true);
    setMsg(null);
    try {
      setM(await fn());
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    } finally {
      setBusy(false);
    }
  }

  async function connect() {
    setBusy(true);
    setMsg(null);
    try {
      window.location.href = await mailboxConnectUrl(hint.trim() || undefined);
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
      setBusy(false);
    }
  }

  return (
    <div className="settings-body" id="mailbox">
      {msg && (
        <div role="status" aria-live="polite" className={`grid-toast ${msg.ok ? "grid-toast-ok" : "grid-toast-error"}`}>
          {msg.text}
        </div>
      )}
      {m?.connected ? (
        <>
          <div className="settings-grid">
            <span>Mailbox</span>
            <span translate="no">{m.mailbox}</span>
            <span>New mail</span>
            <span>{m.instant ? "Read the moment it arrives, plus a check every 15 minutes" : "Checked every 15 minutes"}</span>
            <span>Instant mail</span>
            <span className="mailbox-push">
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={m.push_wanted}
                  disabled={busy}
                  onChange={(e) => {
                    const on = e.target.checked;
                    run(() => setMailboxPush(on));
                  }}
                />
                <span>{m.push_wanted ? "On" : "Off — the 15-minute check only"}</span>
              </label>
              {m.push_wanted && m.push_error && (
                <span className="field-note">
                  Google hasn’t allowed it yet: {m.push_error}. Mail is still read every 15 minutes. It needs Google Cloud’s organisation
                  policy “Domain restricted sharing” to allow Gmail’s push account (gmail-api-push@system.gserviceaccount.com) on the
                  icegate-mail topic — then switch this off and on again.
                </span>
              )}
              {m.push_wanted && m.instant && <span className="field-note">Working — new mail arrives in seconds.</span>}
            </span>
            <span>Last check</span>
            <span>
              {istTime(m.last_run)}
              {!m.last_error && m.last_new != null ? ` · ${m.last_new} new` : ""}
            </span>
            {m.paused && !m.last_error && (
              <>
                <span>Reading</span>
                <span className="field-note">{m.paused}</span>
              </>
            )}
            {m.last_error && (
              <>
                <span>Problem</span>
                <span className="auth-error">{m.last_error}</span>
              </>
            )}
          </div>
          <div className="settings-save">
            <button type="button" className="btn-secondary" disabled={busy} onClick={() => run(disconnectMailbox)}>
              Disconnect
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="field-note">
            Connect the company mailbox the ICEGATE mails are forwarded to. Google asks that mailbox for <b>read-only</b> access: the ERP can't
            send, delete, move or mark anything read.
          </p>
          <div className="settings-save">
            <input
              type="email"
              aria-label="Mailbox address"
              placeholder="icegate@claruslogistics.in"
              value={hint}
              onChange={(e) => setHint(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              style={{ flex: 1, minWidth: 0, maxWidth: 320 }}
            />
            <button type="button" disabled={busy || m?.ready === false} onClick={connect}>
              {busy ? "Opening Google…" : "Connect mailbox"}
            </button>
          </div>
          {m?.ready === false && <p className="field-note">Google sign-in isn't set up on the server yet — see the setup steps.</p>}
        </>
      )}
    </div>
  );
}
