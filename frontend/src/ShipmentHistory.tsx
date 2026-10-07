import LoadError from "./LoadError";
import { useCallback, useEffect, useMemo, useState } from "react";
import { editContainer, shipmentHistory, updateShipment, type HistoryEntry } from "./api";
import { useConfirm } from "./ConfirmDialog";
import { historyTime, historyValue } from "./history";
import type { Shipment } from "./types";

function errorText(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : typeof (d as { message?: string })?.message === "string" ? (d as { message: string }).message : "Something went wrong — try again.";
}

/**
 * Shipment → History (client, 2026-09-30): every recorded change to this shipment, its containers and its
 * documents — who (or the ERP itself), when, was → now. The newest change of a shipment field can be put back
 * (the normal edit, so it's checked and recorded too). Filters: what, who, field, text.
 */
export default function ShipmentHistory({ shipment, onChange }: { shipment: Shipment; onChange: (s: Shipment) => void }) {
  const [rows, setRows] = useState<HistoryEntry[] | null>(null);
  const [loadErr, setLoadErr] = useState(false);
  const [kind, setKind] = useState("");
  const [who, setWho] = useState("");
  const [field, setField] = useState("");
  const [q, setQ] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const confirm = useConfirm();

  const load = useCallback(() => {
    shipmentHistory(shipment.id).then(
      (r) => {
        setRows(r);
        setLoadErr(false);
      },
      () => setLoadErr(true),
    );
  }, [shipment.id]);
  useEffect(load, [load, shipment.version]);

  const opts = useMemo(() => {
    const r = rows ?? [];
    const uniq = (xs: string[]) => Array.from(new Set(xs)).sort();
    return {
      kinds: uniq(r.map((x) => x.kind)),
      who: uniq(r.map((x) => (x.automatic ? "ERP (automatic)" : x.who ?? "—"))),
      fields: uniq(r.map((x) => x.label)),
    };
  }, [rows]);

  const shown = useMemo(() => {
    const t = q.trim().toLowerCase();
    return (rows ?? []).filter(
      (x) =>
        (!kind || x.kind === kind) &&
        (!who || (x.automatic ? "ERP (automatic)" : x.who ?? "—") === who) &&
        (!field || x.label === field) &&
        (!t || [x.label, x.old, x.new, x.about, x.who].some((v) => (v ?? "").toLowerCase().includes(t))),
    );
  }, [rows, kind, who, field, q]);

  async function putBack(x: HistoryEntry) {
    if (!x.undo) return;
    const ok = await confirm({
      title: `Put ${x.label}${x.about ? ` (${x.about})` : ""} back?`,
      message: `${x.label} goes back from “${historyValue(x.new)}” to “${historyValue(x.old)}”. The change is recorded like any edit.`,
      confirmLabel: "Put back",
    });
    if (!ok) return;
    try {
      if (x.table === "shipment_containers") {
        const { container_id, ...body } = x.undo as { container_id: number } & Parameters<typeof editContainer>[2];
        await editContainer(shipment.id, container_id, body);
      } else onChange(await updateShipment(shipment.id, x.undo as Partial<Shipment>));
      setMsg({ ok: true, text: `${x.label} put back to ${historyValue(x.old)}.` });
      load();
    } catch (e) {
      setMsg({ ok: false, text: errorText(e) });
    }
  }

  const filtered = !!(kind || who || field || q);
  return (
    <section className="detail-section detail-wide history">
      <div className="customs-filters">
        <label>
          <span>What</span>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">Everything</option>
            {opts.kinds.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Who</span>
          <select value={who} onChange={(e) => setWho(e.target.value)}>
            <option value="">Anyone</option>
            {opts.who.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Field</span>
          <select value={field} onChange={(e) => setField(e.target.value)}>
            <option value="">All fields</option>
            {opts.fields.map((k) => (
              <option key={k}>{k}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Search</span>
          <input type="search" placeholder="value, name…" value={q} onChange={(e) => setQ(e.target.value)} spellCheck={false} />
        </label>
        {filtered && (
          <button type="button" className="link-button" onClick={() => (setKind(""), setWho(""), setField(""), setQ(""))}>
            Clear filters
          </button>
        )}
        {rows && <span className="field-note">{shown.length} change{shown.length === 1 ? "" : "s"}</span>}
      </div>
      {msg && (
        <div role="status" aria-live="polite" className={`grid-toast ${msg.ok ? "grid-toast-ok" : "grid-toast-error"}`}>
          {msg.text}
        </div>
      )}
      {rows === null && loadErr ? (
        <LoadError what="the history" onRetry={load} />
      ) : rows === null ? (
        <p className="field-note">Loading history…</p>
      ) : shown.length === 0 ? (
        <p className="field-note">{filtered ? "No changes match these filters." : "No changes recorded yet."}</p>
      ) : (
        <div className="tracker-grid-wrap">
          <table className="tracker-grid history-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Who</th>
                <th>What</th>
                <th>Was</th>
                <th>Now</th>
                <th aria-label="Put back" />
              </tr>
            </thead>
            <tbody>
              {shown.map((x) => (
                <tr key={x.id}>
                  <td className="num">{historyTime(x.at)}</td>
                  <td>{x.automatic ? <span className="history-auto">ERP (automatic)</span> : x.who}</td>
                  <td>
                    {x.label}
                    {x.kind !== "Shipment" && (
                      <span className="field-note">
                        {" "}
                        · {x.kind}
                        {x.about ? ` ${x.about}` : ""}
                      </span>
                    )}
                  </td>
                  <td className="history-val">{historyValue(x.old)}</td>
                  <td className="history-val">{historyValue(x.new)}</td>
                  <td>
                    {x.undo && (
                      <button type="button" className="btn-secondary" onClick={() => putBack(x)}>
                        Put back
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
