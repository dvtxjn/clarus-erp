import { useEffect, useState } from "react";
import { resolveIcegateMail, shipmentIcegateMails, type IcegateMail } from "./api";
import { istTime } from "./customsMail";

/**
 * Shipment Overview → Customs timeline (client, 2026-09-30): every ICEGATE mail for this shipment, oldest
 * first — Ack, Examination Order, Processed B/E, Query, Out of Charge, Gate Pass — and what it changed.
 */
export default function CustomsTimeline({ shipmentId }: { shipmentId: number }) {
  const [rows, setRows] = useState<IcegateMail[] | null>(null);

  useEffect(() => {
    shipmentIcegateMails(shipmentId).then(setRows).catch(() => setRows([]));
  }, [shipmentId]);

  async function done(m: IcegateMail) {
    const x = await resolveIcegateMail(m.id);
    setRows((r) => r?.map((y) => (y.id === x.id ? x : y)) ?? null);
  }

  return (
    <section className="detail-section detail-wide customs" id="customs" aria-labelledby="customs-head">
      <h3 id="customs-head">Customs timeline</h3>
      {rows === null ? (
        <p className="field-note">Loading ICEGATE mails…</p>
      ) : rows.length === 0 ? (
        <p className="field-note">No ICEGATE mails for this shipment yet. They appear here once the mails are read (Customs mail page).</p>
      ) : (
        <ol className="customs-list">
          {rows.map((m) => {
            const open = m.attention && !m.resolved_at;
            return (
              <li key={m.id} className={`customs-row${open ? " is-open" : ""}`}>
                <time className="customs-when">{istTime(m.received_at)}</time>
                <span className="customs-what">
                  <span className="customs-label">
                    {m.label}
                    {open && <span className="customs-flag">Needs attention</span>}
                    {m.attention && m.resolved_at && <span className="customs-done">Done{m.resolved_note ? ` · ${m.resolved_note}` : ""}</span>}
                  </span>
                  {m.summary && m.summary !== m.label && <span className="customs-summary">{m.summary}</span>}
                  {!!m.notes?.length && <span className="customs-notes">{m.notes.join(" · ")}</span>}
                </span>
                {open && (
                  <button type="button" className="btn-secondary customs-btn" onClick={() => done(m)}>
                    Mark done
                  </button>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
