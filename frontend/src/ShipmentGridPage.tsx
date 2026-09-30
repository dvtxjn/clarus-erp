import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode, type RefObject } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { createPortal } from "react-dom";
import DateCellEditor from "./dateEditor";
import { AgGridReact } from "ag-grid-react";
import {
  AllCommunityModule,
  ModuleRegistry,
  themeQuartz,
  type CellClassParams,
  type CellEditingStoppedEvent,
  type CellKeyDownEvent,
  type CellValueChangedEvent,
  type ColDef,
  type ColumnState,
  type GridApi,
  type ICellRendererParams,
  type RowClassParams,
  type ValueFormatterParams,
} from "ag-grid-community";
import axios from "axios";
import {
  addTrackerColumn,
  billShipment,
  unbillShipment,
  createShipment,
  deleteTrackerColumn,
  listShipments,
  listTrackerColumns,
  removeBuiltinColumn,
  renameClient,
  restoreBuiltinColumn,
  ShipmentConflictError,
  getShipment,
  updateShipment,
} from "./api";
import { useAuth } from "./AuthContext";
import TrackerImportPanel from "./TrackerImportPanel";
import IcegateSettings from "./IcegateSettings";
import LinkFoldersPanel from "./LinkFoldersPanel";
import { driveConfigured } from "./googleDrive";
import { useSaveShipment } from "./useSaveShipment";
import { colorIndex, connectLive, PRESENCE_COLORS, sendPresence, TAB_ID } from "./live";
import ColumnsPanel, { type PanelColumn } from "./ColumnsPanel";
import { useConfirm } from "./ConfirmDialog";
import { ShipmentDetail } from "./ShipmentDetailPage";
import { formatPort, usePorts } from "./ports";
import { SHIPMENT_STATUS_LABELS, type Port, type Shipment, type ShipmentStatus, type TrackerColumn } from "./types";

ModuleRegistry.registerModules([AllCommunityModule]);

/*
 * Layout: one header-only grid (column headers + filters, sticky) on top,
 * then one grid per section (client, or clearance month) under a heading bar. All grids are column-aligned
 * (AG Grid `alignedGrids`), and the header grid's filters/sort are copied to
 * every client section. Done this way because AG Grid's own row grouping is
 * an Enterprise (paid) feature.
 */

const COLUMN_STATE_KEY = "tracker.columnState.v7"; // v7: widths auto-fit like Excel; hand-set ones kept  // + "." + tab
// Excel-style widths (client, 2026-09-30): every column fits its longest value (or its title); a width
// dragged by hand is kept. Auto-fit stops here — longer text shows "…", full value on hover / formula bar.
const MAX_AUTO_WIDTH = 360;
const TAB_KEY = "tracker.tab";
// Ongoing = no Cleared Date yet (live tracking). Cleared = has a Cleared Date;
// removing the date sends the shipment back to Ongoing.
const TABS = { ongoing: "Ongoing", cleared: "Cleared" } as const;
type Tab = keyof typeof TABS;

function loadTab(fromUrl: string | null): Tab {
  if (fromUrl === "ongoing" || fromUrl === "cleared") return fromUrl;
  try {
    return localStorage.getItem(TAB_KEY) === "cleared" ? "cleared" : "ongoing";
  } catch {
    return "ongoing";
  }
}

/** "2026-09" -> "September 2026" */
function monthLabel(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  return new Date(y, m - 1, 1).toLocaleString("en-GB", { month: "long", year: "numeric" });
}
const NO_CLIENT = "(No client)";
const VIEW_KEY = "tracker.view";
const AUTO_REFRESH_MS = 5 * 60 * 1000;
// Group by (client, 2026-09-30): client (one table each), port, stage, ETA week, or none
const VIEWS = { client: "Client", port: "Port", stage: "Stage", eta: "ETA week", all: "None" } as const;
type ViewMode = keyof typeof VIEWS;

function loadView(): ViewMode {
  try {
    const v = localStorage.getItem(VIEW_KEY);
    return v && v in VIEWS ? (v as ViewMode) : "client";
  } catch {
    return "client";
  }
}
/**
 * Column views (client, 2026-09-29): one click shows only the columns a job needs.
 * "Full grid" shows everything, like the sheet. Picking columns by hand makes it "Custom".
 */
const COLUMN_VIEWS = {
  clearance: {
    label: "Clearance",
    cols: ["job", "mbl", "eta", "inw", "consignee", "port", "be_no", "be_dt", "checklist", "icegate_status", "remarks", "cleared_date"],
  },
  movement: {
    label: "Movement",
    cols: ["job", "mbl", "eta", "inw", "consignee", "port", "igm", "container", "gross_wt", "container_status", "cfs", "poc",
      "delivery_status", "remark"],
  },
  billing: {
    label: "Billing",
    cols: ["job", "mbl", "consignee", "license", "be_no", "be_dt", "cleared_date", "checklist", "is_billed"],
  },
  grid: { label: "Full grid", cols: null },
} as const;
type ColumnView = keyof typeof COLUMN_VIEWS | "custom";
const COLVIEW_KEY = "tracker.columnView"; // + "." + tab

/** Quick filter chips on the ongoing tracker (client, 2026-09-30). */
const DAY = 86_400_000;
const daysFromToday = (iso: string | null | undefined): number | null =>
  iso ? Math.round((new Date(`${iso}T00:00:00`).getTime() - new Date(new Date().toDateString()).getTime()) / DAY) : null;
const QUICK_CHIPS: Record<string, { label: string; hint: string; test: (s: Shipment) => boolean }> = {
  deadline: {
    label: "Deadline ≤ 3 days",
    hint: "ETA marked 'd': the move-to-CFS deadline (ETA − 4 days) is within 3 days or has passed",
    test: (s) => {
      const d = daysFromToday(s.eta);
      return !!s.eta_is_deadline && d != null && d - 4 <= 3;
    },
  },
  week: {
    label: "ETA this week",
    hint: "ETA today or in the next 7 days",
    test: (s) => {
      const d = daysFromToday(s.eta);
      return d != null && d >= 0 && d <= 7;
    },
  },
  nobe: {
    label: "Arrived, BE not filed",
    hint: "ETA has passed and there's no BE number yet",
    test: (s) => {
      const d = daysFromToday(s.eta);
      return d != null && d <= 0 && !s.be_no;
    },
  },
  exceptions: {
    label: "Exceptions",
    hint: "Cleared Date entered but a check is still missing",
    test: (s) => !!s.cleared_date && !s.is_fully_cleared,
  },
};
const ETA_WEEKS = ["Arrived", "This week", "Next week", "Later", "No ETA"];
function etaWeek(eta: string | null): string {
  const d = daysFromToday(eta);
  if (d == null) return "No ETA";
  if (d < 0) return "Arrived";
  if (d <= 7) return "This week";
  if (d <= 14) return "Next week";
  return "Later";
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-08-27" -> "27 Aug" ("27 Aug 25" when it isn't this year) — compact dates, denser columns. */
function shortDate(v: string | null | undefined, withYear = false): string {
  if (!v) return "";
  const [y, m, d] = v.split("-");
  const year = !withYear && String(new Date().getFullYear()) === y ? "" : ` ${y.slice(2)}`;
  return `${d} ${MONTHS[Number(m) - 1]}${year}`;
}
/** INW is typed text ("19-Sep-2026", "19/09/2026", "2026-09-19"): shown the same short way. */
function shortInw(v: string | null | undefined): string {
  const t = (v ?? "").trim();
  let m = t.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) return shortDate(t);
  m = t.match(/^(\d{1,2})[-\s/.]([A-Za-z]{3})[A-Za-z]*[-\s/.](\d{2,4})$/);
  if (m) {
    const mon = MONTHS.findIndex((x) => x.toLowerCase() === m![2].toLowerCase());
    if (mon >= 0) return shortDate(`${m[3].length === 2 ? "20" + m[3] : m[3]}-${String(mon + 1).padStart(2, "0")}-${m[1].padStart(2, "0")}`);
  }
  m = t.match(/^(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})$/);
  if (m) return shortDate(`${m[3].length === 2 ? "20" + m[3] : m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}`);
  return t;
}
function formatDate(p: ValueFormatterParams): string {
  return shortDate(p.value as string | null);
}

/** Blank dates always sink to the bottom, whichever way the column is sorted. */
function dateComparator(a: string | null, b: string | null, _na: unknown, _nb: unknown, desc: boolean): number {
  if (!a && !b) return 0;
  if (!a) return desc ? -1 : 1;
  if (!b) return desc ? 1 : -1;
  return a < b ? -1 : a > b ? 1 : 0;
}

const text = (field: keyof Shipment, headerName: string, width = 130): ColDef<Shipment> => ({
  field,
  headerName,
  width,
  cellDataType: "text",
});
const dateCol = (field: keyof Shipment, headerName: string, width = 76): ColDef<Shipment> => ({
  field,
  headerName,
  width,
  cellDataType: "dateString",
  cellEditor: DateCellEditor, // Google-Sheets style calendar (client, 2026-09-29)
  cellEditorPopup: true,
  cellEditorParams: { format: "iso" },
  valueFormatter: formatDate,
  comparator: dateComparator,
});
const flag = (field: keyof Shipment, headerName: string, width = 72): ColDef<Shipment> => ({
  field,
  headerName,
  width,
  cellDataType: "boolean",
});

type FlagField =
  | "duty_paid"
  | "cfs_inv_received"
  | "line_paid"
  | "ooc"
  | "do"
  | "cfs_paid_by_us"
  | "tds_deducted"
  | "tds_on_cfs";
type FlagList = [FlagField, string, string][]; // field, chip text, tooltip
const FLAGS: FlagList = [
  ["duty_paid", "Duty", "Duty paid"],
  ["cfs_inv_received", "CFS Inv", "CFS invoice received"],
  ["line_paid", "Line", "Shipping line paid"],
  ["ooc", "OOC", "Out of charge"],
  ["do", "DO", "Delivery order"],
];
const CFS_TDS_FLAGS: FlagList = [
  ["cfs_paid_by_us", "CFS by us", "CFS paid by us"],
  ["tds_deducted", "TDS", "TDS cut on the shipment"],
  ["tds_on_cfs", "TDS on CFS", "We cut TDS on the CFS payment"],
];
const FLAG_LABELS = Object.fromEntries([...FLAGS, ...CFS_TDS_FLAGS].map(([f, , tip]) => [f, tip])) as Record<
  FlagField,
  string
>;

interface GridContext {
  toggleFlag: (s: Shipment, field: FlagField) => void;
  saveText: (s: Shipment, field: MiniField | "eta_is_deadline", value: string | boolean | null, label: string) => Promise<void>;
}

