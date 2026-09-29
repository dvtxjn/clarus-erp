import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  downloadInvoiceRegister,
  downloadInvoicesPdf,
  getInvoiceRegister,
  type RegisterFilters,
  type RegisterRow,
} from "./api";

/**
 * Invoices (client, 2026-09-30): every tax and reimbursement invoice across shipments in one
 * list — filter by year, month, type, status, client or number, then print the chosen ones as
 * one PDF or download the register, without opening each shipment. Admin only (invoicing).
 */
const inr = (v: string | number) => Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const date = (v: string | null) =>
  v ? new Date(`${v}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" }) : "—";

export default function InvoicesPage() {
  const [f, setF] = useState<RegisterFilters>({ status: "issued" });
  const [rows, setRows] = useState<RegisterRow[] | null>(null);
  const [years, setYears] = useState<string[]>([]);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => {
      getInvoiceRegister(f)
        .then((r) => {
          setRows(r.invoices);
          setYears(r.financial_years);
          setPicked(new Set());
        })
        .catch(() => setError("Couldn't load the invoices."));
    }, 250); // typing in the search boxes
    return () => window.clearTimeout(t);
  }, [f]);

  const totals = useMemo(() => {
    const list = rows ?? [];
    const sum = (k: "taxable" | "non_gst" | "gst" | "net_payable") => list.reduce((n, r) => n + Number(r[k]), 0);
    return { count: list.length, taxable: sum("taxable"), non_gst: sum("non_gst"), gst: sum("gst"), net: sum("net_payable") };
  }, [rows]);

  const set = (k: keyof RegisterFilters, v: string) => setF((x) => ({ ...x, [k]: v || undefined }));
  const toggle = (id: number) =>
    setPicked((p) => {
      const n = new Set(p);
      if (n.has(id)) n.delete(id);
      else n.add(id);
      return n;
    });
  const all = rows ?? [];
  const chosen = picked.size ? all.filter((r) => picked.has(r.id)) : all;

  async function run(what: string, fn: () => Promise<void>) {
    setBusy(what);
    setError(null);
    try {
      await fn();
    } catch {
      setError("Couldn't prepare the download.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="dashboard-page invoices-page">
      <div className="dash-head">
        <h1>Invoices</h1>
        <span className="tracker-subtitle">Tax and reimbursement invoices from every shipment</span>
      </div>

      <div className="inv-filters">
        <select value={f.fy ?? ""} onChange={(e) => set("fy", e.target.value)} aria-label="Financial year">
          <option value="">All years</option>
          {years.map((y) => (
            <option key={y} value={y}>
              FY {y}
            </option>
          ))}
        </select>
        <input type="month" value={f.month ?? ""} onChange={(e) => set("month", e.target.value)} aria-label="Month" />
        <select value={f.kind ?? ""} onChange={(e) => set("kind", e.target.value)} aria-label="Type">
          <option value="">Tax + reimbursement</option>
          <option value="tax">Tax invoices</option>
          <option value="reimbursement">Reimbursement invoices</option>
        </select>
        <select value={f.status ?? ""} onChange={(e) => set("status", e.target.value)} aria-label="Status">
          <option value="">Any status</option>
          <option value="issued">Issued</option>
          <option value="draft">Draft</option>
          <option value="cancelled">Cancelled</option>
        </select>
        <input placeholder="Client" value={f.client ?? ""} onChange={(e) => set("client", e.target.value)} />
        <input placeholder="Number, job, MBL, BE, IRN" value={f.q ?? ""} onChange={(e) => set("q", e.target.value)} />
        <span className="inv-filters-actions">
          <button
            disabled={!chosen.length || !!busy}
            onClick={() => run("pdf", () => downloadInvoicesPdf(chosen.map((r) => r.id)))}
            title="One PDF, one invoice per page — to print or send"
          >
            {busy === "pdf" ? "Preparing…" : `Print / PDF (${picked.size ? `${picked.size} chosen` : `all ${all.length}`})`}
          </button>
          <button className="btn-secondary" disabled={!!busy} onClick={() => run("xlsx", () => downloadInvoiceRegister(f))}>
            {busy === "xlsx" ? "Preparing…" : "Register (Excel)"}
          </button>
        </span>
      </div>
      {error && <div className="auth-error">{error}</div>}

      <div className="tracker-grid-wrap">
        <table className="tracker-grid inv-register">
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  aria-label="Choose all"
                  checked={all.length > 0 && picked.size === all.length}
                  onChange={() => setPicked(picked.size === all.length ? new Set() : new Set(all.map((r) => r.id)))}
                />
              </th>
              <th>Number</th>
              <th>Type</th>
              <th>Date</th>
              <th>Client</th>
              <th>Job</th>
              <th>BE</th>
              <th className="num">Taxable</th>
              <th className="num">Non-GST</th>
              <th className="num">GST</th>
              <th className="num">Net payable</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows === null && (
              <tr>
                <td colSpan={12} className="tracker-empty">
                  Loading…
                </td>
              </tr>
            )}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={12} className="tracker-empty">
                  No invoices match.
                </td>
              </tr>
            )}
            {all.map((r) => (
              <tr key={r.id} className={picked.has(r.id) ? "is-picked" : ""}>
                <td>
                  <input type="checkbox" checked={picked.has(r.id)} onChange={() => toggle(r.id)} aria-label={`Choose ${r.number ?? "draft"}`} />
                </td>
                <td className="inv-no">{r.number ?? "Draft"}</td>
                <td>
                  <span className={`doc-marker ${r.kind === "tax" ? "doc-marker-basic" : "doc-marker-cfs"}`}>
                    {r.kind === "tax" ? "TAX" : "REIMB"}
                  </span>
                </td>
                <td>{date(r.invoice_date)}</td>
                <td title={r.gstin}>{r.customer}</td>
                <td>
                  <Link to={`/shipments/${r.shipment_id}`}>{r.job ? `Job ${r.job}` : r.mbl}</Link>
                </td>
                <td>{r.be_no ?? "—"}</td>
                {r.not_applicable ? (
                  <td colSpan={4} className="num final-na">
                    Not applicable
                  </td>
                ) : (
                  <>
                    <td className="num">{inr(r.taxable)}</td>
                    <td className="num">{inr(r.non_gst)}</td>
                    <td className="num">{inr(r.gst)}</td>
                    <td className="num">
                      <strong>{inr(r.net_payable)}</strong>
                    </td>
                  </>
                )}
                <td>
                  <span className={`final-status s-${r.status}`}>{r.status}</span>
                </td>
              </tr>
            ))}
          </tbody>
          {all.length > 0 && (
            <tfoot>
              <tr>
                <td colSpan={7}>
                  <strong>{totals.count} invoices</strong>
                </td>
                <td className="num">{inr(totals.taxable)}</td>
                <td className="num">{inr(totals.non_gst)}</td>
                <td className="num">{inr(totals.gst)}</td>
                <td className="num">
                  <strong>{inr(totals.net)}</strong>
                </td>
                <td />
              </tr>
            </tfoot>
          )}
        </table>
      </div>
    </div>
  );
}
