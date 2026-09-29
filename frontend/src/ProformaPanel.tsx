import { useEffect, useLayoutEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  listProformas,
  createProforma,
  listChargeMaster,
  addProformaLineItem,
  removeProformaLineItem,
  updateProformaStatus,
  deleteDraftProforma,
  updateProforma,
  updateProformaLineItem,
  fillProformaFromShipment,
  getInvoice,
  downloadInvoice,
  listOrganizations,
  restoreProformaLine,
} from "./api";
import { useSaveShipment } from "./useSaveShipment";
import { OrganizationForm } from "./DailyUpdates";
import FinalInvoicesPanel from "./FinalInvoicesPanel";
import { useConfirm } from "./ConfirmDialog";
import type { Proforma, ChargeMasterEntry, Shipment, ChargeCategory, InvoiceView, Organization } from "./types";

export default function ProformaPanel({
  shipment,
  onShipmentChange,
}: {
  shipment: Shipment;
  onShipmentChange: (s: Shipment) => void;
}) {
  const [prefillChargeId, setPrefillChargeId] = useState<number | null>(null);
  const confirm = useConfirm();
  const [proformas, setProformas] = useState<Proforma[]>([]);
  const [charges, setCharges] = useState<ChargeMasterEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [activeId, setActiveId] = useState<number | null>(null);

  function refresh() {
    setLoading(true);
    Promise.all([listProformas(shipment.id), listChargeMaster()])
      .then(([p, c]) => {
        setProformas(p);
        setCharges(c);
        if (p.length && activeId === null) setActiveId(p[0].id);
      })
      .finally(() => setLoading(false));
  }

  useEffect(refresh, [shipment.id]);

  const [freshId, setFreshId] = useState<number | null>(null);
  async function handleNewVersion(role?: "seller" | "buyer") {
    const created = await createProforma(shipment.id, role ? { bill_to_role: role } : {});
    setActiveId(created.id);
    setFreshId(created.id);
    refresh();
  }

  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState("");
  async function saveName() {
    if (!active) return;
    const updated = await updateProforma(active.id, { name: newName.trim() || null });
    setProformas((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
    setRenaming(false);
  }

  const active = proformas.find((p) => p.id === activeId) ?? null;

  async function handleDeleteDraft() {
    if (!active || active.status !== "draft") return;
    const ok = await confirm({
      title: "Delete draft?",
      message: `Delete draft "${active.name || `v${active.version_number}`}"${active.line_items.length ? ` and its ${active.line_items.length} line item(s)` : ""}? It moves to Recently deleted — the admin can restore it.`,
      confirmLabel: "Delete draft",
      danger: true,
    });
    if (!ok) return;
    await deleteDraftProforma(active.id);
    const rest = proformas.filter((p) => p.id !== active.id);
    setProformas(rest);
    setActiveId(rest[0]?.id ?? null);
  }

  if (loading) return <div className="tracker-empty">Loading…</div>;

  // versions, the bill-to and notes — top of the left column
  const side = (
    <>
      <div className="proforma-toolbar">
        <div className="version-tabs">
          {proformas.map((p) => (
            <button
              key={p.id}
              className={p.id === activeId ? "tab active" : "tab"}
              onClick={() => {
                setActiveId(p.id);
                setRenaming(false);
              }}
              title={p.bill_to ? `Bill to ${p.bill_to}` : undefined}
            >
              {p.bill_to_role && <span className={`party-badge party-${p.bill_to_role}`}>{p.bill_to_role}</span>}
              {p.name || `v${p.version_number}`} · {p.status}
            </button>
          ))}
        </div>
        <div className="proforma-toolbar-actions">
          {active && !renaming && (
            <button
              className="btn-secondary"
              onClick={() => {
                setNewName(active.name ?? "");
                setRenaming(true);
              }}
            >
              Rename
            </button>
          )}
          {active?.status === "draft" && (
            <button className="btn-secondary link-danger" onClick={handleDeleteDraft}>
              Delete draft
            </button>
          )}
          {shipment.is_hss ? (
            <>
              <button onClick={() => handleNewVersion("seller")} title="HSS: invoice addressed to the seller">
                + Seller invoice{shipment.hss_seller ? ` (${shipment.hss_seller})` : ""}
              </button>
              <button onClick={() => handleNewVersion("buyer")} title="HSS: invoice addressed to the buyer">
                + Buyer invoice{shipment.hss_buyer ? ` (${shipment.hss_buyer})` : ""}
              </button>
            </>
          ) : (
            <button onClick={() => handleNewVersion()}>+ New Version</button>
          )}
        </div>
      </div>

      {renaming && active && (
        <form
          className="rename-bar"
          onSubmit={(e) => {
            e.preventDefault();
            saveName();
          }}
        >
          <input
            autoFocus
            maxLength={80}
            placeholder={`v${active.version_number}`}
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => e.key === "Escape" && setRenaming(false)}
            aria-label="Proforma name"
          />
          <button type="submit">Save name</button>
          <button type="button" className="btn-secondary" onClick={() => setRenaming(false)}>
            Cancel
          </button>
        </form>
      )}

      {shipment.is_hss && (
        <div className="hss-banner">
          <strong>HSS shipment</strong> — two invoices: seller <b>{shipment.hss_seller ?? "?"}</b> and buyer{" "}
          <b>{shipment.hss_buyer ?? "?"}</b>. Change the parties on the Overview tab.
        </div>
      )}
      {active?.bill_to && (
        <p className="tracker-subtitle">
          Bill to: <strong>{active.bill_to}</strong>
          {active.bill_to_role && ` (HSS ${active.bill_to_role})`}
        </p>
      )}

      <ExamReminder
        shipment={shipment}
        examCharge={charges.find((c) => c.code === "EC") ?? null}
        proforma={active}
        onShipmentChange={onShipmentChange}
        onAddExamCharge={(id) => setPrefillChargeId(id)}
      />

      {active && active.id === freshId && active.line_items.length > 0 && (
        <div className="prefill-note">
          <strong>Charges pre-filled</strong> from the licence rates, HSS rule and the shipment's documents — review each
          line (click to edit, ✕ to remove) before sending.
          <button type="button" className="link-button" onClick={() => setFreshId(null)}>
            Got it
          </button>
        </div>
      )}

    </>
  );

  return (
    <div className="proforma-panel">
      {!active ? (
        <div className="pf-split">
          <aside className="pf-left">{side}</aside>
          <section className="pf-right">
            <div className="tracker-empty">
              No proforma yet — {shipment.is_hss ? "create the seller and/or buyer invoice." : "create the first version."}
            </div>
            <FinalInvoicesPanel shipmentId={shipment.id} proforma={active} />
          </section>
        </div>
      ) : (
        <ProformaVersion
          side={side}
          finals={<FinalInvoicesPanel shipmentId={shipment.id} proforma={active} />}
          proforma={active}
          charges={charges}
          containerCount={containerCount(shipment)}
          weightKg={weightKg(shipment)}
          isHss={!!shipment.is_hss}
          prefillChargeId={prefillChargeId}
          onPrefilled={() => setPrefillChargeId(null)}
          onChange={(updated) => {
            setProformas((prev) => prev.map((p) => (p.id === updated.id ? updated : p)));
          }}
        />
      )}
    </div>
  );
}

/**
 * Examination means an Examination charge is due. Status comes from the OOC
 * copy (Examination row of its Processing Details table) or is set by hand here.
 */
function ExamReminder({
  shipment: s,
  examCharge,
  proforma,
  onShipmentChange,
  onAddExamCharge,
}: {
  shipment: Shipment;
  examCharge: ChargeMasterEntry | null;
  proforma: Proforma | null;
  onShipmentChange: (s: Shipment) => void;
  onAddExamCharge: (chargeId: number) => void;
}) {
  const saveShipment = useSaveShipment();
  const [saving, setSaving] = useState(false);
  const hasExamLine = !!examCharge && !!proforma?.line_items.some((li) => li.charge_master_id === examCharge.id);
  const source =
    s.under_examination == null
      ? "No OOC copy read yet — examination unknown."
      : s.examination_at
        ? `Per the OOC copy: examined ${s.examination_at}.`
        : s.under_examination
          ? "Marked as under examination by hand."
          : "Per the OOC copy (or marked by hand): not examined.";

  async function toggle() {
    setSaving(true);
    try {
      onShipmentChange((await saveShipment(s, { under_examination: !s.under_examination })).shipment);
    } finally {
      setSaving(false);
    }
  }

  const tone = s.under_examination ? (hasExamLine ? "ok" : "warn") : "neutral";
  return (
    <div className={`exam-reminder exam-${tone}`}>
      <div>
        <strong>
          {s.under_examination
            ? hasExamLine
              ? "Under examination — Examination charge is on this proforma."
              : "Under examination — add the Examination charge."
            : "Not under examination."}
        </strong>
        <div className="exam-source">{source}</div>
      </div>
      <div className="exam-actions">
        {s.under_examination && !hasExamLine && examCharge && proforma?.status === "draft" && (
          <button type="button" onClick={() => onAddExamCharge(examCharge.id)}>
            Add Examination charge
          </button>
        )}
        <label className="toggle-row">
          <span>Under examination</span>
          <input type="checkbox" role="switch" checked={!!s.under_examination} disabled={saving} onChange={toggle} />
        </label>
      </div>
    </div>
  );
}

/** BE gross weight in kg (the tracker keeps "95.800 MTS"). */
function weightKg(s: Shipment): number | null {
  const raw = s.gross_wt ?? "";
  const m = raw.match(/[\d.]+/);
  if (!m) return null;
  const v = Number(m[0]);
  return /MT/i.test(raw) ? Math.round(v * 1000) : v;
}

/** The shipment's "Cntr" as a number (free text in the tracker, e.g. "5"). */
function containerCount(s: Shipment): number | null {
  const m = (s.container ?? "").match(/\d+/);
  return m && Number(m[0]) > 0 ? Number(m[0]) : null;
}

const SECTION_LABELS: Record<ChargeCategory, string> = {
  service: "Billed by Clarus",
  reimbursement: "Reimbursement (at actuals)",
  royalty: "Royalty",
  cost_inclusion: "Cost Inclusion",
};

// lines filled from documents (invoice / BE / challan) — can be put back from them
const FROM_DOCUMENTS: Record<string, string> = {
  DO: "Shipping Line (liner invoice)",
  CD: "Customs Duty (BE / challan)",
  SD: "Stamp Duty",
  CFS: "CFS (CFS invoice)",
  EC: "Examination (under examination)",
};

/** "std ₹7,000 / container" for the charge dropdown. */
function standardRate(c: ChargeMasterEntry): string {
  if (c.default_rate == null) return "";
  const per = c.calculation_basis === "per_container" ? " / container" : c.calculation_basis === "per_kg" ? " / kg" : "";
  return ` — std ₹${Number(c.default_rate).toLocaleString("en-IN")}${per}`;
}

const inr = (v: string | number | null | undefined) =>
  v == null || v === "" ? "" : Number(v).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const dmy = (iso: string | null | undefined) => (iso ? iso.split("-").reverse().join("-") : "");

function errorText(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : "Something went wrong — please try again.";
}

function ProformaVersion({
  side,
  finals,
  proforma,
  charges,
  containerCount,
  weightKg,
  isHss,
  prefillChargeId,
  onPrefilled,
  onChange,
}: {
  side: ReactNode;
  finals: ReactNode;
  proforma: Proforma;
  charges: ChargeMasterEntry[];
  containerCount: number | null;
  weightKg: number | null;
  isHss: boolean;
  prefillChargeId: number | null;
  onPrefilled: () => void;
  onChange: (p: Proforma) => void;
}) {
  const [chargeId, setChargeId] = useState<number | "">("");
  const [rate, setRate] = useState("");
  const [category, setCategory] = useState<ChargeCategory | "">("");
  const [invoice, setInvoice] = useState<InvoiceView | null>(null);
  const [fillResult, setFillResult] = useState<{ added: string[]; updated: string[]; skipped: string[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<"xlsx" | "pdf" | null>(null);
  const confirm = useConfirm();
  const draft = proforma.status === "draft";
  const [pane, setPane] = useState<"proforma" | "final">("proforma");

  // The invoice layout is rebuilt server-side after every change
  useEffect(() => {
    getInvoice(proforma.id).then(setInvoice).catch((e) => setError(errorText(e)));
  }, [proforma]);
  useEffect(() => setFillResult(null), [proforma.id]);

  // "Add Examination charge" from the reminder: pick the charge, fill its default rate
  useEffect(() => {
    if (prefillChargeId == null) return;
    const c = charges.find((x) => x.id === prefillChargeId);
    selectCharge(prefillChargeId);
    if (c?.default_rate != null) setRate(String(Number(c.default_rate)));
    document.getElementById("proforma-rate")?.focus();
    onPrefilled();
  }, [prefillChargeId, charges, onPrefilled]);
  const [quantity, setQuantity] = useState("1");
  const [busy, setBusy] = useState(false);

  const selected = charges.find((c) => c.id === chargeId);
  const perContainer = selected?.calculation_basis === "per_container";
  const perKg = selected?.calculation_basis === "per_kg";
  // GST Difference is worked out from the bill rate; Royalty only applies to HSS shipments
  const pickable = charges.filter((c) => c.code !== "GSTD" && (isHss || c.code !== "ROY"));

  // Agency / Examination are per container, Royalty per kg of the BE gross weight;
  // the standard rate is filled in (editable)
  function selectCharge(id: number | "") {
    setChargeId(id);
    const c = charges.find((x) => x.id === id);
    setRate(c?.default_rate != null ? String(Number(c.default_rate)) : "");
    setQuantity(
      c?.calculation_basis === "per_container" && containerCount
        ? String(containerCount)
        : c?.calculation_basis === "per_kg" && weightKg
          ? String(weightKg)
          : "1",
    );
  }

  async function run(action: () => Promise<Proforma>) {
    setError(null);
    try {
      onChange(await action());
    } catch (e) {
      setError(errorText(e));
      throw e;
    }
  }

  async function handleAdd(e: FormEvent) {
    e.preventDefault();
    if (!chargeId || !rate) return;
    setBusy(true);
    try {
      await run(() =>
        addProformaLineItem(proforma.id, {
          charge_master_id: Number(chargeId),
          rate: Number(rate),
          quantity: Number(quantity) || 1,
          ...(category ? { category } : {}),
        }),
      );
      setChargeId("");
      setRate("");
      setQuantity("1");
      setCategory("");
    } catch {
      /* shown in the error bar */
    } finally {
      setBusy(false);
    }
  }

  async function handleFill() {
    setBusy(true);
    setError(null);
    try {
      const res = await fillProformaFromShipment(proforma.id);
      onChange(res.proforma);
      setFillResult({ added: res.added, updated: res.updated, skipped: res.skipped });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleDownload(fmt: "xlsx" | "pdf") {
    setDownloading(fmt);
    setError(null);
    try {
      await downloadInvoice(proforma.id, fmt);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setDownloading(null);
    }
  }

  async function restore(key: string) {
    setBusy(true);
    try {
      await run(() => restoreProformaLine(proforma.id, key));
    } catch {
      /* shown in the error bar */
    } finally {
      setBusy(false);
    }
  }

  const saveLine = (lineId: number, changes: Parameters<typeof updateProformaLineItem>[2]) =>
    run(() => updateProformaLineItem(proforma.id, lineId, changes));

  return (
    // split pane (client, 2026-09-30): everything you do on the left, one uniform column;
    // the invoice on the right — or the final invoices made from it
    <div className="proforma-version pf-split">
      <aside className="pf-left">
        {side}
          <div className="invoice-actions">
            {draft && (
              <button
                onClick={handleFill}
                disabled={busy}
                title="Add Agency, Examination, Customs Duty (+ challan interest), Stamp Duty, CFS, Royalty (HSS) and shipping line from what the shipment knows; refreshes Customs / Stamp Duty"
              >
                Fill / refresh from shipment
              </button>
            )}
            <button className="btn-secondary" onClick={() => handleDownload("xlsx")} disabled={!!downloading}>
              {downloading === "xlsx" ? "Preparing…" : "Download Excel"}
            </button>
            <button className="btn-secondary" onClick={() => handleDownload("pdf")} disabled={!!downloading}>
              {downloading === "pdf" ? "Preparing…" : "Download PDF"}
            </button>
            {draft && proforma.line_items.length > 0 && (
              <button
                onClick={async () => {
                  if (
                    invoice?.customs_duty?.source === "be" &&
                    !(await confirm({
                      title: "No duty challan",
                      message:
                        "There's no duty challan or OOC copy for this BE, so the interest is unknown and Customs Duty is only the BE amount. Upload the challan and Fill / refresh first, or mark as sent anyway?",
                      confirmLabel: "Mark as sent anyway",
                    }))
                  )
                    return;
                  run(() => updateProformaStatus(proforma.id, "sent")).catch(() => {});
                }}
              >
                Mark as Sent
              </button>
            )}
            {draft && (
              <span className="field-note">
                Click any shaded cell to edit it. Draft lines update themselves when documents or the challan change — except
                ones you've edited (marked ✎).
              </span>
            )}
          </div>

          {error && <div className="invoice-error">{error}</div>}
          {draft && (proforma.suppressed?.length ?? 0) > 0 && (
            <div className="removed-lines">
              <span>Removed from this proforma (not updated automatically):</span>
              {proforma.suppressed!.map((key) => (
                <span key={key} className="removed-line">
                  {FROM_DOCUMENTS[key.split(":")[0]] ?? key}
                  <button type="button" className="link-button" disabled={busy} onClick={() => restore(key)}>
                    Restore
                  </button>
                </span>
              ))}
            </div>
          )}
          {fillResult && (
            <div className="fill-result">
              <div>
                <strong>Added:</strong> {fillResult.added.length ? fillResult.added.join(", ") : "nothing new"}
              </div>
              {fillResult.updated.length > 0 && (
                <div>
                  <strong>Refreshed:</strong> {fillResult.updated.join(", ")}
                </div>
              )}
              {fillResult.skipped.length > 0 && (
                <ul>
                  {fillResult.skipped.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              )}
              <button className="btn-secondary" onClick={() => setFillResult(null)}>
                Dismiss
              </button>
            </div>
          )}

          {draft && (
            <form className="add-shipment-form" onSubmit={handleAdd}>
              <select value={chargeId} onChange={(e) => selectCharge(e.target.value ? Number(e.target.value) : "")}>
                <option value="">Select charge…</option>
                {pickable.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.sac_code}, {Number(c.gst_rate)}% GST){standardRate(c)}
                    {FROM_DOCUMENTS[c.code] ? " — or from documents" : ""}
                  </option>
                ))}
              </select>
              <input
                id="proforma-rate"
                placeholder="Rate"
                type="number"
                step="0.01"
                value={rate}
                onChange={(e) => setRate(e.target.value)}
                required
              />
              <input
                placeholder="Qty"
                type="number"
                step="0.01"
                value={quantity}
                onChange={(e) => setQuantity(e.target.value)}
              />
              <select value={category} onChange={(e) => setCategory(e.target.value as ChargeCategory | "")} aria-label="Section">
                <option value="">Section: charge default</option>
                {(Object.keys(SECTION_LABELS) as ChargeCategory[]).map((c) => (
                  <option key={c} value={c}>
                    {SECTION_LABELS[c]}
                  </option>
                ))}
              </select>
              {perKg && (
                <span className="field-note">
                  {weightKg
                    ? `₹/kg × ${weightKg.toLocaleString("en-IN")} kg = ₹${((Number(rate) || 0) * (Number(quantity) || 0)).toLocaleString("en-IN")} + GST`
                    : "Per kg — this shipment has no gross weight; enter the quantity."}
                </span>
              )}
              {perContainer && (
                <span className="field-note">
                  {containerCount
                    ? `× ${containerCount} container${containerCount > 1 ? "s" : ""} = ₹${((Number(rate) || 0) * (Number(quantity) || 0)).toLocaleString("en-IN")} + GST`
                    : "Per container — this shipment has no container count; enter the quantity."}
                </span>
              )}
              <button type="submit" disabled={busy}>
                Add Line Item
              </button>
              {selected && FROM_DOCUMENTS[selected.code] && (
                <button
                  type="button"
                  className="btn-secondary"
                  disabled={busy}
                  title="Use the figure from the uploaded invoice / BE / challan instead of typing a rate"
                  onClick={() => restore(selected.code === "DO" ? "DO:Liner Inv" : selected.code).then(() => selectCharge(""))}
                >
                  Add from documents
                </button>
              )}
            </form>
          )}

        <div className="pf-finals-link">
          <span>Final invoices (tax + reimbursement)</span>
          <button type="button" className="btn-secondary" onClick={() => setPane("final")}>
            Open →
          </button>
        </div>
      </aside>
      <section className="pf-right">
        <div className="pf-pane-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={pane === "proforma"} className={pane === "proforma" ? "on" : ""} onClick={() => setPane("proforma")}>
            Proforma
          </button>
          <button type="button" role="tab" aria-selected={pane === "final"} className={pane === "final" ? "on" : ""} onClick={() => setPane("final")}>
            Final invoices
          </button>
        </div>
        {pane === "final" ? (
          <div className="pf-final-pane">{finals}</div>
        ) : (
      <InvoicePreview>
          {invoice && <DutyNotice invoice={invoice} />}

          {!invoice ? (
            <div className="tracker-empty">Loading invoice…</div>
          ) : (
            <InvoiceSheet
              invoice={invoice}
              editable={draft}
              onSave={saveLine}
              onSaveProforma={(changes) => run(() => updateProforma(proforma.id, changes))}
              onRemove={(id) => run(() => removeProformaLineItem(proforma.id, id)).catch(() => {})}
            />
          )}
      </InvoicePreview>
        )}
      </section>
    </div>
  );
}

/** Where the customs duty interest came from, and whether today's challan list is in. */
function DutyNotice({ invoice }: { invoice: InvoiceView }) {
  const cd = invoice.customs_duty;
  if (!cd) return null;
  const interest = Number(cd.interest) > 0 ? `interest ₹${inr(cd.interest)}` : "no interest";
  if (cd.source === "ooc")
    return (
      <div className="duty-notice duty-ok">
        Customs Duty from the OOC copy's total (final amount paid){Number(cd.interest) > 0 ? ` — incl. interest ₹${inr(cd.interest)}` : ""}.
      </div>
    );
  if (!cd.challan_uploaded_at)
    return (
      <div className="duty-notice duty-action" role="alert">
        <strong>Upload the duty challan for this BE.</strong> There's no challan or OOC copy yet, so the interest is
        unknown and Customs Duty is only the BE amount. <Link to="/dashboard">Upload it on the Dashboard</Link>, then click{" "}
        <b>Fill / refresh</b>.
      </div>
    );
  if (!cd.challan_today)
    return (
      <div className="duty-notice duty-warn">
        Challan from {dmy(cd.challan_uploaded_at.slice(0, 10))} ({interest}) — upload today's list on the Dashboard, then{" "}
        <b>Fill / refresh</b> for current interest.
      </div>
    );
  return <div className="duty-notice duty-ok">Customs Duty per today's challan: {interest}.</div>;
}

/** Bill To: the party (after the '-' on HSS) with its details from the organization repository. */
function BillTo({
  inv,
  editable,
  onSaveProforma,
}: {
  inv: InvoiceView;
  editable: boolean;
  onSaveProforma: (changes: { bill_to_org_id?: number | null }) => Promise<void>;
}) {
  const [mode, setMode] = useState<"view" | "pick" | "new">("view");
  const [orgs, setOrgs] = useState<Organization[]>([]);
  const bt = inv.bill_to;
  const org = bt.organization;

  useEffect(() => {
    if (mode === "pick") listOrganizations().then(setOrgs);
  }, [mode]);

  return (
    <div className="inv-box">
      <div className="inv-box-head">Bill To</div>
      <div className="inv-billto">{bt.name ?? "—"}</div>
      {org ? (
        <div className="inv-org">
          {org.address && <div>{org.address}</div>}
          {(org.gstin || org.pan || org.state) && (
            <div>{[org.gstin && `GSTIN ${org.gstin}`, org.pan && `PAN ${org.pan}`, org.state].filter(Boolean).join(" · ")}</div>
          )}
          {(org.email || org.phone) && <div>{[org.email, org.phone].filter(Boolean).join(" · ")}</div>}
        </div>
      ) : (
        <div className="inv-org-missing">"{bt.party}" (BE importer) isn't in the organization repository — no address / GSTIN on the invoice.</div>
      )}
      {mode === "view" && (
        <div className="inv-org-actions">
          {!org && (
            <button type="button" className="link-button" onClick={() => setMode("new")}>
              Add details
            </button>
          )}
          {editable && (
            <button type="button" className="link-button" onClick={() => setMode("pick")}>
              {org ? "Change organization" : "Pick existing"}
            </button>
          )}
        </div>
      )}
      {mode === "pick" && (
        <div className="inv-org-actions">
          <select
            defaultValue={org?.id ?? ""}
            aria-label="Bill To organization"
            onChange={async (e) => {
              await onSaveProforma({ bill_to_org_id: e.target.value ? Number(e.target.value) : null }).catch(() => {});
              setMode("view");
            }}
          >
            <option value="">Match by name automatically</option>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>
                {o.name}
              </option>
            ))}
          </select>
          <button type="button" className="link-button" onClick={() => setMode("view")}>
            Cancel
          </button>
        </div>
      )}
      {mode === "new" && (
        <OrganizationForm
          org={null}
          initialName={bt.party ?? undefined}
          onSaved={async (o) => {
            if (editable) await onSaveProforma({ bill_to_org_id: o.id }).catch(() => {});
            else await onSaveProforma({}).catch(() => {});
            setMode("view");
          }}
          onCancel={() => setMode("view")}
        />
      )}
      <KV
        k="BL consignee"
        v={bt.bl_consignee ? `${bt.bl_consignee}${bt.bl_consignee_ad_code ? ` (AD ${bt.bl_consignee_ad_code})` : ""}` : null}
      />
      <KV k="BE importer" v={bt.be_importer} />
      {bt.hss && <KV k="HSS" v={`${bt.hss.seller ?? "?"} → ${bt.hss.buyer ?? "?"}`} />}
    </div>
  );
}

