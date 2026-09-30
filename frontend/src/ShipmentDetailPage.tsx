import CustomsTimeline from "./CustomsTimeline";
import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { useAuth } from "./AuthContext";
import { useParams, useSearchParams, Link } from "react-router-dom";
import { correctInvoiceAmounts, getShipment, listDocuments, refreshIcegate, setCostInclusion } from "./api";
import { useSaveShipment } from "./useSaveShipment";
import { DOCUMENT_TYPE_LABELS, SHIPMENT_STATUS_LABELS, type InvoiceCharge, type Shipment, type ShipmentDocument } from "./types";
import DocumentManagerPanel from "./DocumentManagerPanel";
import ProformaPanel from "./ProformaPanel";
import FpodContainers from "./FpodContainers";
import { formatPort, usePorts } from "./ports";

type Tab = "overview" | "customs" | "documents" | "proforma";

// sea ports: free days start at the POD inward; every other port is inland (ICD) — client, 2026-09-30
const SEA_PORTS = new Set(["INMUN1", "INNSA1"]);

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-08-27" -> "27-Aug-2026" */
function fmtDate(v: string | null): string | null {
  if (!v) return null;
  const [y, m, d] = v.split("-");
  return `${d}-${MONTHS[Number(m) - 1]}-${y}`;
}

/** "108560.00" -> "₹1,08,560.00" (Indian grouping) */
function fmtMoney(v: string | null): string | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  if (Number.isNaN(n)) return v;
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

const TABS: Tab[] = ["overview", "customs", "documents", "proforma"];

export default function ShipmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  // the open tab lives in the URL (?tab=proforma): links, Back and refresh land on it
  const [params, setParams] = useSearchParams();
  const fromUrl = params.get("tab") as Tab | null;
  const tab: Tab = fromUrl && TABS.includes(fromUrl) ? fromUrl : "overview";
  const setTab = (t: Tab) => setParams(t === "overview" ? {} : { tab: t });
  return <ShipmentDetail shipmentId={Number(id)} tab={tab} onTab={setTab} />;
}

/**
 * The shipment: a page of its own, or (peek) a panel over the tracker — open a row,
 * glance, close, next row (client, 2026-09-29).
 */
export function ShipmentDetail({
  shipmentId,
  onClose,
  tab: tabProp,
  onTab,
}: {
  shipmentId: number;
  onClose?: () => void;
  tab?: Tab;
  onTab?: (t: Tab) => void;
}) {
  const peek = !!onClose;
  const [shipment, setShipment] = useState<Shipment | null>(null);
  const [loading, setLoading] = useState(true);
  const [localTab, setLocalTab] = useState<Tab>("overview"); // peek panel: no URL of its own
  const tab = tabProp ?? localTab;
  const setTab = onTab ?? setLocalTab;
  const isAdmin = useAuth().user?.role === "admin"; // invoicing is admin-only

  const reload = useCallback(() => getShipment(shipmentId).then(setShipment), [shipmentId]);

  useEffect(() => {
    setLoading(true);
    reload().finally(() => setLoading(false));
  }, [reload]);

  if (loading) return <div className="tracker-empty">Loading…</div>;
  if (!shipment)
    return (
      <div className="tracker-empty">
        <p>This shipment doesn’t exist or was deleted.</p>
        <Link to="/shipments">Back to the Shipment Tracker</Link>
      </div>
    );

  return (
    <div className={peek ? "detail-page detail-peek" : "detail-page"}>
      {peek ? (
        <div className="peek-bar">
          <Link to={`/shipments/${shipment.id}`} className="back-link">
            Open full page ↗
          </Link>
          <button type="button" className="peek-close" onClick={onClose} aria-label="Close" title="Close (Esc)">
            ✕
          </button>
        </div>
      ) : (
        <Link to="/shipments" className="back-link">
          ← Back to Shipment Tracker
        </Link>
      )}

      <header className="detail-header">
        <div className="detail-title">
          <span className="detail-job">{shipment.job ? `Job ${shipment.job}` : "No job number yet"}</span>
          <span className="detail-client">
            {shipment.client ?? "—"} · {shipment.consignee ?? "—"}
          </span>
        </div>
        {/* left: the two keys everything is filed and searched by; right: where the clearance stands */}
        <div className="key-ids">
          <div className="key-id key-id-keys">
            <div className={`key-id-cell${(shipment.mbl ?? "").length + (shipment.hbl ?? "").length > 26 ? " key-id-long" : ""}`}>
              <span className="key-id-label">BL No (MBL{shipment.hbl ? " / HBL" : ""})</span>
              <span className="key-id-value">
                <CopyValue value={shipment.mbl} label="BL no" />
                {shipment.hbl && (
                  <span className="key-id-date">
                    {" / "}
                    <CopyValue value={shipment.hbl} label="HBL no" />
                  </span>
                )}
              </span>
            </div>
            <div className={`key-id-cell${shipment.be_no ? "" : " key-id-missing"}`}>
              <span className="key-id-label">BE No · BE Date</span>
              <span className="key-id-value">
                {shipment.be_no ? <CopyValue value={shipment.be_no} label="BE no" /> : "Not filed yet"}
                {shipment.be_no && <span className="key-id-date"> · {fmtDate(shipment.be_dt) ?? "date missing"}</span>}
              </span>
            </div>
          </div>
          <div className="key-id key-id-flags">
            <span className="key-id-label">Clearance</span>
            <div className="flag-row">
              {statusFlags(shipment).map(([label, value]) => (
                <span className={`flag-chip ${value ? "flag-on" : "flag-pending"}`} key={label} title={value ? "Done" : "Pending"}>
                  <span className="flag-icon">{value ? "✓" : "✗"}</span> {label}
                </span>
              ))}
            </div>
          </div>
        </div>
        <span className={`status-pill status-${shipment.status}`}>{SHIPMENT_STATUS_LABELS[shipment.status]}</span>
      </header>


      {shipment.cleared_date && !shipment.is_fully_cleared && (
        <div className="auth-error detail-stuck-banner">
          Clearance exception: Cleared Date is set but {shipment.missing_for_clearance.join(", ")}{" "}
          {shipment.missing_for_clearance.length > 1 ? "aren't" : "isn't"} ticked — it stays with the ongoing
          shipments until sorted.
        </div>
      )}

      <div className="detail-tabs" role="tablist" aria-label="Shipment sections">
        <button role="tab" aria-selected={tab === "overview"} className={tab === "overview" ? "tab active" : "tab"} onClick={() => setTab("overview")}>
          Overview
        </button>
        <button role="tab" aria-selected={tab === "customs"} className={tab === "customs" ? "tab active" : "tab"} onClick={() => setTab("customs")}>
          Customs timeline
        </button>
        <button role="tab" aria-selected={tab === "documents"} className={tab === "documents" ? "tab active" : "tab"} onClick={() => setTab("documents")}>
          Documents
        </button>
        {isAdmin && (
          <button role="tab" aria-selected={tab === "proforma"} className={tab === "proforma" ? "tab active" : "tab"} onClick={() => setTab("proforma")}>
            Proforma &amp; Billing
          </button>
        )}
      </div>

      {tab === "overview" && <OverviewTab shipment={shipment} onChange={setShipment} />}
      {tab === "customs" && <CustomsTimeline shipmentId={shipment.id} />}
      {tab === "documents" && <DocumentManagerPanel shipment={shipment} onShipmentChanged={reload} />}
      {tab === "proforma" && isAdmin && <ProformaPanel shipment={shipment} onShipmentChange={setShipment} />}
    </div>
  );
}

