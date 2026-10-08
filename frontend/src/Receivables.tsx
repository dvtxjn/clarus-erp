import Toast from "./Toast";
import LoadError from "./LoadError";
import { fmtDay } from "./dates";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  allocatePayment,
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
import { copyText } from "./clipboard";

/**
 * Payments & outstanding (client, 2026-09-30, P1): what each client owes and how old it is,
 * record money received (split over their invoices, with any TDS they deducted), a statement
 * PDF and a reminder message to copy. Admin only, like the rest of invoicing.
 */
const inr = (v: string | number) => Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const n = (v: string | number | undefined) => Number(v || 0);
const shortDate = fmtDay; // one date style across invoicing
const BUCKETS = ["0-30", "31-60", "61-90", "90+"];
const MODES = ["NEFT", "RTGS", "IMPS", "Cheque", "UPI", "Cash", "Other"];

export default function Receivables() {
  const confirm = useConfirm();
  const [client, setClient] = useState("");
  const [withPaid, setWithPaid] = useState(false);
  const [rows, setRows] = useState<ClientReceivable[] | null>(null);
  const [payments, setPayments] = useState<PaymentRecord[]>([]);
  const [loadErr, setLoadErr] = useState(false);
  const [payErr, setPayErr] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [paying, setPaying] = useState<ClientReceivable | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [bank, setBank] = useState<[string, string][]>([]);
  const [allocating, setAllocating] = useState<PaymentRecord | null>(null);
  // payments table filters
  const [pFrom, setPFrom] = useState("");
  const [pTo, setPTo] = useState("");
  const [pMode, setPMode] = useState("");
  const [pSearch, setPSearch] = useState("");

  const load = () => {
    getReceivables(client, withPaid).then(
      (r) => {
        setRows(r.clients);
        setLoadErr(false);
      },
      () => setLoadErr(true),
    );
    listPayments(client).then(
      (p) => {
        setPayments(p);
        setPayErr(false);
      },
      () => setPayErr(true),
    );
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
      onAccount: list.reduce((a, c) => a + n(c.on_account), 0),
      tds: list.reduce((a, c) => a + n(c.tds_estimate), 0),
      net: list.reduce((a, c) => a + n(c.net_due), 0),
      buckets: Object.fromEntries(BUCKETS.map((b) => [b, list.reduce((a, c) => a + n(c.buckets[b]), 0)])),
    };
  }, [rows]);

  const shownPayments = useMemo(() => {
    const q = pSearch.trim().toLowerCase();
    return payments.filter((p) => {
      if (pFrom && p.received_on < pFrom) return false;
      if (pTo && p.received_on > pTo) return false;
      if (pMode && (p.mode ?? "") !== pMode) return false;
      if (!q) return true;
      const hay = [p.party, p.reference, p.notes, ...p.allocations.flatMap((a) => [a.number, a.mbl, a.be_no, a.job])]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [payments, pFrom, pTo, pMode, pSearch]);

  function reminder(c: ClientReceivable): string {
    const open = c.invoices.filter((i) => n(i.outstanding) > 0);
    const lines = open.map((i) => {
      const refs = [i.mbl && `BL ${i.mbl}`, i.be_no && `BE ${i.be_no}`].filter(Boolean).join(" · ");
      return `• ${i.number} dated ${shortDate(i.invoice_date)}${refs ? ` (${refs})` : ""} — ₹${inr(i.outstanding)}`;
    });
    const less: string[] = [];
    if (n(c.on_account) > 0) less.push(`Less: received on account — ₹${inr(c.on_account)}`);
    if (n(c.tds_estimate) > 0) less.push(`Less: TDS you deduct (approx.) — ₹${inr(c.tds_estimate)}`);
    if (less.length) less.push(`Balance payable: ₹${inr(c.net_due)}`);
    const pay = bank.map(([k, v]) => `${k}: ${v}`).join("\n");
    return [
      `Dear ${c.party},`,
      "",
      `As per our records, ₹${inr(c.outstanding)} is outstanding against the following invoices:`,
      ...lines,
      ...(less.length ? ["", ...less] : []),
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
        {totals.onAccount > 0 && (
          <div className="stat-card">
            <div className="stat-value">₹{inr(totals.onAccount)}</div>
            <div className="stat-label">On account (not yet set against)</div>
          </div>
        )}
        {totals.tds > 0 && (
          <div className="stat-card">
            <div className="stat-value">~₹{inr(totals.tds)}</div>
            <div className="stat-label">TDS expected</div>
          </div>
        )}
        {(totals.onAccount > 0 || totals.tds > 0) && (
          <div className="stat-card">
            <div className="stat-value">₹{inr(totals.net)}</div>
            <div className="stat-label">Net still to come</div>
          </div>
        )}
        {BUCKETS.map((b) => (
          <div key={b} className={`stat-card${b === "90+" && totals.buckets[b] > 0 ? " stat-card-danger" : ""}`}>
            <div className="stat-value">₹{inr(totals.buckets[b])}</div>
            <div className="stat-label">{b} days</div>
          </div>
        ))}
      </div>

      <div className="inv-filters">
        <input list="org-names" aria-label="Client" placeholder="Client (type or pick)…" value={client} onChange={(e) => setClient(e.target.value)} />
        <label className="toggle-row">
          <span>Show paid invoices too</span>
          <input type="checkbox" role="switch" checked={withPaid} onChange={() => setWithPaid((x) => !x)} />
        </label>
      </div>
      {msg && <Toast ok={msg.ok} stamp={msg}>{msg.text}</Toast>}

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
            {loadErr && (
              <tr>
                <td colSpan={11}>
                  <LoadError what="receivables" onRetry={load} />
                </td>
              </tr>
            )}
            {rows === null && !loadErr && (
              <tr>
                <td colSpan={11} className="tracker-empty">
                  Loading…
                </td>
              </tr>
            )}
            {rows?.length === 0 && !loadErr && (
              <tr>
                <td colSpan={11} className="tracker-empty">
                  Nothing outstanding.
                </td>
              </tr>
            )}
            {(rows ?? []).map((c) => (
              <ClientRows
                key={c.key}
                c={c}
                open={open === c.key}
                onToggle={() => setOpen(open === c.key ? null : c.key)}
                onPay={() => setPaying(c)}
                onStatement={() => downloadStatement(c.key).catch(() => setMsg({ ok: false, text: "Couldn't make the statement." }))}
                onReminder={async () =>
                  setMsg(
                    (await copyText(reminder(c)))
                      ? { ok: true, text: `Reminder for ${c.party} copied — paste it into WhatsApp or email.` }
                      : { ok: false, text: "Couldn't copy — the browser blocked the clipboard. Try again, or use the Statement PDF." },
                  )
                }
              />
            ))}
          </tbody>
        </table>
      </div>

      <h2 className="recv-h2">Payments received</h2>
      <div className="inv-filters">
        <label className="final-field-inline">
          From <input type="date" aria-label="Received from" value={pFrom} onChange={(e) => setPFrom(e.target.value)} />
        </label>
        <label className="final-field-inline">
          To <input type="date" aria-label="Received to" value={pTo} onChange={(e) => setPTo(e.target.value)} />
        </label>
        <select aria-label="Mode" value={pMode} onChange={(e) => setPMode(e.target.value)}>
          <option value="">All modes</option>
          {MODES.map((m) => (
            <option key={m}>{m}</option>
          ))}
        </select>
        <input aria-label="Search payments" placeholder="Reference, invoice, BL, BE…" value={pSearch} onChange={(e) => setPSearch(e.target.value)} />
        {(pFrom || pTo || pMode || pSearch) && (
          <button
            type="button"
            className="btn-secondary"
            onClick={() => {
              setPFrom("");
              setPTo("");
              setPMode("");
              setPSearch("");
            }}
          >
            Clear
          </button>
        )}
        <span className="doc-group-count">
          {shownPayments.length} of {payments.length}
        </span>
      </div>
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
            {payErr && (
              <tr>
                <td colSpan={8}>
                  <LoadError what="payments" onRetry={load} />
                </td>
              </tr>
            )}
            {shownPayments.length === 0 && !payErr && (
              <tr>
                <td colSpan={8} className="tracker-empty">
                  {payments.length ? "No payments match these filters." : "No payments recorded yet."}
                </td>
              </tr>
            )}
            {shownPayments.map((p) => (
              <tr key={p.id}>
                <td>{shortDate(p.received_on)}</td>
                <td>{p.party}</td>
                <td className="num">
                  <strong>{inr(p.amount)}</strong>
                </td>
                <td>{p.mode ?? "—"}</td>
                <td>{p.reference ?? "—"}</td>
                <td>
                  {p.allocations.length === 0 && "—"}
                  {p.allocations.map((a) => (
                    <div key={a.invoice_id}>
                      {a.shipment_id ? <Link to={`/shipments/${a.shipment_id}`}>{a.number}</Link> : a.number} ₹{inr(a.amount)}
                      {n(a.tds) ? ` + TDS ${inr(a.tds)}` : ""}{" "}
                      <span className="doc-group-count">
                        BL {a.mbl ?? "—"} · BE {a.be_no ?? "—"}
                      </span>
                    </div>
                  ))}
                </td>
                <td className="num">
                  {n(p.unallocated) ? (
                    <>
                      {inr(p.unallocated)}
                      <div>
                        <button type="button" className="link-button" onClick={() => setAllocating(p)}>
                          Set against invoices…
                        </button>
                      </div>
                    </>
                  ) : (
                    "—"
                  )}
                </td>
                <td>
                  <button
                    type="button"
                    className="link-button link-danger"
                    aria-label={`Remove payment of ₹${inr(p.amount)} from ${p.party}`}
                    title="Entered by mistake? Remove it (Recently deleted can bring it back)"
                    onClick={async () => {
                      if (!(await confirm({ title: "Remove this payment?", message: "The invoices it paid become outstanding again. It can be restored from Recently deleted.", confirmLabel: "Remove", danger: true })))
                        return;
                      try {
                        await deletePayment(p.id);
                        setMsg({ ok: true, text: `Payment of ₹${inr(p.amount)} from ${p.party} removed.` });
                      } catch (e) {
                        setMsg({ ok: false, text: `Couldn't remove the payment — ${errText(e, "try again")}.` });
                      }
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
      {allocating && (
        <AllocateDialog
          p={allocating}
          c={(rows ?? []).find((c) => c.key === allocating.key) ?? null}
          onClose={() => setAllocating(null)}
          onSaved={() => {
            setAllocating(null);
            setMsg({ ok: true, text: `Money on account from ${allocating.party} set against the invoices.` });
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
          {n(c.on_account) > 0 && <div className="field-note">less ₹{inr(c.on_account)} on account</div>}
          {n(c.tds_estimate) > 0 && <div className="field-note">less ~₹{inr(c.tds_estimate)} TDS expected</div>}
          {n(c.net_due) !== n(c.outstanding) && <div className="field-note">net ₹{inr(c.net_due)}</div>}
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
              {n(i.tds_estimate) > 0 && ` · TDS expected ~₹${inr(i.tds_estimate)}`}
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

function errText(e: unknown, fallback: string): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : fallback;
}

type Alloc = Record<number, { amount: string; tds: string }>;

/**
 * Oldest first: fill each invoice's outstanding until the money runs out. Where the client
 * cuts TDS and none is typed yet, the expected ~2% goes in the TDS box (it settles the invoice too).
 */
function splitOldestFirst(open: OpenInvoice[], total: number, alloc: Alloc): Alloc {
  let rest = total;
  const next: Alloc = {};
  for (const i of open) {
    const typed = alloc[i.id]?.tds ?? "";
    const tdsStr = typed !== "" ? typed : n(i.tds_estimate) > 0 ? n(i.tds_estimate).toFixed(2) : "";
    const need = Math.max(0, n(i.outstanding) - n(tdsStr));
    const take = Math.min(need, rest);
    // TDS only goes with money actually set against the invoice
    next[i.id] = { amount: take ? take.toFixed(2) : "", tds: take || typed !== "" ? tdsStr : "" };
    rest -= take;
  }
  return next;
}

function toAllocations(open: OpenInvoice[], alloc: Alloc) {
  return open
    .filter((i) => n(alloc[i.id]?.amount) || n(alloc[i.id]?.tds))
    .map((i) => ({ invoice_id: i.id, amount: n(alloc[i.id]?.amount).toFixed(2), tds: n(alloc[i.id]?.tds).toFixed(2) }));
}

function SplitTable({ open, alloc, setAlloc }: { open: OpenInvoice[]; alloc: Alloc; setAlloc: (f: (a: Alloc) => Alloc) => void }) {
  const over = (i: OpenInvoice) => n(alloc[i.id]?.amount) + n(alloc[i.id]?.tds) > n(i.outstanding) + 1;
  return (
    <div className="tracker-grid-wrap">
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
        {open.length === 0 && (
          <tr>
            <td colSpan={4} className="tracker-empty">
              No open invoices for this client — the money stays on account.
            </td>
          </tr>
        )}
        {open.map((i) => (
          <tr key={i.id}>
            <td>
              {i.number}{" "}
              <span className="doc-group-count">
                BL {i.mbl ?? "—"} · BE {i.be_no ?? "—"} · {shortDate(i.invoice_date)}
                {n(i.tds_estimate) > 0 && ` · TDS expected ~₹${inr(i.tds_estimate)}`}
              </span>
              {over(i) && <div className="auth-error">More than this invoice's outstanding.</div>}
            </td>
            <td className="num">{inr(i.outstanding)}</td>
            <td className="num">
              <input
                className="rate-input num"
                inputMode="decimal"
                aria-label={`Amount against ${i.number}`}
                aria-invalid={over(i)}
                value={alloc[i.id]?.amount ?? ""}
                onChange={(e) => setAlloc((a) => ({ ...a, [i.id]: { amount: e.target.value, tds: a[i.id]?.tds ?? "" } }))}
              />
            </td>
            <td className="num">
              <input
                className="rate-input num"
                inputMode="decimal"
                aria-label={`TDS against ${i.number}`}
                placeholder={n(i.tds_estimate) > 0 ? `~${n(i.tds_estimate).toFixed(0)}` : undefined}
                value={alloc[i.id]?.tds ?? ""}
                onChange={(e) => setAlloc((a) => ({ ...a, [i.id]: { amount: a[i.id]?.amount ?? "", tds: e.target.value } }))}
              />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
    </div>
  );
}

function PaymentDialog({ c, onClose, onSaved }: { c: ClientReceivable; onClose: () => void; onSaved: (p: PaymentRecord) => void }) {
  const open = c.invoices.filter((i) => n(i.outstanding) > 0);
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10));
  const [amount, setAmount] = useState("");
  const [mode, setMode] = useState("NEFT");
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [alloc, setAlloc] = useState<Alloc>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const allocated = open.reduce((a, i) => a + n(alloc[i.id]?.amount), 0);
  const left = n(amount) - allocated;
  const anyOver = open.some((i) => n(alloc[i.id]?.amount) + n(alloc[i.id]?.tds) > n(i.outstanding) + 1);
  const hasTds = open.some((i) => n(i.tds_estimate) > 0);

  const autoSplit = () => setAlloc((a) => splitOldestFirst(open, n(amount), a));

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
          reference: reference.trim() || undefined,
          notes: notes.trim() || undefined,
          allocations: toAllocations(open, alloc),
        }),
      );
    } catch (e) {
      setErr(errText(e, "Couldn't record the payment."));
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
          <button type="button" className="btn-secondary" onClick={autoSplit}>
            Split oldest first
          </button>
        </div>
        <SplitTable open={open} alloc={alloc} setAlloc={setAlloc} />
        {hasTds && <p className="field-note">The split fills the expected TDS (~2% of the taxable value) — change it to what the client actually deducted.</p>}
        <p className={`field-note${left < -0.005 ? " auth-error" : ""}`}>
          Set against invoices: ₹{inr(allocated)} ·{" "}
          {left >= 0 ? `stays on account: ₹${inr(left)}` : `₹${inr(-left)} more than received — reduce the split`}
        </p>
        <label className="final-field">
          <span>Notes</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} />
        </label>
        {err && <div className="auth-error" role="alert">{err}</div>}
        <div className="final-actions">
          <button disabled={busy || !n(amount) || left < -0.005 || anyOver} onClick={save}>
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

/** Money that came in on account, set against the client's invoices later (once they're issued). */
function AllocateDialog({ p, c, onClose, onSaved }: { p: PaymentRecord; c: ClientReceivable | null; onClose: () => void; onSaved: () => void }) {
  const open = (c?.invoices ?? []).filter((i) => n(i.outstanding) > 0);
  const free = n(p.unallocated);
  const [alloc, setAlloc] = useState<Alloc>(() => splitOldestFirst(open, free, {}));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const allocated = open.reduce((a, i) => a + n(alloc[i.id]?.amount), 0);
  const left = free - allocated;
  const anyOver = open.some((i) => n(alloc[i.id]?.amount) + n(alloc[i.id]?.tds) > n(i.outstanding) + 1);
  const list = toAllocations(open, alloc);

  const save = async () => {
    setBusy(true);
    setErr(null);
    try {
      await allocatePayment(p.id, list);
      onSaved();
    } catch (e) {
      setErr(errText(e, "Couldn't set the money against the invoices."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal pay-dialog" onMouseDown={(e) => e.stopPropagation()} role="dialog" aria-label="Set against invoices">
        <h3>Set against invoices — {p.party}</h3>
        <p className="field-note">
          Received {shortDate(p.received_on)}
          {p.reference ? ` (${p.reference})` : ""}: ₹{inr(p.amount)} · on account ₹{inr(free)}
        </p>
        <div className="pay-split-head">
          <strong>Set against</strong>
          <button type="button" className="btn-secondary" onClick={() => setAlloc((a) => splitOldestFirst(open, free, a))}>
            Split oldest first
          </button>
        </div>
        <SplitTable open={open} alloc={alloc} setAlloc={setAlloc} />
        <p className={`field-note${left < -0.005 ? " auth-error" : ""}`}>
          Set against invoices: ₹{inr(allocated)} ·{" "}
          {left >= 0 ? `still on account: ₹${inr(left)}` : `₹${inr(-left)} more than is on account — reduce the split`}
        </p>
        {err && <div className="auth-error" role="alert">{err}</div>}
        <div className="final-actions">
          <button disabled={busy || list.length === 0 || left < -0.005 || anyOver} onClick={save}>
            {busy ? "Saving…" : "Set against invoices"}
          </button>
          <button className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