/** The proforma in the client's template layout; draft line cells are editable like Excel. */
function InvoiceSheet({
  invoice: inv,
  editable,
  onSave,
  onSaveProforma,
  onRemove,
}: {
  invoice: InvoiceView;
  editable: boolean;
  onSave: (lineId: number, changes: Parameters<typeof updateProformaLineItem>[2]) => Promise<void>;
  onSaveProforma: (changes: { bill_to_org_id?: number | null; bill_rate?: number | null }) => Promise<void>;
  onRemove: (lineId: number) => void;
}) {
  const ref = inv.reference;
  const d = inv.details;
  const cols = editable ? 8 : 7;
  return (
    <div className="invoice-sheet">
      <div className="inv-company">
        <div className="inv-company-name">{inv.company.name}</div>
        <div>{inv.company.address}</div>
        <div>{inv.company.tax_line}</div>
        <div>{inv.company.contact_line}</div>
      </div>
      <div className="inv-title">
        {inv.title}
        {inv.copy_label && <span className="inv-copy">{inv.copy_label}</span>}
      </div>
      {inv.disclaimer && <div className="inv-disclaimer">{inv.disclaimer}</div>}

      <div className="inv-parties">
        <BillTo inv={inv} editable={editable} onSaveProforma={onSaveProforma} />
        <div className="inv-box">
          <div className="inv-box-head">Invoice details</div>
          <KV k="Invoice date" v={dmy(d.invoice_date)} />
          <KV k="Job" v={d.job} />
          <KV k="BE No / Date" v={[d.be_no, dmy(d.be_date)].filter(Boolean).join(" / ")} />
          <KV k="Port" v={d.port} />
          <KV k="Version" v={d.name ? `${d.name} (v${d.version})` : `v${d.version}`} />
        </div>
      </div>

      <div className="inv-reference">
        <KV k="Assessable value" v={ref.assessable_value ? `₹${inr(ref.assessable_value)}` : null} />
        <KV k="MBL / HBL" v={[ref.mbl, ref.hbl].filter(Boolean).join(" / ")} />
        <KV k="HSS" v={ref.hss} />
        <KV k="Containers" v={ref.containers != null ? String(ref.containers) : null} />
        <KV k="Weight (kgs)" v={ref.weight_kgs} />
        <KV k="Examination" v={ref.exam_applicable} />
      </div>

      {/* value of goods / GST beside the assessable value (client, 2026-09-30) */}
      <div className="tracker-grid-wrap">
        <table className="inv-table inv-value">
          <thead>
            <tr>
              <th className="num">{inv.value.label}</th>
              <th className="num">GST input</th>
              <th className="num">Value / kg</th>
              <th className="num">Bill rate (₹/kg)</th>
              <th className="num">GST output (18%)</th>
              <th className="num">GST difference</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td className="num">{inr(inv.value.value_of_goods)}</td>
              <td className="num">{inr(inv.value.gst_input)}</td>
              <td className="num">{inr(inv.value.value_per_kg) || "—"}</td>
              <EditCell
                editable={editable}
                numeric
                allowEmpty
                raw={inv.value.bill_rate ?? ""}
                display={inv.value.bill_rate ? inr(inv.value.bill_rate) : editable ? "enter…" : "—"}
                className="num"
                title="HSS bill rate per kg — set by the rules; type one to fix it by hand, clear it to go back to automatic."
                onSave={(v) => onSaveProforma({ bill_rate: v === "" ? null : Number(v) })}
              />
              <td className="num">{inr(inv.value.gst_output) || "—"}</td>
              <td className="num">{inr(inv.value.gst_difference) || "—"}</td>
            </tr>
          </tbody>
        </table>
        {inv.value.bill_rate && (
          <div className="bill-rate-suggest">
            {inv.value.bill_rate_manual ? (
              <>
                Bill rate typed by hand — kept unless the costs pass it.{" "}
                {editable && (
                  <button type="button" className="link-button" onClick={() => onSaveProforma({ bill_rate: null }).catch(() => {})}>
                    Back to automatic (₹{inr(inv.value.suggested_bill_rate)}/kg)
                  </button>
                )}
              </>
            ) : (
              <>Bill rate by the rules: value/kg + at least 10 paise, GST difference positive, next 25 paise — follows the costs.</>
            )}
          </div>
        )}
        <div className="inv-value-note">{inv.value.note}</div>
      </div>


      <div className="tracker-grid-wrap">
        <table className="inv-table">
          <thead>
            <tr>
              <th className="inv-desc">Description</th>
              <th>SAC</th>
              <th className="num">Rate</th>
              <th className="num">Qty</th>
              <th className="num">Amount (₹)</th>
              <th className="num">GST (₹)</th>
              <th className="num">Total (₹)</th>
              {editable && <th />}
            </tr>
          </thead>
          {inv.sections.filter((sec) => sec.lines.length > 0 || sec.category !== "royalty").map((sec) => (
            <tbody key={sec.category}>
              <tr className="inv-section">
                <td colSpan={cols}>
                  {sec.title}
                  {!sec.counts_in_total && <span className="inv-section-note"> — for reference, not in the total</span>}
                </td>
              </tr>
              {sec.lines.map((li) => (
                <tr key={li.id}>
                  <EditCell editable={editable} raw={li.description ?? ""} display={li.description ?? ""}
                    className={`inv-desc${li.is_manual ? " inv-manual" : ""}`}
                    onSave={(v) => onSave(li.id, { description: v })} />
                  <td>{li.sac_code}</td>
                  <EditCell editable={editable} numeric raw={li.rate} display={inr(li.rate)} className="num"
                    onSave={(v) => onSave(li.id, { rate: Number(v) })} />
                  <EditCell editable={editable} numeric raw={li.quantity} display={li.quantity} className="num"
                    onSave={(v) => onSave(li.id, { quantity: Number(v) })} />
                  <td className="num">{inr(li.amount)}</td>
                  <EditCell editable={editable} numeric allowEmpty raw={li.gst_amount} display={inr(li.gst_amount)} className="num"
                    title={li.gst_is_actual ? "Actual GST (clear the cell to go back to the GST rate)" : `${li.gst_rate}% of amount`}
                    onSave={(v) => onSave(li.id, { gst_amount: v === "" ? null : Number(v) })} />
                  <td className="num">{inr(li.total)}</td>
                  {editable && (
                    <td className="inv-row-actions">
                      <select
                        value={sec.category}
                        aria-label="Move to section"
                        onChange={(e) => onSave(li.id, { category: e.target.value as ChargeCategory }).catch(() => {})}
                      >
                        {(Object.keys(SECTION_LABELS) as ChargeCategory[]).map((c) => (
                          <option key={c} value={c}>
                            {SECTION_LABELS[c]}
                          </option>
                        ))}
                      </select>
                      <button className="link-danger" onClick={() => onRemove(li.id)} title="Remove line">
                        ✕
                      </button>
                    </td>
                  )}
                </tr>
              ))}
              {sec.lines.length === 0 && (
                <tr>
                  <td colSpan={cols} className="inv-empty">—</td>
                </tr>
              )}
              <tr className="inv-subtotal">
                <td colSpan={6}>Subtotal — {sec.title}</td>
                <td className="num">{inr(sec.subtotal)}</td>
                {editable && <td />}
              </tr>
            </tbody>
          ))}
          <tbody>
            {Number(inv.round_off) !== 0 && (
              <tr className="inv-roundoff">
                <td colSpan={6}>Round off</td>
                <td className="num">{Number(inv.round_off) > 0 ? "+" : "−"}{inr(Math.abs(Number(inv.round_off)))}</td>
                {editable && <td />}
              </tr>
            )}
            <tr className="inv-grand">
              <td colSpan={6}>Grand Total — {inv.grand_total_label}</td>
              <td className="num">₹{inr(inv.grand_total)}</td>
              {editable && <td />}
            </tr>
          </tbody>
        </table>
      </div>

      <div className="inv-footer">
        <div>
          <div className="inv-box-head">Notes</div>
          <ol className="inv-notes">
            {inv.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ol>
        </div>
        <div>
          <div className="inv-box-head">Bank details</div>
          {inv.bank.map(([k, v]) => (
            <KV key={k} k={k} v={v} />
          ))}
        </div>
      </div>
    </div>
  );
}

function KV({ k, v }: { k: string; v: string | null | undefined }) {
  return (
    <div className="inv-kv">
      <span>{k}</span>
      <span>{v || "—"}</span>
    </div>
  );
}

/** Click to edit; Enter / leaving the cell saves, Esc cancels. */
function EditCell({
  editable,
  raw,
  display,
  numeric,
  allowEmpty,
  className,
  title,
  onSave,
}: {
  editable: boolean;
  raw: string;
  display: string;
  numeric?: boolean;
  allowEmpty?: boolean;
  className?: string;
  title?: string;
  onSave: (value: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  async function commit() {
    const v = value.trim();
    const bad = numeric && v !== "" && (Number.isNaN(Number(v)) || Number(v) < 0);
    if (v === String(raw).trim() || bad || (v === "" && !allowEmpty)) {
      setEditing(false);
      return;
    }
    setSaving(true);
    try {
      await onSave(v);
    } catch {
      /* error shown above the invoice */
    } finally {
      setSaving(false);
      setEditing(false);
    }
  }

  if (!editable) return <td className={className} title={title}>{display}</td>;
  if (!editing)
    return (
      <td
        className={`${className ?? ""} inv-editable`}
        title={title}
        tabIndex={0}
        onClick={() => {
          setValue(numeric ? String(Number(raw)) : raw);
          setEditing(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === "F2") {
            setValue(numeric ? String(Number(raw)) : raw);
            setEditing(true);
          }
        }}
      >
        {display}
      </td>
    );
  return (
    <td className={`${className ?? ""} inv-editing`}>
      <input
        autoFocus
        disabled={saving}
        inputMode={numeric ? "decimal" : undefined}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onFocus={(e) => e.target.select()}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
          if (e.key === "Escape") setEditing(false);
        }}
      />
    </td>
  );
}

/**
 * The invoice as one A4 page in the right half, like a document preview (client, 2026-09-30).
 * The page is always A4 (794 × 1123 px at 96 dpi): an invoice taller than that is shrunk to
 * fit inside it, as the PDF is. "Fit page" scales the page to the pane; "100 %" shows it
 * full size to edit.
 */
const A4_W = 794;
const A4_H = 1123;

function InvoicePreview({ children }: { children: ReactNode }) {
  const pane = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<"fit" | "full">(() => {
    try {
      return localStorage.getItem("clarus.invoiceZoom") === "full" ? "full" : "fit";
    } catch {
      return "fit";
    }
  });
  const [pageScale, setPageScale] = useState(0.7);
  const [inner, setInner] = useState(1); // content shrunk to fit one A4 page
  const [paneH, setPaneH] = useState(800);

  useLayoutEffect(() => {
    const el = pane.current;
    const c = content.current;
    if (!el || !c) return;
    const measure = () => {
      const top = el.getBoundingClientRect().top + window.scrollY;
      const h = Math.max(480, window.innerHeight - top - 12);
      setPaneH(h);
      const natural = c.scrollHeight; // at the content's own (unscaled) size
      setInner(Math.min(1, (A4_H - 76) / Math.max(1, natural))); // page margins + a little air
      const fit = Math.min((el.clientWidth - 24) / A4_W, (h - 44) / A4_H);
      setPageScale(mode === "fit" ? Math.max(0.3, fit) : 1);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(c);
    ro.observe(el);
    window.addEventListener("resize", measure);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [mode]);

  const pick = (m: "fit" | "full") => {
    setMode(m);
    try {
      localStorage.setItem("clarus.invoiceZoom", m);
    } catch {
      /* private window */
    }
  };

  return (
    <div className="invoice-preview" ref={pane} style={{ height: paneH }}>
      <div className="invoice-preview-zoom">
        <button type="button" className={mode === "fit" ? "on" : ""} onClick={() => pick("fit")}>
          Fit page
        </button>
        <button type="button" className={mode === "full" ? "on" : ""} onClick={() => pick("full")}>
          100 %
        </button>
      </div>
      {/* the A4 sheet, scaled to the pane */}
      <div className="a4-frame" style={{ width: A4_W * pageScale, height: A4_H * pageScale }}>
        <div className="a4-page" style={{ transform: `scale(${pageScale})` }}>
          {/* the invoice, shrunk to fit one page when it's longer */}
          <div
            ref={content}
            className="a4-content"
            style={inner < 1 ? { transform: `scale(${inner})`, width: `${100 / inner}%` } : undefined}
          >
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
