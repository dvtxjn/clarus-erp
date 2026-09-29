import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { listDeleted, restoreDeleted, type DeletedItem } from "./api";

const KIND_LABELS: Record<DeletedItem["kind"], string> = {
  shipment: "Shipment",
  document: "Document",
  proforma: "Proforma",
  final_invoice: "Final invoice",
};

function errorText(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : "Something went wrong — please try again.";
}

/**
 * Admin only. Nothing is ever removed from the database: deleted shipments, documents,
 * proformas and draft invoices land here and can be put back.
 */
export default function DeletedPage() {
  const [items, setItems] = useState<DeletedItem[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const load = useCallback(() => listDeleted().then(setItems), []);
  useEffect(() => {
    load().catch(() => setMsg({ kind: "error", text: "Couldn't load Recently deleted." }));
  }, [load]);

  async function restore(d: DeletedItem) {
    const key = `${d.kind}:${d.id}`;
    setBusy(key);
    setMsg(null);
    try {
      await restoreDeleted(d.kind, d.id);
      setMsg({ kind: "ok", text: `Restored: ${d.label}` });
      await load();
    } catch (e) {
      setMsg({ kind: "error", text: errorText(e) });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="rates-page">
      <div>
        <h1>Recently deleted</h1>
        <p className="field-note">
          Deleted shipments, documents, proformas and draft invoices are kept here — nothing is erased. Restore puts
          it back exactly as it was. Issued invoices can't be deleted (cancel them instead).
        </p>
      </div>
      {msg && <div className={`grid-toast grid-toast-${msg.kind}`}>{msg.text}</div>}
      {items === null ? (
        <div className="tracker-empty">Loading…</div>
      ) : items.length === 0 ? (
        <div className="tracker-empty">Nothing has been deleted.</div>
      ) : (
        <table className="rates-table">
          <thead>
            <tr>
              <th>What</th>
              <th>Item</th>
              <th>Shipment</th>
              <th>Deleted</th>
              <th>By</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((d) => (
              <tr key={`${d.kind}:${d.id}`}>
                <td>{KIND_LABELS[d.kind]}</td>
                <td>{d.label}</td>
                <td>
                  {d.shipment_id && !d.shipment_deleted && d.kind !== "shipment" ? (
                    <Link to={`/shipments/${d.shipment_id}`}>{d.shipment}</Link>
                  ) : (
                    d.shipment ?? "—"
                  )}
                  {d.shipment_deleted && <span className="exception-badge"> shipment deleted</span>}
                </td>
                <td>{new Date(d.deleted_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}</td>
                <td>{d.deleted_by ?? "—"}</td>
                <td className="num">
                  <button
                    className="btn-secondary"
                    disabled={busy !== null || d.shipment_deleted}
                    title={d.shipment_deleted ? "Restore the shipment first" : undefined}
                    onClick={() => restore(d)}
                  >
                    {busy === `${d.kind}:${d.id}` ? "Restoring…" : "Restore"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
