import { fmtWhen } from "./dates";
import { useReadOnly } from "./AuthContext";
import LoadError from "./LoadError";
import { useEffect, useState } from "react";
import { resolveIcegateMail, shipmentIcegateMails, type IcegateMail } from "./api";
import { errorCodeLines, istTime, readableCustoms } from "./customsMail";
import type { Shipment } from "./types";

/**
 * Shipment Overview → Customs timeline (client, 2026-09-30): every ICEGATE mail for this shipment, oldest
 * first — Ack, Examination Order, Processed B/E, Query, Out of Charge, Gate Pass — and what it changed.
 */
function BeStatusCard({ s }: { s: Shipment }) {
  const b = s.icegate?.be_status;
  if (!b) return null;
  const t = (v?: string | null) => (v ? fmtWhen(v.replace(" ", "T").replace(/\.0$/, "") + "+05:30") : "—");
  const rows: [string, string][] = [
    ["Status", readableCustoms(b.label)],
    ["Appraisement", b.appraisement === "SYSTEM" ? "System (no officer)" : b.appraisement || "—"],
    ["With", b.queue || "—"],
    ["Assessed", t(b.assessed_at)],
    ["Duty paid", t(b.paid_at)],
    ["Examined", t(b.exam_at)],
    ["OOC", t(b.ooc_at)],
  ];
  if (b.query) rows.push(["Query", b.query_reply ? `Replied ${t(b.reply_date)}: ${b.query_reply}` : "Raised — reply needed"]);
  if (b.amendments?.length) rows.push(["Amendments", b.amendments.map((a) => readableCustoms(`${a.date} ${a.status}`)).join(", ")]);
  return (
    <div className="be-status-card">
      <div className="be-status-head">
        <b>On ICEGATE</b>
        <span className="field-note">read {t(b.fetched_at)} · every 30 min, 8 am – 10 pm</span>
      </div>
      <dl className="be-status-grid">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {b.note && <p className="field-note">{b.note}</p>}
    </div>
  );
}

export default function CustomsTimeline({ shipmentId, shipment }: { shipmentId: number; shipment?: Shipment }) {
  const ro = useReadOnly();
  const [rows, setRows] = useState<IcegateMail[] | null>(null);
  const [loadErr, setLoadErr] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    shipmentIcegateMails(shipmentId).then(
      (r) => {
        setRows(r);
        setLoadErr(false);
      },
      () => setLoadErr(true),
    );
  }, [shipmentId, attempt]);

  async function done(m: IcegateMail) {
    const x = await resolveIcegateMail(m.id);
    setRows((r) => r?.map((y) => (y.id === x.id ? x : y)) ?? null);
  }

  return (
    <section className="detail-section detail-wide customs" id="customs" aria-labelledby="customs-head">
      <h3 id="customs-head">Customs timeline</h3>
      {shipment && <BeStatusCard s={shipment} />}
      {rows === null && loadErr ? (
        <LoadError what="the ICEGATE mails" onRetry={() => setAttempt((n) => n + 1)} />
      ) : rows === null ? (
        <p className="field-note">Loading ICEGATE mails…</p>
      ) : rows.length === 0 ? (
        <p className="field-note">No ICEGATE mails for this shipment yet. They appear here once the mails are read on the Customs mail page.</p>
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
                  {m.summary && m.summary !== m.label && <span className="customs-summary">{readableCustoms(m.summary)}</span>}
                  {errorCodeLines(m.summary).map((l) => (
                    <span key={l} className="customs-error-line">{l}</span>
                  ))}
                  {!!m.notes?.length && <span className="customs-notes">{readableCustoms(m.notes.join(" · "))}</span>}
                </span>
                {open && !ro && (
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