type ToggleField = "cfs_paid_by_us" | "line_paid_by_us" | "tds_deducted" | "tds_on_cfs" | "under_examination";

function OverviewTab({ shipment: s, onChange }: { shipment: Shipment; onChange: (s: Shipment) => void }) {
  const ports = usePorts();
  const [saving, setSaving] = useState<ToggleField | null>(null);
  const saveShipment = useSaveShipment();
  async function toggle(field: ToggleField) {
    setSaving(field);
    try {
      onChange((await saveShipment(s, { [field]: !s[field] } as Partial<Shipment>)).shipment);
    } finally {
      setSaving(null);
    }
  }
  const toggles: [Exclude<ToggleField, "under_examination">, string][] = [
    ["cfs_paid_by_us", "CFS paid by us"],
    ["line_paid_by_us", "Shipping line paid by us"],
    ["tds_deducted", "TDS cut on the shipment"],
    ["tds_on_cfs", "TDS cut on CFS payment"],
  ];
  const examination =
    s.under_examination == null
      ? null
      : s.under_examination
        ? s.examination_at
          ? `Yes — ${s.examination_at}`
          : "Yes (marked by hand)"
        : "No";

  const inland = !!s.port && !SEA_PORTS.has(s.port);
  return (
    // shipment & movement (+ remarks) across the top; then customs duty + status | CFS | shipping line
    <div className="detail-grid">
      {/* shipment + container & movement: one wide block across the top, fields in a grid */}
      <section className="detail-section detail-wide">
        <h3>Shipment &amp; movement</h3>
        <div className="field-grid">
            <EditField label="Port (POD)" field="port" kind="port" s={s} onChange={onChange} display={formatPort(s.port, ports) || null} />
            <EditField label="ETA" field="eta" kind="date" s={s} onChange={onChange} display={fmtDate(s.eta)} />
            <EditField label="INW" field="inw" s={s} onChange={onChange} hint="Typed like the sheet, e.g. 19-Sep-2026" />
            <Field label="Day" value={s.days} />
            <EditField label="License" field="license" s={s} onChange={onChange} />
            <EditField label="Containers" field="container" s={s} onChange={onChange} />
            <EditField label="Gross Wt" field="gross_wt" s={s} onChange={onChange} />
            <EditField label="Container Status" field="container_status" s={s} onChange={onChange} />
            <EditField label="CFS" field="cfs" s={s} onChange={onChange} />
            <EditField label="POC" field="poc" s={s} onChange={onChange} />
            <EditField label="Delivery" field="delivery_status" s={s} onChange={onChange} />
            <EditField label="Shipping Line" field="shipping_line" s={s} onChange={onChange} />
            <Field
              label="Line (from BL)"
              value={s.line_from_bl?.line ?? null}
              hint="Worked out from the MBL's format (e.g. 9 digits = Maersk, HDMU = HMM)"
            />
        </div>
        {s.line_from_bl?.note && <p className="bl-note">{s.line_from_bl.note}</p>}
        {/* IGM details: internal fields — here only, not tracker columns (client, 2026-09-30). Filled on command
            from ICEGATE's Sea IGM (MBL + port; inland: at the gateway the ICD names) or typed in. */}
        <IcegateBar s={s} onChange={onChange} />
        <div className="field-grid">
            {/* IGM no: read from ICEGATE (client, 2026-09-30) — inland: the gateway's sea IGM here, the ICD's own
                IGM under FPOD ICD BL details; typed only as a fallback before the first ICEGATE read */}
            {inland && s.icegate?.gateway_igm ? (
              <Field
                label="Gateway IGM"
                value={[s.icegate.gateway_igm.no, s.icegate.gateway_igm.date].filter(Boolean).join(" · ") || null}
                hint={`The sea IGM at the gateway port (${s.icegate.gateway_igm.port ?? "—"}). The ICD's own IGM is under FPOD ICD BL details.`}
              />
            ) : s.icegate?.fetched_at && s.igm ? (
              <Field label="IGM" value={[s.igm, fmtDate(s.igm_date)].filter(Boolean).join(" · ")} />
            ) : (
              <>
                <EditField label="IGM No" field="igm" s={s} onChange={onChange} />
                <EditField label="IGM Date" field="igm_date" kind="date" s={s} onChange={onChange} display={fmtDate(s.igm_date)} />
              </>
            )}
            <EditField label="Line No" field="line_no" s={s} onChange={onChange} />
            <EditField label="Voyage" field="voyage" s={s} onChange={onChange} />
            <EditField label="Cont (IGM)" field="cont" s={s} onChange={onChange} />
            <EditField label="MBL Date" field="mbl_date" kind="date" s={s} onChange={onChange} display={fmtDate(s.mbl_date)} />
            <EditField label="HBL Date" field="hbl_date" kind="date" s={s} onChange={onChange} display={fmtDate(s.hbl_date)} />
            <EditField label="GW (IGM)" field="gw" s={s} onChange={onChange} />
            <EditField label="Total Pkg" field="total_pkg" s={s} onChange={onChange} />
            <EditField label="Pkg Code" field="pkg_code" s={s} onChange={onChange} />
            {s.icegate?.vessel?.vessel_code && <Field label="Vessel" value={`${s.icegate.vessel.vessel_code}${s.icegate.vessel.imo_no ? ` · IMO ${s.icegate.vessel.imo_no}` : ""}`} />}
        </div>
        {/* inland: what the ICD BL status adds on top of the IGM details (repeats left out) */}
        {inland && s.icegate?.icd && (
          <>
            <div className="amount-block-title detail-subhead">FPOD ICD BL details</div>
            <div className="field-grid">
              <Field label="ICD IGM" value={[s.icegate.icd.icd_igm_no, s.icegate.icd.icd_igm_date].filter(Boolean).join(" · ") || null} />
              <Field label="SMTP" value={[s.icegate.icd.smtp_no, s.icegate.icd.smtp_date].filter(Boolean).join(" · ") || null} hint="Rail / road permit from the gateway to the ICD" />
              <Field label="Gateway port" value={s.icegate.icd.gateway_port ? formatPort(s.icegate.icd.gateway_port, ports) || s.icegate.icd.gateway_port : null} />
              <Field label="BE location" value={s.icegate.icd.be_location ?? null} />
              <Field label="Importer (ICD)" value={s.icegate.icd.importer ?? null} />
              {Object.entries(s.icegate.icd)
                .filter(([k]) => !["icd_igm_no", "icd_igm_date", "smtp_no", "smtp_date", "gateway_port", "be_location", "importer"].includes(k))
                .map(([k, v]) => (
                  <Field key={k} label={k.replace(/_/g, " ")} value={v} />
                ))}
            </div>
            {(s.icegate.differences?.length ?? 0) > 0 && (
              <ul className="icegate-diffs" role="list">
                {s.icegate.differences!.map((d) => (
                  <li key={d.field}>
                    <strong>{d.field}</strong> differs: IGM {d.igm} · ICD {d.icd}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
        <div className="detail-wide-foot">
          <HssEditor shipment={s} onChange={onChange} />
          <div className="detail-remarks">
            <EditField label="Remark" field="remark" s={s} onChange={onChange} />
            <EditField label="Remarks" field="remarks" s={s} onChange={onChange} multiline />
          </div>
        </div>
      </section>
      <div className="detail-col">
        <section className="detail-section">
          <h3>Customs duty</h3>
          <BeAmounts shipment={s} onChange={onChange} />
          {toggles.filter(([f]) => f === "tds_deducted").map(([field, label]) => (
            <label className="toggle-row" key={field}>
              <span>{label}</span>
              <input
                type="checkbox"
                role="switch"
                checked={!!s[field]}
                disabled={saving === field}
                onChange={() => toggle(field)}
              />
            </label>
          ))}
        </section>
        <section className="detail-section">
          <h3>Status</h3>
          <EditField label="OOC Date" field="ooc_date" kind="date" s={s} onChange={onChange} display={fmtDate(s.ooc_date)} />
          <Field label="Examination" value={examination} hint="Read from the OOC copy" />
          <label className="toggle-row" title="Normally read from the OOC copy — switch it here if needed">
            <span>Under examination</span>
            <input
              type="checkbox"
              role="switch"
              checked={!!s.under_examination}
              disabled={saving === "under_examination"}
              onChange={() => toggle("under_examination")}
            />
          </label>
          <EditField label="Cleared Date" field="cleared_date" kind="date" s={s} onChange={onChange} display={fmtDate(s.cleared_date)} />
        </section>
      </div>
      <div className="detail-col">
        <section className="detail-section">
          <h3>CFS</h3>
          {toggles.filter(([f]) => f === "cfs_paid_by_us" || f === "tds_on_cfs").map(([field, label]) => (
            <label className="toggle-row" key={field}>
              <span>{label}</span>
              <input
                type="checkbox"
                role="switch"
                checked={!!s[field]}
                disabled={saving === field}
                onChange={() => toggle(field)}
              />
            </label>
          ))}
          <InvoiceGroup group="cfs" shipment={s} onChange={onChange} />
          {s.cfs_paid_by_us ? (
            <>
              <Field
                label="TDS @ 2% of basic"
                value={s.tds_on_cfs ? fmtMoney(s.cfs_tds_amount) : "Not cut"}
                hint="2% of the CFS basic value (before GST)"
              />
              <Field
                label="Payment after TDS"
                value={fmtMoney(s.cfs_payment_after_tds)}
                hint="Basic + GST − 2% of basic"
                strong
              />
              <label className="toggle-row" title="How CFS goes on the proforma">
                <span>CFS on the proforma</span>
                <select
                  value={s.cfs_billed_as}
                  onChange={async (e) =>
                    onChange((await saveShipment(s, { cfs_billed_as: e.target.value as Shipment["cfs_billed_as"] })).shipment)
                  }
                >
                  <option value="reimbursement">Reimbursement (at actuals)</option>
                  <option value="taxable">Taxable — Billed by Clarus + 18% GST</option>
                </select>
              </label>
            </>
          ) : (
            <p className="field-note">CFS not paid by us — we only pass the invoice on to the client.</p>
          )}
        </section>
      </div>
      <div className="detail-col">
        <section className="detail-section">
          <h3>Shipping line</h3>
          {toggles.filter(([f]) => f === "line_paid_by_us").map(([field, label]) => (
            <label className="toggle-row" key={field}>
              <span>{label}</span>
              <input
                type="checkbox"
                role="switch"
                checked={!!s[field]}
                disabled={saving === field}
                onChange={() => toggle(field)}
              />
            </label>
          ))}
          <InvoiceGroup group="line" shipment={s} onChange={onChange} />
          <p className="field-note">
            {s.line_paid_by_us
              ? "Shipping line paid by us — goes on the proforma as a Reimbursement."
              : "Shipping line paid by the client directly — shown on the proforma as Cost Inclusion (not in the total)."}
          </p>
          <label
            className="toggle-row"
            title="Auto follows the client's setting (e.g. Harekrishna Rubber: not included). Paid by us always goes to Reimbursement."
          >
            <span>Shipping line in cost inclusion</span>
            <select
              value={s.line_cost_inclusion ?? "auto"}
              disabled={s.line_paid_by_us}
              onChange={async (e) => {
                const v = e.target.value === "auto" ? null : (e.target.value as "include" | "exclude");
                onChange((await saveShipment(s, { line_cost_inclusion: v })).shipment);
              }}
            >
              <option value="auto">Auto (client's setting)</option>
              <option value="include">Include</option>
              <option value="exclude">Leave out</option>
            </select>
          </label>
        </section>
      </div>
      {/* inland (ICD) shipments: free days run per container from its arrival at the FPOD — at the bottom,
          its length varies with the number of containers (client, 2026-09-30) */}
      {inland && <FpodContainers key={s.icegate?.fetched_at ?? "none"} shipment={s} portLabel={formatPort(s.port, ports) || s.port!} onRefreshed={onChange} />}
    </div>
  );
}

/** A key number (BL / BE): shown in full (wraps rather than cut), click copies it. */
function CopyValue({ value, label }: { value: string | null | undefined; label: string }) {
  const [copied, setCopied] = useState(false);
  if (!value) return null;
  async function copy() {
    try {
      await navigator.clipboard.writeText(value!);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked: the text can still be selected */
    }
  }
  return (
    <button type="button" className="copy-value" onClick={copy} title={`${value} — click to copy`} aria-label={`Copy ${label} ${value}`} translate="no">
      {value}
      <span className="copy-value-tag" aria-live="polite">{copied ? "Copied" : ""}</span>
    </button>
  );
}

/** HSS = consignee "SELLER - BUYER" (detected automatically); both parties editable. */
function HssEditor({ shipment: s, onChange }: { shipment: Shipment; onChange: (s: Shipment) => void }) {
  const [editing, setEditing] = useState(false);
  const [seller, setSeller] = useState("");
  const [buyer, setBuyer] = useState("");
  const [busy, setBusy] = useState(false);
  const saveShipment = useSaveShipment();

  async function save(changes: Partial<Shipment>) {
    setBusy(true);
    try {
      onChange((await saveShipment(s, changes)).shipment);
      setEditing(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="hss-editor">
      <label className="toggle-row" title="Any consignee written 'SELLER - BUYER' is detected as HSS automatically">
        <span>HSS (high sea sale)</span>
        <input type="checkbox" role="switch" checked={s.is_hss} disabled={busy} onChange={() => save({ is_hss: !s.is_hss })} />
      </label>
      {s.is_hss && !editing && (
        <div className="field-row">
          <span className="field-label">Seller → Buyer</span>
          <span className="field-value">
            {s.hss_seller ?? "?"} → {s.hss_buyer ?? "?"}{" "}
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                setSeller(s.hss_seller ?? "");
                setBuyer(s.hss_buyer ?? "");
                setEditing(true);
              }}
            >
              Edit
            </button>
          </span>
        </div>
      )}
      {s.is_hss && editing && (
        <div className="hss-edit-form">
          <input placeholder="Seller" value={seller} onChange={(e) => setSeller(e.target.value)} aria-label="HSS seller" />
          <input placeholder="Buyer" value={buyer} onChange={(e) => setBuyer(e.target.value)} aria-label="HSS buyer" />
          <button type="button" className="btn-secondary" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => save({ hss_seller: seller.trim() || null, hss_buyer: buyer.trim() || null })}
          >
            Save
          </button>
        </div>
      )}
    </div>
  );
}

type BeField = "assessable_value" | "igst_amount" | "duty_amount";
const BE_FIELDS: [BeField, string][] = [
  ["assessable_value", "Assessable Value"],
  ["igst_amount", "IGST"],
  ["duty_amount", "Duty Amount"],
];

/** BE figures (read from the Assessed / OOC copy) — "Edit" to correct a misread. */
function BeAmounts({ shipment: s, onChange }: { shipment: Shipment; onChange: (s: Shipment) => void }) {
  const saveShipment = useSaveShipment();
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState<Record<BeField, string>>({ assessable_value: "", igst_amount: "", duty_amount: "" });
  const [error, setError] = useState<string | null>(null);

  function start() {
    setValues({
      assessable_value: s.assessable_value ?? "",
      igst_amount: s.igst_amount ?? "",
      duty_amount: s.duty_amount ?? "",
    });
    setError(null);
    setEditing(true);
  }
  async function save() {
    const payload: Partial<Record<BeField, string | null>> = {};
    for (const [f] of BE_FIELDS) {
      const v = values[f].trim().replace(/,/g, "");
      if (v !== "" && !/^\d+(\.\d{1,2})?$/.test(v)) return setError("Amounts must be numbers, e.g. 197656 or 197656.50");
      payload[f] = v === "" ? null : v;
    }
    try {
      onChange((await saveShipment(s, payload as Partial<Shipment>)).shipment);
      setEditing(false);
    } catch {
      setError("Couldn't save.");
    }
  }

  return (
    <div className="amount-block">
      <div className="amount-block-head">
        <span className="amount-block-title">Bill of Entry</span>
        {!editing && (
          <button type="button" className="link-btn" onClick={start}>
            Edit
          </button>
        )}
      </div>
      {BE_FIELDS.map(([f, label]) =>
        editing ? (
          <label className="field-row" key={f}>
            <span className="field-label">{label}</span>
            <input
              className="amount-input"
              inputMode="decimal"
              value={values[f]}
              onChange={(e) => setValues((v) => ({ ...v, [f]: e.target.value }))}
            />
          </label>
        ) : (
          <Field key={f} label={label} value={fmtMoney(s[f])} strong={f === "duty_amount"} hint="From the Assessed / OOC BE" />
        ),
      )}
      {editing && (
        <div className="amount-actions">
          {error && <span className="auth-error">{error}</span>}
          <button type="button" className="btn-secondary" onClick={() => setEditing(false)}>
            Cancel
          </button>
          <button type="button" onClick={save}>
            Save
          </button>
        </div>
      )}
    </div>
  );
}

const INVOICE_GROUPS = {
  cfs: {
    title: "CFS",
    types: ["cfs_tax_invoice", "cfs_proforma_invoice"],
    taxType: "cfs_tax_invoice",
    receiptType: "cfs_receipt",
    empty: "No CFS invoice uploaded yet — upload it in the Documents tab.",
    totals: [
      ["cfs_amount_before_tax", "CFS (before tax)"],
      ["cfs_gst_amount", "CFS GST"],
      ["cfs_amount_total", "CFS Total"],
    ],
  },
  line: {
    title: "Shipping line (destination charges)",
    types: ["shipping_line_invoice", "shipping_line_proforma"],
    taxType: "shipping_line_invoice",
    receiptType: "shipping_line_receipt",
    empty: "No shipping line destination charges invoice yet — upload it in the Documents tab.",
    totals: [
      ["line_amount_before_tax", "Cost inclusion (before tax)"],
      ["line_gst_amount", "Cost inclusion GST"],
      ["line_amount_total", "Cost inclusion Total"],
    ],
  },
} as const;

/**
 * Every invoice of a group with its own figures (each correctable).
 * CFS totals = sum of the tax invoices, or of the proformas until a tax invoice
 * arrives. Shipping line totals = sum of all its destination-charges invoices.
 */
function InvoiceGroup({
  group,
  shipment: s,
  onChange,
}: {
  group: keyof typeof INVOICE_GROUPS;
  shipment: Shipment;
  onChange: (s: Shipment) => void;
}) {
  const cfg = INVOICE_GROUPS[group];
  const [docs, setDocs] = useState<ShipmentDocument[]>([]);
  const [receipts, setReceipts] = useState<ShipmentDocument[]>([]);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [before, setBefore] = useState("");
  const [gst, setGst] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      listDocuments(s.id).then((all) => {
        setDocs(all.filter((d) => (cfg.types as readonly string[]).includes(d.document_type)));
        setReceipts(all.filter((d) => d.document_type === cfg.receiptType));
      }),
    [s.id, cfg],
  );
  useEffect(() => {
    load();
  }, [load, s.cfs_amount_total, s.line_amount_total]);

  // tax invoices count; proformas only until one arrives
  const tax = docs.filter((d) => d.document_type === cfg.taxType);
  const counted = new Set((tax.length ? tax : docs).map((d) => d.id));
  const num = (v: string) => Number(v.replace(/,/g, "")) || 0;

  function start(d: ShipmentDocument) {
    setEditingId(d.id);
    setBefore(d.amount_before_tax ?? "");
    setGst(d.gst_amount ?? "");
    setError(null);
  }
  async function save(d: ShipmentDocument) {
    const b = before.trim().replace(/,/g, "");
    const g = gst.trim().replace(/,/g, "");
    if (!/^\d+(\.\d{1,2})?$/.test(b) || !/^\d+(\.\d{1,2})?$/.test(g))
      return setError("Enter both amounts as numbers, e.g. 40000 and 7200");
    try {
      await correctInvoiceAmounts(s.id, d.id, b, g);
      setEditingId(null);
      onChange(await getShipment(s.id));
      load();
    } catch {
      setError("Couldn't save.");
    }
  }

  return (
    <div className="amount-block">
      <div className="amount-block-head">
        <span className="amount-block-title">
          {cfg.title}
          {docs.length > 0 &&
            ` · ${tax.length ? `${tax.length} tax invoice${tax.length > 1 ? "s" : ""}` : `${docs.length} proforma${docs.length > 1 ? "s" : ""}`} counted`}
        </span>
      </div>
      {docs.length === 0 && <p className="field-note">{cfg.empty}</p>}
      {/* several invoices scroll inside the box instead of stretching it */}
      <div className="invoice-list">
      {docs.map((d) => (
        <div key={d.id} className={`invoice-row${counted.has(d.id) ? "" : " invoice-not-counted"}`}>
          <div className="invoice-row-head">
            <span title={d.generated_filename}>
              {DOCUMENT_TYPE_LABELS[d.document_type]}
              {!counted.has(d.id) && <span className="field-note"> · not counted (tax invoice received)</span>}
              {d.amounts_edited && <span className="edited-tag">corrected</span>}
            </span>
            {editingId !== d.id && (
              <button type="button" className="link-btn" onClick={() => start(d)}>
                Edit
              </button>
            )}
          </div>
          {editingId === d.id ? (
            <>
              <label className="field-row">
                <span className="field-label">Basic (before tax)</span>
                <input className="amount-input" inputMode="decimal" value={before} onChange={(e) => setBefore(e.target.value)} />
              </label>
              <label className="field-row">
                <span className="field-label">GST</span>
                <input className="amount-input" inputMode="decimal" value={gst} onChange={(e) => setGst(e.target.value)} />
              </label>
              <Field label="Total (basic + GST)" value={fmtMoney(String(num(before) + num(gst)))} strong />
              <div className="amount-actions">
                {error && <span className="auth-error">{error}</span>}
                <button type="button" className="btn-secondary" onClick={() => setEditingId(null)}>
                  Cancel
                </button>
                <button type="button" onClick={() => save(d)}>
                  Save
                </button>
              </div>
            </>
          ) : (
            <div className="invoice-figures">
              <span>Basic {fmtMoney(d.amount_before_tax) ?? "—"}</span>
              <span>GST {fmtMoney(d.gst_amount) ?? "—"}</span>
              <strong>{fmtMoney(d.amount_total) ?? "—"}</strong>
            </div>
          )}
          {group === "line" && editingId !== d.id && (
            <CostInclusion
              doc={d}
              onSaved={async () => {
                onChange(await getShipment(s.id));
                load();
              }}
            />
          )}
        </div>
      ))}
      </div>
      {receipts.length > 0 && <Receipts receipts={receipts} onSaved={async () => { onChange(await getShipment(s.id)); load(); }} />}
      {docs.length > 0 &&
        cfg.totals.map(([field, label], i) => (
          <Field key={field} label={label} value={fmtMoney(s[field])} strong={i === cfg.totals.length - 1} />
        ))}
    </div>
  );
}

/** Receipts: what was actually paid (editable when misread). */
function Receipts({ receipts, onSaved }: { receipts: ShipmentDocument[]; onSaved: () => Promise<void> }) {
  const [editingId, setEditingId] = useState<number | null>(null);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const paid = receipts.reduce((sum, r) => sum + (Number(r.amount_total) || 0), 0);

  async function save(r: ShipmentDocument) {
    const v = value.replace(/,/g, "").trim();
    if (!/^\d+(\.\d{1,2})?$/.test(v)) return setError("Enter the amount as a number");
    try {
      await correctInvoiceAmounts(r.shipment_id, r.id, v, "0");
      setEditingId(null);
      await onSaved();
    } catch {
      setError("Couldn't save.");
    }
  }

  return (
    <div className="receipts">
      <div className="receipts-head">
        <span>Receipts · paid</span>
        <strong>{fmtMoney(String(paid))}</strong>
      </div>
      {receipts.map((r) => (
        <div key={r.id} className="receipt-row">
          <span title={r.generated_filename}>
            {((r.extraction?.fields ?? {}) as { receipt_no?: string }).receipt_no ?? r.original_filename}
            {r.amounts_edited && <span className="edited-tag">corrected</span>}
          </span>
          {editingId === r.id ? (
            <span className="receipt-edit">
              <input className="amount-input" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} />
              <button type="button" onClick={() => save(r)}>Save</button>
              <button type="button" className="btn-secondary" onClick={() => setEditingId(null)}>Cancel</button>
            </span>
          ) : (
            <span className="receipt-amt">
              {r.amount_total ? fmtMoney(r.amount_total) : <span className="field-empty">not read</span>}
              <button type="button" className="link-btn" onClick={() => { setEditingId(r.id); setValue(r.amount_total ?? ""); setError(null); }}>
                Edit
              </button>
            </span>
          )}
        </div>
      ))}
      {error && <span className="auth-error">{error}</span>}
    </div>
  );
}

/**
 * Which part of a shipping line invoice is the proforma's cost inclusion.
 * Rule: charges billed in INR whose head isn't freight. Lines can be ticked
 * in/out, or the figure typed by hand (e.g. when the lines couldn't be read).
 */
function CostInclusion({ doc, onSaved }: { doc: ShipmentDocument; onSaved: () => Promise<void> }) {
  const fields = (doc.extraction?.fields ?? {}) as { charges?: InvoiceCharge[]; charges_complete?: boolean; carrier?: string; invoice_no?: string };
  const charges = fields.charges_complete ? fields.charges ?? [] : [];
  const excluded = new Set(doc.cost_excluded ?? []);
  const [typing, setTyping] = useState(false);
  const [open, setOpen] = useState<{ top: number; left: number } | null>(null); // charge lines: an overlay
  const popover = useRef<HTMLDivElement>(null);
  const [before, setBefore] = useState("");
  const [gst, setGst] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(body: Parameters<typeof setCostInclusion>[2]) {
    setBusy(true);
    setError(null);
    try {
      await setCostInclusion(doc.shipment_id, doc.id, body);
      setTyping(false);
      await onSaved();
    } catch {
      setError("Couldn't save.");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (popover.current && !popover.current.contains(e.target as Node)) setOpen(null);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    const scrolled = (e: Event) => {
      if (!(e.target instanceof Node && popover.current?.contains(e.target))) setOpen(null);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    window.addEventListener("scroll", scrolled, true);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("scroll", scrolled, true);
    };
  }, [open]);

  const partial = doc.cost_before_tax != null;
  const leftOut = charges.filter((_, i) => excluded.has(i)).length;
  return (
    <div className="cost-inclusion" ref={popover}>
      <div className="cost-inclusion-head">
        <span>
          {[fields.carrier, fields.invoice_no].filter(Boolean).join(" · ")}
          {(fields.carrier || fields.invoice_no) && " — "}
          Cost inclusion:{" "}
          <strong>
            {partial
              ? `${fmtMoney(doc.cost_before_tax)} + GST ${fmtMoney(doc.cost_gst)}`
              : "whole invoice"}
          </strong>
          {doc.cost_manual && <span className="edited-tag">typed by hand</span>}
        </span>
        <span className="cost-inclusion-actions">
          {!typing && (
            <button type="button" className="link-btn" onClick={() => {
              setBefore(doc.cost_before_tax ?? doc.amount_before_tax ?? "");
              setGst(doc.cost_gst ?? doc.gst_amount ?? "");
              setTyping(true);
            }}>
              Type figure
            </button>
          )}
          {(partial || doc.cost_manual) && (
            <button type="button" className="link-btn" disabled={busy} onClick={() => send({ reset: true })}
              title="Back to the rule: INR charges that aren't freight">
              Reset
            </button>
          )}
        </span>
      </div>
      {typing && (
        <div className="cost-inclusion-typing">
          <input className="amount-input" inputMode="decimal" placeholder="Before tax" value={before} onChange={(e) => setBefore(e.target.value)} />
          <input className="amount-input" inputMode="decimal" placeholder="GST" value={gst} onChange={(e) => setGst(e.target.value)} />
          <button type="button" disabled={busy} onClick={() => {
            const b = before.replace(/,/g, "").trim(), g = (gst.replace(/,/g, "").trim() || "0");
            if (!/^\d+(\.\d{1,2})?$/.test(b) || !/^\d+(\.\d{1,2})?$/.test(g)) return setError("Enter amounts as numbers");
            send({ before_tax: b, gst: g });
          }}>
            Save
          </button>
          <button type="button" className="btn-secondary" onClick={() => setTyping(false)}>
            Cancel
          </button>
        </div>
      )}
      {charges.length > 0 && !doc.cost_manual && (
        <>
          <button
            type="button"
            className="charge-toggle"
            aria-expanded={!!open}
            onClick={(e) => {
              if (open) return setOpen(null);
              const r = e.currentTarget.getBoundingClientRect();
              setOpen({ top: r.bottom + 4, left: Math.max(8, Math.min(r.left, window.innerWidth - 460)) });
            }}
          >
            {charges.length} charge{charges.length === 1 ? "" : "s"}
            {leftOut > 0 && ` · ${leftOut} left out`} — choose {open ? "▴" : "▾"}
          </button>
          {open && (
            <div className="charge-popover" style={open} role="dialog" aria-label="Charges in the cost inclusion">
              <div className="charge-popover-head">Tick the charges that go in the cost inclusion</div>
            <ul className="charge-lines">
              {charges.map((c, i) => (
                <li key={i} className={excluded.has(i) ? "charge-out" : undefined}>
                  <label>
                    <input
                      type="checkbox"
                      checked={!excluded.has(i)}
                      disabled={busy}
                      onChange={() => {
                        const next = new Set(excluded);
                        if (next.has(i)) next.delete(i);
                        else next.add(i);
                        send({ excluded: [...next] });
                      }}
                    />
                    <span className="charge-desc">
                      {c.description}
                      {c.currency !== "INR" && <span className="charge-tag">{c.currency}</span>}
                      {c.review && <span className="charge-tag charge-review" title="Billed in INR but named like freight — left out; tick if it's a destination charge">check</span>}
                    </span>
                  </label>
                  <span className="charge-amt">{fmtMoney(String(c.amount ?? ""))}</span>
                </li>
              ))}
            </ul>
            </div>
          )}
        </>
      )}
      {charges.length === 0 && !doc.cost_manual && (
        <p className="field-note">Charge lines couldn't be read from this invoice — the whole invoice counts. Use "Type figure" to change it.</p>
      )}
      {error && <span className="auth-error">{error}</span>}
    </div>
  );
}

/** The clearance checks, shown as chips at the top of the shipment page. */
function statusFlags(s: Shipment): [string, boolean][] {
  return [
    ["Duty Paid", s.duty_paid],
    ["OOC", s.ooc],
    ["CFS Invoice", s.cfs_inv_received],
    ["Line Paid", s.line_paid],
    ["DO", s.do],
  ];
}

type EditKind = "text" | "date" | "port";

/**
 * A field on the Overview you can edit in place, like Notion (client, 2026-09-30): click it,
 * type, Enter (or click away) saves — Esc cancels. Saved like a tracker cell (someone else's
 * newer change is never overwritten silently).
 */
function EditField({
  label,
  field,
  s,
  onChange,
  kind = "text",
  display,
  hint,
  multiline,
}: {
  label: string;
  field: keyof Shipment;
  s: Shipment;
  onChange: (s: Shipment) => void;
  kind?: EditKind;
  display?: string | null;
  hint?: string;
  multiline?: boolean;
}) {
  const ports = usePorts();
  const saveShipment = useSaveShipment();
  const raw = (s[field] as string | null | undefined) ?? "";
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(raw);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const start = () => {
    setV(raw);
    setErr(null);
    setEditing(true);
  };
  const save = async (value = v) => {
    const next = value.trim() === "" ? null : value.trim();
    if ((next ?? "") === (raw ?? "")) return setEditing(false);
    setBusy(true);
    try {
      onChange((await saveShipment(s, { [field]: next } as Partial<Shipment>, label)).shipment);
      setEditing(false);
    } catch {
      setErr("Couldn't save");
    } finally {
      setBusy(false);
    }
  };
  const keys = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") setEditing(false);
    if (e.key === "Enter" && (!multiline || e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      save();
    }
  };

  const shown = display !== undefined ? display : raw || null;
  return (
    <div className={`field-row edit-field${editing ? " is-editing" : ""}`} title={hint}>
      <span className="field-label">{label}</span>
      {editing ? (
        kind === "port" ? (
          <select autoFocus value={v} disabled={busy} onChange={(e) => save(e.target.value)} onBlur={() => setEditing(false)} onKeyDown={keys}>
            <option value="">—</option>
            {ports.map((p) => (
              <option key={p.code} value={p.code}>
                {p.code} · {p.name}
              </option>
            ))}
          </select>
        ) : multiline ? (
          <textarea autoFocus rows={2} value={v} disabled={busy} onChange={(e) => setV(e.target.value)} onBlur={() => save()} onKeyDown={keys} />
        ) : (
          <input
            autoFocus
            type={kind === "date" ? "date" : "text"}
            onFocus={(e) => e.currentTarget.select()}
            value={v}
            disabled={busy}
            onChange={(e) => setV(e.target.value)}
            onBlur={() => save()}
            onKeyDown={keys}
          />
        )
      ) : (
        <button type="button" className={`field-value edit-value${shown == null ? " field-empty" : ""}`} onClick={start} title="Click to edit">
          {shown ?? "—"}
        </button>
      )}
      {err && <span className="auth-error">{err}</span>}
    </div>
  );
}

function Field({ label, value, hint, strong }: { label: string; value: string | null; hint?: string; strong?: boolean }) {
  return (
    <div className="field-row" title={hint}>
      <span className="field-label">{label}</span>
      <span className={`field-value${strong ? " field-strong" : ""}${value == null ? " field-empty" : ""}`}>
        {value ?? "—"}
      </span>
    </div>
  );
}


/** "IGM details" heading + the one button that reads ICEGATE for this shipment (sea IGM, and for inland
 *  shipments the ICD BL status too). Staff: the MBL must be the full one ICEGATE knows (HMM: HDMU…). */
function IcegateBar({ s, onChange }: { s: Shipment; onChange: (s: Shipment) => void }) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  async function run() {
    setBusy(true);
    setMsg(null);
    try {
      const { summary, shipment } = await refreshIcegate(s.id);
      onChange(shipment);
      const n = Object.keys(summary.changed).length;
      if (!summary.sea_found && !summary.icd_found) {
        // not found usually means the IGM isn't filed yet (ship not in); a wrong MBL is the other reason
        const days = s.eta ? Math.round((new Date(`${s.eta}T00:00:00`).getTime() - new Date(new Date().toDateString()).getTime()) / 86_400_000) : null;
        const check = summary.hint ? `${summary.hint[0].toUpperCase()}${summary.hint.slice(1)}.` : "Check it's the full MBL with the line's prefix (e.g. HMM: HDMU…).";
        setMsg({
          ok: false,
          text:
            days != null && days > 0
              ? `IGM not filed yet on ICEGATE (ETA ${fmtDate(s.eta)}, in ${days} day${days === 1 ? "" : "s"}). Fetch again after arrival.${summary.hint ? ` Also: ${summary.hint}.` : ""}`
              : `ICEGATE has nothing for MBL ${s.mbl} yet: either the IGM isn't filed, or the MBL isn't the one filed. ${check}`,
        });
      } else {
        const parts = [
          summary.looked_up_as ? `searched as ${summary.looked_up_as}` : null,
          summary.sea_found ? (n ? `${n} IGM field${n === 1 ? "" : "s"} filled` : "IGM details already up to date") : "sea IGM not found",
          summary.inland ? (summary.icd_found ? "ICD BL read" : "not at the ICD yet") : null,
          summary.differences?.length ? `${summary.differences.length} difference${summary.differences.length === 1 ? "" : "s"} to check` : null,
          ...summary.notes,
        ].filter(Boolean);
        setMsg({ ok: !summary.differences?.length && !summary.notes.length, text: parts.join(" · ") });
      }
    } catch (e) {
      const detail = axios.isAxiosError(e) ? e.response?.data?.detail : null;
      setMsg({ ok: false, text: typeof detail === "string" ? detail : "Couldn't reach ICEGATE — try again." });
    } finally {
      setBusy(false);
    }
  }
  const at = s.icegate?.fetched_at
    ? new Date(s.icegate.fetched_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })
    : null;
  return (
    <>
      <div className="icegate-bar">
        <span className="amount-block-title">IGM details</span>
        <span className="field-note">{at ? `read from ICEGATE ${at}` : "not read from ICEGATE yet"}</span>
        <button type="button" className="btn-secondary" onClick={run} disabled={busy || !s.mbl}>
          {busy ? "Reading ICEGATE…" : "Fetch from ICEGATE"}
        </button>
      </div>
      {msg && (
        <div role="status" className={msg.ok ? "grid-toast grid-toast-ok" : "grid-toast grid-toast-error"}>
          {msg.text}
        </div>
      )}
    </>
  );
}
