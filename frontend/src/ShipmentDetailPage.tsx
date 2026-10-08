import { fmtDay, fmtDayShort, fmtWhen } from "./dates";
import LoadError from "./LoadError";
import { tabKeys } from "./tabKeys";
import { copyText } from "./clipboard";
import CustomsTimeline from "./CustomsTimeline";
import { nextStep } from "./clearanceFlow";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import axios from "axios";
import { useAuth, useReadOnly } from "./AuthContext";
import { kgLooking } from "./weight";
import { docsCache, rememberShipment, shipmentCache } from "./detailCache";
import { useParams, useSearchParams, useNavigate, Link } from "react-router-dom";
import { correctInvoiceAmounts, getPublicSettings, getShipment, listDocuments, openDocumentFile, refreshIcegate, setCostInclusion } from "./api";
import { useDismiss } from "./useDismiss";
import { useSaveShipment } from "./useSaveShipment";
import { SHIPMENT_STATUS_LABELS, docShort, type DocumentType, type InvoiceCharge, type Shipment, type ShipmentDocument } from "./types";
import DocumentManagerPanel from "./DocumentManagerPanel";
import ProformaPanel from "./ProformaPanel";
import FpodContainers from "./FpodContainers";
import ShipmentHistory from "./ShipmentHistory";
import { formatPort, usePorts } from "./ports";
import DateInput from "./DateInput";

type Tab = "overview" | "customs" | "documents" | "history" | "proforma";

// sea ports: free days start at the POD inward; every other port is inland (ICD) — client, 2026-09-30
const SEA_PORTS = new Set(["INMUN1", "INNSA1"]);

/** "2026-08-27" -> "27 Aug 2026" */
function fmtDate(v: string | null): string | null {
  return v ? fmtDay(v) : null;
}

