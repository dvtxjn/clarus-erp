import { useState } from "react";
import { Link } from "react-router-dom";
import { ShipmentConflictError, updateShipment } from "./api";
import { MATCH_LABELS, type FolderResult } from "./folderMatch";
import { findFolderFor } from "./googleDrive";
import type { Shipment } from "./types";

type Row = { shipment: Shipment; result?: FolderResult; error?: string; linked?: boolean };
const PARALLEL = 3;

/**
 * Tracker: link every shipment that has no Drive folder yet to its "JOB <job> - <MBL/HBL>"
 * folder (client, 2026-09-29). Only a folder matching BOTH the job number and the MBL/HBL
 * is linked automatically; anything unsure is listed to check. Never changes a folder
 * that's already linked.
 */
export default function LinkFoldersPanel({
  shipments,
  onLinked,
  onClose,
}: {
  shipments: Shipment[];
  onLinked: (s: Shipment) => void;
  onClose: () => void;
}) {
  const todo = shipments.filter((s) => !s.drive_folder_id);
  const [rows, setRows] = useState<Row[] | null>(null);
  const [running, setRunning] = useState(false);

  async function run() {
    setRunning(true);
    const out: Row[] = todo.map((shipment) => ({ shipment }));
    setRows([...out]);
    let next = 0;
    async function worker() {
      while (next < out.length) {
        const i = next++;
        const s = out[i].shipment;
        try {
          const result = await findFolderFor(s);
          out[i] = { shipment: s, result };
          if (result.auto) {
            const saved = await updateShipment(
              s.id,
              { drive_folder_id: result.auto.id, drive_folder_link: result.auto.url },
              { drive_folder_id: null, drive_folder_link: null }, // only if still unlinked
            );
            out[i] = { shipment: saved, result, linked: true };
            onLinked(saved);
          }
        } catch (e) {
          out[i] = {
            shipment: s,
            error: e instanceof ShipmentConflictError ? "Someone linked a folder meanwhile" : e instanceof Error ? e.message : "Search failed",
          };
        }
        setRows([...out]);
      }
    }
    await Promise.all(Array.from({ length: Math.min(PARALLEL, out.length) }, worker));
    setRunning(false);
  }

  const label = (s: Shipment) => `${s.job ? `Job ${s.job} · ` : ""}${s.mbl}`;
  const done = rows?.filter((r) => r.result || r.error).length ?? 0;
  const linked = rows?.filter((r) => r.linked) ?? [];
  const unsure = rows?.filter((r) => r.result && !r.linked && r.result.candidates.length > 0) ?? [];
  const none = rows?.filter((r) => r.result && r.result.candidates.length === 0) ?? [];
  const failed = rows?.filter((r) => r.error) ?? [];

  return (
    <div className="import-panel">
      <div className="import-head">
        <div>
          <h3>Link Drive folders</h3>
          <p className="field-note">
            Finds each shipment's folder by its name "JOB &lt;job&gt; - &lt;MBL/HBL&gt;". Linked automatically only when
            exactly one folder has both the job number and the MBL/HBL; anything unsure is listed below.{" "}
            {todo.length} shipment{todo.length === 1 ? "" : "s"} without a folder.
          </p>
        </div>
        <div className="daily-actions">
          {!rows && (
            <button onClick={run} disabled={todo.length === 0}>
              Find folders
            </button>
          )}
          <button className="btn-secondary" onClick={onClose} disabled={running}>
            Close
          </button>
        </div>
      </div>
      {rows && (
        <div className="import-summary">
          <div className="import-counts">
            <span>{running ? `Searching… ${done} of ${rows.length}` : `Done: ${rows.length} checked`}</span>
            <span><b>{linked.length}</b> linked</span>
            <span className={unsure.length ? "import-warn" : undefined}><b>{unsure.length}</b> to check</span>
            <span><b>{none.length}</b> not found</span>
            {failed.length > 0 && <span className="import-warn"><b>{failed.length}</b> failed</span>}
          </div>
          {unsure.length > 0 && (
            <div className="import-block">
              <strong>To check</strong> — open the shipment → Documents → pick the right folder:
              <ul>
                {unsure.map((r) => (
                  <li key={r.shipment.id}>
                    <Link to={`/shipments/${r.shipment.id}`}>{label(r.shipment)}</Link>:{" "}
                    {r.result!.candidates.map((c) => `${c.folder.name} (${MATCH_LABELS[c.match]})`).join("; ")}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {none.length > 0 && (
            <div className="import-block">
              <strong>No folder found</strong>: {none.map((r) => label(r.shipment)).join(", ")}
            </div>
          )}
          {failed.length > 0 && (
            <div className="import-block">
              <strong>Failed</strong>: {failed.map((r) => `${label(r.shipment)} (${r.error})`).join("; ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
