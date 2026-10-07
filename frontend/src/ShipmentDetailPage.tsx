import { tabKeys } from "./tabKeys";
import { copyText } from "./clipboard";
import CustomsTimeline from "./CustomsTimeline";
import { nextStep } from "./clearanceFlow";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import axios from "axios";
import { useAuth } from "./AuthContext";
import { useParams, useSearchParams, useNavigate, Link } from "react-router-dom";
import { correctInvoiceAmounts, getPublicSettings, getShipment, listDocuments, refreshIcegate, setCostInclusion } from "./api";
import { useSaveShipment } from "./useSaveShipment";
import { DOCUMENT_TYPE_LABELS, SHIPMENT_STATUS_LABELS, type InvoiceCharge, type Shipment, type ShipmentDocument } from "./types";
import DocumentManagerPanel from "./DocumentManagerPanel";
import ProformaPanel from "./ProformaPanel";
import FpodContainers from "./FpodContainers";
import ShipmentHistory from "./ShipmentHistory";
import { formatPort, usePorts } from "./ports";

type Tab = "overview" | "customs" | "documents" | "history" | "proforma";

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

/** Documents per shipment, last loaded — shared by the Overview's CFS / shipping line blocks. */
const docsCache = new Map<number, ShipmentDocument[]>();

const TABS: Tab[] = ["overview", "customs", "documents", "history", "proforma"];

export default function ShipmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  // the open tab lives in the URL (?tab=proforma): links, Back and refresh land on it
  const [params, setParams] = useSearchParams();
  const fromUrl = params.get("tab") as Tab | null;
  const tab: Tab = fromUrl && TABS.includes(fromUrl) ? fromUrl : "overview";
  // switching tabs replaces the entry, so Back leaves the shipment instead of stepping through its tabs
  const setTab = (t: Tab) => setParams(t === "overview" ? {} : { tab: t }, { replace: true });
  return <ShipmentDetail shipmentId={Number(id)} tab={tab} onTab={setTab} />;
}

/**
 * Back goes where you came from — the Invoicing page, Dashboard, a search… — not always the
 * tracker (client, 2026-09-30). Opened fresh (new tab, bookmark) there's nowhere to go back to,
 * so it falls back to the tracker. Still a real link, for ⌘/middle-click.
 */
