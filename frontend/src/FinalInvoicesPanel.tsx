import { fmtDay } from "./dates";
import { useEffect, useState } from "react";
import {
  cancelFinalInvoice,
  createFinalInvoices,
  deleteFinalInvoice,
  downloadFinalInvoice,
  downloadFinalPair,
  issueFinalInvoice,
  issueFinalPair,
  listFinalInvoices,
  updateFinalInvoice,
} from "./api";
import { useAuth } from "./AuthContext";
import { useConfirm } from "./ConfirmDialog";
import type { FinalInvoice, FinalInvoiceLine, Proforma } from "./types";

const inr = (v: string | number | null | undefined) =>
  v == null || v === "" ? "" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const TAX_TYPES: FinalInvoiceLine["tax_type"][] = ["T", "P", "E", "R", "N"];

function errorText(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : "Something went wrong — please try again.";
}

/**
 * Final invoices (what goes to the client and the authorities), made from a proforma:
 * Tax Invoice = Billed by Clarus charges; Reimbursement Invoice = charges paid by us.
 * Drafts can be overridden by hand (every change is logged); Issue numbers and locks them.
 */
export default function FinalInvoicesPanel({ shipmentId, proforma }: { shipmentId: number; proforma: Proforma | null }) {
  const confirm = useConfirm();
  const [items, setItems] = useState<FinalInvoice[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => listFinalInvoices(shipmentId).then(setItems).catch(() => setItems([]));
  useEffect(() => {
    load();
  }, [shipmentId]);

  // this proforma's pair (newest of each kind, not cancelled): tax first
  const pair = (["tax", "reimbursement"] as const)
    .map((k) => items.find((i) => i.proforma_id === proforma?.id && i.kind === k && i.status !== "cancelled"))
    .filter((i): i is FinalInvoice => !!i);
  const others = items.filter((i) => !pair.includes(i));
  const pairDraft = pair.some((i) => i.status === "draft");

  async function issuePair() {
    if (!proforma) return;
    const na = pair.find((i) => i.not_applicable);
    const ok = await confirm({
      title: "Issue both invoices?",
      message:
        "The tax and reimbursement invoices get the next number together and are locked — only IRN / ACK can be added after this." +
        (na ? ` The ${na.kind} invoice has no charges: it's issued as BILL CANCELLED — NOT APPLICABLE so the numbers stay paired.` : ""),
      confirmLabel: "Issue both",
    });
    if (!ok) return;
    setBusy(true);
    setError(null);
    try {
      await issueFinalPair(proforma.id);
      await load();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function create() {
    if (!proforma) return;
    const hasDrafts = items.some((i) => i.proforma_id === proforma.id && i.status === "draft");
    if (
      hasDrafts &&
      !(await confirm({
        title: "Replace draft final invoices?",
        message: "Draft final invoices from this proforma will be replaced (including any changes made to them).",
        confirmLabel: "Replace drafts",
      }))
    )
      return;
    setBusy(true);
    setError(null);
    try {
      const created = await createFinalInvoices(proforma.id);
      await load();
      setOpenId(created[0]?.id ?? null);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="final-invoices">
      <div className="final-head">
        <div>
          <h3>Final invoices</h3>
          <p className="field-note">
            Tax Invoice = Billed by Clarus charges · Reimbursement Invoice = charges paid by us. Royalty and Cost Inclusion
            aren't invoiced by Clarus. Check every field before issuing — this goes to the authorities.
          </p>
        </div>
        {proforma && (
          <button onClick={create} disabled={busy}>
            {busy ? "Creating…" : `Create final invoices from ${proforma.name || `v${proforma.version_number}`}`}
          </button>
        )}
      </div>
      {error && <div role="alert" className="invoice-error">{error}</div>}
      {items.length === 0 && <p className="tracker-subtitle">No final invoices yet.</p>}

      {/* the pair from this proforma: one number, issued together, one PDF or two (client, 2026-09-30) */}
      {pair.length > 0 && (
        <div className="final-pair">
          <div className="final-pair-head">
            <strong>{pair[0].number ? pair.map((i) => i.number).join("  +  ") : "Draft pair — tax + reimbursement"}</strong>
            <span className="final-pair-actions">
              {pairDraft && (
                <button onClick={issuePair} disabled={busy}>
                  Issue both
                </button>
              )}
              <button className="btn-secondary" onClick={() => proforma && downloadFinalPair(proforma.id).catch((e) => setError(errorText(e)))}>
                One PDF (both)
              </button>
              <button
                className="btn-secondary"
                onClick={async () => {
                  for (const inv of pair) await downloadFinalInvoice(inv.id).catch((e) => setError(errorText(e)));
                }}
              >
                Two PDFs
              </button>
            </span>
          </div>
          {pair.map(card)}
        </div>
      )}
      {others.length > 0 && <div className="final-others-head">Earlier / cancelled</div>}
      {others.map(card)}
    </section>
  );

  function card(inv: FinalInvoice) {
    return (
        <div key={inv.id} className={`final-card final-${inv.status}`}>
          <button type="button" className="final-card-head" aria-expanded={openId === inv.id} onClick={() => setOpenId(openId === inv.id ? null : inv.id)}>
            <span className="final-kind">{inv.kind === "tax" ? "Tax Invoice" : "Reimbursement Invoice"}</span>
            <span className="final-number">{inv.number ?? "Draft"}</span>
            <span className={`final-status s-${inv.status}`}>{inv.status}</span>
            <span className="final-cust">{inv.customer.name}</span>
            {inv.not_applicable ? (
              <strong className="final-amount final-na">Not applicable</strong>
            ) : (
              <strong className="final-amount">₹{inr(inv.totals.net_payable)}</strong>
            )}
            <span className="final-toggle" aria-hidden="true">{openId === inv.id ? "▾" : "▸"}</span>
          </button>
          {openId === inv.id && (
            <FinalInvoiceEditor
              inv={inv}
              onChange={(u) => setItems((prev) => prev.map((x) => (x.id === u.id ? u : x)))}
              onDeleted={() => {
                setItems((prev) => prev.filter((x) => x.id !== inv.id));
                setOpenId(null);
              }}
              onReload={load}
            />
          )}
        </div>
    );
  }
}

function FinalInvoiceEditor({
  inv,
  onChange,
  onDeleted,
  onReload,
}: {
  inv: FinalInvoice;
  onChange: (i: FinalInvoice) => void;
  onDeleted: () => void;
  onReload: () => void;
}) {
  const { user } = useAuth();
  const confirm = useConfirm();
  const draft = inv.status === "draft";
  // an issued bill can be altered until the 10th of next month (client, 2026-09-30)
  const today = new Date().toISOString().slice(0, 10);
  const canAlter = inv.status === "issued" && !!inv.alter_until && today <= inv.alter_until;
  const [altering, setAltering] = useState(false);
  const editable = draft || altering;
  const [f, setF] = useState(() => toForm(inv));
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => setF(toForm(inv)), [inv]);

  const dirty = JSON.stringify(f) !== JSON.stringify(toForm(inv));

  async function save(eInvoiceFiled?: boolean) {
    setSaving(true);
    setMsg(null);
    try {
      const body = editable
        ? {
            invoice_date: f.invoice_date || null,
            due_date: f.due_date || null,
            customer: f.customer,
            header: f.header,
            lines: f.lines.map((l) => ({
              description: l.description,
              sub_description: l.sub_description || null,
              sac: l.sac || null,
              tax_type: l.tax_type,
              non_gst_value: l.non_gst_value || "0",
              taxable_value: l.taxable_value || "0",
              gst_rate: l.gst_rate || "0",
            })),
            advance_received: f.advance_received || "0",
            remarks: f.remarks || null,
            ...(altering ? { e_invoice_filed: eInvoiceFiled } : {}),
          }
        : { irn: f.irn || null, ack_no: f.ack_no || null, ack_date: f.ack_date || null };
      onChange(await updateFinalInvoice(inv.id, body));
      setAltering(false);
      setMsg({ kind: "ok", text: altering ? "Invoice altered — same number; the change is logged and the new PDF kept." : "Saved — changes are logged." });
    } catch (e) {
      const detail = (e as { response?: { status?: number; data?: { detail?: { ask?: string } } } })?.response;
      if (detail?.status === 409 && detail.data?.detail?.ask === "e_invoice_filed") {
        // e-invoicing applies (admin setting): ask before altering
        setSaving(false);
        const notFiled = await confirm({
          title: "Has the e-invoice been filed?",
          message: "E-invoicing applies to Clarus. A bill whose e-invoice (IRN) is filed can't be altered.",
          confirmLabel: "Not filed — alter it",
          cancelLabel: "Yes, it's filed",
        });
        if (notFiled) return save(false);
        setMsg({ kind: "error", text: "Filed e-invoices can't be altered — cancel the e-invoice on the IRP (within 24 hours) or issue a credit note." });
        return;
      }
      setMsg({ kind: "error", text: errorText(e) });
    } finally {
      setSaving(false);
    }
  }

  async function act(kind: "issue" | "cancel" | "delete") {
    const texts = {
      issue: ["Issue this invoice?", "It gets the next invoice number and is locked — only IRN / ACK can be added after this.", "Issue"],
      cancel: ["Cancel this invoice?", "It stays on record as cancelled and its number is not reused.", "Cancel invoice"],
      delete: draft
        ? ["Delete this draft?", "The draft is moved to Recently deleted (the admin can restore it).", "Delete draft"]
        : [`Delete ${inv.number}?`, "It moves to Recently deleted (you can restore it). Its number is never given again.", "Delete invoice"],
    }[kind];
    let reason = "";
    const ok = await confirm({
      title: texts[0],
      message: texts[1],
      confirmLabel: texts[2],
      danger: kind !== "issue",
      ...(kind === "cancel" ? { inputLabel: "Reason (kept with the invoice)", onInput: (v: string) => (reason = v) } : {}),
    });
    if (!ok) return;
    try {
      if (dirty && kind === "issue") await save();
      if (kind === "issue") onChange(await issueFinalInvoice(inv.id));
      if (kind === "cancel") onChange(await cancelFinalInvoice(inv.id, reason));
      if (kind === "delete") {
        await deleteFinalInvoice(inv.id);
        onDeleted();
      }
      if (kind !== "delete") onReload();
    } catch (e) {
      setMsg({ kind: "error", text: errorText(e) });
    }
  }

  const setLine = (i: number, patch: Partial<FinalInvoiceLine>) =>
    setF((x) => ({ ...x, lines: x.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));
  const t = inv.totals;

  return (
    <div className="final-editor">
      <div className="final-grid">
        <fieldset>
          <legend>Invoice</legend>
          <Field label="Invoice date" type="date" value={f.invoice_date} disabled={!editable} onChange={(v) => setF({ ...f, invoice_date: v })} />
          <Field label="Due date" type="date" value={f.due_date} disabled={!editable} onChange={(v) => setF({ ...f, due_date: v })} />
          <Field label="Job number" value={f.header.job_number ?? ""} disabled={!editable} onChange={(v) => setF({ ...f, header: { ...f.header, job_number: v } })} />
          <Field label="Job type" value={f.header.job_type ?? ""} disabled={!editable} onChange={(v) => setF({ ...f, header: { ...f.header, job_type: v } })} />
          <div className="final-pos">Place of supply: {inv.place_of_supply || "—"} ({inv.intra_state ? "CGST + SGST" : "IGST"})</div>
        </fieldset>
        <fieldset>
          <legend>Customer</legend>
          {(["name", "address", "pan", "gstin", "state_code", "state_name"] as const).map((k) => (
            <Field
              key={k}
              label={{ name: "Name", address: "Address", pan: "PAN", gstin: "GSTIN", state_code: "State code", state_name: "State" }[k]}
              value={f.customer[k] ?? ""}
              disabled={!editable}
              onChange={(v) => setF({ ...f, customer: { ...f.customer, [k]: k === "gstin" || k === "pan" ? v.toUpperCase() : v } })}
            />
          ))}
        </fieldset>
      </div>

      <fieldset>
        <legend>Shipment details (as printed)</legend>
        <div className="final-header-grid">
          {inv.header_fields.map(([k, label]) => (
            <Field key={k} label={label} value={f.header[k] ?? ""} disabled={!editable} onChange={(v) => setF({ ...f, header: { ...f.header, [k]: v } })} />
          ))}
        </div>
      </fieldset>

      <div className="tracker-grid-wrap">
        <table className="final-lines">
          <thead>
            <tr>
              <th>Description</th>
              <th>Sub-description</th>
              <th>SAC</th>
              <th>Type</th>
              <th className="num">Non-GST ₹</th>
              <th className="num">Taxable ₹</th>
              <th className="num">GST %</th>
              <th className="num">Total ₹</th>
              {editable && <th />}
            </tr>
          </thead>
          <tbody>
            {f.lines.map((l, i) => (
              <tr key={i}>
                <td><input value={l.description} disabled={!editable} onChange={(e) => setLine(i, { description: e.target.value })} /></td>
                <td><input value={l.sub_description ?? ""} placeholder="—" disabled={!editable} onChange={(e) => setLine(i, { sub_description: e.target.value })} /></td>
                <td><input className="w-sac" value={l.sac ?? ""} disabled={!editable} onChange={(e) => setLine(i, { sac: e.target.value })} /></td>
                <td>
                  <select value={l.tax_type} disabled={!editable} onChange={(e) => setLine(i, { tax_type: e.target.value as FinalInvoiceLine["tax_type"] })}>
                    {TAX_TYPES.map((x) => <option key={x}>{x}</option>)}
                  </select>
                </td>
                {(["non_gst_value", "taxable_value", "gst_rate"] as const).map((k) => (
                  <td key={k} className="num">
                    <input className="num" inputMode="decimal" value={l[k]} disabled={!editable} onChange={(e) => setLine(i, { [k]: e.target.value })} />
                  </td>
                ))}
                <td className="num">{inr(inv.lines[i]?.total)}</td>
                {editable && (
                  <td>
                    <button type="button" className="link-button link-danger" aria-label="Remove line" onClick={() => setF({ ...f, lines: f.lines.filter((_, j) => j !== i) })}>✕</button>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
        {editable && (
          <button
            type="button"
            className="link-button"
            onClick={() =>
              setF({ ...f, lines: [...f.lines, { description: "", sac: "996713", tax_type: inv.kind === "tax" ? "T" : "P", non_gst_value: "0", taxable_value: "0", gst_rate: inv.kind === "tax" ? "18" : "0" }] })
            }
          >
            + line
          </button>
        )}
      </div>

      <div className="final-grid">
        <fieldset>
          <legend>{draft ? "Other" : "E-invoice"}</legend>
          {draft ? (
            <>
              <Field label="Advance received ₹" value={f.advance_received} onChange={(v) => setF({ ...f, advance_received: v })} />
              <Field label="Remarks" value={f.remarks} onChange={(v) => setF({ ...f, remarks: v })} />
            </>
          ) : (
            <>
              <Field label="IRN" value={f.irn} disabled={inv.status !== "issued"} onChange={(v) => setF({ ...f, irn: v })} />
              <Field label="ACK No." value={f.ack_no} disabled={inv.status !== "issued"} onChange={(v) => setF({ ...f, ack_no: v })} />
              <Field label="ACK Date" value={f.ack_date} disabled={inv.status !== "issued"} onChange={(v) => setF({ ...f, ack_date: v })} />
            </>
          )}
        </fieldset>
        <div className="final-totals">
          <div><span>Total before tax</span><span>₹{inr(t.before_tax)}</span></div>
          <div><span>GST</span><span>₹{inr(t.gst)}</span></div>
          <div><span>Invoice value</span><span>₹{inr(t.invoice_value)}</span></div>
          <div><span>Less advance</span><span>₹{inr(t.advance_received)}</span></div>
          <div><span>Round off</span><span>₹{inr(t.round_off)}</span></div>
          <div className="final-net"><span>Net payable</span><span>₹{inr(t.net_payable)}</span></div>
          <div className="final-words">{t.in_words}</div>
          {dirty && <div className="field-note">Totals update when you save.</div>}
        </div>
      </div>

      {msg && <div role="status" className={msg.kind === "ok" ? "grid-toast grid-toast-ok" : "grid-toast grid-toast-error"}>{msg.text}</div>}
      <div className="final-actions">
        {(draft || inv.status === "issued") && (
          <button disabled={!dirty || saving} onClick={() => save()}>
            {saving ? "Saving…" : altering ? "Save the altered invoice" : "Save changes"}
          </button>
        )}
        {canAlter && !altering && (
          <button className="btn-secondary" onClick={() => setAltering(true)} title="Correct a mistake — the number stays the same">
            Alter invoice
          </button>
        )}
        {altering && (
          <button className="btn-secondary" onClick={() => { setAltering(false); setF(toForm(inv)); }}>
            Stop altering
          </button>
        )}
        {canAlter && (
          <span className="field-note">
            Can be altered until{" "}
            {fmtDay(inv.alter_until)}
          </span>
        )}
        <button className="btn-secondary" onClick={() => downloadFinalInvoice(inv.id).catch((e) => setMsg({ kind: "error", text: errorText(e) }))}>
          Download PDF{draft ? " (draft)" : ""}
        </button>
        {draft && <span className="field-note">Issue both invoices together from the top.</span>}
        {draft && <button className="btn-secondary link-danger" onClick={() => act("delete")}>Delete draft</button>}
        {inv.status === "issued" && user?.role === "admin" && (
          <button className="btn-secondary link-danger" onClick={() => act("cancel")}>Cancel invoice</button>
        )}
        {!draft && user?.role === "admin" && (
          <button className="btn-secondary link-danger" onClick={() => act("delete")}>Delete invoice</button>
        )}
      </div>
    </div>
  );
}

function toForm(inv: FinalInvoice) {
  return {
    invoice_date: inv.invoice_date ?? "",
    due_date: inv.due_date ?? "",
    customer: { ...inv.customer },
    header: { ...inv.header } as Record<string, string | null>,
    lines: inv.lines.map((l) => ({
      description: l.description,
      sub_description: l.sub_description ?? "",
      sac: l.sac ?? "",
      tax_type: l.tax_type,
      non_gst_value: String(Number(l.non_gst_value)),
      taxable_value: String(Number(l.taxable_value)),
      gst_rate: String(Number(l.gst_rate)),
    })) as FinalInvoiceLine[],
    advance_received: String(Number(inv.totals.advance_received ?? 0)),
    remarks: inv.remarks ?? "",
    irn: inv.irn ?? "",
    ack_no: inv.ack_no ?? "",
    ack_date: inv.ack_date ?? "",
  };
}

function Field({
  label,
  value,
  onChange,
  disabled,
  type,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  disabled?: boolean;
  type?: string;
}) {
  return (
    <label className="final-field">
      <span>{label}</span>
      <input type={type} value={value ?? ""} disabled={disabled} onChange={(e) => onChange(e.target.value)} />
    </label>
  );
}
