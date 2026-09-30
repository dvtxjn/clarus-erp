import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { applyTrackerImport, previewTrackerImport, type TrackerImportResult } from "./api";

function errorText(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : "Something went wrong — please try again.";
}

/**
 * Upload the Google Sheets tracker CSV: preview (nothing saved) → Apply.
 * Sheet wins over app edits; Bill of Entry data wins over the sheet; shipments
 * missing from the sheet are flagged, never deleted.
 */
export default function TrackerImportPanel({ onApplied, onClose }: { onApplied: () => void; onClose: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<TrackerImportResult | null>(null);
  const [done, setDone] = useState<TrackerImportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [openRows, setOpenRows] = useState(false);

  async function pick(f: File | undefined) {
    if (!f) return;
    setFile(f);
    setPreview(null);
    setDone(null);
    setError(null);
    setBusy(true);
    try {
      setPreview(await previewTrackerImport(f));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function apply() {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      setDone(await applyTrackerImport(file));
      setPreview(null);
      onApplied();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const p = preview ?? done;
  return (
    <div className="import-panel">
      <div className="import-head">
        <div>
          <h3>Import tracker CSV</h3>
          <p className="field-note">
            Google Sheets → File → Download → CSV. You'll see what changes before anything is saved. The sheet wins over
            edits made here, except data read from a Bill of Entry; shipments missing from the sheet are flagged, never
            deleted. Documents, proformas and invoices are never touched.
          </p>
        </div>
        <div className="daily-actions">
          <input ref={fileRef} type="file" accept=".csv" hidden onChange={(e) => pick(e.target.files?.[0])} />
          <button onClick={() => fileRef.current?.click()} disabled={busy}>
            {busy && !preview ? "Reading…" : "Choose CSV"}
          </button>
          <button className="btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
      </div>
      {error && <div role="alert" className="invoice-error">{error}</div>}
      {p && (
        <div className="import-summary">
          <div className="import-counts">
            <span>{done ? "Imported" : "Preview"}: {file?.name}</span>
            <span><b>{p.rows}</b> rows</span>
            <span><b>{p.new.length}</b> new</span>
            <span><b>{p.updated.length}</b> updated</span>
            <span><b>{p.unchanged}</b> unchanged</span>
            <span className={p.missing.length ? "import-warn" : undefined}><b>{p.missing.length}</b> not in the sheet (flagged)</span>
          </div>
          {p.unknown_columns.length > 0 && (
            <div className="field-note">Columns not used (renamed or new?): {p.unknown_columns.join(", ")}</div>
          )}
          {p.skipped.length > 0 && <div className="field-note">Skipped: {p.skipped.join("; ")}</div>}
          {p.new.length > 0 && (
            <div className="import-block">
              <strong>New shipments</strong>
              <ul>{p.new.map((n) => <li key={n.row}>{n.job ? `Job ${n.job} · ` : ""}{n.mbl}{n.hbl ? ` / ${n.hbl}` : ""} · {n.consignee ?? "—"}</li>)}</ul>
            </div>
          )}
          {p.updated.length > 0 && (
            <div className="import-block">
              <button type="button" className="link-button" onClick={() => setOpenRows((o) => !o)}>
                {openRows ? "Hide" : "Show"} changes ({p.updated.reduce((n, u) => n + u.changes.length, 0)} fields)
              </button>
              {openRows && (
                <table className="import-table">
                  <thead>
                    <tr><th>Shipment</th><th>Field</th><th>Now</th><th>Sheet</th><th /></tr>
                  </thead>
                  <tbody>
                    {p.updated.flatMap((u) => [
                      ...u.changes.map((c, i) => (
                        <tr key={`${u.shipment_id}-c${i}`}>
                          <td>{i === 0 && <Link to={`/shipments/${u.shipment_id}`}>{u.job ? `Job ${u.job}` : u.mbl}</Link>}{i === 0 && u.check && <span className="exception-badge" title={`Matched by ${u.matched_by} — check it's the right shipment`}>check</span>}</td>
                          <td>{c.label}</td><td className="import-old">{c.old ?? "—"}</td><td>{c.new ?? "—"}</td><td />
                        </tr>
                      )),
                      ...u.kept.map((c, i) => (
                        <tr key={`${u.shipment_id}-k${i}`} className="import-kept">
                          <td>{u.changes.length === 0 && i === 0 && <Link to={`/shipments/${u.shipment_id}`}>{u.job ? `Job ${u.job}` : u.mbl}</Link>}</td>
                          <td>{c.label}</td><td>{c.old ?? "—"}</td><td className="import-old">{c.new ?? "—"}</td><td>{c.why}</td>
                        </tr>
                      )),
                    ])}
                  </tbody>
                </table>
              )}
            </div>
          )}
          {p.missing.length > 0 && (
            <div className="import-block">
              <strong>In the app but not in the sheet</strong> — flagged, not deleted:
              <ul>{p.missing.map((m) => <li key={m.shipment_id}><Link to={`/shipments/${m.shipment_id}`}>{m.job ? `Job ${m.job}` : m.mbl}</Link> · {m.mbl} · {m.consignee ?? "—"}</li>)}</ul>
            </div>
          )}
          {preview && (
            <div className="final-actions">
              <button onClick={apply} disabled={busy || (p.new.length + p.updated.length + p.missing.length === 0)}>
                {busy ? "Importing…" : "Apply import"}
              </button>
              <span className="field-note">Every change is logged.</span>
            </div>
          )}
          {done && <div role="status" className="grid-toast grid-toast-ok">Import applied — the tracker is up to date with the sheet.</div>}
        </div>
      )}
    </div>
  );
}
