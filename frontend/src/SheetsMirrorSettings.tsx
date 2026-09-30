import { useEffect, useState } from "react";
import { getSheetsMirror, runSheetsMirror, setSheetsMirror, type SheetsMirror } from "./api";

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Couldn't save.";
}

/**
 * Settings → Google Sheets copy (client, 2026-09-30, P0): a view-only copy of the live tracker, written
 * every 15 minutes, so the office can still see shipments if the ERP is ever down.
 */
export default function SheetsMirrorSettings() {
  const [m, setM] = useState<SheetsMirror | null>(null);
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getSheetsMirror()
      .then((x) => {
        setM(x);
        setLink(x.link ?? "");
      })
      .catch(() => setM(null));
  }, []);

  async function act(fn: () => Promise<SheetsMirror>) {
    setBusy(true);
    setErr(null);
    try {
      const x = await fn();
      setM(x);
      setLink(x.link ?? "");
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="settings-body">
      <ol className="field-note">
        <li>Make a new Google Sheet (any name).</li>
        <li>
          Share it with <b>{m?.share_with ?? "the ERP's Google account"}</b> as <b>Editor</b>. Share with staff as <b>Viewer</b> only.
        </li>
        <li>Paste its link below and save. The ERP fills the "Tracker" tab straight away, then every {m?.every_minutes ?? 15} minutes.</li>
      </ol>
      <div className="settings-save">
        <input
          type="url"
          aria-label="Google Sheet link"
          placeholder="https://docs.google.com/spreadsheets/d/…"
          value={link}
          onChange={(e) => setLink(e.target.value)}
          style={{ flex: 1, minWidth: 0 }}
        />
        <button type="button" disabled={busy || link.trim() === (m?.link ?? "")} onClick={() => act(() => setSheetsMirror(link))}>
          {busy ? "Saving…" : "Save"}
        </button>
        {m?.link && (
          <button type="button" className="btn-secondary" disabled={busy} onClick={() => act(runSheetsMirror)}>
            Update now
          </button>
        )}
      </div>
      {err && <p className="auth-error" role="alert">{err}</p>}
      {m?.link && (
        <div className="settings-grid">
          <span>Sheet</span>
          <span>
            <a href={m.link} target="_blank" rel="noreferrer">Open ↗</a>
          </span>
          <span>Last update</span>
          <span>
            {m.last_run ? when(m.last_run) : "not yet"}
            {m.last_error ? "" : m.rows ? ` · ${m.rows - 1} live shipments` : ""}
          </span>
          {m.last_error && (
            <>
              <span>Problem</span>
              <span className="auth-error">{m.last_error}</span>
            </>
          )}
        </div>
      )}
      <p className="field-note">Live shipments only, no invoice figures. Anything typed in the sheet is overwritten.</p>
    </div>
  );
}