function ChecklistCell(p: ICellRendererParams<Shipment, unknown, GridContext> & { flags: FlagList }) {
  if (!p.data) return null;
  const s = p.data;
  return (
    <span className="checklist-cell">
      {p.flags.map(([f, label, tip]) => (
        <button
          key={f}
          type="button"
          className={s[f] ? "check-chip is-on" : "check-chip"}
          aria-pressed={!!s[f]}
          title={`${tip}: ${s[f] ? "Yes" : "No"} — click to change`}
          onClick={() => p.context.toggleFlag(s, f)}
        >
          {s[f] && <span aria-hidden="true">✓ </span>}
          {label}
        </button>
      ))}
    </span>
  );
}

/** " · Status → IGM Filed" when a save moved the status (status follows the evidence). */
/** A friendly reason for a failed save (e.g. two saves at the very same moment). */
function saveErrorText(err: unknown): string {
  const detail = axios.isAxiosError(err) ? err.response?.data?.detail : null;
  return typeof detail === "string" ? detail : "nothing changed.";
}

function statusNote(before: ShipmentStatus, after: ShipmentStatus): string {
  return before !== after ? ` · Status → ${SHIPMENT_STATUS_LABELS[after]}` : "";
}

/** Cleared Date entered but not every clearance check ticked — needs a person to look at it. */
function isException(s: Shipment | undefined): boolean {
  return !!s && !!s.cleared_date && !s.is_fully_cleared;
}

const CUSTOM_TYPES = { text: "text", date: "dateString", number: "number", boolean: "boolean" } as const;

function customColumn(c: TrackerColumn): ColDef<Shipment> {
  return {
    colId: c.key,
    headerName: c.label,
    width: c.data_type === "boolean" ? 100 : 140,
    cellDataType: CUSTOM_TYPES[c.data_type],
    valueGetter: (p) => p.data?.custom_fields?.[c.key] ?? null,
    valueSetter: (p) => {
      p.data.custom_fields = { ...(p.data.custom_fields ?? {}), [c.key]: p.newValue };
      return true;
    },
    ...(c.data_type === "date"
      ? { valueFormatter: formatDate, comparator: dateComparator, cellEditor: DateCellEditor, cellEditorPopup: true, cellEditorParams: { format: "iso" } }
      : {}),
  };
}

function withSavedState(defs: ColDef<Shipment>[], key: string): ColDef<Shipment>[] {
  let saved: ColumnState[];
  try {
    saved = JSON.parse(localStorage.getItem(key) ?? "[]");
  } catch {
    return defs;
  }
  if (!Array.isArray(saved) || saved.length === 0) return defs;
  const byId = new Map(saved.map((c, i) => [c.colId, { ...c, i }]));
  const idOf = (d: ColDef<Shipment>) => d.colId ?? (d.field as string | undefined) ?? "";
  const hasSort = saved.some((c) => c.sort);
  return defs
    .map((d, i) => {
      const c = byId.get(idOf(d));
      const order = c ? c.i : saved.length + i; // new columns go to the end, as applyOrder does
      if (!c) return { d, order };
      return {
        d: {
          ...d,
          ...(c.width ? { width: c.width } : {}),
          hide: !!c.hide,
          pinned: c.pinned ?? null,
          ...(hasSort ? { sort: c.sort ?? null, sortIndex: c.sortIndex ?? null } : {}),
        },
        order,
      };
    })
    .sort((a, b) => a.order - b.order)
    .map((x) => x.d);
}

function buildColumnDefs(ports: Port[], tab: Tab, trackerCols: TrackerColumn[], byClient: boolean): ColDef<Shipment>[] {
  const removed = new Set(trackerCols.filter((c) => !c.is_custom && c.is_removed).map((c) => c.key));
  const all: ColDef<Shipment>[] = [
    {
      headerName: "",
      colId: "open",
      width: 44, // a whole-cell button: easy to hit (client, 2026-09-30)
      pinned: "left",
      editable: false,
      sortable: false,
      filter: false,
      resizable: false,
      suppressMovable: true,
      cellRenderer: (p: ICellRendererParams<Shipment>) =>
        p.data ? (
          <Link
            to={`/shipments/${p.data.id}`}
            className="grid-open-link"
            aria-label={`Open job ${p.data.job}`}
            title="Open overview (Ctrl / ⌘-click: new tab)"
            onClick={(e) => {
              if (e.metaKey || e.ctrlKey || e.shiftKey) return; // new tab / full page as usual
              e.preventDefault();
              window.dispatchEvent(new CustomEvent("tracker:peek", { detail: p.data!.id }));
            }}
          >
            ↗
          </Link>
        ) : null,
    },
    { ...text("job", "Job", 56), pinned: "left" },
    {
      ...text("mbl", "MBL", 212),
      minWidth: 150, // the number + the HBL / FTA buttons
      pinned: "left",
      cellRenderer: (p: ICellRendererParams<Shipment, string, GridContext>) => (
        <span className="mbl-cell">
          <span className="mbl-text">
            {p.value}
            {p.data?.missing_from_sheet_at && (
              <span className="exception-badge" title="Not in the last tracker CSV import — check it (never deleted automatically)">
                {" "}not in sheet
              </span>
            )}
          </span>
          {p.data && (
            <>
              <MiniFieldButton row={p.data} field="hbl" label="HBL" ctx={p.context} />
              <MiniFieldButton row={p.data} field="fta_info" label="FTA" ctx={p.context} />
            </>
          )}
        </span>
      ),
    },
    { ...text("be_description", "Desc", 220), headerTooltip: "BE Description" },
    {
      ...dateCol("eta", "ETA", 118),
      minWidth: 112, // "d" + date + deadline
      sort: "asc",
      // redraw when the deadline switch changes too (the ETA value itself doesn't)
      equals: () => false,
      headerTooltip: "d = deadline: the shipment must be moved to the CFS 4 days before the ETA",
      cellRenderer: (p: ICellRendererParams<Shipment, string, GridContext>) =>
        p.data ? <EtaCell row={p.data} ctx={p.context} /> : null,
    },
    {
      // INW with the sheet's Day count as a badge (Day is calculated from INW)
      ...text("inw", "INW", 118),
      cellEditor: DateCellEditor, // INW is typed text ("08-Oct-2026"); the calendar writes it the same way
      cellEditorPopup: true,
      cellEditorParams: { format: "sheet" },
      headerTooltip: "Day = today − INW (+1 if INW is today or past)",
      cellRenderer: (p: ICellRendererParams<Shipment>) =>
        p.data ? (
          <span className="inw-cell">
            <span title={p.data.inw ?? undefined}>{shortInw(p.data.inw)}</span>
            <span className={`day-badge${p.data.days === "Pending" ? " day-pending" : ""}`}>
              {p.data.days === "Pending" ? "Pending" : p.data.days.replace(/ days?$/, "d")}
            </span>
          </span>
        ) : null,
    },
    { ...text("license", "Lic", 84), headerTooltip: "License" },
    // grouped by client, each section's bar already names it
    ...(byClient ? [] : [text("client", "Client", 124)]),
    text("consignee", "Consignee", 168),
    {
      // POD and Port were the same information; one column, shown with the port name
      field: "port",
      headerName: "POD",
      width: 156, // "INMUN1 · Nhava Sheva"
      cellEditor: "agSelectCellEditor",
      cellEditorParams: { values: ["", ...ports.map((p) => p.code)] },
      valueFormatter: (p) => formatPort(p.value, ports),
      filterValueGetter: (p) => formatPort(p.data?.port, ports),
    },
    { ...text("container_status", "Cntr St", 78), headerTooltip: "Container Status" },
    text("cfs", "CFS", 96),
    text("be_no", "BE No", 82),
    { ...dateCol("be_dt", "BE Dt", 80), valueFormatter: (p: ValueFormatterParams) => shortDate(p.value as string | null, true) },
    text("container", "Cntr", 58),
    {
      // weight is always MTS: the unit sits in the title, cells show the number
      ...text("gross_wt", "Wt (MTS)", 76),
      headerTooltip: "Gross Weight, MTS",
      cellClass: "num-cell",
      valueFormatter: (p) => (typeof p.value === "string" ? p.value.replace(/\s*MTS\s*$/i, "") : p.value),
      valueParser: (p) => {
        const v = String(p.newValue ?? "").trim();
        return /^\d+(\.\d+)?$/.test(v) ? `${v} MTS` : v || null;
      },
    },
    text("remark", "Remark", 76),
    text("poc", "POC", 100),
    text("remarks", "Remarks", 150),
    { ...dateCol("cleared_date", "Cleared"), headerTooltip: "Cleared Date" },
    {
      // Duty Paid? / CFS Inv? / Line Paid? / OOC? / DO? as one row of click-to-toggle chips
      colId: "checklist",
      headerName: "Checklist",
      width: 290, // starting width; auto-fit then sizes it to the chips actually shown
      editable: false,
      sortable: false,
      headerTooltip: "Click a chip to toggle it. Filter with e.g. OOC:N",
      valueGetter: (p) => (p.data ? FLAGS.map(([f, l]) => `${l}:${p.data![f] ? "Y" : "N"}`).join(" ") : ""),
      cellRenderer: ChecklistCell,
      cellRendererParams: { flags: FLAGS },
    },
    {
      // ICEGATE's own BE status, read every 30 min (08–22 IST) — e.g. "Assessed 26-Sep (system) · with SUP"
      colId: "icegate_status",
      headerName: "ICEGATE status",
      width: 200,
      editable: false,
      headerTooltip: "Bill of entry status on ICEGATE, read automatically every 30 minutes (8 am – 10 pm)",
      valueGetter: (p) => p.data?.icegate?.be_status?.label ?? "",
      tooltipValueGetter: (p) => {
        const b = p.data?.icegate?.be_status;
        return b ? `${b.label}\nRead ${new Date(b.fetched_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}` : "";
      },
    },
    text("igm", "IGM", 78),
    { ...text("delivery_status", "Deliv", 86), headerTooltip: "Delivery" },
    dateCol("mbl_date", "MBL Dt"),
    dateCol("hbl_date", "HBL Dt"),
    text("gw", "GW", 80),
    { ...text("total_pkg", "Pkgs", 64), headerTooltip: "Total Packages" },
    { ...text("pkg_code", "Pkg", 64), headerTooltip: "Package Code" },
    { ...text("line_no", "Line#", 64), headerTooltip: "Line No" },
    dateCol("igm_date", "IGM Dt"),
    text("voyage", "Voyage", 90),
    text("cont", "Cont", 80),
    { ...flag("is_billed", "Billed", 62), headerTooltip: "Tick when billed. Un-ticking (cancelling a bill) is admin-only." },
    ...trackerCols.filter((c) => c.is_custom).map(customColumn),
  ];
  const defs = all.filter((d) => !d.field || !removed.has(d.field as string));
  if (tab === "ongoing") {
    // Billed belongs to cleared shipments; Cleared date goes last (client, 2026-09-29)
    const rest = defs.filter((d) => d.field !== "is_billed" && d.field !== "cleared_date");
    const cleared = defs.find((d) => d.field === "cleared_date");
    return cleared ? [...rest, cleared] : rest;
  }
  // Cleared: sorted by clearance date, with Cleared Date + Billed? up front
  // for the "what did we clear / is it billed" review.
  const up = ["cleared_date", "is_billed"];
  const front = up.map((f) => defs.find((d) => d.field === f)).filter((d): d is ColDef<Shipment> => !!d);
  const rest = defs.filter((d) => !up.includes(d.field as string));
  const at = rest.findIndex((d) => d.field === "mbl") + 1;
  return [...rest.slice(0, at), ...front, ...rest.slice(at)].map((d) =>
    d.field === "eta" ? { ...d, sort: undefined } : d.field === "cleared_date" ? { ...d, sort: "asc" as const } : d,
  );
}

