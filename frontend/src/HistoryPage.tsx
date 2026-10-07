import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { allHistory, historyFilters, type HistoryEntry } from "./api";
import { historyTime, historyValue } from "./history";

/**
 * Change history (admin, client 2026-09-30): the whole log of changes — by people and by the ERP itself —
 * newest first. Filters (in the URL): who, what, dates, job / BL / BE / text. Each shipment row links to it
 * (History tab there to put a field back).
 */
const PAGE = 300;
const MAX = 5000;

export default function HistoryPage() {
  const [params, setParams] = useSearchParams();
  const who = params.get("who") ?? "";
  const kind = params.get("kind") ?? "";
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const q = params.get("q") ?? "";
  const [text, setText] = useState(q);
  const [rows, setRows] = useState<HistoryEntry[] | null>(null);
  const [limit, setLimit] = useState(PAGE); // "Load more" raises it (QA 2026-10-07)
  const [f, setF] = useState<{ users: { id: number; name: string }[]; kinds: { kind: string; label: string }[] }>({ users: [], kinds: [] });

  useEffect(() => {
    historyFilters().then(setF).catch(() => undefined);
  }, []);
  useEffect(() => setLimit(PAGE), [who, kind, from, to, q]);
  useEffect(() => {
    if (limit === PAGE) setRows(null);
    allHistory({ limit, who: who || undefined, kind: kind || undefined, date_from: from || undefined, date_to: to || undefined, q: q || undefined })
      .then(setRows)
      .catch(() => setRows((x) => x ?? []));
  }, [who, kind, from, to, q, limit]);
  useEffect(() => {
    const t = window.setTimeout(() => text !== q && set("q", text.trim()), 400);
    return () => window.clearTimeout(t);
  }, [text]); // eslint-disable-line react-hooks/exhaustive-deps

  function set(key: string, value: string) {
    const p = new URLSearchParams(params);
    if (value) p.set(key, value);
    else p.delete(key);
    setParams(p, { replace: true });
  }
  const filtered = !!(who || kind || from || to || q);

  return (
    <div className="rates-page customs-page">
      <div>
        <h1>Change history</h1>
        <p className="field-note">Every change recorded in the ERP — by people and by the ERP itself (ICEGATE, mails, invoices read). India time.</p>
      </div>
      <div className="customs-filters">
        <label>
          <span>Who</span>
          <select value={who} onChange={(e) => set("who", e.target.value)}>
            <option value="">Anyone</option>
            <option value="auto">ERP (automatic)</option>
            {f.users.map((u) => (
              <option key={u.id} value={String(u.id)}>
                {u.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>What</span>
          <select value={kind} onChange={(e) => set("kind", e.target.value)}>
            <option value="">Everything</option>
            {f.kinds.map((k) => (
              <option key={k.kind} value={k.kind}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>From</span>
          <input type="date" value={from} onChange={(e) => set("from", e.target.value)} />
        </label>
        <label>
          <span>To</span>
          <input type="date" value={to} onChange={(e) => set("to", e.target.value)} />
        </label>
        <label>
          <span>Job, BL, BE or text</span>
          <input type="search" placeholder="e.g. 185, HDMU…" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
        </label>
        {filtered && (
          <button type="button" className="link-button" onClick={() => (setText(""), setParams({}, { replace: true }))}>
            Clear filters
          </button>
        )}
        {rows && (
          <span className="field-note">
            {rows.length} change{rows.length === 1 ? "" : "s"}
            {rows.length >= limit ? ` (newest ${limit})` : ""}
          </span>
        )}
      </div>
      {rows === null ? (
        <div className="tracker-empty">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="tracker-empty">{filtered ? "No changes match these filters." : "No changes recorded yet."}</div>
      ) : (
        <div className="tracker-grid-wrap">
          <table className="tracker-grid history-table">
            <thead>
              <tr>
                <th>When</th>
                <th>Who</th>
                <th>Job</th>
                <th>BL</th>
                <th>BE no</th>
                <th>What</th>
                <th>Was</th>
                <th>Now</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.id}>
                  <td className="num">{historyTime(x.at)}</td>
                  <td>{x.automatic ? <span className="history-auto">ERP (automatic)</span> : x.who}</td>
                  <td>{x.shipment_id ? <Link to={`/shipments/${x.shipment_id}?tab=history`}>{x.job ? `Job ${x.job}` : "Open"}</Link> : "—"}</td>
                  <td translate="no">{x.mbl ?? "—"}</td>
                  <td translate="no">{x.be_no ?? "—"}</td>
                  <td>
                    {x.label}
                    {x.kind !== "Shipment" && <span className="field-note"> · {x.kind} #{x.record_id}</span>}
                  </td>
                  <td className="history-val">{historyValue(x.old)}</td>
                  <td className="history-val">{historyValue(x.new)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length >= limit && limit < MAX && (
            <button type="button" className="link-button attention-more" onClick={() => setLimit((n) => Math.min(n + PAGE, MAX))}>
              Load {PAGE} older changes
            </button>
          )}
        </div>
      )}
    </div>
  );
}