function BackLink() {
  const navigate = useNavigate();
  const canGoBack = (window.history.state?.idx ?? 0) > 0;
  return (
    <Link
      to="/shipments"
      className="back-link"
      onClick={(e) => {
        if (!canGoBack || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
        e.preventDefault();
        navigate(-1);
      }}
    >
      {canGoBack ? "← Back" : "← Shipment Tracker"}
    </Link>
  );
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
  full = false,
  onFull,
}: {
  shipmentId: number;
  onClose?: () => void;
  tab?: Tab;
  onTab?: (t: Tab) => void;
  full?: boolean;
  onFull?: (full: boolean) => void;
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
    // switching jobs in the peek: the old job stays (dimmed) until the new one has arrived — no blank flash
    let live = true;
    setLoading(true);
    // documents come with the first load, so the Overview draws complete (no late push-down)
    const docs = listDocuments(shipmentId).then((all) => void docsCache.set(shipmentId, all)).catch(() => {});
    const one = getShipment(shipmentId).then(
      (s) => live && setShipment(s),
      () => live && setShipment(null),
    );
    Promise.all([one, docs]).finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [shipmentId]);

  // tabs: one underline that slides to the active tab (transform only), so the labels never shift
  const tabsRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const list = tabsRef.current;
    const on = list?.querySelector<HTMLElement>(".tab.active");
    if (!list || !on) return;
    list.style.setProperty("--ind-x", `${on.offsetLeft}px`);
    list.style.setProperty("--ind-w", String(on.offsetWidth));
  });

  // the tab title names the shipment (full page only; the peek panel leaves the tracker's title alone)
  const job = shipment?.job;
  useEffect(() => {
    if (!peek && job) document.title = `Job ${job} · Clarus ERP`;
  }, [peek, job]);

  if (!shipment && loading) return <DetailSkeleton peek={peek && !full} />;
  if (!shipment)
    return (
      <div className="tracker-empty">
        <p>This shipment doesn’t exist or was deleted.</p>
        <Link to="/shipments">Back to the Shipment Tracker</Link>
      </div>
    );

  return (
    <div
      key={shipment.id}
      className={`detail-page${peek && !full ? " detail-peek" : ""}${loading ? " is-stale" : ""}`}
      aria-busy={loading || undefined}
    >
      {peek ? (
        <div className="peek-bar">
          {onFull ? (
            <button type="button" className="peek-size btn-secondary" onClick={() => onFull(!full)} aria-pressed={full}>
              {full ? "⇥ Half view" : "⇤ Full width"}
            </button>
          ) : (
            <Link to={`/shipments/${shipment.id}`} className="back-link">
              Open full page ↗
            </Link>
          )}
          <span className="peek-bar-right">
            <Link to={`/shipments/${shipment.id}`} className="peek-newtab" target="_blank" rel="noreferrer" title="Open in a new tab">
              New tab ↗
            </Link>
            <button type="button" className="peek-close" onClick={onClose} aria-label="Close" title="Close (Esc)">
              ✕
            </button>
          </span>
        </div>
      ) : (
        <BackLink />
      )}

      <header className="detail-header">
        <div className="detail-title">
          <span className="detail-job">
            {shipment.job ? `Job ${shipment.job}` : "No job number yet"}
            <span className={`status-pill status-${shipment.status}`}>{SHIPMENT_STATUS_LABELS[shipment.status]}</span>
          </span>
          <span className="detail-client">
            {shipment.client ?? "—"} · {shipment.consignee ?? "—"}
          </span>
        </div>
      </header>

      {/* tier 1: the keys, what's next, where the clearance stands, and the three payments — at a glance */}
      <div className="tier1">
        <KeyStrip s={shipment} />
        <div className="tier1-flow">
          <NextStepBar shipment={shipment} />
          <ClearanceStepper s={shipment} onChange={setShipment} />
        </div>
        <PaymentTiles s={shipment} />
      </div>

      {shipment.cleared_date && !shipment.is_fully_cleared && (
        <div className="auth-error detail-stuck-banner">
          Clearance exception: Cleared Date is set but {shipment.missing_for_clearance.join(", ")}{" "}
          {shipment.missing_for_clearance.length > 1 ? "aren't" : "isn't"} ticked — it stays with the ongoing
          shipments until sorted.
        </div>
      )}

      <div className="detail-tabs" role="tablist" onKeyDown={tabKeys} aria-label="Shipment sections" ref={tabsRef}>
        <button role="tab" aria-selected={tab === "overview"} className={tab === "overview" ? "tab active" : "tab"} onClick={() => setTab("overview")}>
          Overview
        </button>
        <button role="tab" aria-selected={tab === "customs"} className={tab === "customs" ? "tab active" : "tab"} onClick={() => setTab("customs")}>
          Customs timeline
        </button>
        <button role="tab" aria-selected={tab === "documents"} className={tab === "documents" ? "tab active" : "tab"} onClick={() => setTab("documents")}>
          Documents
        </button>
        <button role="tab" aria-selected={tab === "history"} className={tab === "history" ? "tab active" : "tab"} onClick={() => setTab("history")}>
          History
        </button>
        {isAdmin && (
          <button role="tab" aria-selected={tab === "proforma"} className={tab === "proforma" ? "tab active" : "tab"} onClick={() => setTab("proforma")}>
            Proforma &amp; Billing
          </button>
        )}
      </div>

      <div className="tab-body" key={tab}>
      {tab === "overview" && <OverviewTab shipment={shipment} onChange={setShipment} />}
      {tab === "customs" && <CustomsTimeline shipmentId={shipment.id} shipment={shipment} />}
      {tab === "documents" && <DocumentManagerPanel shipment={shipment} onShipmentChanged={reload} />}
      {tab === "history" && <ShipmentHistory shipment={shipment} onChange={setShipment} />}
      {tab === "proforma" && isAdmin && <ProformaPanel shipment={shipment} onShipmentChange={setShipment} />}
      </div>
    </div>
  );
}