/** "108560.00" -> "₹1,08,560.00" (Indian grouping) */
function fmtMoney(v: string | null): string | null {
  if (v == null || v === "") return null;
  const n = Number(v);
  if (Number.isNaN(n)) return v;
  return `₹${n.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}


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
  hint,
}: {
  shipmentId: number;
  onClose?: () => void;
  tab?: Tab;
  onTab?: (t: Tab) => void;
  full?: boolean;
  onFull?: (full: boolean) => void;
  /** the tracker row just clicked: its job / BL / client head the peek while the full job loads */
  hint?: Pick<Shipment, "id" | "job" | "mbl" | "client" | "consignee"> | null;
}) {
  const peek = !!onClose;
  const [shipment, setShipment] = useState<Shipment | null>(null);
  // a save that lands after switching jobs must not paint the old job over the new one
  const idRef = useRef(shipmentId);
  idRef.current = shipmentId;
  const onSaved = useCallback((x: Shipment) => {
    if (x.id === idRef.current) setShipment(x);
    else rememberShipment(x);
  }, []);
  const [loading, setLoading] = useState(true);
  // why the load failed: 404 = gone; anything else (network, 500) gets a Retry, never "doesn't exist"
  const [loadErr, setLoadErr] = useState<"gone" | "failed" | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [localTab, setLocalTab] = useState<Tab>("overview"); // peek panel: no URL of its own
  const tab = tabProp ?? localTab;
  const setTab = onTab ?? setLocalTab;
  const isAdmin = useAuth().user?.role === "admin"; // invoicing is admin-only

  // the shipment's documents: the Money card and its charge drawer read them (cached per job: reopening draws at once)
  const [docs, setDocs] = useState<ShipmentDocument[]>(() => docsCache.get(shipmentId) ?? []);
  const [drawer, setDrawer] = useState<MoneyGroup | null>(null);
  const [uploadType, setUploadType] = useState<DocumentType | undefined>();
  const loadDocs = useCallback(
    () =>
      listDocuments(shipmentId).then((all) => {
        docsCache.set(shipmentId, all);
        if (shipmentId === idRef.current) setDocs(all); // switched jobs meanwhile: don't show the old one's
      }),
    [shipmentId],
  );
  // a reload that lands after the peek moved to another job only refreshes the cache, never the panel
  const reload = useCallback(() => Promise.all([getShipment(shipmentId).then(onSaved), loadDocs()]).then(() => {}), [shipmentId, loadDocs, onSaved]);

  useEffect(() => {
    // switching jobs in the peek: the old job stays (dimmed) until the new one has arrived — no blank flash
    let live = true;
    const seen = shipmentCache.get(shipmentId);
    if (seen) setShipment(seen);
    setLoading(!seen); // dim (and skeleton) only for a job not seen yet
    // documents come with the first load, so the Overview draws complete (no late push-down)
    if (seen) setDocs(docsCache.get(shipmentId) ?? []); // an unseen job: the old one's stay with it (dimmed) until both arrive
    setDrawer(null);
    const docsLoad = listDocuments(shipmentId)
      .then((all) => {
        docsCache.set(shipmentId, all);
      })
      .catch(() => {});
    // shipment and documents land together: the Money card never shows one job's figures with another's invoices
    const one = Promise.all([getShipment(shipmentId), docsLoad]).then(
      ([s]) => {
        if (!live) return;
        setShipment(s);
        setDocs(docsCache.get(shipmentId) ?? []);
        setLoadErr(null);
      },
      (e) => {
        if (!live) return;
        setShipment(null);
        setLoadErr(axios.isAxiosError(e) && e.response?.status === 404 ? "gone" : "failed");
      },
    );
    Promise.all([one, docsLoad]).finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, [shipmentId, reloadKey]);

  useEffect(() => {
    if (shipment) shipmentCache.set(shipment.id, shipment);
  }, [shipment]);

  // Proforma tab on a wide page: the invoice preview takes the whole right half, top to bottom, and
  // everything else moves to the left half (client, 2026-10-08)
  const [pageEl, setPageEl] = useState<HTMLDivElement | null>(null);
  const [previewSlot, setPreviewSlot] = useState<HTMLElement | null>(null);
  const [pageW, setPageW] = useState(0);
  useEffect(() => {
    if (!pageEl) return;
    const ro = new ResizeObserver(() => setPageW(pageEl.clientWidth));
    ro.observe(pageEl);
    return () => ro.disconnect();
  }, [pageEl]);
  const pfWide = tab === "proforma" && isAdmin && pageW >= 1100;

  const [slowSwitch, setSlowSwitch] = useState(false);
  const isSwitching = loading && !!shipment && shipment.id !== shipmentId;
  useEffect(() => {
    setSlowSwitch(false);
    if (!isSwitching) return;
    const t = window.setTimeout(() => setSlowSwitch(true), 150);
    return () => window.clearTimeout(t);
  }, [isSwitching, shipmentId]);

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

  // switching to a job not loaded yet: the old job dims and can't be clicked; a fast load (<150 ms)
  // swaps straight in, a slower one shows the new job's header (from the row) over a skeleton
  const switching = loading && !!shipment && shipment.id !== shipmentId;
  const showSkeleton = loading && (!shipment || (switching && slowSwitch));
  const peekBar = (
        <div className="peek-bar">
          {onFull ? (
            <button type="button" className="peek-size btn-secondary" onClick={() => onFull(!full)} aria-pressed={full}>
              {full ? "⇥ Half view" : "⇤ Full width"}
            </button>
          ) : (
            <Link to={`/shipments/${shipmentId}`} className="back-link">
              Open full page ↗
            </Link>
          )}
          <span className="peek-bar-right">
            <Link to={`/shipments/${shipmentId}`} className="peek-newtab" target="_blank" rel="noreferrer" title="Open in a new tab">
              New tab ↗
            </Link>
            <button type="button" className="peek-close" onClick={onClose} aria-label="Close" title="Close (Esc)">
              ✕
            </button>
          </span>
        </div>
  );

  if (showSkeleton) {
    const h = hint?.id === shipmentId ? hint : null;
    return (
      <div className={`detail-page${peek && !full ? " detail-peek" : ""}`} aria-busy="true" aria-label="Loading the shipment">
        {peek && peekBar}
        {peek && (
          <header className="detail-header">
            <div className="detail-title">
              <span className="detail-job">{h ? (h.job ? `Job ${h.job}` : "No job number yet") : "Loading…"}</span>
              {h && (
                <span className="detail-client">
                  {[h.mbl && `BL ${h.mbl}`, h.client, h.consignee].filter(Boolean).join(" · ")}
                </span>
              )}
            </div>
            <span className="peek-loading" role="status">
              <span className="spinner" aria-hidden="true" /> Loading…
            </span>
          </header>
        )}
        <DetailSkeleton peek={peek && !full} body={peek} />
      </div>
    );
  }
  if (!shipment && loadErr === "failed")
    return <LoadError what="this shipment" onRetry={() => setReloadKey((n) => n + 1)} />;
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
      ref={setPageEl}
      className={`detail-page${peek && !full ? " detail-peek" : ""}${loading ? " is-stale" : ""}${pfWide ? " pf-wide" : ""}`}
      aria-busy={loading || undefined}
      inert={switching || undefined}
    >
      <div className="detail-main">
      {peek ? (
        peekBar
      ) : (
        <BackLink />
      )}

      <header className="detail-header">
        {/* the job is the first box of the key strip and the status sits beside Duty; the header holds only the sections (client, 2026-10-08) */}
        <h1 className="sr-only">{shipment.job ? `Job ${shipment.job}` : "No job number yet"}</h1>
        <div className="detail-subrow">
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
        </div>
      </header>

      {/* tier 1: the keys, what's next, where the clearance stands, and the three payments — at a glance */}
      <div className={`tier1${tab === "proforma" ? " no-flow" : ""}`}>
        <KeyStrip s={shipment} />
        {/* the clearance progress isn't needed while billing (client, 2026-10-08) */}
        {tab !== "proforma" && (
          <section className="tier1-flow" aria-label="Clearance">
            <NextStepBar shipment={shipment} />
            <ClearanceStepper s={shipment} onChange={onSaved} />
          </section>
        )}
        <MoneyCard
          s={shipment}
          docs={docs}
          open={drawer}
          onOpen={setDrawer}
          onDuty={() => {
            setTab("overview");
            window.setTimeout(() =>
              document.getElementById(`duty-${shipment.id}`)?.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" }),
            );
          }}
          onUpload={(t) => {
            setUploadType(t);
            setTab("documents");
          }}
        />
      </div>
      <Collapse open={drawer != null} className="charge-drawer-wrap">
        {drawer && (
          <ChargeDrawer
            group={drawer}
            shipment={shipment}
            docs={docs}
            onChange={onSaved}
            onSaved={reload}
            onClose={() => setDrawer(null)}
          />
        )}
      </Collapse>

      {shipment.cleared_date && !shipment.is_fully_cleared && (
        <div className="auth-error detail-stuck-banner">
          Clearance exception: Cleared Date is set but {shipment.missing_for_clearance.join(", ")}{" "}
          {shipment.missing_for_clearance.length > 1 ? "aren't" : "isn't"} ticked — it stays with the ongoing
          shipments until sorted.
        </div>
      )}


      <div className="tab-body" key={tab}>
      {tab === "overview" && <OverviewTab shipment={shipment} onChange={onSaved} />}
      {tab === "customs" && <CustomsTimeline shipmentId={shipment.id} shipment={shipment} />}
      {tab === "documents" && <DocumentManagerPanel shipment={shipment} onShipmentChanged={reload} initialType={uploadType} />}
      {tab === "history" && <ShipmentHistory shipment={shipment} onChange={onSaved} />}
      {tab === "proforma" && isAdmin && (
        <ProformaPanel shipment={shipment} onShipmentChange={onSaved} previewSlot={pfWide ? previewSlot : null} />
      )}
      </div>
      </div>
      {pfWide && <aside className="pf-preview-col" ref={setPreviewSlot} aria-label="Invoice preview" />}
    </div>
  );
}

/** First open: grey blocks in the page's own shape (key strip, next step, stepper, cards) instead of "Loading…". */
function DetailSkeleton({ peek, body = false }: { peek: boolean; body?: boolean }) {
  return (
    <div className={`detail-page detail-skeleton${peek ? " detail-peek" : ""}${body ? " sk-body" : ""}`} aria-busy="true" aria-label="Loading the shipment">
      {!body && <div className="sk sk-title" />}
      <div className="sk sk-strip" />
      <div className="sk sk-next" />
      <div className="sk sk-stepper" />
      <div className="sk sk-money" />
      <div className="sk sk-tabs" />
      <div className="sk sk-card" />
      <div className="sk sk-card" />
    </div>
  );
}

type ToggleField = "cfs_paid_by_us" | "line_paid_by_us" | "tds_on_cfs";

/**
 * The Overview's own width (not the window's: the half peek stays one column). Same breakpoints as the
 * CSS container queries on .detail-page: 1100 = the 12-column layout, 1600 = three columns.
 */
const OVERVIEW_WIDE = 1100;
function useBoxWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    const ro = new ResizeObserver(([e]) => setWidth(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width] as const;
}

function OverviewTab({ shipment: s, onChange }: { shipment: Shipment; onChange: (s: Shipment) => void }) {
  const ports = usePorts();
  const [box, width] = useBoxWidth<HTMLDivElement>();
  const wide = width >= OVERVIEW_WIDE;
  // IGM & ICD details: open by default at every width
  const [igmUser, setIgmOpen] = useState<boolean | null>(null);
  const igmOpen = igmUser ?? true; // always shown unless folded by hand (client, 2026-10-08)
  const inland = !!s.port && !SEA_PORTS.has(s.port);
  return (
    // two stacks side by side when wide (index.css): shipment (with IGM & ICD) | duty, notes, billing, so no card leaves a
    // hole beside a taller one; containers full width under both. Narrow: one column (the stacks dissolve).
    <div className="overview" ref={box}>
      <div className="ov-col ov-col-main">
        <section className="detail-section ov-ship">
          <h3>Shipment &amp; movement</h3>
          <div className="field-grid">
            <EditField label="Port (POD)" field="port" kind="port" s={s} onChange={onChange} display={formatPort(s.port, ports) || null} />
            <EditField label="ETA" field="eta" kind="date" s={s} onChange={onChange} display={fmtDate(s.eta)} />
            <EditField label="INW" field="inw" s={s} onChange={onChange} display={s.inw ? s.inw.replace(/^(\d{1,2})-([A-Za-z]{3})-(\d{4})$/, (_, d, m, y) => `${d.padStart(2, "0")} ${m} ${y}`) : null} hint="Typed like the sheet, e.g. 19-Sep-2026" />
            <Field label="Day" value={s.days} />
            <EditField label="Containers" field="container" s={s} onChange={onChange} />
            <EditField label="Gross Wt" field="gross_wt" s={s} onChange={onChange} />
            <EditField label="Container status" field="container_status" s={s} onChange={onChange} />
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
          <IcegateBar s={s} onChange={onChange} open={igmOpen} onToggle={() => setIgmOpen(!igmOpen)} />
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
      <div className="ov-col ov-col-side">
      <div className="ov-duty">
        <section className="detail-section" id={`duty-${s.id}`}>
          <h3>Customs duty</h3>
          <EditField label="License" field="license" s={s} onChange={onChange} />
          {inland && s.icegate?.icd?.be_location && <Field label="BE location" value={s.icegate.icd.be_location} hint="From the ICD BL status" />}
          {inland && s.icegate?.icd?.importer && <Field label="Importer (ICD)" value={s.icegate.icd.importer} hint="From the ICD BL status" />}
          <BeAmounts shipment={s} onChange={onChange} />
        </section>
      </div>
      <section className="detail-section ov-notes">
        <h3>Notes</h3>
        <EditField label="Short remark" field="remark" s={s} onChange={onChange} />
        <EditField label="Notes" field="remarks" s={s} onChange={onChange} multiline />
      </section>
      <BillingSettings s={s} onChange={onChange} />
      </div>
      {/* every shipment's containers (from the sea IGM) with their free days — inland: from each container's
          arrival at the FPOD; sea port: from the INW (client, 2026-09-30) */}
      {s.port && (
        <FpodContainers key={s.icegate?.fetched_at ?? "none"} shipment={s} inland={inland} portLabel={formatPort(s.port, ports) || s.port} onRefreshed={onChange} wide={wide} />
      )}
    </div>
  );
}

/**
 * How this job is billed, as one quiet row of chips (+ the two proforma choices). One plain line under it
 * says what the settings add up to — these move money, so it isn't left to tooltips alone.
 */
function BillingSettings({ s, onChange }: { s: Shipment; onChange: (s: Shipment) => void }) {
  const ro = useReadOnly(); // view-only login: no edit controls
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
  const sw = (field: ToggleField, label: string, help: string) => (
    <SwitchRow label={label} help={help} on={!!s[field]} busy={saving === field} onToggle={() => toggle(field)} />
  );
  const summary = [
    s.is_hss ? "High sea sale" : null,
    s.cfs_paid_by_us
      ? `CFS paid by us${s.tds_on_cfs ? `, ${tdsPct(s)}% TDS cut` : ""}, billed ${s.cfs_billed_as === "taxable" ? "as taxable + 18% GST" : "at actuals"}`
      : "CFS paid by the client — we pass the invoice on",
    s.line_paid_by_us
      ? "line paid by us (reimbursement)"
      : `line paid by the client (${s.line_excluded_by ? "left off the proforma" : "shown as cost inclusion"}${lineOverridden(s) ? ", overridden for this job" : ", client default"})`,
  ].filter(Boolean);
  return (
    <section className="detail-section billing-settings ov-billing" aria-label="Billing settings">
      <h3>Billing settings</h3>
      <div className="bill-grid">
        <HssEditor shipment={s} onChange={onChange} />
        {sw("cfs_paid_by_us", "CFS paid by us", "We pay the CFS and bill it on")}
        {s.cfs_paid_by_us && sw("tds_on_cfs", "TDS on CFS", "TDS is cut when we pay the CFS")}
        {s.cfs_paid_by_us && s.tds_on_cfs && <TdsRate shipment={s} onChange={onChange} />}
        {sw("line_paid_by_us", "Shipping line paid by us", "We pay the shipping line and bill it as a reimbursement")}
        {s.cfs_paid_by_us && (
          <label className="switch-row">
            <span className="switch-label">
              CFS on proforma
              <InfoTip text="How CFS goes on the proforma" />
            </span>
            <select
              className="chip-select"
              disabled={ro}
              value={s.cfs_billed_as}
              onChange={async (e) => onChange((await saveShipment(s, { cfs_billed_as: e.target.value as Shipment["cfs_billed_as"] })).shipment)}
            >
              <option value="reimbursement">At actuals</option>
              <option value="taxable">Taxable + 18% GST</option>
            </select>
          </label>
        )}
        {!s.line_paid_by_us && (
          <label className="switch-row">
            <span className="switch-label">
              Line cost
              <InfoTip text="Shipping line in the cost inclusion. Preset to the client default; pick the other to override for this shipment only" />
            </span>
            <LineCostSelect s={s} onSave={async (v) => onChange((await saveShipment(s, { line_cost_inclusion: v })).shipment)} />
          </label>
        )}
      </div>
      <p className="billing-summary">{summary.join(" · ")}.</p>
    </section>
  );
}

/**
 * Shipping line in the cost inclusion: Include / Leave out, the client default marked "(client default)" and
 * preset — picking it goes back to following the client; picking the other overrides this shipment only.
 */
/** One reading of the line-cost setting for every place that shows it: null, or the same as the client, = client default. */
const lineClientDefault = (s: Shipment) => (s.line_client_excluded_by ? "exclude" : "include");
const lineOverridden = (s: Shipment) => s.line_cost_inclusion != null && s.line_cost_inclusion !== lineClientDefault(s);

function LineCostSelect({ s, disabled, onSave }: { s: Shipment; disabled?: boolean; onSave: (v: "include" | "exclude" | null) => void }) {
  const ro = useReadOnly(); // view-only login: no edit controls
  const clientDefault = lineClientDefault(s);
  const value = s.line_cost_inclusion ?? clientDefault;
  const tag = (v: "include" | "exclude") => (v === clientDefault ? " (client default)" : " (override)");
  return (
    <select
      className="chip-select line-cost-select"
      aria-label="Shipping line in the cost inclusion"
      value={value}
      disabled={disabled || ro}
      title={s.line_client_excluded_by ? `Client default: left out (${s.line_client_excluded_by})` : "Client default: included"}
      onChange={(e) => {
        const v = e.target.value as "include" | "exclude";
        onSave(v === clientDefault ? null : v);
      }}
    >
      <option value="include">Include{tag("include")}</option>
      <option value="exclude">Leave out{tag("exclude")}</option>
    </select>
  );
}

/** An on/off billing setting: label, (i) for what it means, a switch. */
function SwitchRow({ label, help, on, busy, onToggle }: { label: string; help?: string; on: boolean; busy?: boolean; onToggle: () => void }) {
  const ro = useReadOnly(); // view-only login: no edit controls
  return (
    <div className="switch-row">
      <span className="switch-label">
        {label}
        {help && <InfoTip text={help} />}
      </span>
      <button type="button" role="switch" aria-checked={on} aria-label={label} className="switch" disabled={busy || ro} onClick={onToggle}>
        <span className="switch-knob" aria-hidden="true" />
      </button>
    </div>
  );
}

/** (i): the longer explanation, on hover or keyboard focus. */
function InfoTip({ text }: { text: string }) {
  return (
    <span className="info-tip" tabIndex={0} role="img" aria-label={text} title={text}>
      i
    </span>
  );
}

const tdsPct = (s: Shipment) => (s.cfs_tds_rate == null ? "2" : String(Number(s.cfs_tds_rate)));

/**
 * TDS rate on the CFS payment: fixed at 2% unless the admin allows other rates in Settings;
 * then 1% / 2% / 10% or a typed rate (client, 2026-09-30).
 */
function TdsRate({ shipment: s, onChange }: { shipment: Shipment; onChange: (s: Shipment) => void }) {
  const ro = useReadOnly(); // view-only login: no edit controls
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
              disabled={busy || ro}
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
  const ro = useReadOnly(); // view-only login: no edit controls
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
      <SwitchRow
        label="High sea sale"
        help="Any consignee written 'SELLER - BUYER' is detected as HSS automatically"
        on={!!s.is_hss}
        busy={busy}
        onToggle={() => save({ is_hss: !s.is_hss })}
      />
      {s.is_hss && !editing && (
        <div className="field-row">
          <span className="field-label">Seller → Buyer</span>
          <span className="field-value">
            {s.hss_seller ?? "?"} → {s.hss_buyer ?? "?"}{" "}
            <button
              type="button"
              className="link-btn"
              hidden={ro}
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
            disabled={busy || ro}
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
  const ro = useReadOnly(); // view-only login: no edit controls
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
        {!editing && !ro && (
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
          {/* one line: "₹3,97,810 (incl. interest ₹3,564)" — display only */}
          <Field
            label={s.ooc ? "Final Duty" : "Duty due"}
            value={Number(final.interest) > 0 ? `${fmtMoney(final.total)} (incl. interest ${fmtMoney(final.interest)})` : fmtMoney(final.total)}
            strong
            hint={finalHint}
          />
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
    title: "CFS charges",
    types: ["cfs_tax_invoice", "cfs_proforma_invoice"],
    taxType: "cfs_tax_invoice",
    receiptType: "cfs_receipt",
    uploadType: "cfs_tax_invoice",
  },
  line: {
    title: "Shipping line · destination charges",
    types: ["shipping_line_invoice", "shipping_line_proforma"],
    taxType: "shipping_line_invoice",
    receiptType: "shipping_line_receipt",
    uploadType: "shipping_line_invoice",
  },
} as const;
type MoneyGroup = keyof typeof INVOICE_GROUPS;

type DocFields = { charges?: InvoiceCharge[]; charges_complete?: boolean; carrier?: string; invoice_no?: string; bl_mismatch?: boolean };
const docFields = (d: ShipmentDocument) => (d.extraction?.fields ?? {}) as DocFields;
/** Charge lines read from the invoice ([] when they didn't add up) — same as the backend's invoice_charges. */
const chargesOf = (d: ShipmentDocument) => (docFields(d).charges_complete ? docFields(d).charges ?? [] : []);

/**
 * The group's invoices and which of them count — mirrors cfs_totals.py: tax invoices, else proformas,
 * each invoice once; a line invoice whose BL isn't this shipment's doesn't count.
 */
function groupDocs(group: MoneyGroup, docs: ShipmentDocument[]) {
  const cfg = INVOICE_GROUPS[group];
  const all = docs.filter((d) => (cfg.types as readonly string[]).includes(d.document_type));
  const eligible = all.filter((d) => !(group === "line" && docFields(d).bl_mismatch === true));
  const tax = eligible.filter((d) => d.document_type === cfg.taxType);
  const counted = (tax.length ? tax : eligible).filter((d) => d.extraction?.duplicate_of == null);
  const why = (d: ShipmentDocument): string | null => {
    if (counted.includes(d)) return null;
    if (d.extraction?.duplicate_of != null) return "duplicate — counted once";
    if (group === "line" && docFields(d).bl_mismatch === true) return "BL ≠ shipment — not counted";
    return "not counted (tax invoice received)";
  };
  const receipts = docs.filter((d) => d.document_type === cfg.receiptType);
  return { all, counted, why, receipts };
}

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Opens / closes its content to the measured height (180ms, height + opacity), then lets it size itself
 * so a sticky footer inside still sticks. Reduced motion: no animation.
 */
function Collapse({ open, children, className, id }: { open: boolean; children: React.ReactNode; className?: string; id?: string }) {
  const box = useRef<HTMLDivElement>(null);
  const [mounted, setMounted] = useState(open);
  const first = useRef(true);
  useLayoutEffect(() => {
    if (open && !mounted) return setMounted(true);
    const el = box.current;
    if (!el) return;
    const skip = first.current && open; // already open on the first draw: no animation
    first.current = false;
    if (skip) return;
    let timer = 0;
    const end = () => {
      window.clearTimeout(timer);
      el.removeEventListener("transitionend", onEnd);
      if (open) {
        el.style.height = "";
        el.style.overflow = "";
      } else setMounted(false);
    };
    const onEnd = (e: TransitionEvent) => e.target === el && e.propertyName === "height" && end();
    if (reducedMotion()) {
      end();
      return;
    }
    const full = el.scrollHeight;
    el.style.overflow = "hidden";
    el.style.height = open ? "0px" : `${full}px`;
    el.style.opacity = open ? "0" : "1";
    void el.offsetHeight; // start from there
    el.style.height = open ? `${full}px` : "0px";
    el.style.opacity = open ? "1" : "0";
    el.addEventListener("transitionend", onEnd);
    timer = window.setTimeout(end, 260); // in case transitionend never comes
    return () => {
      window.clearTimeout(timer);
      el.removeEventListener("transitionend", onEnd);
    };
  }, [open, mounted]);
  if (!mounted) return null;
  return (
    <div ref={box} id={id} className={`collapse${className ? ` ${className}` : ""}`}>
      {children}
    </div>
  );
}

/**
 * CFS / shipping line charges, under the Money card: every invoice with its figures and charge lines
 * (tick what goes in the cost inclusion), receipts, and the totals in a footer that stays in view.
 * Esc, × or the row's Charges button closes it.
 */
function ChargeDrawer({
  group,
  shipment: s,
  docs,
  onChange,
  onSaved,
  onClose,
}: {
  group: MoneyGroup;
  shipment: Shipment;
  docs: ShipmentDocument[];
  onChange: (s: Shipment) => void;
  onSaved: () => Promise<void>;
  onClose: () => void;
}) {
  const ro = useReadOnly(); // view-only login: no edit controls
  const cfg = INVOICE_GROUPS[group];
  const saveShipment = useSaveShipment();
  const [busy, setBusy] = useState(false);
  useDismiss(null, true, onClose);
  // focus moves to the drawer's heading on open and back to its Charges button on close
  const headRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const head = headRef.current;
    head?.focus({ preventScroll: true });
    return () => {
      const a = document.activeElement;
      if (!a || a === document.body || head?.closest(".charge-drawer")?.contains(a) || !a.isConnected)
        document.querySelector<HTMLButtonElement>(`[data-charges="${group}"]`)?.focus();
    };
  }, [group]);
  const { all, why, receipts } = groupDocs(group, docs);
  const paidField = group === "cfs" ? "cfs_paid_by_us" : "line_paid_by_us";

  async function save(patch: Partial<Shipment>) {
    setBusy(true);
    try {
      onChange((await saveShipment(s, patch)).shipment);
    } finally {
      setBusy(false);
    }
  }

  const totals =
    group === "cfs"
      ? [s.cfs_amount_before_tax, s.cfs_gst_amount, s.cfs_amount_total]
      : [s.line_amount_before_tax, s.line_gst_amount, s.line_amount_total];
  const note =
    group === "line"
      ? s.line_paid_by_us
        ? "Billed on the proforma as a reimbursement"
        : s.line_excluded_by
          ? `Left off the proforma (${s.line_excluded_by})`
          : "Shown on proforma as Cost inclusion, not in the total"
      : s.cfs_paid_by_us
        ? `Billed on the proforma ${s.cfs_billed_as === "taxable" ? "as taxable + 18% GST" : "at actuals"}`
        : "Paid by the client — we pass the invoice on";

  return (
    <section className="charge-drawer" id="charge-drawer" aria-label={cfg.title}>
      <header className="charge-drawer-head">
        <h3 ref={headRef} tabIndex={-1}>{cfg.title}</h3>
        <div className="charge-drawer-controls">
          <SwitchRow label="Paid by us" on={!!s[paidField]} busy={busy} onToggle={() => save({ [paidField]: !s[paidField] } as Partial<Shipment>)} />
          {group === "line" && !s.line_paid_by_us && (
            <label className="switch-row">
              <span className="switch-label">In cost inclusion</span>
              <LineCostSelect s={s} disabled={busy || ro} onSave={(v) => save({ line_cost_inclusion: v })} />
            </label>
          )}
          {group === "cfs" && s.cfs_paid_by_us && (
            <label className="switch-row">
              <span className="switch-label">CFS on proforma</span>
              <select
                className="chip-select"
                value={s.cfs_billed_as}
                disabled={busy || ro}
                onChange={(e) => save({ cfs_billed_as: e.target.value as Shipment["cfs_billed_as"] })}
              >
                <option value="reimbursement">At actuals</option>
                <option value="taxable">Taxable + 18% GST</option>
              </select>
            </label>
          )}
          <button type="button" className="charge-drawer-close" onClick={onClose} aria-label="Close charges" title="Close (Esc)">
            ✕
          </button>
        </div>
      </header>
      <div className="charge-drawer-body">
        {all.map((d) => (
          <InvoiceCard key={d.id} group={group} doc={d} notCounted={why(d)} onSaved={onSaved} />
        ))}
        {receipts.length > 0 && <Receipts receipts={receipts} onSaved={onSaved} />}
        {group === "cfs" && s.cfs_paid_by_us && (
          <div className="charge-tds">
            <Field
              label={`TDS @ ${tdsPct(s)}%`}
              value={s.tds_on_cfs ? fmtMoney(s.cfs_tds_amount) : "Not cut"}
              hint={`${tdsPct(s)}% of the CFS basic value (before GST)`}
              amount
            />
            <Field label="After TDS" value={fmtMoney(s.cfs_payment_after_tds)} hint={`Basic + GST − ${tdsPct(s)}% of basic`} strong amount />
          </div>
        )}
      </div>
      <footer className="charge-drawer-foot">
        <span className="charge-foot-figs">
          <span>Before tax <strong>{fmtMoney(totals[0]) ?? "—"}</strong></span>
          <span>GST <strong>{fmtMoney(totals[1]) ?? "—"}</strong></span>
          <span>Total <strong>{fmtMoney(totals[2]) ?? "—"}</strong></span>
        </span>
        <span className="charge-foot-note">{note}</span>
      </footer>
    </section>
  );
}

/**
 * One invoice in the charge drawer: a header line (tick-all, name, amount, View PDF) that folds open to its
 * figures (correctable) and — shipping line — the charge lines that make its cost inclusion.
 * Starts open when it has more than one charge.
 */
function InvoiceCard({
  group,
  doc: d,
  notCounted,
  onSaved,
}: {
  group: MoneyGroup;
  doc: ShipmentDocument;
  notCounted: string | null;
  onSaved: () => Promise<void>;
}) {
  const ro = useReadOnly(); // view-only login: no edit controls
  const fields = docFields(d);
  const charges = group === "line" ? chargesOf(d) : [];
  const excluded = new Set(d.cost_excluded ?? []);
  const [open, setOpen] = useState(charges.length > 1);
  const [editing, setEditing] = useState(false); // basic / GST correction
  const [typing, setTyping] = useState(false); // cost inclusion typed by hand
  const [before, setBefore] = useState("");
  const [gst, setGst] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tick = useRef<HTMLInputElement>(null);
  const num = (v: string) => Number(v.replace(/,/g, "")) || 0;
  const isAmount = (v: string) => /^\d+(\.\d{1,2})?$/.test(v);

  const kept = charges.filter((_, i) => !excluded.has(i)).length;
  const canTick = charges.length > 0 && !d.cost_manual;
  useEffect(() => {
    if (tick.current) tick.current.indeterminate = kept > 0 && kept < charges.length;
  }, [kept, charges.length]);

  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
      setEditing(false);
      setTyping(false);
      await onSaved();
    } catch {
      setError("Couldn't save.");
    } finally {
      setBusy(false);
    }
  }
  const send = (body: Parameters<typeof setCostInclusion>[2]) => run(() => setCostInclusion(d.shipment_id, d.id, body));

  // what this invoice adds: the cost inclusion part (line), the whole invoice (CFS)
  const partial = d.cost_before_tax != null;
  const amount =
    group === "line" && partial ? String(num(d.cost_before_tax ?? "") + num(d.cost_gst ?? "")) : d.amount_total;
  const name = [docShort(d.document_type), fields.invoice_no].filter(Boolean).join(" · ");
  const bodyId = `inv-${d.id}`;

  return (
    <div className={`inv-card${notCounted ? " is-not-counted" : ""}`}>
      <div className="inv-card-head">
        <button
          type="button"
          className="inv-caret"
          aria-expanded={open}
          aria-controls={bodyId}
          aria-label={`${open ? "Fold" : "Open"} ${name}`}
          onClick={() => setOpen(!open)}
        >
          <span aria-hidden="true"><svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M2.5 3.75 5 6.25l2.5-2.5" /></svg></span>
        </button>
        {canTick && (
          <input
            ref={tick}
            type="checkbox"
            className="inv-tick"
            aria-label={`All charges of ${name} in the cost inclusion`}
            checked={kept === charges.length}
            disabled={busy || ro}
            onChange={() => send({ excluded: kept === charges.length ? charges.map((_, i) => i) : [] })}
          />
        )}
        <span className="inv-name">
          {name}
          {fields.carrier && <span className="inv-carrier"> · {fields.carrier}</span>}
        </span>
        <span className="inv-tags">
          {notCounted && <span className="field-note">{notCounted}</span>}
          {d.amounts_edited && <span className="edited-tag">corrected</span>}
          {d.cost_manual && <span className="edited-tag">typed by hand</span>}
          {canTick && (
            <span className="field-note">
              {kept} of {charges.length}
            </span>
          )}
        </span>
        <strong className="inv-amt">{fmtMoney(amount) ?? "—"}</strong>
        <button type="button" className="link-btn" onClick={() => openDocumentFile(d.shipment_id, d.id)}>
          View PDF
        </button>
      </div>
      <Collapse open={open} id={bodyId}>
        <div className="inv-card-body">
          {editing ? (
            <div className="inv-edit">
              <label className="field-row">
                <span className="field-label">Basic (before tax)</span>
                <input className="amount-input" inputMode="decimal" value={before} onChange={(e) => setBefore(e.target.value)} onKeyDown={escCancel(() => setEditing(false))} />
              </label>
              <label className="field-row">
                <span className="field-label">GST</span>
                <input className="amount-input" inputMode="decimal" value={gst} onChange={(e) => setGst(e.target.value)} onKeyDown={escCancel(() => setEditing(false))} />
              </label>
              <Field label="Total (basic + GST)" value={fmtMoney(String(num(before) + num(gst)))} strong />
              <div className="amount-actions">
                <button type="button" className="btn-secondary" onClick={() => setEditing(false)}>
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={busy || ro}
                  onClick={() => {
                    const b = before.trim().replace(/,/g, ""), g = gst.trim().replace(/,/g, "");
                    if (!isAmount(b) || !isAmount(g)) return setError("Enter both amounts as numbers, e.g. 40000 and 7200");
                    run(() => correctInvoiceAmounts(d.shipment_id, d.id, b, g));
                  }}
                >
                  Save
                </button>
              </div>
            </div>
          ) : (
            <div className="invoice-figures">
              <span>Basic {fmtMoney(d.amount_before_tax) ?? "—"}</span>
              <span>GST {fmtMoney(d.gst_amount) ?? "—"}</span>
              <strong>Invoice {fmtMoney(d.amount_total) ?? "—"}</strong>
              <button
                type="button"
                className="link-btn"
                hidden={ro}
                onClick={() => {
                  setBefore(d.amount_before_tax ?? "");
                  setGst(d.gst_amount ?? "");
                  setError(null);
                  setEditing(true);
                }}
              >
                Edit
              </button>
            </div>
          )}
          {group === "line" && (
            <>
              {canTick ? (
                <ul className="charge-lines">
                  {charges.map((c, i) => (
                    <li key={i} className={excluded.has(i) ? "charge-out" : undefined}>
                      <label>
                        <input
                          type="checkbox"
                          checked={!excluded.has(i)}
                          disabled={busy || ro}
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
                          {c.review && (
                            <span className="charge-tag charge-review" title="Billed in INR but named like freight — left out; tick if it's a destination charge">
                              check
                            </span>
                          )}
                        </span>
                      </label>
                      <span className="charge-amt">{fmtMoney(String(c.amount ?? ""))}</span>
                    </li>
                  ))}
                </ul>
              ) : (
                !d.cost_manual && (
                  <p className="field-note">Charge lines couldn't be read from this invoice — the whole invoice counts. Use “Type figure” to change it.</p>
                )
              )}
              {typing ? (
                <div className="cost-inclusion-typing">
                  <input className="amount-input" inputMode="decimal" placeholder="Before tax…" aria-label="Cost inclusion before tax" value={before} onChange={(e) => setBefore(e.target.value)} onKeyDown={escCancel(() => setTyping(false))} />
                  <input className="amount-input" inputMode="decimal" placeholder="GST…" aria-label="Cost inclusion GST" value={gst} onChange={(e) => setGst(e.target.value)} onKeyDown={escCancel(() => setTyping(false))} />
                  <button
                    type="button"
                    disabled={busy || ro}
                    onClick={() => {
                      const b = before.replace(/,/g, "").trim(), g = gst.replace(/,/g, "").trim() || "0";
                      if (!isAmount(b) || !isAmount(g)) return setError("Enter amounts as numbers");
                      send({ before_tax: b, gst: g });
                    }}
                  >
                    Save
                  </button>
                  <button type="button" className="btn-secondary" onClick={() => setTyping(false)}>
                    Cancel
                  </button>
                </div>
              ) : (
                <div className="cost-inclusion-actions">
                  <span className="field-note">
                    Cost inclusion: {partial ? `${fmtMoney(d.cost_before_tax)} + GST ${fmtMoney(d.cost_gst)}` : "whole invoice"}
                  </span>
                  <button
                    type="button"
                    className="link-btn"
                    hidden={ro}
                    onClick={() => {
                      setBefore(d.cost_before_tax ?? d.amount_before_tax ?? "");
                      setGst(d.cost_gst ?? d.gst_amount ?? "");
                      setError(null);
                      setTyping(true);
                    }}
                  >
                    Type figure
                  </button>
                  {(partial || d.cost_manual) && (
                    <button type="button" className="link-btn" hidden={ro} disabled={busy} onClick={() => send({ reset: true })} title="Back to the rule: INR charges that aren't freight">
                      Reset
                    </button>
                  )}
                </div>
              )}
            </>
          )}
          {error && (
            <span className="auth-error" role="alert">
              {error}
            </span>
          )}
        </div>
      </Collapse>
    </div>
  );
}

/** Receipts: what was actually paid (editable when misread). */
function Receipts({ receipts, onSaved }: { receipts: ShipmentDocument[]; onSaved: () => Promise<void> }) {
  const ro = useReadOnly(); // view-only login: no edit controls
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
              <input className="amount-input" inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} onKeyDown={escCancel(() => setEditingId(null))} />
              <button type="button" onClick={() => save(r)}>Save</button>
              <button type="button" className="btn-secondary" onClick={() => setEditingId(null)}>Cancel</button>
            </span>
          ) : (
            <span className="receipt-amt">
              {r.amount_total ? fmtMoney(r.amount_total) : <span className="field-empty">not read</span>}
              {!ro && (
                <button type="button" className="link-btn" onClick={() => { setEditingId(r.id); setValue(r.amount_total ?? ""); setError(null); }}>
                  Edit
                </button>
              )}
            </span>
          )}
        </div>
      ))}
      {error && <span className="auth-error">{error}</span>}
    </div>
  );
}

const escCancel = (cancel: () => void) => (e: React.KeyboardEvent) => {
  if (e.key !== "Escape") return;
  e.preventDefault(); // cancels this edit only — the drawer and peek stay
  cancel();
};

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
  return v ? fmtDayShort(v) : null;
}

/** One card, six cells: the keys everything is filed and searched by, and where the shipment is. */
function KeyStrip({ s }: { s: Shipment }) {
  const ports = usePorts();
  const portName = s.port ? ports.find((p) => p.code === s.port)?.name ?? s.port : null;
  const age = /^\d+$/.test(s.days) ? `Day ${s.days}` : s.days || "—";
  // BL / BE / container numbers are never cut: those cells wrap to a second line instead
  const cells: { label: string; value: React.ReactNode; sub?: React.ReactNode; empty?: boolean; wide?: boolean; id?: boolean; client?: boolean }[] = [
    { label: "Job", value: s.job || "No number yet", empty: !s.job, id: true },
    // the client is the first key, so the header under the job holds only the tabs (client, 2026-10-08)
    { label: "Client", value: s.consignee || s.client || "—", sub: s.consignee && s.client ? s.client : null, empty: !s.consignee && !s.client, id: true, client: true },
    {
      label: s.hbl ? "BL (MBL / HBL)" : "BL",
      value: <CopyValue value={s.mbl} label="BL no" />,
      sub: s.hbl ? <CopyValue value={s.hbl} label="HBL no" /> : s.shipping_line || s.line_from_bl?.line || null,
      wide: true,
      id: true,
    },
    {
      label: "BE No",
      value: s.be_no ? <CopyValue value={s.be_no} label="BE No" /> : "Not filed yet",
      sub: s.be_no ? fmtDate(s.be_dt) ?? "date not entered" : null,
      empty: !s.be_no,
      id: true,
    },
    { label: "Port", value: portName ?? "—", sub: portName && portName !== s.port ? s.port : null, empty: !s.port },
    { label: "Containers", value: s.container || "—", sub: s.container_status, empty: !s.container, id: true },
    {
      label: "ETA → Inward",
      value: (
        <>
          <span className="key-date">{shortDate(s.eta) ?? "—"}</span> <span className="key-arrow">→</span> <span className="key-date">{s.inw ? shortDate(s.inw) : "—"}</span>
        </>
      ),
      sub: s.eta_is_deadline ? "ETA is a deadline" : null,
      id: true, // both dates always show in full: wraps under a narrow peek
    },
    { label: "Age", value: age, sub: /^\d+$/.test(s.days) ? "Since inward" : null, empty: !/^\d+$/.test(s.days) },
  ];
  return (
    <div className="key-strip" role="group" aria-label="Shipment keys">
      {cells.map((c) => (
        <div className={`key-cell${c.wide ? " key-cell-wide" : ""}${c.client ? " key-cell-client" : ""}`} key={c.label}>
          <span className="key-label">{c.label}</span>
          <span className={`key-value${c.empty ? " is-empty" : ""}${c.id ? " is-id" : ""}`}>{c.value}</span>
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
  const ro = useReadOnly(); // view-only login: no edit controls
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
    <div className="stepper-card">
      <ol className="stepper">
        {steps.map((x, i) => {
          const state = x.alert ? "alert" : x.done ? "done" : i === current ? "now" : "todo";
          return (
            <li key={x.label} className={`step step-${state}`} aria-current={i === current ? "step" : undefined}>
              <span className="step-dot" aria-hidden="true">
                <StepGlyph state={state} />
              </span>
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
          disabled={busy || ro}
          onClick={toggleExam}
          title={s.examination_at ? `Marked for examination: ${s.examination_at}` : "Normally read from the OOC copy — switch it here if needed"}
        >
          Under examination
        </button>
      </div>
    </div>
  );
}

/** The stepper's 14px glyphs (colour from the step's state; the word under it says the same). */
function StepGlyph({ state }: { state: "done" | "now" | "todo" | "alert" }) {
  if (state === "done")
    return (
      <svg width="14" height="14" viewBox="0 0 14 14">
        <circle cx="7" cy="7" r="7" fill="currentColor" />
        <path d="M4 7.2 6 9.2 10 5" fill="none" stroke="var(--color-surface)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    );
  if (state === "alert")
    return (
      <svg width="14" height="14" viewBox="0 0 14 14">
        <circle cx="7" cy="7" r="7" fill="currentColor" />
        <path d="M7 3.8v3.8" stroke="var(--color-surface)" strokeWidth="1.6" strokeLinecap="round" />
        <circle cx="7" cy="10" r=".9" fill="var(--color-surface)" />
      </svg>
    );
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <circle cx="7" cy="7" r="6" stroke={state === "now" ? "var(--color-border)" : "currentColor"} strokeWidth="1.5" />
      {state === "now" && <path d="M7 1a6 6 0 0 1 6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />}
    </svg>
  );
}

/**
 * Money: Duty / CFS / Line, one fixed-height row each — the amount, its state in words, one action.
 * CFS and Line open the charge drawer under it; nothing attached = Upload.
 */
function MoneyCard({
  s,
  docs,
  open,
  onOpen,
  onDuty,
  onUpload,
}: {
  s: Shipment;
  docs: ShipmentDocument[];
  open: MoneyGroup | null;
  onOpen: (g: MoneyGroup | null) => void;
  onDuty: () => void;
  onUpload: (t: DocumentType) => void;
}) {
  const ro = useReadOnly(); // view-only login: no edit controls
  const fd = s.final_duty;
  const dutyAmt = fd && fd.source !== "be" && (s.ooc || Number(fd.interest) > 0) ? fd.total : s.duty_amount;
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;
  type Row = { key: string; label: string; dot: "ok" | "warn" | "todo" | "muted"; value: string; words?: boolean; meta: string; action: React.ReactNode; badge?: React.ReactNode };

  const drawerBtn = (g: MoneyGroup) => (
    <button
      type="button"
      className="link-btn money-action"
      aria-expanded={open === g}
      aria-controls={open === g ? "charge-drawer" : undefined}
      data-charges={g}
      onClick={() => onOpen(open === g ? null : g)}
    >
      Charges <span className={`money-caret${open === g ? " is-open" : ""}`} aria-hidden="true"><svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"><path d="M2.5 3.75 5 6.25l2.5-2.5" /></svg></span>
    </button>
  );
  const uploadBtn = (g: MoneyGroup) => ro ? null : (
    <button type="button" className="link-btn money-action" onClick={() => onUpload(INVOICE_GROUPS[g].uploadType)}>
      Upload
    </button>
  );

  const cfs = groupDocs("cfs", docs).counted;
  const line = groupDocs("line", docs).counted;
  const by = (us: boolean) => (us ? "Paid by us" : "Paid by client");

  const cfsRow: Row = cfs.length
    ? {
        key: "cfs",
        label: "CFS",
        dot: s.cfs_inv_received ? "ok" : "warn",
        value: fmtMoney(s.cfs_amount_total) ?? "—",
        meta: `${by(s.cfs_paid_by_us)} · ${plural(cfs.length, "invoice")}`,
        action: drawerBtn("cfs"),
      }
    : {
        key: "cfs",
        label: "CFS",
        dot: s.cfs_inv_received ? "ok" : "todo",
        value: "Not attached",
        words: true,
        // ticked as received / paid, but the invoice itself isn't in the ERP yet
        meta: s.cfs_inv_received ? "CFS paid ✓ · invoice not attached" : by(s.cfs_paid_by_us),
        action: uploadBtn("cfs"),
      };

  let lineRow: Row;
  if (!line.length) {
    lineRow = { key: "line", label: "Shipping line", dot: s.line_paid ? "ok" : "todo", value: "Not attached", words: true, meta: by(s.line_paid_by_us), action: uploadBtn("line") };
  } else if (s.line_paid_by_us) {
    lineRow = { key: "line", label: "Shipping line", dot: s.line_paid ? "ok" : "warn", value: fmtMoney(s.line_amount_total) ?? "—", meta: `Paid by us · ${plural(line.length, "invoice")}`, action: drawerBtn("line") };
  } else if (s.line_excluded_by) {
    lineRow = { key: "line", label: "Shipping line", dot: "muted", value: "Left out", words: true, meta: `${plural(line.length, "invoice")} · ${s.line_excluded_by}`, action: drawerBtn("line") };
  } else if (!Number(s.line_amount_total)) {
    lineRow = { key: "line", label: "Shipping line", dot: "warn", value: "Pick charges", words: true, meta: `Cost inclusion · ${plural(line.length, "invoice")}`, action: drawerBtn("line") };
  } else {
    const all = line.flatMap((d) => chargesOf(d).map((_, i) => !(d.cost_excluded ?? []).includes(i)));
    const picked = all.length ? ` · ${all.filter(Boolean).length} of ${all.length} charges` : "";
    lineRow = { key: "line", label: "Shipping line", dot: "ok", value: fmtMoney(s.line_amount_total)!, meta: `Cost inclusion · ${plural(line.length, "invoice")}${picked}`, action: drawerBtn("line") };
  }

  const rows: Row[] = [
    {
      key: "duty",
      label: "Duty",
      dot: s.duty_paid ? "ok" : dutyAmt == null ? "todo" : "warn",
      value: dutyAmt == null ? "Not assessed" : fmtMoney(dutyAmt)!,
      words: dutyAmt == null,
      // the shipment's status sits beside the duty (client, 2026-10-08)
      badge: <span className={`status-pill status-${s.status}`}>{SHIPMENT_STATUS_LABELS[s.status]}</span>,
      meta: [
        s.duty_paid ? "Paid" : dutyAmt == null ? "Waiting for the assessed BE" : "Not paid yet",
        dutyAmt != null && dutyAmt === fd?.total && Number(fd?.interest) > 0 ? `incl. interest ${fmtMoney(fd!.interest)}` : "",
      ].filter(Boolean).join(" · "),
      action: (
        <button type="button" className="link-btn money-action" onClick={onDuty}>
          Details
        </button>
      ),
    },
    cfsRow,
    lineRow,
  ];
  const dotWord = { ok: "done", warn: "needs attention", todo: "pending", muted: "left out" } as const;

  return (
    <section className="money-card" aria-label="Money">
      {rows.map((r) => (
        <div className="money-row" key={r.key}>
          <span className="money-label">
            <span className={`sdot sdot-${r.dot}`} role="img" aria-label={dotWord[r.dot]} />
            {r.label}
          </span>
          <span className="money-value-line">
            <span className={`money-value${r.words ? " is-words" : ""}${r.dot === "muted" ? " is-muted" : ""}`}>{r.value}</span>
            {r.badge}
          </span>
          <span className="money-meta">{r.meta}</span>
          {r.action}
        </div>
      ))}
    </section>
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
  const readOnly = !!useAuth().user?.read_only;
  const raw = (s[field] as string | null | undefined) ?? "";
  const [editing, setEditing] = useState(false);
  const [v, setV] = useState(raw);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const start = () => {
    if (readOnly) return; // view-only login
    setV(raw);
    setErr(null);
    setEditing(true);
  };
  const [askKg, setAskKg] = useState<{ typed: string; mts: string } | null>(null);
  const save = async (value = v, sure = false) => {
    let next = value.trim() === "" ? null : value.trim();
    if (field === "gross_wt" && next && /^\d+(\.\d+)?$/.test(next)) next = `${next} MTS`; // like the tracker cell: weight is MTS
    if ((next ?? "") === (raw ?? "")) return setEditing(false);
    const mts = field === "gross_wt" && !sure ? kgLooking(next) : null;
    if (mts) return setAskKg({ typed: next!, mts }); // a plain number over 1000 is probably kg: ask first
    setAskKg(null);
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
    if (e.key === "Escape") {
      e.preventDefault(); // cancels the edit only — the peek stays
      setEditing(false);
    }
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
        ) : kind === "date" ? (
          <DateInput autoFocus ariaLabel={label} value={v} disabled={busy} onCommit={(iso) => save(iso)} onCancel={() => setEditing(false)} />
        ) : multiline ? (
          <>
            <textarea autoFocus rows={2} value={v} disabled={busy} onChange={(e) => setV(e.target.value)} onBlur={() => save()} onKeyDown={keys} aria-describedby={`${field}-saves`} />
            <span className="field-note edit-saves" id={`${field}-saves`}>Saves when you click away · ⌘/Ctrl+Enter</span>
          </>
        ) : (
          <input
            autoFocus
            type="text"
            onFocus={(e) => e.currentTarget.select()}
            value={v}
            disabled={busy}
            onChange={(e) => setV(e.target.value)}
            onBlur={() => save()}
            onKeyDown={keys}
          />
        )
      ) : (
        <button type="button" className={`field-value edit-value${shown == null ? " field-empty" : ""}${readOnly ? " is-readonly" : ""}`} onClick={start} aria-label={`${label}: ${shown ?? "empty"}${readOnly ? "" : " — edit"}`} aria-disabled={readOnly || undefined}>
          {shown ?? "—"}
        </button>
      )}
      {askKg && (
        <span className="kg-ask" role="alert">
          Looks like kg — save as {askKg.mts} MTS?{" "}
          <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => save(`${askKg.mts} MTS`, true)}>
            Save as MTS
          </button>{" "}
          <button type="button" className="link-btn" disabled={busy} onClick={() => save(askKg.typed, true)}>
            Keep as typed
          </button>
        </span>
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
  const ro = useReadOnly(); // view-only login: no edit controls
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
    ? fmtWhen(s.icegate.fetched_at)
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
        {!s.icegate?.final && !ro && (
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