const gridTheme = themeQuartz.withParams({
  fontFamily: "inherit",
  headerFontSize: 11,
  headerFontWeight: 600,
  rowHeight: 26,
  headerHeight: 30,
  spacing: 4,
  cellHorizontalPadding: 6,
  fontSize: 12,
  // palette from :root in index.css (follows the chosen accent)
  accentColor: "var(--color-accent)",
  backgroundColor: "var(--color-surface)", // follows the theme (light / dim / dark)
  foregroundColor: "var(--color-text)",
  headerTextColor: "var(--color-text-muted)",
  chromeBackgroundColor: "var(--color-subtle)",
  borderColor: "var(--color-border)",
  headerBackgroundColor: "var(--color-subtle)",
  rowHoverColor: "var(--color-inv-sub)",
  selectedRowBackgroundColor: "var(--color-accent-soft)",
});

// --- live presence: which cell each other person/tab is on (Google-Sheets style) ---
type Presence = { key: string; name: string; sid: number | null; f: string | null; edit: boolean; color: number; at: number };
const presenceByCell = new Map<string, Presence>(); // "<shipment id>:<column id>" -> who is there
const cellKey = (id: number | undefined, col: string) => `${id}:${col}`;
const presenceAt = (p: CellClassParams<Shipment>) => presenceByCell.get(cellKey(p.data?.id, p.column.getColId()));
const presenceRules: Record<string, (p: CellClassParams<Shipment>) => boolean> = Object.fromEntries(
  PRESENCE_COLORS.map((_, i) => [`presence-c${i}`, (p: CellClassParams<Shipment>) => presenceAt(p)?.color === i]),
);
presenceRules["presence-edit"] = (p) => !!presenceAt(p)?.edit;

const defaultColDef: ColDef<Shipment> = {
  cellClassRules: presenceRules,
  editable: true,
  sortable: true,
  resizable: true,
  filter: true,
  floatingFilter: true,
  suppressFloatingFilterButton: true, // narrower filter boxes
  wrapHeaderText: true, // two-line headers, like Excel, so columns can be narrow
  autoHeaderHeight: true,
  // One line per row (client, 2026-09-29): long values are cut with "…" for now — the full
  // value shows on hover. Column widths get tuned later.
  wrapText: false,
  autoHeight: false,
  tooltipValueGetter: (p) => {
    const v = p.valueFormatted ?? p.value;
    return typeof v === "string" && v.length > 12 ? v : undefined;
  },
};
// Client/month sections have no visible header row
const sectionColDef: ColDef<Shipment> = { ...defaultColDef, wrapHeaderText: false, autoHeaderHeight: false, floatingFilter: false };

type GridRef = RefObject<AgGridReact<Shipment> | null>;

function sortState(api: GridApi): ColumnState[] {
  return api
    .getColumnState()
    .filter((c) => c.sort)
    .map(({ colId, sort, sortIndex }) => ({ colId, sort, sortIndex }));
}