/** First open: grey blocks in the page's own shape (key strip, next step, stepper, cards) instead of "Loading…". */
function DetailSkeleton({ peek }: { peek: boolean }) {
  return (
    <div className={`detail-page detail-skeleton${peek ? " detail-peek" : ""}`} aria-busy="true" aria-label="Loading the shipment">
      <div className="sk sk-title" />
      <div className="sk sk-strip" />
      <div className="sk sk-next" />
      <div className="sk sk-stepper" />
      <div className="sk sk-tabs" />
      <div className="sk sk-card" />
      <div className="sk sk-card" />
    </div>
  );
}

type ToggleField = "cfs_paid_by_us" | "line_paid_by_us" | "tds_on_cfs";

/** The Overview goes two-column once its own box is this wide (full page / full-width peek), not by window size. */
const OVERVIEW_WIDE = 1000;
function useWideBox<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [wide, setWide] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWide(e.contentRect.width >= OVERVIEW_WIDE));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, wide] as const;
}

function OverviewTab({ shipment: s, onChange }: { shipment: Shipment; onChange: (s: Shipment) => void }) {
  const ports = usePorts();
  const [igmOpen, setIgmOpen] = useState(false);
  const [box, wide] = useWideBox<HTMLDivElement>();
  const inland = !!s.port && !SEA_PORTS.has(s.port);
  return (
    // desktop: movement | duty, CFS, line, notes; then containers and billing settings full width. Narrow: one column.
    <div className={`overview${wide ? " is-wide" : ""}`} ref={box}>
      <div className="ov-col">
        <section className="detail-section">
          <h3>Shipment &amp; movement</h3>
          <div className="field-grid">
            <EditField label="Port (POD)" field="port" kind="port" s={s} onChange={onChange} display={formatPort(s.port, ports) || null} />
            <EditField label="ETA" field="eta" kind="date" s={s} onChange={onChange} display={fmtDate(s.eta)} />
            <EditField label="INW" field="inw" s={s} onChange={onChange} hint="Typed like the sheet, e.g. 19-Sep-2026" />
            <Field label="Day" value={s.days} />
            <EditField label="Containers" field="container" s={s} onChange={onChange} />
            <EditField label="Gross Wt" field="gross_wt" s={s} onChange={onChange} />
            <EditField label="Cont. status" field="container_status" s={s} onChange={onChange} />
            <EditField label="CFS" field="cfs" s={s} onChange={onChange} />
            <EditField label="POC" field="poc" s={s} onChange={onChange} />
            <EditField label="Delivery" field="delivery_status" s={s} onChange={onChange} />
            {/* one line field: what's typed, else what the MBL's format says (e.g. 9 digits = Maersk, HDMU = HMM) */}
            <EditField
              label="Shipping line"
              field="shipping_line"
              s={s}
              onChange={onChange}
              display={s.shipping_line || (s.line_from_bl?.line ? `${s.line_from_bl.line} (from BL)` : null)}
              hint="Typed, or worked out from the MBL's format"
            />
          </div>
          {s.line_from_bl?.note && <p className="bl-note">{s.line_from_bl.note}</p>}
          {/* IGM details: internal fields — here only, not tracker columns (client, 2026-09-30). Filled on command
              from ICEGATE's Sea IGM (MBL + port; inland: at the gateway the ICD names) or typed in. Folded by default. */}
          <IcegateBar s={s} onChange={onChange} open={igmOpen} onToggle={() => setIgmOpen((o) => !o)} />
          {igmOpen && (
            <div id="igm-details" className="fold-body">
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
                    {Object.entries(s.icegate.icd)
                      .filter(([k]) => !["icd_igm_no", "icd_igm_date", "smtp_no", "smtp_date", "gateway_port", "be_location", "importer"].includes(k))
                      .map(([k, v]) => (
                        <Field key={k} label={k.replace(/_/g, " ")} value={v} />
                      ))}
                  </div>
                </>
              )}
            </div>
          )}
          {/* a difference between the IGM and the ICD is worth seeing even with the details folded */}
          {inland && (s.icegate?.differences?.length ?? 0) > 0 && (
            <ul className="icegate-diffs" role="list">
              {s.icegate!.differences!.map((d) => (
                <li key={d.field}>
                  <strong>{d.field}</strong> differs: IGM {d.igm} · ICD {d.icd}
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      <div className="ov-col">
        <section className="detail-section">
          <h3>Customs duty</h3>
          <EditField label="License" field="license" s={s} onChange={onChange} />
          {inland && s.icegate?.icd?.be_location && <Field label="BE location" value={s.icegate.icd.be_location} hint="From the ICD BL status" />}
          {inland && s.icegate?.icd?.importer && <Field label="Importer (ICD)" value={s.icegate.icd.importer} hint="From the ICD BL status" />}
          <BeAmounts shipment={s} onChange={onChange} />
        </section>
        <section className="detail-section">
          <h3>CFS</h3>
          <InvoiceGroup group="cfs" shipment={s} onChange={onChange} />
          {s.cfs_paid_by_us && (
            <>
              <Field
                label={`TDS @ ${tdsPct(s)}%`}
                value={s.tds_on_cfs ? fmtMoney(s.cfs_tds_amount) : "Not cut"}
                hint={`${tdsPct(s)}% of the CFS basic value (before GST)`}
                amount
              />
              <Field label="After TDS" value={fmtMoney(s.cfs_payment_after_tds)} hint={`Basic + GST − ${tdsPct(s)}% of basic`} strong amount />
            </>
          )}
        </section>
        <section className="detail-section">
          <h3>Shipping line · destination charges</h3>
          <InvoiceGroup group="line" shipment={s} onChange={onChange} />
        </section>
        <section className="detail-section">
          <h3>Notes</h3>
          <EditField label="Short remark" field="remark" s={s} onChange={onChange} />
          <EditField label="Notes" field="remarks" s={s} onChange={onChange} multiline />
        </section>
      </div>
      {/* every shipment's containers (from the sea IGM) with their free days — inland: from each container's
          arrival at the FPOD; sea port: from the INW (client, 2026-09-30) */}
      {s.port && (
        <FpodContainers key={s.icegate?.fetched_at ?? "none"} shipment={s} inland={inland} portLabel={formatPort(s.port, ports) || s.port} onRefreshed={onChange} wide={wide} />
      )}
      <BillingSettings s={s} onChange={onChange} />
    </div>
  );
}

/**
 * How this job is billed, as one quiet row of chips (+ the two proforma choices). One plain line under it
 * says what the settings add up to — these move money, so it isn't left to tooltips alone.
 */
function BillingSettings({ s, onChange }: { s: Shipment; onChange: (s: Shipment) => void }) {
  const saveShipment = useSaveShipment();
  const [saving, setSaving] = useState<ToggleField | null>(null);
  async function toggle(field: ToggleField) {
    setSaving(field);
    try {
      onChange((await saveShipment(s, { [field]: !s[field] } as Partial<Shipment>)).shipment);
    } finally {
      setSaving(null);
    }
  }
  const chip = (field: ToggleField, label: string, title: string) => (
    <button
      type="button"
      className={`chip-toggle${s[field] ? " is-on" : ""}`}
      aria-pressed={!!s[field]}
      disabled={saving === field}
      onClick={() => toggle(field)}
      title={title}
    >
      {label}
    </button>
  );
  const summary = [
    s.is_hss ? "High sea sale" : null,
    s.cfs_paid_by_us
      ? `CFS paid by us${s.tds_on_cfs ? `, ${tdsPct(s)}% TDS cut` : ""}, billed ${s.cfs_billed_as === "taxable" ? "as taxable + 18% GST" : "at actuals"}`
      : "CFS paid by the client — we pass the invoice on",
    s.line_paid_by_us
      ? "line paid by us (reimbursement)"
      : `line paid by the client (${s.line_cost_inclusion === "exclude" ? "left off the proforma" : s.line_cost_inclusion === "include" ? "shown as cost inclusion" : "cost inclusion per client setting"})`,
  ].filter(Boolean);
  return (
    <section className="detail-section billing-settings" aria-label="Billing settings">
      <div className="billing-row">
        <h3>Billing settings</h3>
        <HssEditor shipment={s} onChange={onChange} />
        {chip("cfs_paid_by_us", "CFS paid by us", "We pay the CFS and bill it on")}
        {s.cfs_paid_by_us && chip("tds_on_cfs", "TDS on CFS", "TDS is cut when we pay the CFS")}
        {s.cfs_paid_by_us && s.tds_on_cfs && <TdsRate shipment={s} onChange={onChange} />}
        {chip("line_paid_by_us", "Line paid by us", "We pay the shipping line and bill it as a reimbursement")}
        {s.cfs_paid_by_us && (
          <select
            className="chip-select"
            aria-label="CFS on the proforma"
            title="How CFS goes on the proforma"
            value={s.cfs_billed_as}
            onChange={async (e) => onChange((await saveShipment(s, { cfs_billed_as: e.target.value as Shipment["cfs_billed_as"] })).shipment)}
          >
            <option value="reimbursement">CFS: at actuals</option>
            <option value="taxable">CFS: taxable + 18% GST</option>
          </select>
        )}
        {!s.line_paid_by_us && (
          <select
            className="chip-select"
            aria-label="Shipping line in cost inclusion"
            title="Auto follows the client's setting (e.g. Harekrishna Rubber: not included)"
            value={s.line_cost_inclusion ?? "auto"}
            onChange={async (e) => {
              const v = e.target.value === "auto" ? null : (e.target.value as "include" | "exclude");
              onChange((await saveShipment(s, { line_cost_inclusion: v })).shipment);
            }}
          >
            <option value="auto">Line cost: client's setting</option>
            <option value="include">Line cost: include</option>
            <option value="exclude">Line cost: leave out</option>
          </select>
        )}
      </div>
      <p className="billing-summary">{summary.join(" · ")}.</p>
    </section>
  );
}

/** A key number (BL / BE): shown in full (wraps rather than cut), click copies it. */
const tdsPct = (s: Shipment) => (s.cfs_tds_rate == null ? "2" : String(Number(s.cfs_tds_rate)));

/**
 * TDS rate on the CFS payment: fixed at 2% unless the admin allows other rates in Settings;
 * then 1% / 2% / 10% or a typed rate (client, 2026-09-30).
 */
function TdsRate({ shipment: s, onChange }: { shipment: Shipment; onChange: (s: Shipment) => void }) {
  const [editable, setEditable] = useState(false);
  const [custom, setCustom] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const saveShipment = useSaveShipment();
  useEffect(() => {
    getPublicSettings()
      .then((p) => setEditable(p.tds_rate_editable))
      .catch(() => setEditable(false));
  }, []);
  const pct = tdsPct(s);
  const preset = ["1", "2", "10"].includes(pct);
  if (!editable && pct === "2") return null; // the usual: shown in the TDS line below
  async function save(v: string) {
    const n = Number(v.trim());
    if (!v.trim() || !Number.isFinite(n) || n <= 0 || n > 20) {
      setErr("Enter a rate above 0% and up to 20%.");
      return;
    }
    setErr(null);
    setBusy(true);
    try {
      onChange((await saveShipment(s, { cfs_tds_rate: n === 2 ? null : String(n) })).shipment);
      setCustom(null);
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      setErr(typeof d === "string" ? d : "Couldn't save the rate.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <label className="toggle-row">
        <span>TDS rate</span>
        {editable ? (
          <span style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
            <select
              value={custom !== null || !preset ? "custom" : pct}
              disabled={busy}
              onChange={(e) => (e.target.value === "custom" ? setCustom(preset ? "" : pct) : save(e.target.value))}
            >
              <option value="1">1%</option>
              <option value="2">2% (CFS)</option>
              <option value="10">10%</option>
              <option value="custom">Other…</option>
            </select>
            {(custom !== null || !preset) && (
              <input
                type="text"
                inputMode="decimal"
                aria-label="TDS rate in percent"
                placeholder="e.g. 5…"
                style={{ width: 70 }}
                value={custom ?? pct}
                aria-invalid={!!err}
                onChange={(e) => setCustom(e.target.value)}
                onBlur={(e) => custom !== null && e.target.value.trim() && e.target.value.trim() !== pct && save(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && save((e.target as HTMLInputElement).value)}
              />
            )}
          </span>
        ) : (
          <span className="field-note">{pct}% (other rates are off in Settings)</span>
        )}
      </label>
      {err && <div className="auth-error" role="alert">{err}</div>}
    </>
  );
}

function CopyValue({ value, label }: { value: string | null | undefined; label: string }) {
  const [copied, setCopied] = useState<"Copied" | "Couldn't copy" | "">("");
  if (!value) return null;
  async function copy() {
    setCopied((await copyText(value!)) ? "Copied" : "Couldn't copy");
    window.setTimeout(() => setCopied(""), 1500);
  }
  return (
    <button type="button" className="copy-value" onClick={copy} title={`${value} — click to copy`} aria-label={`Copy ${label} ${value}`} translate="no">
      {value}
      <span className="copy-value-tag" aria-live="polite">{copied}</span>
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
      <button
        type="button"
        className={`chip-toggle${s.is_hss ? " is-on" : ""}`}
        aria-pressed={s.is_hss}
        disabled={busy}
        onClick={() => save({ is_hss: !s.is_hss })}
        title="High sea sale. Any consignee written 'SELLER - BUYER' is detected as HSS automatically"
      >
        HSS
      </button>
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
  // after OOC the duty that counts is what was paid, interest included; before it, only once a challan shows interest
  const fd = s.final_duty;
  const final = fd && fd.source !== "be" && (s.ooc || Number(fd.interest) > 0) ? fd : null;
  const finalHint = final?.source === "ooc" ? "From the OOC copy's total (the amount paid)" : "BE duty + interest from the duty challan";

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
          <Field key={f} label={label} value={fmtMoney(s[f])} strong={f === "duty_amount" && !final} hint="From the Assessed / OOC BE" />
        ),
      )}
      {!editing && final && (
        <>
          <Field label="Interest" value={fmtMoney(final.interest)} hint={finalHint} />
          <Field label={s.ooc ? "Final Duty (incl. interest)" : "Duty due (incl. interest)"} value={fmtMoney(final.total)} strong hint={finalHint} />
        </>
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
  // start from the documents already loaded for this shipment: the block draws complete instead of
  // appearing empty and then pushing the page down (the "twitch", client 2026-09-30)
  const cached = docsCache.get(s.id);
  const [docs, setDocs] = useState<ShipmentDocument[]>(() => (cached ?? []).filter((d) => (cfg.types as readonly string[]).includes(d.document_type)));
  const [receipts, setReceipts] = useState<ShipmentDocument[]>(() => (cached ?? []).filter((d) => d.document_type === cfg.receiptType));
  const [loaded, setLoaded] = useState(!!cached);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [before, setBefore] = useState("");
  const [gst, setGst] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      listDocuments(s.id).then((all) => {
        docsCache.set(s.id, all);
        setDocs(all.filter((d) => (cfg.types as readonly string[]).includes(d.document_type)));
        setReceipts(all.filter((d) => d.document_type === cfg.receiptType));
        setLoaded(true);
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
      {/* the card's heading already names the group; this line only says what is counted */}
      {docs.length > 0 && (
        <div className="amount-block-head">
          <span className="field-note">
            {tax.length ? `${tax.length} tax invoice${tax.length > 1 ? "s" : ""}` : `${docs.length} proforma${docs.length > 1 ? "s" : ""}`} counted
          </span>
        </div>
      )}
      {docs.length === 0 && <p className="field-note">{loaded ? cfg.empty : "Loading invoices…"}</p>}
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

/** What the clearance is waiting on now: one line under the header (see clearanceFlow.ts). */
function NextStepBar({ shipment }: { shipment: Shipment }) {
  const n = nextStep(shipment);
  if (!n) return null;
  return (
    <div className={`next-step${n.blocked ? " is-blocked" : ""}`} role="status">
      <span className="next-step-label">{n.blocked ? "Blocked" : "Next"}</span>
      <strong className="next-step-title">{n.title}</strong>
      <span className="next-step-detail">
        {n.detail}
        {n.also.length > 0 && ` Also open: ${n.also.join(", ")}.`}
      </span>
    </div>
  );
}

/** "2026-10-04" (or an ICEGATE timestamp starting with one) -> "04 Oct"; anything else as it came. */
function shortDate(v: string | null | undefined): string | null {
  if (!v) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(v);
  return m ? `${m[3]} ${MONTHS[Number(m[2]) - 1]}` : v.split(" ")[0];
}

/** One card, six cells: the keys everything is filed and searched by, and where the shipment is. */
function KeyStrip({ s }: { s: Shipment }) {
  const ports = usePorts();
  const portName = s.port ? ports.find((p) => p.code === s.port)?.name ?? s.port : null;
  const age = /^\d+$/.test(s.days) ? `Day ${s.days}` : s.days || "—";
  const cells: { label: string; value: React.ReactNode; sub?: React.ReactNode; empty?: boolean; wide?: boolean }[] = [
    {
      label: s.hbl ? "BL (MBL / HBL)" : "BL",
      value: <CopyValue value={s.mbl} label="BL no" />,
      sub: s.hbl ? <CopyValue value={s.hbl} label="HBL no" /> : s.shipping_line || s.line_from_bl?.line || null,
      wide: true,
    },
    {
      label: "BE",
      value: s.be_no ? <CopyValue value={s.be_no} label="BE no" /> : "Not filed yet",
      sub: s.be_no ? fmtDate(s.be_dt) ?? "date not entered" : null,
      empty: !s.be_no,
    },
    { label: "Port", value: portName ?? "—", sub: portName && portName !== s.port ? s.port : null, empty: !s.port },
    { label: "Containers", value: s.container || "—", sub: s.container_status, empty: !s.container },
    {
      label: "ETA → Inward",
      value: (
        <>
          {shortDate(s.eta) ?? "—"} <span className="key-arrow">→</span> {s.inw ? shortDate(s.inw) : "—"}
        </>
      ),
      sub: s.eta_is_deadline ? "ETA is a deadline" : null,
    },
    { label: "Age", value: age, sub: /^\d+$/.test(s.days) ? "since inward" : null, empty: !/^\d+$/.test(s.days) },
  ];
  return (
    <div className="key-strip" role="group" aria-label="Shipment keys">
      {cells.map((c) => (
        <div className={`key-cell${c.wide ? " key-cell-wide" : ""}`} key={c.label}>
          <span className="key-label">{c.label}</span>
          <span className={`key-value${c.empty ? " is-empty" : ""}`}>{c.value}</span>
          {c.sub && <span className="key-sub">{c.sub}</span>}
        </div>
      ))}
    </div>
  );
}

/**
 * IGM → BE filed → Assessed → Duty → OOC → CFS → Line → DO. Done = ✓ + date, the first open step = "Now",
 * the rest hollow. Red only for a real exception (an unanswered customs query). The OOC / Cleared dates and
 * the examination switch sit under it (they used to be the Status card).
 */
function ClearanceStepper({ s, onChange }: { s: Shipment; onChange: (s: Shipment) => void }) {
  const saveShipment = useSaveShipment();
  const [busy, setBusy] = useState(false);
  const q = s.icegate?.be_status;
  const openQuery = !!q?.query && !q?.query_reply;
  const steps: { label: string; done: boolean; date?: string | null; note?: string; alert?: boolean }[] = [
    { label: "IGM", done: !!s.igm, date: shortDate(s.igm_date) },
    { label: "BE filed", done: !!s.be_no, date: shortDate(s.be_dt) },
    { label: "Assessed", done: s.duty_amount != null || !!q?.assessed_at, date: shortDate(q?.assessed_at), alert: openQuery, note: openQuery ? "Query" : undefined },
    { label: "Duty", done: s.duty_paid, date: shortDate(q?.paid_at) },
    { label: "OOC", done: s.ooc, date: shortDate(s.ooc_date), note: !s.ooc && s.under_examination ? "Exam" : undefined },
    { label: "CFS", done: s.cfs_inv_received },
    { label: "Line", done: s.line_paid },
    { label: "DO", done: s.do },
  ];
  const current = steps.findIndex((x) => !x.done);
  async function toggleExam() {
    setBusy(true);
    try {
      onChange((await saveShipment(s, { under_examination: !s.under_examination })).shipment);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="stepper-card" aria-label="Clearance">
      <ol className="stepper">
        {steps.map((x, i) => {
          const state = x.alert ? "alert" : x.done ? "done" : i === current ? "now" : "todo";
          return (
            <li key={x.label} className={`step step-${state}`} aria-current={i === current ? "step" : undefined}>
              <span className="step-dot" aria-hidden="true">{state === "done" ? "✓" : state === "alert" ? "!" : ""}</span>
              <span className="step-label">{x.label}</span>
              <span className="step-sub">
                {x.note ?? (x.done ? x.date ?? "Done" : i === current ? "Now" : "Pending")}
              </span>
            </li>
          );
        })}
      </ol>
      <div className="stepper-foot">
        <EditField label="OOC date" field="ooc_date" kind="date" s={s} onChange={onChange} display={fmtDate(s.ooc_date)} />
        <EditField label="Cleared date" field="cleared_date" kind="date" s={s} onChange={onChange} display={fmtDate(s.cleared_date)} />
        <button
          type="button"
          className={`chip-toggle${s.under_examination ? " is-on" : ""}`}
          aria-pressed={!!s.under_examination}
          disabled={busy}
          onClick={toggleExam}
          title={s.examination_at ? `Marked for examination: ${s.examination_at}` : "Normally read from the OOC copy — switch it here if needed"}
        >
          Under examination
        </button>
      </div>
    </section>
  );
}

/** Duty / CFS / Line in words: what's known, what's paid, what's still not attached. */
function PaymentTiles({ s }: { s: Shipment }) {
  const fd = s.final_duty;
  const dutyAmt = fd && fd.source !== "be" && (s.ooc || Number(fd.interest) > 0) ? fd.total : s.duty_amount;
  const tiles: { label: string; done: boolean; value: string; sub: string }[] = [
    {
      label: "Duty",
      done: s.duty_paid,
      value: dutyAmt == null ? "Not assessed" : fmtMoney(dutyAmt)!,
      sub: s.duty_paid ? "Paid" : dutyAmt == null ? "Waiting for the assessed BE" : "Not paid yet",
    },
    {
      label: "CFS",
      done: s.cfs_inv_received,
      value: s.cfs_amount_total ? fmtMoney(s.cfs_amount_total)! : "Not attached",
      sub: `${s.cfs_inv_received ? "Invoice received" : "Invoice pending"} · ${s.cfs_paid_by_us ? "paid by us" : "paid by client"}`,
    },
    {
      label: "Line",
      done: s.line_paid,
      value: s.line_amount_total ? fmtMoney(s.line_amount_total)! : "Not attached",
      sub: `${s.line_paid ? "Paid" : "Not paid yet"} · ${s.line_paid_by_us ? "by us" : "by client"}`,
    },
  ];
  return (
    <div className="pay-tiles">
      {tiles.map((t) => (
        <div className="pay-tile" key={t.label}>
          <span className="pay-label">
            <span className={`dot ${t.done ? "dot-ok" : "dot-todo"}`} aria-hidden="true" />
            {t.label}
          </span>
          <span className={`pay-value${t.value.startsWith("₹") ? "" : " is-words"}`}>{t.value}</span>
          <span className="pay-sub">{t.sub}</span>
        </div>
      ))}
    </div>
  );
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

function Field({ label, value, hint, strong, amount }: { label: string; value: string | null; hint?: string; strong?: boolean; amount?: boolean }) {
  return (
    <div className={`field-row${amount ? " field-amount" : ""}${strong ? " field-total" : ""}`} title={hint}>
      <span className="field-label">{label}</span>
      <span className={`field-value${strong ? " field-strong" : ""}${value == null ? " field-empty" : ""}`}>
        {value ?? "—"}
      </span>
    </div>
  );
}


/** "IGM details" heading + the one button that reads ICEGATE for this shipment (sea IGM, and for inland
 *  shipments the ICD BL status too). Staff: the MBL must be the full one ICEGATE knows (HMM: HDMU…). */
function IcegateBar({ s, onChange, open, onToggle }: { s: Shipment; onChange: (s: Shipment) => void; open: boolean; onToggle: () => void }) {
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
        <button type="button" className="fold-toggle" aria-expanded={open} aria-controls="igm-details" onClick={onToggle}>
          <span className="fold-caret" aria-hidden="true">▸</span>
          IGM &amp; ICD details
          <span className="fold-meta">
            {s.icegate?.final ? `· final, read ${at ?? "after clearance"}` : at ? `· read from ICEGATE ${at}` : s.igm ? "· not read from ICEGATE yet" : "· not read yet"}
          </span>
        </button>
        {!s.icegate?.final && (
          <button type="button" className="btn-secondary btn-sm" onClick={run} disabled={busy || !s.mbl}>
            {busy ? "Reading ICEGATE…" : "Fetch"}
          </button>
        )}
      </div>
      {msg && (
        <div role="status" className={msg.ok ? "grid-toast grid-toast-ok" : "grid-toast grid-toast-error"}>
          {msg.text}
        </div>
      )}
    </>
  );
}
