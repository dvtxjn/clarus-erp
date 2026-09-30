import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  deletePayment,
  downloadStatement,
  getReceivables,
  getSettings,
  listPayments,
  recordPayment,
  type ClientReceivable,
  type OpenInvoice,
  type PaymentRecord,
} from "./api";
import { useConfirm } from "./ConfirmDialog";

/**
 * Payments & outstanding (client, 2026-09-30, P1): what each client owes and how old it is,
 * record money received (split over their invoices, with any TDS they deducted), a statement
 * PDF and a reminder message to copy. Admin only, like the rest of invoicing.
 */
const inr = (v: string | number) => Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const n = (v: string | number | undefined) => Number(v || 0);
const shortDate = (v: string | null) =>
  v ? new Date(`${v}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "2-digit" }) : "—";
const BUCKETS = ["0-30", "31-60", "61-90", "90+"];
const MODES = ["NEFT", "RTGS", "IMPS", "Cheque", "UPI", "Cash", "Other"];

export default function Receivables() {
  const confirm = useConfirm();
  const [client, setClient] = useState("");
  const [withPaid, setWithPaid] = useState(false);
  const [rows, setRows] = useState<ClientReceivable[] | null>(null);
  const [payments, setPayments] = useState<PaymentRecord[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [paying, setPaying] = useState<ClientReceivable | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [bank, setBank] = useState<[string, string][]>([]);

  const load = () => {
    getReceivables(client, withPaid).then((r) => setRows(r.clients)).catch(() => setRows([]));
    listPayments(client).then(setPayments).catch(() => setPayments([]));
  };
  useEffect(() => {
    const t = window.setTimeout(load, 250);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, withPaid]);
  useEffect(() => {
    getSettings()
      .then((s) => setBank(s.bank))
      .catch(() => setBank([]));
  }, []);

  const totals = useMemo(() => {
    const list = rows ?? [];
    return {
      outstanding: list.reduce((a, c) => a + n(c.outstanding), 0),
      buckets: Object.fromEntries(BUCKETS.map((b) => [b, list.reduce((a, c) => a + n(c.buckets[b]), 0)])),
    };
  }, [rows]);

  function reminder(c: ClientReceivable): string {
    const open = c.invoices.filter((i) => n(i.outstanding) > 0);
    const lines = open.map((i) => `• ${i.number} dated ${shortDate(i.invoice_date)} — ₹${inr(i.outstanding)}`);
    const pay = bank.map(([k, v]) => `${k}: ${v}`).join("\n");
    return [
      `Dear ${c.party},`,
      "",
      `As per our records, ₹${inr(c.outstanding)} is outstanding against the following invoices:`,
      ...lines,
      "",
      "Kindly arrange the payment at the earliest. Please ignore if already paid.",
      "",
      pay,
      "",
      "Regards,",
      "Clarus Logistics LLP",
    ].join("\n");
  }

  return (
    <div className="recv">
      <div className="stat-row recv-stats">
        <div className="stat-card">
          <div className="stat-value">₹{inr(totals.outstanding)}</div>
          <div className="stat-label">Outstanding</div>
        </div>
        {BUCKETS.map((b) => (
          <div key={b} className={`stat-card${b === "90+" && totals.buckets[b] > 0 ? " stat-card-danger" : ""}`}>
            <div className="stat-value">₹{inr(totals.buckets[b])}</div>
            <div className="stat-label">{b} days</div>
          </div>
        ))}
      </div>

      <div className="inv-filters">
        <input list="org-names" placeholder="Client (type or pick)" value={client} onChange={(e) => setClient(e.target.value)} />
        <label className="toggle-row">
          <span>Show paid invoices too</span>
          <input type="checkbox" role="switch" checked={withPaid} onChange={() => setWithPaid((x) => !x)} />
        </label>
      </div>
      {msg && <div role="status" className={msg.ok ? "grid-toast grid-toast-ok" : "grid-toast grid-toast-error"}>{msg.text}</div>}

      <div className="tracker-grid-wrap">
        <table className="tracker-grid inv-register">
          <thead>
            <tr>
              <th>Client</th>
              <th className="num">Billed</th>
              <th className="num">Received</th>
              <th className="num">TDS</th>
              <th className="num">Outstanding</th>
              {BUCKETS.map((b) => (
                <th key={b} className="num">
                  {b}
                </th>
              ))}
              <th className="num">Oldest</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows === null && (
              <tr>
                <td colSpan={11} className="tracker-empty">
                  Loading…
                </td>
              </tr>
            )}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={11} className="tracker-empty">
                  Nothing outstanding.
                </td>
              </tr>
            )}
            {(rows ?? []).map((c) => (
              <ClientRows
                key={c.party + c.gstin}
                c={c}
                open={open === c.party + c.gstin}
                onToggle={() => setOpen(open === c.party + c.gstin ? null : c.party + c.gstin)}
                onPay={() => setPaying(c)}
                onStatement={() => downloadStatement(c.party).catch(() => setMsg({ ok: false, text: "Couldn't make the statement." }))}
                onReminder={() =>
                  navigator.clipboard
                    ?.writeText(reminder(c))
                    .then(() => setMsg({ ok: true, text: `Reminder for ${c.party} copied — paste it into WhatsApp or email.` }))
                }
              />
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="recv-h2">Payments received</h2>
      <div className="tracker-grid-wrap">
        <table className="tracker-grid inv-register">
          <thead>
            <tr>
              <th>Date</th>
              <th>Client</th>
              <th className="num">Amount</th>
              <th>Mode</th>
              <th>Reference</th>
              <th>Against</th>
              <th className="num">On account</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {payments.length === 0 && (
              <tr>
                <td colSpan={8} className="tracker-empty">
                  No payments recorded yet.
                </td>
              </tr>
            )}
            {payments.map((p) => (
              <tr key={p.id}>
                <td>{shortDate(p.received_on)}</td>
                <td>{p.party}</td>
                <td className="num">
                  <strong>{inr(p.amount)}</strong>
                </td>
                <td>{p.mode ?? "—"}</td>
                <td>{p.reference ?? "—"}</td>
                <td>
                  {p.allocations.map((a) => `${a.number} ₹${inr(a.amount)}${n(a.tds) ? ` + TDS ${inr(a.tds)}` : ""}`).join(", ") || "—"}
                </td>
                <td className="num">{n(p.unallocated) ? inr(p.unallocated) : "—"}</td>
                <td>
                  <button
                    type="button"
                    className="link-button link-danger"
                    title="Entered by mistake? Remove it (Recently deleted can bring it back)"
                    onClick={async () => {
                      if (!(await confirm({ title: "Remove this payment?", message: "The invoices it paid become outstanding again. It can be restored from Recently deleted.", confirmLabel: "Remove", danger: true })))
                        return;
                      await deletePayment(p.id);
                      load();
                    }}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {paying && (
        <PaymentDialog
          c={paying}
          onClose={() => setPaying(null)}
          onSaved={(p) => {
            setPaying(null);
            setMsg({ ok: true, text: `Payment of ₹${inr(p.amount)} from ${p.party} recorded.` });
            load();
          }}
        />
      )}
    </div>
  );
}

function ClientRows({
  c,
  open,
  onToggle,
  onPay,
  onStatement,
  onReminder,
}: {
  c: ClientReceivable;
  open: boolean;
  onToggle: () => void;
  onPay: () => void;
  onStatement: () => void;
  onReminder: () => void;
}) {
  const due = n(c.outstanding) > 0;
  return (
    <>
      <tr className="recv-client" onClick={onToggle}>
        <td>
          <button type="button" className="row-toggle" aria-expanded={open} onClick={(e) => { e.stopPropagation(); onToggle(); }}>
            <span className="licence-caret" aria-hidden="true">{open ? "▾" : "▸"}</span> <strong>{c.party}</strong>
          </button>
          <span className="doc-group-count">{c.gstin}</span>
        </td>
        <td className="num">{inr(c.billed)}</td>
        <td className="num">{inr(c.received)}</td>
        <td className="num">{n(c.tds) ? inr(c.tds) : "—"}</td>
        <td className="num">
          <strong>{inr(c.outstanding)}</strong>
          {n(c.on_account) > 0 && <div className="field-note">₹{inr(c.on_account)} on account</div>}
        </td>
        {BUCKETS.map((b) => (
          <td key={b} className={`num${b === "90+" && n(c.buckets[b]) > 0 ? " recv-late" : ""}`}>
            {n(c.buckets[b]) ? inr(c.buckets[b]) : "—"}
          </td>
        ))}
        <td className="num">{due ? `${c.oldest_days} d` : "—"}</td>
        <td className="recv-actions" onClick={(e) => e.stopPropagation()}>
          {due && <button onClick={onPay}>Record payment</button>}
          {due && (
            <button className="btn-secondary" onClick={onStatement}>
              Statement
            </button>
          )}
          {due && (
            <button className="btn-secondary" onClick={onReminder} title="Copies a reminder with the open invoices and bank details">
              Copy reminder
            </button>
          )}
        </td>
      </tr>
      {open &&
        c.invoices.map((i) => (
          <tr key={i.id} className="recv-invoice">
            <td>
              {i.number} · <Link to={`/shipments/${i.shipment_id}`}>{i.job ? `Job ${i.job}` : "shipment"}</Link> · BL{" "}
              {i.mbl ?? "—"} · BE {i.be_no ?? "—"} · {shortDate(i.invoice_date)}
            </td>
            <td className="num">{inr(i.net_payable)}</td>
            <td className="num">{inr(i.paid)}</td>
            <td className="num">{n(i.tds) ? inr(i.tds) : "—"}</td>
            <td className="num">{inr(i.outstanding)}</td>
            <td colSpan={4} className="num">
              {i.age_days} days
            </td>
            <td />
            <td>
              <span className={`final-status s-${i.pay_status === "paid" ? "issued" : "draft"}`}>{i.pay_status}</span>
            </td>
          </tr>
        ))}
    </>
  );
}

function PaymentDialog({ c, onClose, onSaved }: { c: ClientReceivable; onClose: () => void; onSaved: (p: PaymentRecord) => void }) {
  const open = c.invoices.filter((i) => n(i.outstanding) > 0);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState("");
  const [mode, setMode] = useState("NEFT");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [alloc, setAlloc] = useState<Record<number, { amount: string; tds: string }>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const allocated = open.reduce((a, i) => a + n(alloc[i.id]?.amount), 0);
  const left = n(amount) - allocated;

  // oldest first: fill each invoice's outstanding (less any TDS typed) until the money runs out
  const autoSplit = (total = n(amount)) => {
    let rest = total;
    const next: Record<number, { amount: string; tds: string }> = {};
    for (const i of open) {
      const tds = n(alloc[i.id]?.tds);
      const need = Math.max(0, n(i.outstanding) - tds);
      const take = Math.min(need, rest);
      next[i.id] = { amount: take ? take.toFixed(2) : "", tds: alloc[i.id]?.tds ?? "" };
      rest -= take;
    }
    setAlloc(next);
  };

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      onSaved(
        await recordPayment({
          received_on: date,
          party: c.party,
          party_gstin: c.gstin || null,
          amount: n(amount).toFixed(2),
          mode,
          reference: reference || undefined,
          notes: notes || undefined,
          allocations: open
            .filter((i) => n(alloc[i.id]?.amount) || n(alloc[i.id]?.tds))
            .map((i) => ({ invoice_id: i.id, amount: n(alloc[i.id]?.amount).toFixed(2), tds: n(alloc[i.id]?.tds).toFixed(2) })),
        }),
      );
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setErr(typeof d === "string" ? d : "Couldn't record the payment.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal pay-dialog" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="Record payment">
        <h3>Payment from {c.party}</h3>
        <div className="settings-form">
          <label className="final-field">
            <span>Received on</span>
            <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </label>
          <label className="final-field">
            <span>Amount received (₹)</span>
            <input
              inputMode="decimal"
              autoFocus
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              onBlur={() => allocated === 0 && autoSplit()}
            />
          </label>
          <label className="final-field">
            <span>Mode</span>
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              {MODES.map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label className="final-field">
            <span>Reference (UTR / cheque no.)</span>
            <input value={reference} onChange={(e) => setReference(e.target.value)} />
          </label>
        </div>
        <div className="pay-split-head">
          <strong>Set against</strong>
          <button type="button" className="btn-secondary" onClick={() => autoSplit()}>
            Split oldest first
          </button>
        </div>
        <table className="tracker-grid inv-register">
          <thead>
            <tr>
              <th>Invoice</th>
              <th className="num">Outstanding</th>
              <th className="num">Amount</th>
              <th className="num" title="Tax the client deducted — it settles the invoice too">
                TDS
              </th>
            </tr>
          </thead>
          <tbody>
            {open.map((i: OpenInvoice) => (
              <tr key={i.id}>
                <td>
                  {i.number}{" "}
                  <span className="doc-group-count">
                    BL {i.mbl ?? "—"} · BE {i.be_no ?? "—"} · {shortDate(i.invoice_date)}
                  </span>
                </td>
                <td className="num">{inr(i.outstanding)}</td>
                <td className="num">
                  <input
                    className="rate-input num"
                    inputMode="decimal"
                    value={alloc[i.id]?.amount ?? ""}
                    onChange={(e) => setAlloc((a) => ({ ...a, [i.id]: { amount: e.target.value, tds: a[i.id]?.tds ?? "" } }))}
                  />
                </td>
                <td className="num">
                  <input
                    className="rate-input num"
                    inputMode="decimal"
                    value={alloc[i.id]?.tds ?? ""}
                    onChange={(e) => setAlloc((a) => ({ ...a, [i.id]: { amount: a[i.id]?.amount ?? "", tds: e.target.value } }))}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className={`field-note${left < -0.005 ? " auth-error" : ""}`}>
          Set against invoices: ₹{inr(allocated)} ·{" "}
          {left >= 0 ? `stays on account: ₹${inr(left)}` : `₹${inr(-left)} more than received — reduce the split`}
        </p>
        <label className="final-field">
          <span>Notes</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        {err && <div className="auth-error">{err}</div>}
        <div className="final-actions">
          <button disabled={busy || !n(amount) || left < -0.005} onClick={save}>
            {busy ? "Saving…" : "Record payment"}
          </button>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
