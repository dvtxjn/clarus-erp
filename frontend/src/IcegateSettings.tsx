import { useEffect, useRef, useState } from "react";
import { getIcegateStatus, listShipments, refreshIcegate, type IcegateStatus } from "./api";

const when = (iso: string) =>
  new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });

/**
 * Shipments → Read ICEGATE (client, 2026-09-30; moved from Settings to sit by the shipments): the automatic read every 6 h (which shipments it takes), and a
 * backfill on command — every shipment, one at a time, with progress (Google Cloud gives the server CPU
 * only while it answers, so the page walks the list instead of a long background job).
 */
export default function IcegateSettings() {
  const [status, setStatus] = useState<IcegateStatus | null>(null);
  const [run, setRun] = useState<{ done: number; total: number; filled: number; notFound: number; errors: number; current?: string } | null>(null);
  const stop = useRef(false);

  useEffect(() => {
    getIcegateStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  async function backfill() {
    stop.current = false;
    const all = (await listShipments({ include_archived: true })).filter((s) => s.mbl && !s.icegate?.final);
    const r = { done: 0, total: all.length, filled: 0, notFound: 0, errors: 0 };
    setRun({ ...r });
    for (const s of all) {
      if (stop.current) break;
      setRun({ ...r, current: s.job ? `Job ${s.job}` : s.mbl ?? "" });
      try {
        const { summary } = await refreshIcegate(s.id);
        if (!summary.sea_found && !summary.icd_found) r.notFound++;
        else if (Object.keys(summary.changed).length || summary.containers?.added || summary.containers?.updated) r.filled++;
      } catch {
        r.errors++;
      }
      r.done++;
      setRun({ ...r });
      await new Promise((ok) => setTimeout(ok, 1500)); // gentle on ICEGATE
    }
    setRun({ ...r });
    getIcegateStatus().then(setStatus).catch(() => {});
  }

  const busy = !!run && run.done < run.total && !stop.current;
  return (
    <div className="settings-body icegate-settings">
      <div className="settings-grid">
        <span>Automatic read</span>
        <span>
          Every {status?.every_hours ?? 6} hours: sea shipments with no inward yet and ETA within 4 days; inland shipments until every
          container has arrived at the ICD.
        </span>
        <span>Last run</span>
        <span>
          {status?.last_run
            ? `${when(status.last_run.at)} · ${status.last_run.checked} checked · ${status.last_run.filled} updated${status.last_run.not_found ? ` · ${status.last_run.not_found} not on ICEGATE yet` : ""}${status.last_run.errors ? ` · ${status.last_run.errors} failed` : ""}`
            : "not yet"}
        </span>
        <span>Next run reads</span>
        <span>
          {status
            ? status.due_now.length
              ? status.due_now.map((s) => (s.job ? `Job ${s.job}` : s.mbl)).join(", ")
              : "nothing due right now"
            : "…"}
        </span>
        <span>Cleared — last read</span>
        <span>
          Each cleared shipment is read once after its Cleared Date, then its ICEGATE details are final and never read again
          {status ? (status.final_due.length ? ` · next run: ${status.final_due.length} cleared` : " · all done") : ""}.
        </span>
      </div>
      <div className="settings-save">
        <button type="button" onClick={backfill} disabled={busy}>
          {busy ? "Reading…" : "Read all shipments now"}
        </button>
        {busy && (
          <button type="button" className="btn-secondary" onClick={() => (stop.current = true)}>
            Stop
          </button>
        )}
        {run && (
          <span role="status" className="field-note">
            {run.done} / {run.total}
            {busy && run.current ? ` · reading ${run.current}` : ""} · {run.filled} updated · {run.notFound} not on ICEGATE
            {run.errors ? ` · ${run.errors} failed` : ""}
          </span>
        )}
      </div>
      {run && (
        <div className="icegate-progress" aria-hidden="true">
          <span style={{ width: `${(run.done / Math.max(1, run.total)) * 100}%` }} />
        </div>
      )}
      <p className="field-note">
        Backfill: every shipment not yet final, one at a time — about 2 seconds each. Typed container arrivals are kept; the stored
        MBL is never changed (HMM without HDMU is searched with it).
      </p>
    </div>
  );
}