export default function ShipmentGridPage() {
  const headerRef = useRef<AgGridReact<Shipment>>(null);
  const sectionRefs = useRef(new Map<string, GridRef>());
  const [shipments, setShipments] = useState<Shipment[] | null>(null);
  const [quickFilter, setQuickFilter] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [view, setView] = useState<ViewMode>(loadView);
  // filter chips above the table (client, 2026-09-30): ports (any of) + quick checks (all of)
  const [chips, setChips] = useState<Set<string>>(new Set());
  const [showColFilters, setShowColFilters] = useState(false);
  const toggleChip = (c: string) =>
    setChips((prev) => {
      const next = new Set(prev);
      if (next.has(c)) next.delete(c);
      else next.add(c);
      return next;
    });
  const [searchParams, setSearchParams] = useSearchParams();
  const [tab, setTab] = useState<Tab>(() => loadTab(searchParams.get("tab")));
  const [visibleCounts, setVisibleCounts] = useState<Record<string, number>>({});
  const [message, setMessage] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  // formula bar (client, 2026-09-30): the selected cell's full value, to copy — or type over, like Excel
  const [fx, setFx] = useState<{ client: string; rowId: number; colId: string } | null>(null);
  const statusFilter = (searchParams.get("status") as ShipmentStatus | null) ?? undefined;
  // side panel ("peek"): the shipment opens over the tracker; kept in the URL (?peek=58)
  const peekId = Number(searchParams.get("peek")) || null;
  // "full" = the same panel widened over the tracker: the tracker stays loaded behind it, so going back to
  // the half view (or closing) is instant — no reload of the whole page (client, 2026-09-30)
  const peekFull = searchParams.get("full") === "1";
  const setPeekFull = useCallback(
    (full: boolean) =>
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (full) next.set("full", "1");
          else next.delete("full");
          return next;
        },
        { replace: true },
      ),
    [setSearchParams],
  );
  const setPeek = useCallback(
    (id: number | null) =>
      setSearchParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id) next.set("peek", String(id));
          else {
            next.delete("peek");
            next.delete("full");
          }
          return next;
        },
        { replace: true },
      ),
    [setSearchParams],
  );
  useEffect(() => {
    const open = (e: Event) => setPeek((e as CustomEvent<number>).detail);
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.querySelector(".ag-cell-inline-editing, .confirm-dialog")) setPeek(null);
    };
    window.addEventListener("tracker:peek", open);
    window.addEventListener("keydown", esc);
    return () => {
      window.removeEventListener("tracker:peek", open);
      window.removeEventListener("keydown", esc);
    };
  }, [setPeek]);
  const ports = usePorts();
  const confirm = useConfirm();
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  const [trackerCols, setTrackerCols] = useState<TrackerColumn[]>([]);
  const [showColumns, setShowColumns] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [showFolders, setShowFolders] = useState(false);
  const [showIcegate, setShowIcegate] = useState(false);
  const [hiddenCols, setHiddenCols] = useState<Set<string>>(new Set());
  const [colView, setColView] = useState<ColumnView>(() => {
    try {
      return (localStorage.getItem(`${COLVIEW_KEY}.${tab}`) as ColumnView | null) ?? "custom";
    } catch {
      return "custom";
    }
  });
  const columnStateKey = `${COLUMN_STATE_KEY}.${tab}`;
  // Saved widths/order/pinning go into the definitions, so every grid first renders at its
  // final layout — applying them after load re-wrapped and re-measured every row (visible jump).
  const columnDefs = useMemo(
    () =>
      withSavedState(
        buildColumnDefs(ports, tab, trackerCols, tab === "ongoing" && view === "client"),
        `${COLUMN_STATE_KEY}.${tab}`,
      ),
    [ports, tab, trackerCols, view],
  );

  const refresh = useCallback(async () => {
    const data = await listShipments({
      include_archived: true, // billed (archived) shipments still belong in Cleared
      status: statusFilter,
    });
    // unchanged rows keep their old object (same version, same Day): the grid then redraws only real changes
    setShipments((prev) => {
      if (!prev) return data;
      const old = new Map(prev.map((x) => [x.id, x]));
      let same = prev.length === data.length;
      const next = data.map((x, i) => {
        const o = old.get(x.id);
        const keep = o && o.version === x.version && o.days === x.days && JSON.stringify(o) === JSON.stringify(x) ? o : x;
        if (keep !== prev[i]) same = false;
        return keep;
      });
      return same ? prev : next;
    });
    const cols = await listTrackerColumns();
    // same columns -> keep the same array: a new one rebuilds every column definition, and the grid snaps
    // widths back to their defaults for a moment (part of the "twitch", client 2026-09-30)
    setTrackerCols((prev) => (JSON.stringify(prev) === JSON.stringify(cols) ? prev : cols));
  }, [statusFilter]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Keep the tracker current (Day counts, other people's edits) without a
  // manual reload — but never while someone is mid-edit in a cell.
  useEffect(() => {
    const isEditing = () => sectionApis().some((api) => api.getEditingCells().length > 0);
    const tick = () => {
      if (document.visibilityState === "visible" && !isEditing()) refresh();
    };
    const id = setInterval(tick, AUTO_REFRESH_MS);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", tick);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh]);

  // --- live updates: other people's edits appear within about a second ---
  const [live, setLive] = useState(false);
  const [people, setPeople] = useState<Presence[]>([]);
  const peopleRef = useRef(new Map<string, Presence>()); // "<uid>:<tab>" -> where they are
  const shipmentsRef = useRef<Shipment[] | null>(null);
  useEffect(() => {
    shipmentsRef.current = shipments;
  }, [shipments]);
  const pendingIds = useRef(new Set<number>());
  const deferredIds = useRef(new Set<number>()); // changed while I'm typing in that row
  const flushTimer = useRef<number | undefined>(undefined);

  const nodesFor = (id: number) =>
    sectionApis()
      .map((api) => ({ api, node: api.getRowNode(String(id)) }))
      .filter((x): x is { api: GridApi<Shipment>; node: NonNullable<typeof x.node> } => !!x.node);
  const isEditingRow = (id: number) =>
    sectionApis().some((api) =>
      api.getEditingCells().some((c) => api.getDisplayedRowAtIndex(c.rowIndex)?.data?.id === id),
    );

  const applyRemote = useCallback(async (ids: number[]) => {
    for (const id of ids) {
      if (isEditingRow(id)) {
        deferredIds.current.add(id); // applied when the edit ends; never yank a cell mid-typing
        continue;
      }
      let row: Shipment;
      try {
        row = await getShipment(id);
      } catch (err) {
        const status = axios.isAxiosError(err) ? err.response?.status : null;
        if (status === 404 || status === 403) setShipments((prev) => prev?.filter((s) => s.id !== id) ?? prev);
        continue;
      }
      const old = shipmentsRef.current?.find((s) => s.id === id);
      if (old && old.version >= row.version) continue;
      const changed = old
        ? (Object.keys(row) as (keyof Shipment)[]).filter((k) => JSON.stringify(row[k]) !== JSON.stringify(old[k]))
        : [];
      const changedCustom = old
        ? Object.keys({ ...row.custom_fields, ...old.custom_fields }).filter(
            (k) => row.custom_fields?.[k] !== old.custom_fields?.[k],
          )
        : [];
      setShipments((prev) => {
        if (!prev) return prev;
        const i = prev.findIndex((s) => s.id === id);
        if (i < 0) return [...prev, row];
        if (prev[i].version >= row.version) return prev;
        const next = [...prev];
        next[i] = row;
        return next;
      });
      window.setTimeout(() => {
        for (const { api, node } of nodesFor(id)) {
          const cols = [...changed, ...changedCustom].filter((k) => api.getColumn(String(k)));
          if (cols.length) api.flashCells({ rowNodes: [node], columns: cols as string[] });
        }
      }, 60);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshPresenceCells = (keys: Iterable<string>) => {
    for (const k of keys) {
      const [id, col] = [Number(k.slice(0, k.indexOf(":"))), k.slice(k.indexOf(":") + 1)];
      for (const { api, node } of nodesFor(id)) api.refreshCells({ rowNodes: [node], columns: [col], force: true });
    }
  };
  const rebuildPresence = () => {
    const before = [...presenceByCell.keys()];
    presenceByCell.clear();
    for (const p of peopleRef.current.values()) if (p.sid != null && p.f) presenceByCell.set(cellKey(p.sid, p.f), p);
    refreshPresenceCells(new Set([...before, ...presenceByCell.keys()]));
    setPeople([...peopleRef.current.values()]);
  };

  useEffect(() => {
    const stop = connectLive((ev) => {
      if (ev.t === "resync") {
        refresh();
      } else if (ev.t === "s") {
        if (ev.del) {
          setShipments((prev) => prev?.filter((s) => s.id !== ev.id) ?? prev);
          return;
        }
        const local = shipmentsRef.current?.find((s) => s.id === ev.id);
        if (local && local.version >= ev.v) return; // my own save, already shown
        pendingIds.current.add(ev.id);
        window.clearTimeout(flushTimer.current);
        flushTimer.current = window.setTimeout(() => {
          const ids = [...pendingIds.current];
          pendingIds.current.clear();
          applyRemote(ids);
        }, 120); // batch a burst of events (e.g. a CSV import) into one pass
      } else if (ev.t === "p") {
        if (ev.tab === TAB_ID) return;
        const key = `${ev.uid}:${ev.tab ?? ""}`;
        if (ev.sid == null) peopleRef.current.delete(key);
        else
          peopleRef.current.set(key, {
            key, name: ev.name, sid: ev.sid, f: ev.f, edit: ev.edit, color: colorIndex(key), at: Date.now(),
          });
        rebuildPresence();
      }
    }, setLive);
    // people who stop sending (closed laptop, lost network) fade out
    const prune = window.setInterval(() => {
      let gone = false;
      for (const [k, p] of peopleRef.current) {
        if (Date.now() - p.at > 25000) {
          peopleRef.current.delete(k);
          gone = true;
        }
      }
      if (gone) rebuildPresence();
    }, 5000);
    return () => {
      stop();
      window.clearInterval(prune);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh, applyRemote]);

  // --- my presence: tell others which cell I'm on (on every move + every 10 s) ---
  const myCell = useRef<{ sid: number; f: string; edit: boolean } | null>(null);
  const announce = useCallback((sid: number, f: string, edit: boolean) => {
    const c = myCell.current;
    if (c && c.sid === sid && c.f === f && c.edit === edit) return;
    myCell.current = { sid, f, edit };
    sendPresence(sid, f, edit);
  }, []);
  useEffect(() => {
    const beat = window.setInterval(() => {
      const c = myCell.current;
      if (c && document.visibilityState === "visible") sendPresence(c.sid, c.f, c.edit);
    }, 10000);
    const onVisibility = () => {
      const c = myCell.current;
      if (document.visibilityState === "hidden") sendPresence(null, null);
      else if (c) sendPresence(c.sid, c.f, c.edit);
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.clearInterval(beat);
      document.removeEventListener("visibilitychange", onVisibility);
      sendPresence(null, null);
    };
  }, []);
  const onEditingStopped = useCallback((e: CellEditingStoppedEvent<Shipment>) => {
    if (e.data) announce(e.data.id, e.column.getColId(), false);
    if (deferredIds.current.size) {
      const ids = [...deferredIds.current];
      deferredIds.current.clear();
      window.setTimeout(() => applyRemote(ids), 300); // after my own save lands
    }
  }, [announce, applyRemote]);

  useEffect(() => {
    if (!message) return;
    const t = setTimeout(() => setMessage(null), 4000);
    return () => clearTimeout(t);
  }, [message]);

  function changeTab(t: Tab) {
    setTab(t);
    setVisibleCounts({});
    try {
      localStorage.setItem(TAB_KEY, t);
    } catch {
      /* ignore */
    }
  }

  // Ongoing vs Cleared is decided only by the Cleared Date (billing doesn't hide a shipment)
  // Cleared = Cleared Date + all five checks. A Cleared Date with anything
  // missing is an exception and stays here in Ongoing (highlighted) for manual action.
  const allOngoing = useMemo(() => (shipments ?? []).filter((s) => !s.is_fully_cleared), [shipments]);
  const ongoing = useMemo(() => {
    const ports = [...chips].filter((c) => c.startsWith("port:")).map((c) => c.slice(5));
    const quick = [...chips].filter((c) => !c.startsWith("port:"));
    return allOngoing.filter((s) => {
      if (ports.length && !ports.includes(s.port ?? "")) return false;
      return quick.every((q) => QUICK_CHIPS[q]?.test(s));
    });
  }, [allOngoing, chips]);
  const cleared = useMemo(() => (shipments ?? []).filter((s) => s.is_fully_cleared), [shipments]);

  function changeView(v: ViewMode) {
    setView(v);
    setVisibleCounts({});
    try {
      localStorage.setItem(VIEW_KEY, v);
    } catch {
      /* ignore */
    }
  }

  /**
   * Ongoing — "By client": one table per client, A–Z; "All shipments": one table.
   * Cleared — one table per clearance month, oldest month first (not by client).
   */
  const groups = useMemo<[string, Shipment[]][]>(() => {
    if (tab === "cleared") {
      const byMonth = new Map<string, Shipment[]>();
      for (const s of cleared) {
        const ym = s.cleared_date!.slice(0, 7);
        if (!byMonth.has(ym)) byMonth.set(ym, []);
        byMonth.get(ym)!.push(s);
      }
      return [...byMonth.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([ym, rows]) => [monthLabel(ym), rows]);
    }
    if (view === "all") return [["All shipments", ongoing]];
    const keyOf = (s: Shipment): string => {
      if (view === "port") return s.port ? formatPort(s.port, ports) || s.port : "No port";
      if (view === "stage") return SHIPMENT_STATUS_LABELS[s.status];
      if (view === "eta") return etaWeek(s.eta);
      return s.client?.trim() || NO_CLIENT;
    };
    const by = new Map<string, Shipment[]>();
    for (const s of ongoing) {
      const key = keyOf(s);
      if (!by.has(key)) by.set(key, []);
      by.get(key)!.push(s);
    }
    const order = (k: string): number =>
      view === "stage"
        ? Object.values(SHIPMENT_STATUS_LABELS).indexOf(k)
        : view === "eta"
          ? ETA_WEEKS.indexOf(k)
          : 0;
    return [...by.entries()].sort(([a], [b]) =>
      order(a) - order(b) ||
      (a === NO_CLIENT || a === "No port" ? 1 : b === NO_CLIENT || b === "No port" ? -1 : a.localeCompare(b, undefined, { sensitivity: "base" })),
    );
  }, [tab, view, ongoing, cleared, ports]);

  useEffect(() => {
    const live = new Set(groups.map(([k]) => k));
    for (const k of [...sectionRefs.current.keys()]) if (!live.has(k)) sectionRefs.current.delete(k);
  }, [groups]);

  function refFor(client: string): GridRef {
    let ref = sectionRefs.current.get(client);
    if (!ref) {
      ref = { current: null };
      sectionRefs.current.set(client, ref);
    }
    return ref;
  }

  const sectionApis = () =>
    [...sectionRefs.current.values()].map((r) => r.current?.api).filter((a): a is GridApi<Shipment> => !!a);


  // --- header grid drives filters + sort for every client section ---
  function syncSection(api: GridApi<Shipment>) {
    const header = headerRef.current?.api;
    if (!header) return;
    api.applyColumnState({
      state: header.getColumnState().map(({ colId, hide, width, pinned }) => ({ colId, hide, width, pinned })),
    });
    api.setFilterModel(header.getFilterModel());
    api.applyColumnState({ state: sortState(header), defaultState: { sort: null } });
  }
  const onHeaderFilterChanged = () => sectionApis().forEach(syncSection);
  const onHeaderSortChanged = () => {
    sectionApis().forEach(syncSection);
    saveColumnState();
  };

  const fitting = useRef(false);
  const edgeDoubleClick = useRef<string | null>(null); // column whose resize edge was just double-clicked
  // columns whose width someone dragged by hand (per tab) — auto-fit leaves them alone
  const manualKey = `${columnStateKey}.manual`;
  const manualWidths = useRef<Set<string>>(new Set());
  useEffect(() => {
    try {
      manualWidths.current = new Set(JSON.parse(localStorage.getItem(manualKey) ?? "[]"));
    } catch {
      manualWidths.current = new Set();
    }
  }, [manualKey]);
  // re-fit when the data or the view changes (like Excel keeping columns readable as rows arrive)
  // ONE fit, once every client section has finished drawing its rows: fitting earlier measured half-drawn
  // sections, narrowed columns, and a second pass widened them again — the "twitch" (client, 2026-09-30).
  const fitTimer = useRef<number | undefined>(undefined);
  const fitRun = useRef(0);
  const scheduleFit = (ms = 120) => {
    window.clearTimeout(fitTimer.current);
    const run = ++fitRun.current;
    fitTimer.current = window.setTimeout(() => {
      const started = performance.now();
      let lastSig = "";
      let stable = 0;
      const check = () => {
        if (run !== fitRun.current) return; // a newer change took over
        const apis = sectionApis();
        const sig = apis.map((a) => `${a.getDisplayedRowCount()}/${a.getRenderedNodes().length}`).join(",");
        const drawn = apis.length > 0 && apis.every((a) => a.getRenderedNodes().length >= a.getDisplayedRowCount());
        stable = sig === lastSig ? stable + 1 : 0;
        lastSig = sig;
        if ((drawn && stable >= 3) || performance.now() - started > 3000) autoFitAll();
        else requestAnimationFrame(check);
      };
      requestAnimationFrame(check);
    }, ms);
  };
  useEffect(() => {
    if (!shipments) return;
    scheduleFit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shipments, tab, view, colView]);
  const saveManual = () => {
    try {
      localStorage.setItem(manualKey, JSON.stringify([...manualWidths.current]));
    } catch {
      /* storage unavailable */
    }
  };

  /** Excel-style autofit: each column as wide as its title or its longest value in any client section
   *  (capped at MAX_AUTO_WIDTH), measured on what's actually drawn (chips, badges included). */
  function fitToContent(ids: string[]) {
    const header = headerRef.current?.api;
    if (!header || !ids.length || fitting.current) return;
    fitting.current = true; // our own autosize calls fire resize events too
    const need = new Map<string, number>();
    header.autoSizeColumns(ids, false); // the header grid has no rows: this is the title's width
    for (const c of header.getColumnState()) if (ids.includes(c.colId)) need.set(c.colId, c.width ?? 0);
    const apis = sectionApis();
    for (const api of apis) {
      api.autoSizeColumns(ids, true);
      for (const c of api.getColumnState()) if (ids.includes(c.colId)) need.set(c.colId, Math.max(need.get(c.colId) ?? 0, c.width ?? 0));
    }
    const current = new Map(header.getColumnState().map((c) => [c.colId, c.width ?? 0]));
    // the header grid was just autosized to titles only: compare against what the sections show
    const shown = new Map((apis[0]?.getColumnState() ?? []).map((c) => [c.colId, c.width ?? 0]));
    const state = ids
      .map((colId) => ({ colId, width: Math.min(MAX_AUTO_WIDTH, Math.max(40, need.get(colId) ?? 60)) }))
      // ignore 1–3 px differences (font rounding): no visible nudge for nothing
      .filter((c) => Math.abs(c.width - (shown.get(c.colId) ?? current.get(c.colId) ?? 0)) > 3 || !shown.size);
    const keep = ids.filter((id) => !state.some((c) => c.colId === id)).map((colId) => ({ colId, width: shown.get(colId) ?? current.get(colId) }));
    header.applyColumnState({ state: [...state, ...keep] });
    apis.forEach((api) => api.applyColumnState({ state }));
    fitting.current = false;
    saveColumnState();
  }

  /** Autofit every shown column that nobody has sized by hand. */
  function autoFitAll() {
    const header = headerRef.current?.api;
    if (!header) return;
    const ids = header
      .getColumnState()
      .filter((c) => !c.hide && !manualWidths.current.has(c.colId))
      .map((c) => c.colId);
    fitToContent(ids);
  }

  function saveColumnState() {
    const state = headerRef.current?.api.getColumnState();
    try {
      if (state) localStorage.setItem(columnStateKey, JSON.stringify(state));
    } catch {
      /* storage unavailable — layout just won't persist */
    }
  }

  function onHeaderReady() {
    try {
      const saved = localStorage.getItem(columnStateKey);
      if (saved) headerRef.current?.api.applyColumnState({ state: JSON.parse(saved), applyOrder: true });
    } catch {
      /* ignore bad saved state */
    }
    sectionApis().forEach(syncSection);
    syncHidden();
  }

  // each tab (ongoing / cleared) remembers its own column view
  useEffect(() => {
    try {
      setColView((localStorage.getItem(`${COLVIEW_KEY}.${tab}`) as ColumnView | null) ?? "custom");
    } catch {
      setColView("custom");
    }
  }, [tab]);

  function resetLayout() {
    rememberColView("grid");
    manualWidths.current = new Set(); // back to auto-fit everywhere
    try {
      localStorage.removeItem(columnStateKey);
      localStorage.removeItem(manualKey);
    } catch {
      /* ignore */
    }
    const header = headerRef.current?.api;
    header?.resetColumnState();
    header?.setFilterModel(null);
    sectionApis().forEach((api) => api.resetColumnState());
    setQuickFilter("");
    syncHidden();
    scheduleFit(50);
  }

  // --- undo / redo (Ctrl/⌘+Z, Ctrl/⌘+Shift+Z or Ctrl+Y) ---
  // Our own stack of saved changes: AG Grid's built-in undo is lost whenever rows
  // refresh after a save, and doesn't cover the checklist chips. Undo re-saves the
  // old value (audit-logged like any edit).
  type Change = { id: number; field: string; customKey: string | null; oldValue: unknown; newValue: unknown; label: string };
  const saveShipment = useSaveShipment();
  const undoStack = useRef<Change[]>([]);
  const redoStack = useRef<Change[]>([]);
  const record = useCallback((c: Change) => {
    undoStack.current = [...undoStack.current.slice(-49), c];
    redoStack.current = [];
  }, []);
  const applyChange = useCallback(async (c: Change, direction: "undo" | "redo") => {
    const value = direction === "undo" ? c.oldValue : c.newValue;
    // Only undo if the cell still holds what this change put there (never clobber a colleague)
    const expected = direction === "undo" ? c.newValue : c.oldValue;
    const wrap = (v: unknown) => (c.customKey ? { custom_fields: { [c.customKey]: v } } : { [c.field]: v });
    try {
      const saved = await updateShipment(c.id, wrap(value) as Partial<Shipment>, wrap(expected));
      setShipments((prev) => prev?.map((x) => (x.id === c.id ? saved : x)) ?? prev);
      (direction === "undo" ? redoStack : undoStack).current.push(c);
      setMessage({ kind: "ok", text: `${direction === "undo" ? "Undone" : "Redone"}: ${c.label}` });
    } catch (err) {
      if (err instanceof ShipmentConflictError) {
        // dropped from the stack: the cell has moved on
        const fresh = err.shipment;
        setShipments((prev) => prev?.map((x) => (x.id === c.id ? fresh : x)) ?? prev);
        const who = err.conflicts[0]?.changed_by ?? "someone else";
        setMessage({ kind: "error", text: `${c.label} was changed by ${who} since — not ${direction === "undo" ? "undone" : "redone"}.` });
        return;
      }
      (direction === "undo" ? undoStack : redoStack).current.push(c); // put it back
      setMessage({ kind: "error", text: `Couldn't ${direction} ${c.label}.` });
    }
  }, []);
  useEffect(() => {
    function onKey(ev: KeyboardEvent) {
      if (!(ev.ctrlKey || ev.metaKey)) return;
      const key = ev.key.toLowerCase();
      const redo = (key === "z" && ev.shiftKey) || key === "y";
      if (key !== "z" && !redo) return;
      // typing in a box (cell editor, search, filters): leave the browser's own text undo alone
      const t = ev.target as HTMLElement | null;
      if (t && (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName))) return;
      const c = (redo ? redoStack : undoStack).current.pop();
      if (!c) {
        setMessage({ kind: "ok", text: redo ? "Nothing to redo" : "Nothing to undo" });
        return;
      }
      ev.preventDefault();
      applyChange(c, redo ? "redo" : "undo");
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [applyChange]);

  // --- editing: every cell saves on its own ---
  const onCellValueChanged = useCallback(async (e: CellValueChangedEvent<Shipment>) => {
    const customKey = e.colDef.field ? null : e.colDef.colId;
    const field = (e.colDef.field ?? customKey) as keyof Shipment | undefined;
    if (!field || !e.data || e.oldValue === e.newValue) return;
    const id = e.data.id;
    const revert = () => {
      const restored = customKey
        ? { ...e.data!, custom_fields: { ...e.data!.custom_fields, [customKey]: e.oldValue } }
        : { ...e.data!, [field]: e.oldValue };
      e.node.setData(restored);
      setShipments((prev) => prev?.map((s) => (s.id === id ? restored : s)) ?? prev);
    };
    if (field === "is_billed") {
      try {
        const saved = e.newValue ? await billShipment(id) : await unbillShipment(id);
        setShipments((prev) => prev?.map((s) => (s.id === id ? saved : s)) ?? prev);
        setMessage({ kind: "ok", text: e.newValue ? "Marked as billed" : "Bill cancelled — status restored" });
      } catch (err) {
        revert();
        const status = axios.isAxiosError(err) ? err.response?.status : null;
        setMessage({
          kind: "error",
          text:
            status === 403
              ? e.newValue
                ? "You don't have billing access."
                : "Only an admin can cancel a bill."
              : "Couldn't update Billed.",
        });
      }
      return;
    }
    let value = e.newValue;
    if (typeof value === "string") value = value.trim() === "" ? null : value.trim();
    if (value === undefined) value = null;
    if (field === "mbl" && !value) {
      revert();
      setMessage({ kind: "error", text: "MBL can't be empty." });
      return;
    }
    if (field === "job" && value === null) value = "";
    try {
      const payload = customKey ? { custom_fields: { [customKey]: value } } : { [field]: value };
      // what the user saw before typing (AG Grid has already put the new value in e.data)
      const seen = (customKey
        ? { ...e.data, custom_fields: { ...e.data.custom_fields, [customKey]: e.oldValue ?? null } }
        : { ...e.data, [field]: e.oldValue ?? null }) as Shipment;
      const { shipment: saved, kept } = await saveShipment(seen, payload as Partial<Shipment>, e.colDef.headerName);
      // Replace in state (not just the grid row) so a changed client moves the
      // row into the right section and computed fields (Day) refresh.
      setShipments((prev) => prev?.map((s) => (s.id === id ? saved : s)) ?? prev);
      e.node.setData(saved);
      if (kept === "theirs") {
        setMessage({ kind: "ok", text: `Kept the other change to ${e.colDef.headerName}` });
        return;
      }
      let old = e.oldValue ?? null;
      if (typeof old === "string" && old.trim() === "") old = null;
      if (field === "job" && old === null) old = "";
      record({ id, field: String(field), customKey: customKey ?? null, oldValue: old, newValue: value, label: `${e.colDef.headerName ?? field}` });
      setMessage({ kind: "ok", text: `Saved ${e.colDef.headerName}${statusNote(e.data.status, saved.status)}` });
    } catch (err) {
      revert();
      setMessage({ kind: "error", text: `Couldn't save ${e.colDef.headerName} — ${saveErrorText(err)}` });
    }
  }, [record, saveShipment]);

  // Chip toggles in the Checklist column save like any other cell edit.
  const toggleFlag = useCallback(async (row: Shipment, field: FlagField) => {
    try {
      const { shipment: saved, kept } = await saveShipment(row, { [field]: !row[field] } as Partial<Shipment>, FLAG_LABELS[field]);
      setShipments((prev) => prev?.map((x) => (x.id === row.id ? saved : x)) ?? prev);
      if (kept === "theirs") return;
      record({ id: row.id, field, customKey: null, oldValue: !!row[field], newValue: !row[field], label: FLAG_LABELS[field] });
      setMessage({ kind: "ok", text: `Saved ${FLAG_LABELS[field]}${statusNote(row.status, saved.status)}` });
    } catch (err) {
      setMessage({ kind: "error", text: `Couldn't save — ${saveErrorText(err)}` });
    }
  }, [record, saveShipment]);
  // HBL / FTA from the small buttons on the MBL: saved like any other cell edit (undo too)
  const saveText = useCallback(async (row: Shipment, field: MiniField | "eta_is_deadline", value: string | boolean | null, label: string) => {
    try {
      const { shipment: saved, kept } = await saveShipment(row, { [field]: value } as Partial<Shipment>, label);
      setShipments((prev) => prev?.map((x) => (x.id === row.id ? saved : x)) ?? prev);
      if (kept === "theirs") return;
      record({ id: row.id, field, customKey: null, oldValue: row[field], newValue: value, label });
      setMessage({ kind: "ok", text: `Saved ${label}` });
    } catch (err) {
      setMessage({ kind: "error", text: `Couldn't save ${label} — ${saveErrorText(err)}` });
      throw err;
    }
  }, [record, saveShipment]);
  const gridContext = useMemo<GridContext>(() => ({ toggleFlag, saveText }), [toggleFlag, saveText]);

  // Ctrl/⌘+C copies the focused cell (as shown), unless you've selected text yourself.
  const copyCell = useCallback((e: CellKeyDownEvent<Shipment>) => {
    const ev = e.event as KeyboardEvent | null;
    if (!ev || !(ev.ctrlKey || ev.metaKey) || ev.key.toLowerCase() !== "c") return;
    if (e.api.getEditingCells().length > 0 || window.getSelection()?.toString()) return;
    const value = e.node ? e.api.getCellValue({ rowNode: e.node, colKey: e.column, useFormatter: true }) : null;
    const textValue = value == null ? "" : String(value);
    const ok = () => setMessage({ kind: "ok", text: textValue ? `Copied: ${textValue}` : "Copied (empty cell)" });
    const fallback = () => {
      // Older/stricter browsers: copy through a hidden textarea
      const ta = document.createElement("textarea");
      ta.value = textValue;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const done = document.execCommand("copy");
      ta.remove();
      if (e.rowIndex != null) e.api.setFocusedCell(e.rowIndex, e.column); // give focus back to the cell
      if (done) ok();
      else setMessage({ kind: "error", text: "Couldn't copy — select the text instead." });
    };
    if (navigator.clipboard) navigator.clipboard.writeText(textValue).then(ok, fallback);
    else fallback();
  }, []);

  async function handleRenameClient(oldName: string, newName: string): Promise<boolean> {
    const target = newName.trim();
    if (!target || target === oldName) return true;
    const merging = groups.some(([c]) => c !== oldName && c.toLowerCase() === target.toLowerCase());
    if (
      merging &&
      !(await confirm({
        title: "Merge clients?",
        message: `"${target}" already exists. Merge "${oldName}" into it? All of ${oldName}'s shipments move under ${target}.`,
        confirmLabel: "Merge",
      }))
    )
      return false;
    try {
      const { updated } = await renameClient(oldName === NO_CLIENT ? "" : oldName, target);
      setMessage({ kind: "ok", text: `Renamed client on ${updated} shipment${updated === 1 ? "" : "s"}` });
      await refresh();
      return true;
    } catch {
      setMessage({ kind: "error", text: "Couldn't rename client." });
      return false;
    }
  }

  // --- columns panel ---
  const syncHidden = () => {
    const header = headerRef.current?.api;
    if (header) setHiddenCols(new Set(header.getColumnState().filter((c) => c.hide).map((c) => c.colId)));
  };
  const panelColumns: PanelColumn[] = columnDefs
    .filter((d) => d.colId !== "open")
    .map((d) => {
      const colId = (d.colId ?? d.field) as string;
      return {
        colId,
        label: d.headerName ?? colId,
        visible: !hiddenCols.has(colId),
        isCustom: trackerCols.some((c) => c.is_custom && c.key === colId),
        // mbl is required; checklist is a combined view of five fields
        removable: colId !== "mbl" && colId !== "checklist",
      };
    });
  function rememberColView(v: ColumnView) {
    setColView(v);
    try {
      localStorage.setItem(`${COLVIEW_KEY}.${tab}`, v);
    } catch {
      /* private window */
    }
  }
  function applyColumnView(v: keyof typeof COLUMN_VIEWS) {
    const all = panelColumns.map((c) => c.colId);
    const keep: readonly string[] = COLUMN_VIEWS[v].cols ?? all;
    const show = all.filter((id) => keep.includes(id));
    const hide = all.filter((id) => !keep.includes(id));
    for (const api of [headerRef.current?.api, ...sectionApis()]) {
      if (!api) continue;
      api.setColumnsVisible(hide, false);
      api.setColumnsVisible(show, true);
    }
    syncHidden();
    saveColumnState();
    rememberColView(v);
  }
  function toggleColumn(colId: string, visible: boolean) {
    rememberColView("custom");
    headerRef.current?.api.setColumnsVisible([colId], visible);
    sectionApis().forEach((api) => api.setColumnsVisible([colId], visible));
    syncHidden();
    saveColumnState();
  }
  function showAllColumns() {
    rememberColView("grid");
    const ids = panelColumns.map((c) => c.colId);
    headerRef.current?.api.setColumnsVisible(ids, true);
    sectionApis().forEach((api) => api.setColumnsVisible(ids, true));
    syncHidden();
    saveColumnState();
  }
  async function addColumn(label: string, type: TrackerColumn["data_type"]) {
    try {
      await addTrackerColumn(label, type);
      setTrackerCols(await listTrackerColumns());
      setMessage({ kind: "ok", text: `Added column "${label}"` });
    } catch {
      setMessage({ kind: "error", text: "Couldn't add column." });
    }
  }
  async function deleteColumn(c: PanelColumn) {
    const question = c.isCustom
      ? `Delete the "${c.label}" column and everything typed in it? This can't be undone.`
      : `Remove "${c.label}" from the tracker for everyone? The data is kept and you can restore it later.`;
    if (!(await confirm({ title: c.isCustom ? "Delete column?" : "Remove column?", message: question, confirmLabel: c.isCustom ? "Delete" : "Remove", danger: true })))
      return;
    try {
      if (c.isCustom) await deleteTrackerColumn(c.colId);
      else await removeBuiltinColumn(c.colId, c.label);
      setTrackerCols(await listTrackerColumns());
      setMessage({ kind: "ok", text: `${c.isCustom ? "Deleted" : "Removed"} "${c.label}"` });
    } catch {
      setMessage({ kind: "error", text: `Couldn't remove "${c.label}".` });
    }
  }
  async function restoreColumn(key: string) {
    try {
      await restoreBuiltinColumn(key);
      setTrackerCols(await listTrackerColumns());
    } catch {
      setMessage({ kind: "error", text: "Couldn't restore column." });
    }
  }

  const headerColDef = useMemo(() => ({ ...defaultColDef, floatingFilter: showColFilters }), [showColFilters]);
  const portsPresent = useMemo(() => [...new Set(allOngoing.map((s) => s.port).filter((p): p is string => !!p))].sort(), [allOngoing]);
  const alignedWithSections = () => [...sectionRefs.current.values()].filter((r) => r.current);
  const shownGroups = groups.filter(([client]) => visibleCounts[client] !== 0);

  return (
    <div className="tracker-page tracker-page-wide">
      <header className="tracker-header">
        <div>
          <h1>Shipment Tracker</h1>
          <p className="tracker-subtitle">
            {tab === "cleared"
              ? "Fully cleared shipments (Cleared Date + Duty, CFS Inv, Line, OOC, DO), by month, earliest clearance first."
              : view === "all"
                ? "All ongoing shipments, earliest ETA first."
                : `One table per ${VIEWS[view].toLowerCase()}, earliest ETA first.`}{" "}
            Double-click any cell to edit — changes save automatically.
            Ctrl/⌘+Z undoes.
            {statusFilter && (
              <>
                {" "}Filtered to <strong>{SHIPMENT_STATUS_LABELS[statusFilter]}</strong>{" "}
                <button className="link-btn" onClick={() => setSearchParams({})}>
                  clear
                </button>
              </>
            )}
          </p>
        </div>
        {message && <div role="status" className={`grid-toast grid-toast-${message.kind}`}>{message.text}</div>}
      </header>

      <div className="tracker-tabs" role="tablist" aria-label="Tracker section">
        {(Object.keys(TABS) as Tab[]).map((t) => (
          <button
            key={t}
            role="tab"
            aria-selected={tab === t}
            className={tab === t ? "tracker-tab active" : "tracker-tab"}
            onClick={() => changeTab(t)}
          >
            {TABS[t]}
            {shipments && <span className="tracker-tab-count">{t === "ongoing" ? ongoing.length : cleared.length}</span>}
          </button>
        ))}
      </div>

      <div className="tracker-toolbar">
        <div className="live-bar" title={live ? "Changes by others appear here as they happen" : "Reconnecting — changes will appear when it's back"}>
          <span className={live ? "live-dot live-on" : "live-dot"} />
          {live ? "Live" : "Reconnecting…"}
          {people.map((p) => {
            const row = p.sid != null ? shipments?.find((s) => s.id === p.sid) : undefined;
            return (
              <span key={p.key} className={`live-person presence-chip-c${p.color}`}
                title={row ? `${p.edit ? "Editing" : "On"} ${p.f ?? ""} · ${row.job ? `job ${row.job}` : row.mbl}` : ""}>
                {p.name}
              </span>
            );
          })}
        </div>
        {tab === "ongoing" && (
          <label className="group-by">
            <span>Group by</span>
            <select value={view} onChange={(e) => changeView(e.target.value as ViewMode)}>
              {(Object.keys(VIEWS) as ViewMode[]).map((v) => (
                <option key={v} value={v}>
                  {VIEWS[v]}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="view-switch" role="tablist" aria-label="Columns shown">
          {(Object.keys(COLUMN_VIEWS) as (keyof typeof COLUMN_VIEWS)[]).map((v) => (
            <button
              key={v}
              role="tab"
              aria-selected={colView === v}
              className={colView === v ? "view-switch-btn active" : "view-switch-btn"}
              onClick={() => applyColumnView(v)}
              title={v === "grid" ? "Every column, like the sheet" : `Only the ${COLUMN_VIEWS[v].label.toLowerCase()} columns`}
            >
              {COLUMN_VIEWS[v].label}
            </button>
          ))}
        </div>
        <button
          className={`btn-secondary${showColFilters ? " is-on" : ""}`}
          onClick={() => setShowColFilters((x) => !x)}
          title="A filter box under every column heading"
        >
          Column filters
        </button>
        <div className="tracker-search">
          <input placeholder="Search all columns…" value={quickFilter} onChange={(e) => setQuickFilter(e.target.value)} />
        </div>
        <div className="columns-anchor">
          <button className="btn-secondary" onClick={() => { syncHidden(); setShowColumns((v) => !v); }}>
            Columns{hiddenCols.size > 0 ? ` (${hiddenCols.size} hidden)` : ""}
          </button>
          {showColumns && (
            <ColumnsPanel
              columns={panelColumns}
              removed={trackerCols.filter((c) => !c.is_custom && c.is_removed)}
              isAdmin={isAdmin}
              onToggle={toggleColumn}
              onShowAll={showAllColumns}
              onAdd={addColumn}
              onDelete={deleteColumn}
              onRestore={restoreColumn}
              onClose={() => setShowColumns(false)}
            />
          )}
        </div>
        <button className="btn-secondary" onClick={resetLayout}>
          Reset filters &amp; layout
        </button>
        {isAdmin && (
          <button className="btn-secondary" onClick={() => setShowImport((v) => !v)}>
            Import sheet CSV
          </button>
        )}
        {isAdmin && (
          <button className="btn-secondary" onClick={() => setShowIcegate((v) => !v)} title="IGM, inward and ICD arrival for every shipment">
            Read ICEGATE (IGM)
          </button>
        )}
        {driveConfigured && (
          <button
            className="btn-secondary"
            onClick={() => setShowFolders((v) => !v)}
            title='Find each shipment&apos;s "JOB <job> - <MBL/HBL>" folder in Google Drive'
          >
            Link Drive folders
          </button>
        )}
        <button onClick={() => setShowAddForm((v) => !v)}>{showAddForm ? "Cancel" : "+ Add Shipment"}</button>
      </div>

      {showImport && <TrackerImportPanel onApplied={refresh} onClose={() => setShowImport(false)} />}
      {showIcegate && (
        <div className="import-panel">
          <div className="import-head">
            <h3>ICEGATE: IGM, inward and ICD arrival</h3>
            <button className="btn-secondary" onClick={() => (setShowIcegate(false), refresh())}>
              Close
            </button>
          </div>
          <IcegateSettings />
        </div>
      )}
      {showFolders && shipments && (
        <LinkFoldersPanel
          shipments={shipments}
          onLinked={(saved) => setShipments((prev) => prev?.map((s) => (s.id === saved.id ? saved : s)) ?? prev)}
          onClose={() => setShowFolders(false)}
        />
      )}

      {showAddForm && (
        <AddShipmentForm
          clients={distinctValues(shipments, "client")}
          consignees={distinctValues(shipments, "consignee")}
          onCreated={() => {
            setShowAddForm(false);
            refresh();
          }}
        />
      )}

      {shipments === null ? (
        <div className="tracker-empty">Loading…</div>
      ) : (
        <SettledStack key={`${tab}.${view}`}>
          {tab === "ongoing" && (
            <div className="filter-chips" role="group" aria-label="Filters">
              {portsPresent.map((p) => (
                <button key={p} type="button" className={chips.has(`port:${p}`) ? "chip on" : "chip"} onClick={() => toggleChip(`port:${p}`)}>
                  {formatPort(p, ports) || p}
                </button>
              ))}
              <span className="chip-sep" />
              {Object.entries(QUICK_CHIPS).map(([k, c]) => (
                <button key={k} type="button" className={chips.has(k) ? "chip on" : "chip"} onClick={() => toggleChip(k)} title={c.hint}>
                  {c.label}
                  <span className="chip-count">{allOngoing.filter(c.test).length}</span>
                </button>
              ))}
              {chips.size > 0 && (
                <button type="button" className="link-btn" onClick={() => setChips(new Set())}>
                  Clear filters
                </button>
              )}
            </div>
          )}
          <div
            className="client-grid-header"
            onDoubleClickCapture={(e) => {
              const edge = (e.target as Element).closest(".ag-header-cell-resize");
              edgeDoubleClick.current = edge?.closest(".ag-header-cell")?.getAttribute("col-id") ?? null;
            }}
          >
            <FormulaBar cell={fx ? formulaCell(sectionRefs.current.get(fx.client)?.current?.api, fx.rowId, fx.colId) : null} />
            <AgGridReact<Shipment>
              ref={headerRef}
              theme={gridTheme}
              rowData={[]}
              columnDefs={columnDefs}
              defaultColDef={headerColDef}
              domLayout="autoHeight"
              tooltipShowDelay={350}
              suppressNoRowsOverlay
              alignedGrids={alignedWithSections}
              onGridReady={onHeaderReady}
              onFilterChanged={onHeaderFilterChanged}
              onSortChanged={onHeaderSortChanged}
              onColumnMoved={saveColumnState}
              onColumnResized={(e) => {
                // only a person's resize counts; the ERP's own auto-fits (source "autosizeColumns" / "api",
                // reported a moment later) are ignored — reacting to them looped
                if (!e.finished || !e.columns?.length) return;
                const ids = e.columns.map((c) => c.getColId());
                const dbl = edgeDoubleClick.current;
                if (dbl && ids.includes(dbl)) {
                  // double-click on the column edge: back to auto-fit, measured on every client section
                  // (the grid alone would size it to the title only)
                  edgeDoubleClick.current = null;
                  manualWidths.current.delete(dbl);
                  saveManual();
                  window.setTimeout(() => fitToContent([dbl]), 0);
                  return;
                }
                if (e.source !== "uiColumnResized") return;
                // dragged by hand: keep that width, like Excel
                ids.forEach((id) => manualWidths.current.add(id));
                saveManual();
                saveColumnState();
              }}
              onColumnPinned={saveColumnState}
              onColumnVisible={() => scheduleFit(120)}
            />
          </div>

          {groups.map(([client, rows]) => (
            <section
              key={client}
              className="client-section"
              style={visibleCounts[client] === 0 ? { display: "none" } : undefined}
            >
              <h2 className="client-section-bar">
                {tab === "ongoing" && view === "client" && client !== NO_CLIENT ? (
                  <ClientName name={client} onRename={(n) => handleRenameClient(client, n)} />
                ) : (
                  client
                )}
                <span className="client-section-count">
                  {visibleCounts[client] ?? rows.length}
                  {visibleCounts[client] !== undefined && visibleCounts[client] !== rows.length
                    ? ` of ${rows.length}`
                    : ""}{" "}
                  shipments
                  {tab === "cleared" && ` · ${rows.filter((r) => r.is_billed).length} billed`}
                </span>
                <SectionGlance rows={rows} />
              </h2>
              <AgGridReact<Shipment>
                ref={refFor(client)}
                theme={gridTheme}
                rowData={rows}
                columnDefs={columnDefs}
                defaultColDef={sectionColDef}
                context={gridContext}
                onCellKeyDown={copyCell}
                domLayout="autoHeight"
              tooltipShowDelay={350}
                headerHeight={0}
                floatingFiltersHeight={0}
                alignedGrids={() =>
                  [headerRef, ...[...sectionRefs.current.entries()].filter(([k]) => k !== client).map(([, r]) => r)].filter(
                    (r) => r.current,
                  )
                }
                getRowId={(p) => String(p.data.id)}
                getRowClass={(p: RowClassParams<Shipment>) =>
                  // coloured left edge by status: scan the stage without reading (client, 2026-09-29)
                  [isException(p.data) ? "row-exception" : "", p.data ? `row-st-${p.data.status}` : ""].join(" ")
                }
                quickFilterText={quickFilter}
                onGridReady={(e) => syncSection(e.api)}
                suppressColumnVirtualisation // autosize measures every column, not just the visible ones
                onModelUpdated={(e) => {
                  const n = e.api.getDisplayedRowCount();
                  setVisibleCounts((prev) => (prev[client] === n ? prev : { ...prev, [client]: n }));
                }}
                onCellValueChanged={onCellValueChanged}
                onCellFocused={(e) => {
                  if (e.rowIndex == null || !e.column || typeof e.column === "string") return;
                  const row = e.api.getDisplayedRowAtIndex(e.rowIndex)?.data;
                  if (!row) return;
                  announce(row.id, e.column.getColId(), false);
                  setFx({ client, rowId: row.id, colId: e.column.getColId() });
                }}
                onCellEditingStarted={(e) => e.data && announce(e.data.id, e.column.getColId(), true)}
                onCellEditingStopped={onEditingStopped}
                enterNavigatesVertically
                enterNavigatesVerticallyAfterEdit
                stopEditingWhenCellsLoseFocus
                enableCellTextSelection
              />
            </section>
          ))}

          {shownGroups.length === 0 && <div className="tracker-empty">No shipments match this view.</div>}
        </SettledStack>
      )}
      {peekId && (
        <aside className={`peek-panel${peekFull ? " is-full" : ""}`} aria-label="Shipment">
          <ShipmentDetail key={peekId} shipmentId={peekId} onClose={() => setPeek(null)} full={peekFull} onFull={setPeekFull} />
        </aside>
      )}
    </div>
  );
}

/**
 * The grids first draw every row at the default height, then grow rows whose text wraps.
 * Keep the stack invisible until its size stops changing so rows appear at their final
 * height instead of jumping (capped, so a slow machine still shows the tracker).
 */
function SettledStack({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let quiet: number | undefined;
    const reveal = () => setSettled(true);
    const cap = window.setTimeout(reveal, 1500);
    const ro = new ResizeObserver(() => {
      window.clearTimeout(quiet);
      if (el.querySelector(".ag-row")) quiet = window.setTimeout(reveal, 80);
    });
    ro.observe(el);
    // The grids swallow a plain up/down wheel even though they never scroll vertically themselves (auto height),
    // so the page didn't move over the tracker (client, 2026-09-30). Up/down scrolls the page; sideways and
    // Shift+wheel still scroll the table sideways; scrollable popups (menus, pickers) keep their own scrolling.
    const onWheel = (e: WheelEvent) => {
      if (e.ctrlKey || e.shiftKey || Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
      if ((e.target as Element | null)?.closest?.(".ag-popup, .ag-menu, .ag-rich-select, .ag-filter, .columns-panel, .mini-popover, .date-editor"))
        return;
      e.preventDefault();
      window.scrollBy({ top: e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * window.innerHeight : e.deltaY });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      ro.disconnect();
      el.removeEventListener("wheel", onWheel);
      window.clearTimeout(quiet);
      window.clearTimeout(cap);
    };
  }, []);
  return (
    <div ref={ref} className={settled ? "client-grid-stack" : "client-grid-stack grid-settling"}>
      {children}
    </div>
  );
}

function ClientName({ name, onRename }: { name: string; onRename: (newName: string) => Promise<boolean> }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(name);
  const [saving, setSaving] = useState(false);

  async function save(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    const ok = await onRename(value);
    setSaving(false);
    if (ok) setEditing(false);
  }

  if (!editing) {
    return (
      <>
        {name}
        <button
          type="button"
          className="client-rename-btn"
          title="Rename this client on all their shipments"
          onClick={() => {
            setValue(name);
            setEditing(true);
          }}
        >
          Rename
        </button>
      </>
    );
  }
  return (
    <form className="client-rename-form" onSubmit={save}>
      <input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Escape" && setEditing(false)}
        aria-label="New client name"
      />
      <button type="submit" disabled={saving}>
        {saving ? "Saving…" : "Save"}
      </button>
      <button type="button" className="btn-secondary" onClick={() => setEditing(false)}>
        Cancel
      </button>
    </form>
  );
}

function distinctValues(rows: Shipment[] | null, field: "client" | "consignee"): string[] {
  const seen = new Map<string, string>(); // case-insensitive de-dupe, keep first spelling
  for (const r of rows ?? []) {
    const v = r[field]?.trim();
    if (v && !seen.has(v.toLowerCase())) seen.set(v.toLowerCase(), v);
  }
  return [...seen.values()].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
}

const ADD_NEW = "__add_new__";

/** Dropdown of existing names, with "+ Add new…" switching to a text box. */
function PickOrAdd(props: { label: string; options: string[]; value: string; onChange: (v: string) => void }) {
  const [adding, setAdding] = useState(false);
  if (adding) {
    return (
      <span className="pick-or-add">
        <input
          autoFocus
          placeholder={`New ${props.label.toLowerCase()}`}
          value={props.value}
          onChange={(e) => props.onChange(e.target.value)}
        />
        <button
          type="button"
          className="link-btn"
          onClick={() => {
            setAdding(false);
            props.onChange("");
          }}
        >
          back to list
        </button>
      </span>
    );
  }
  return (
    <select
      aria-label={props.label}
      value={props.value}
      onChange={(e) => {
        if (e.target.value === ADD_NEW) {
          setAdding(true);
          props.onChange("");
        } else props.onChange(e.target.value);
      }}
    >
      <option value="">{props.label}…</option>
      {props.options.map((o) => (
        <option key={o} value={o}>
          {o}
        </option>
      ))}
      <option value={ADD_NEW}>+ Add new {props.label.toLowerCase()}…</option>
    </select>
  );
}

function AddShipmentForm({
  clients,
  consignees,
  onCreated,
}: {
  clients: string[];
  consignees: string[];
  onCreated: () => void;
}) {
  const [job, setJob] = useState("");
  const [mbl, setMbl] = useState("");
  const [port, setPort] = useState("");
  const [client, setClient] = useState("");
  const [consignee, setConsignee] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ports = usePorts();

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await createShipment({
        job,
        mbl,
        port: port || undefined,
        client: client.trim() || undefined,
        consignee: consignee.trim() || undefined,
      });
      onCreated();
    } catch {
      setError("Could not create shipment — check MBL is filled in.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="add-shipment-form" onSubmit={handleSubmit}>
      <input placeholder="Job No" value={job} onChange={(e) => setJob(e.target.value)} />
      <input placeholder="MBL *" value={mbl} onChange={(e) => setMbl(e.target.value)} required />
      <select value={port} onChange={(e) => setPort(e.target.value)}>
        <option value="">Port…</option>
        {ports.map((p) => (
          <option key={p.code} value={p.code}>
            {formatPort(p.code, ports)}
          </option>
        ))}
      </select>
      <PickOrAdd label="Client" options={clients} value={client} onChange={setClient} />
      <PickOrAdd label="Consignee" options={consignees} value={consignee} onChange={setConsignee} />
      <button type="submit" disabled={submitting}>
        {submitting ? "Creating…" : "Create Shipment"}
      </button>
      {error && <div className="auth-error">{error}</div>}
    </form>
  );
}

/** Client section at a glance: containers and weight (client, 2026-09-29). */
function SectionGlance({ rows }: { rows: Shipment[] }) {
  const cntr = rows.reduce((n, r) => n + (parseInt(r.container ?? "", 10) || 0), 0);
  const tonnes = rows.reduce((n, r) => n + (parseFloat((r.gross_wt ?? "").replace(/,/g, "")) || 0), 0);
  return (
    <span className="section-glance">
      <span>{cntr} cntr</span>
      <span>{tonnes.toLocaleString("en-IN", { maximumFractionDigits: 1 })} t</span>
    </span>
  );
}

type MiniField = "hbl" | "fta_info";

/**
 * Small "HBL" / "FTA" button on the MBL (client, 2026-09-29): click to see, copy, add or edit
 * it without a column of its own. Filled = has a value.
 */
function MiniFieldButton({ row, field, label, ctx }: { row: Shipment; field: MiniField; label: string; ctx: GridContext }) {
  const [at, setAt] = useState<{ top: number; left: number } | null>(null);
  const value = row[field] ?? "";
  return (
    <>
      <button
        type="button"
        className={`mini-field${value ? " mini-field-on" : ""}`}
        title={value ? `${label}: ${value}` : `Add ${label}`}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          const r = e.currentTarget.getBoundingClientRect();
          setAt({ top: r.bottom + 4, left: Math.min(r.left, window.innerWidth - 340) });
        }}
      >
        {label}
      </button>
      {at &&
        createPortal(
          <MiniFieldPopover
            at={at}
            label={label}
            initial={value}
            multiline={field === "fta_info"}
            onClose={() => setAt(null)}
            onSave={async (v) => {
              await ctx.saveText(row, field, v.trim() || null, label);
              setAt(null);
            }}
          />,
          document.body,
        )}
    </>
  );
}

function MiniFieldPopover({
  at,
  label,
  initial,
  multiline,
  onClose,
  onSave,
}: {
  at: { top: number; left: number };
  label: string;
  initial: string;
  multiline: boolean;
  onClose: () => void;
  onSave: (v: string) => Promise<void>;
}) {
  const [v, setV] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const away = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && onClose();
    document.addEventListener("mousedown", away);
    return () => document.removeEventListener("mousedown", away);
  }, [onClose]);
  const save = async () => {
    if (v === initial) return onClose();
    setBusy(true);
    try {
      await onSave(v);
    } catch {
      setBusy(false);
    }
  };
  const keys = (e: React.KeyboardEvent) => {
    e.stopPropagation();
    if (e.key === "Escape") onClose();
    if (e.key === "Enter" && (!multiline || e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      save();
    }
  };
  return (
    <div className="mini-popover" ref={box} style={at} role="dialog" aria-label={label} onKeyDown={keys}>
      <div className="mini-popover-head">{label}</div>
      {multiline ? (
        <textarea autoFocus rows={3} value={v} onChange={(e) => setV(e.target.value)} placeholder={`${label} no / notes`} />
      ) : (
        <input autoFocus value={v} onChange={(e) => setV(e.target.value)} placeholder={`${label} no`} />
      )}
      <div className="mini-popover-actions">
        <button
          type="button"
          className="btn-secondary"
          disabled={!v}
          onClick={() => {
            navigator.clipboard?.writeText(v).then(() => setCopied(true));
          }}
        >
          {copied ? "Copied" : "Copy"}
        </button>
        <span style={{ flex: 1 }} />
        <button type="button" className="btn-secondary" onClick={onClose}>
          Cancel
        </button>
        <button type="button" disabled={busy} onClick={save}>
          Save
        </button>
      </div>
    </div>
  );
}

const DEADLINE_DAYS = 4;

/** ETA − 4 days: the deadline to move the shipment to the CFS (client, 2026-09-29). */
export function etaDeadline(eta: string | null): string | null {
  if (!eta) return null;
  const [y, m, d] = eta.split("-").map(Number);
  const dl = new Date(y, m - 1, d - DEADLINE_DAYS);
  return `${dl.getFullYear()}-${String(dl.getMonth() + 1).padStart(2, "0")}-${String(dl.getDate()).padStart(2, "0")}`;
}

/** ETA cell: the small "d" in front turns the deadline on/off; the deadline shows beside the ETA. */
function EtaCell({ row, ctx }: { row: Shipment; ctx: GridContext }) {
  const dl = row.eta_is_deadline ? etaDeadline(row.eta) : null;
  const today = new Date(new Date().toDateString()).getTime();
  const left = dl ? Math.round((new Date(`${dl}T00:00:00`).getTime() - today) / 86_400_000) : null;
  const tone = left == null ? "" : left < 0 ? " dl-past" : left <= 2 ? " dl-soon" : "";
  return (
    <span className="eta-cell">
      <button
        type="button"
        className={`dl-toggle${row.eta_is_deadline ? " dl-on" : ""}`}
        title={row.eta_is_deadline ? "Deadline on — click to turn off" : "Mark a deadline: move to the CFS 4 days before the ETA"}
        onMouseDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          ctx.saveText(row, "eta_is_deadline", !row.eta_is_deadline, "Deadline").catch(() => {});
        }}
      >
        d
      </button>
      <span>{shortDate(row.eta)}</span>
      {dl && (
        <span className={`dl-date${tone}`} title={left != null && left < 0 ? "Deadline passed" : `Deadline in ${left} day(s)`}>
          {shortDate(dl)}
        </span>
      )}
    </span>
  );
}


/** What the formula bar shows for the selected cell: the text as the cell displays it, and whether
 *  typing there may change it (plain text cells only — dates, ticks and pickers keep their own editors). */
interface FormulaCell {
  label: string;
  text: string;
  editable: boolean;
  save: (value: string) => void;
}

function formulaCell(api: GridApi<Shipment> | undefined, rowId: number, colId: string): FormulaCell | null {
  const node = api?.getRowNode(String(rowId));
  const col = api?.getColumn(colId);
  if (!api || !node?.data || !col) return null;
  const def = col.getColDef();
  const raw = api.getCellValue({ rowNode: node, colKey: colId });
  const shown = api.getCellValue({ rowNode: node, colKey: colId, useFormatter: true });
  const text = shown == null || typeof shown === "object" ? (raw == null || typeof raw === "object" ? "" : String(raw)) : String(shown);
  // plain text cells only: dates / numbers / ticks keep their own editors (a typed string would be wrong there)
  const textCell = def.cellDataType === "text" || (def.cellDataType == null && (raw == null || typeof raw === "string"));
  const editable = col.isCellEditable(node) && !def.cellEditor && textCell;
  const job = node.data.job ? `Job ${node.data.job}` : node.data.mbl;
  return {
    label: `${job} · ${def.headerName ?? colId}`,
    text,
    editable,
    save: (value) => node.setDataValue(colId, value), // runs the normal cell save (onCellValueChanged)
  };
}

/** Excel-style formula bar above the tracker: select a cell, its whole value sits here to copy;
 *  on a plain text cell, type and press Enter to save it (Esc puts it back). */
function FormulaBar({ cell }: { cell: FormulaCell | null }) {
  const [draft, setDraft] = useState(cell?.text ?? "");
  const [copied, setCopied] = useState(false);
  useEffect(() => setDraft(cell?.text ?? ""), [cell?.label, cell?.text]);
  const changed = !!cell && draft !== cell.text;
  const copy = () =>
    navigator.clipboard?.writeText(draft).then(() => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    });
  return (
    <div className="formula-bar">
      <span className="formula-name" title={cell?.label}>
        {cell?.label ?? "Select a cell"}
      </span>
      <span className="formula-fx" aria-hidden="true">
        fx
      </span>
      <input
        className="formula-input"
        aria-label={cell ? `Value of ${cell.label}` : "Selected cell value"}
        value={draft}
        readOnly={!cell?.editable}
        placeholder={cell ? "" : "Click any cell to see its full value here"}
        spellCheck={false}
        onFocus={(e) => e.currentTarget.select()}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (!cell) return;
          if (e.key === "Enter" && changed) cell.save(draft);
          if (e.key === "Escape") setDraft(cell.text);
        }}
        onBlur={() => changed && cell?.save(draft)}
      />
      {cell && !cell.editable && <span className="formula-hint">read only here · double-click the cell to edit</span>}
      <button type="button" className="btn-secondary formula-copy" onClick={copy} disabled={!cell || !draft}>
        {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
