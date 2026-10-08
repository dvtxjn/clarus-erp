import axios from "axios";
import type {
  Shipment,
  ShipmentCreateInput,
  User,
  UserRole,
  DashboardSummary,
  ShipmentDocument,
  DocumentChecklistItem,
  HSCode,
  ChargeMasterEntry,
  Proforma,
  ProformaStatus,
  ChargeCategory,
  InvoiceView,
  Organization,
  OrganizationInput,
  DailyStatus,
  ChallanUploadResult,
  PricingRule,
  Licence,
  FinalInvoice,
  Port,
  TrackerColumn,
  ColumnDataType,
  ProformaSnapshot,
} from "./types";

// "" in production (screens and API on one address); the dev server talks to :8000
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const client = axios.create({ baseURL: API_BASE_URL });

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});
// the login ran out (12 h) or was revoked: back to the login page, not a screen where saves quietly fail
client.interceptors.response.use(undefined, async (err) => {
  // a load that hit a network blip or a server switching over (deploy): try once more, quietly
  const cfg = axios.isAxiosError(err) ? (err.config as (typeof err.config & { _retried?: boolean }) | undefined) : undefined;
  const status = axios.isAxiosError(err) ? err.response?.status : undefined;
  if (cfg && !cfg._retried && (cfg.method ?? "get").toLowerCase() === "get" && !axios.isCancel(err)
      && (status === undefined || status === 502 || status === 503 || status === 504)) {
    cfg._retried = true;
    await new Promise((r) => setTimeout(r, 800));
    return client.request(cfg);
  }
  if (axios.isAxiosError(err) && err.response?.status === 401 && !String(err.config?.url ?? "").includes("/auth/login")
      && localStorage.getItem("access_token")) {
    window.dispatchEvent(new CustomEvent("auth:ended", { detail: "Your login has expired — please log in again." }));
  }
  return Promise.reject(err);
});

export async function login(email: string, password: string): Promise<string> {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);
  const { data } = await client.post("/auth/login", form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  localStorage.setItem("access_token", data.access_token);
  return data.access_token;
}

export function logout() {
  localStorage.removeItem("access_token");
}

export async function getCurrentUser(): Promise<User> {
  const { data } = await client.get("/auth/me");
  return data;
}

export interface ShipmentFilters {
  port?: string;
  status?: import("./types").ShipmentStatus;
  is_stuck?: boolean;
  include_archived?: boolean;
  search?: string;
  cleared?: boolean; // true = only fully cleared, false = only ongoing
}

export async function clearedShipmentCount(): Promise<number> {
  const { data } = await client.get("/shipments/cleared-count");
  return data.count;
}

export async function listShipments(filters: ShipmentFilters = {}): Promise<Shipment[]> {
  const { data } = await client.get("/shipments", { params: filters });
  return data;
}

/** Every client / consignee ever used (one spelling each), for the Add Shipment pickers. */
export async function getShipmentNames(): Promise<{ clients: string[]; consignees: string[] }> {
  const { data } = await client.get("/shipments/names");
  return data;
}

export async function createShipment(payload: ShipmentCreateInput): Promise<Shipment> {
  const { data } = await client.post("/shipments", payload);
  return data;
}

export interface ShipmentConflict {
  field: string;
  current: unknown;
  yours: unknown;
  base: unknown;
  changed_by: string | null;
  changed_at: string | null;
}

/** 409 from PATCH /shipments: someone changed a field this edit changes since it was loaded. */
export class ShipmentConflictError extends Error {
  conflicts: ShipmentConflict[];
  shipment: Shipment; // the row as it is now
  constructor(detail: { message: string; conflicts: ShipmentConflict[]; shipment: Shipment }) {
    super(detail.message);
    this.conflicts = detail.conflicts;
    this.shipment = detail.shipment;
  }
}

/** base = the values the user saw for the fields being changed (see useSaveShipment). */
export async function updateShipment(
  id: number,
  payload: Partial<Shipment>,
  base?: Record<string, unknown>,
): Promise<Shipment> {
  try {
    const { data } = await client.patch(`/shipments/${id}`, base ? { ...payload, base } : payload);
    return data;
  } catch (e) {
    const detail = axios.isAxiosError(e) && e.response?.status === 409 ? e.response.data?.detail : null;
    if (detail && typeof detail === "object" && Array.isArray(detail.conflicts)) throw new ShipmentConflictError(detail);
    throw e;
  }
}

export async function getShipment(id: number): Promise<Shipment> {
  const { data } = await client.get(`/shipments/${id}`);
  return data;
}

export async function getDashboardSummary(): Promise<DashboardSummary> {
  const { data } = await client.get("/shipments/summary/dashboard");
  return data;
}

export type AlertKind = "deadline" | "free_days" | "documents" | "icegate";
export interface ShipmentAlert {
  kind: AlertKind;
  severity: "overdue" | "urgent" | "soon";
  days_left: number;
  due: string | null;
  text: string;
  shipment_id: number;
  job: string | null;
  mbl: string | null;
  be_no: string | null;
  client: string | null;
  consignee: string | null;
  port: string | null;
  missing?: string[];
  mail_id?: number;
  lookup?: boolean; // ICEGATE lookup flag: "Look up again" on the row
}

/** Dashboard "Needs attention": "d" deadlines, free days at the POD, documents before BE filing. */
export async function getAlerts(): Promise<ShipmentAlert[]> {
  const { data } = await client.get("/shipments/alerts");
  return data;
}

export async function listHsCodes(): Promise<HSCode[]> {
  const { data } = await client.get("/hs-codes");
  return data;
}

export async function listDocuments(shipmentId: number): Promise<ShipmentDocument[]> {
  const { data } = await client.get(`/shipments/${shipmentId}/documents`);
  return data;
}

export async function getDocumentChecklist(shipmentId: number): Promise<DocumentChecklistItem[]> {
  const { data } = await client.get(`/shipments/${shipmentId}/documents/checklist`);
  return data;
}

export async function updateCharge(
  id: number,
  changes: Partial<Pick<ChargeMasterEntry, "name" | "sac_code" | "gst_rate" | "calculation_basis" | "category" | "default_rate" | "is_active">>,
): Promise<ChargeMasterEntry> {
  const { data } = await client.patch(`/charge-master/${id}`, changes);
  return data;
}

export async function createCharge(payload: {
  name: string;
  code: string;
  sac_code?: string;
  gst_rate?: number;
  calculation_basis?: ChargeMasterEntry["calculation_basis"];
  category?: ChargeMasterEntry["category"];
  default_rate?: number | null;
}): Promise<ChargeMasterEntry> {
  const { data } = await client.post("/charge-master", payload);
  return data;
}

// --- Final invoices (tax / reimbursement) ---

export async function createFinalInvoices(proformaId: number): Promise<FinalInvoice[]> {
  const { data } = await client.post(`/proformas/${proformaId}/final-invoices`);
  return data;
}

export async function listFinalInvoices(shipmentId: number): Promise<FinalInvoice[]> {
  const { data } = await client.get(`/shipments/${shipmentId}/final-invoices`);
  return data;
}

export async function updateFinalInvoice(id: number, changes: Record<string, unknown>): Promise<FinalInvoice> {
  const { data } = await client.patch(`/final-invoices/${id}`, changes);
  return data;
}

export async function issueFinalInvoice(id: number): Promise<FinalInvoice> {
  const { data } = await client.post(`/final-invoices/${id}/issue`);
  return data;
}

export async function cancelFinalInvoice(id: number, reason?: string): Promise<FinalInvoice> {
  const { data } = await client.post(`/final-invoices/${id}/cancel`, { reason: reason || null });
  return data;
}

export async function deleteFinalInvoice(id: number): Promise<void> {
  await client.delete(`/final-invoices/${id}`);
}

/** Tax + reimbursement of one proforma: numbered and locked together (they share the number). */
export async function issueFinalPair(proformaId: number): Promise<FinalInvoice[]> {
  const { data } = await client.post(`/proformas/${proformaId}/final-invoices/issue`);
  return data;
}

/** Both invoices of the pair in one PDF (tax, then reimbursement). */
export async function downloadFinalPair(proformaId: number): Promise<void> {
  await downloadBlob(`/proformas/${proformaId}/final-invoices.pdf`, `invoices-${proformaId}.pdf`);
}

export async function downloadFinalInvoice(id: number): Promise<void> {
  await downloadBlob(`/final-invoices/${id}.pdf`, `invoice-${id}.pdf`);
}

/** One invoice's PDF as a local URL, for the preview on the Invoicing page (revoke it when done). */
export async function invoicePdfUrl(kind: "final" | "proforma", id: number): Promise<string> {
  const path = kind === "final" ? `/final-invoices/${id}.pdf` : `/proformas/${id}/invoice.pdf`;
  const res = await client.get(path, { responseType: "blob" });
  return URL.createObjectURL(res.data);
}

async function downloadBlob(path: string, fallback: string): Promise<void> {
  const res = await client.get(path, { responseType: "blob" });
  const header = res.headers["x-filename"];
  const name = header ? decodeURIComponent(header) : fallback;
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export interface InvoiceSeries {
  tax: string;
  reimbursement: string;
  example_tax: string;
  example_reimbursement: string;
}
export async function getInvoiceSeries(): Promise<InvoiceSeries> {
  const { data } = await client.get("/invoice-series");
  return data;
}
export async function setInvoiceSeries(tax: string, reimbursement: string): Promise<InvoiceSeries> {
  const { data } = await client.put("/invoice-series", { tax, reimbursement });
  return data;
}

export async function getInvoiceCounters(): Promise<{ counters: { fy: string; next_seq: number | null }[] }> {
  const { data } = await client.get("/invoice-counter");
  return data;
}

export async function setInvoiceCounter(fy: string, next_seq: number): Promise<{ fy: string; next_seq: number }> {
  const { data } = await client.put("/invoice-counter", { fy, next_seq });
  return data;
}

// --- Google Sheets tracker CSV re-import ---

export interface TrackerImportResult {
  rows: number;
  new: { row: number; job: string | null; mbl: string; hbl: string | null; consignee: string | null }[];
  updated: {
    shipment_id: number;
    job: string | null;
    mbl: string;
    matched_by: string;
    check: boolean;
    changes: { field: string; label: string; old: string | null; new: string | null }[];
    kept: { field: string; label: string; old: string | null; new: string | null; why: string }[];
  }[];
  unchanged: number;
  missing: { shipment_id: number; job: string | null; mbl: string; consignee: string | null }[];
  cleared?: number; // not in the sheet but cleared / billed (moved to the FNF sheets) — not flagged
  older?: number; // FnF rows from before the ERP — not created
  unknown_columns: string[];
  skipped: string[];
}

async function postCsv(path: string, file: File): Promise<TrackerImportResult> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post(path, form);
  return data;
}

export const previewTrackerImport = (file: File) => postCsv("/tracker-import/preview", file);
export const applyTrackerImport = (file: File) => postCsv("/tracker-import/apply", file);

export async function listLicences(): Promise<Licence[]> {
  const { data } = await client.get("/licences");
  return data;
}

export async function saveLicence(lic: Omit<Licence, "id"> & { id?: number }): Promise<Licence> {
  const { id, ...body } = lic;
  const { data } = id ? await client.put(`/licences/${id}`, body) : await client.post("/licences", body);
  return data;
}

export async function listPricingRules(): Promise<PricingRule[]> {
  const { data } = await client.get("/pricing-rules");
  return data;
}

export async function savePricingRule(rule: Omit<PricingRule, "id"> & { id?: number }): Promise<PricingRule> {
  const { id, ...body } = rule;
  const { data } = id ? await client.put(`/pricing-rules/${id}`, body) : await client.post("/pricing-rules", body);
  return data;
}

export async function deletePricingRule(id: number): Promise<void> {
  await client.delete(`/pricing-rules/${id}`);
}

export async function listAllCharges(): Promise<ChargeMasterEntry[]> {
  const { data } = await client.get("/charge-master", { params: { include_inactive: true } });
  return data;
}

export async function listChargeMaster(): Promise<ChargeMasterEntry[]> {
  const { data } = await client.get("/charge-master");
  return data;
}

export async function listProformas(shipmentId: number): Promise<Proforma[]> {
  const { data } = await client.get(`/shipments/${shipmentId}/proformas`);
  return data;
}

export async function createProforma(
  shipmentId: number,
  opts: { bill_to_role?: "seller" | "buyer"; name?: string } = {},
): Promise<Proforma> {
  const { data } = await client.post(`/shipments/${shipmentId}/proformas`, opts);
  return data;
}

export async function updateProforma(
  proformaId: number,
  changes: { name?: string | null; bill_to?: string | null; bill_to_org_id?: number | null; bill_rate?: number | null },
): Promise<Proforma> {
  const { data } = await client.patch(`/proformas/${proformaId}`, changes);
  return data;
}

export async function addProformaLineItem(
  proformaId: number,
  payload: { charge_master_id: number; description?: string; rate: number; quantity?: number; category?: ChargeCategory }
): Promise<Proforma> {
  const { data } = await client.post(`/proformas/${proformaId}/line-items`, payload);
  return data;
}

export async function removeProformaLineItem(proformaId: number, lineItemId: number): Promise<Proforma> {
  const { data } = await client.delete(`/proformas/${proformaId}/line-items/${lineItemId}`);
  return data;
}

/** Edit one cell of a draft line. gst_amount: number = actual GST, null = back to rate × amount. */
export async function updateProformaLineItem(
  proformaId: number,
  lineItemId: number,
  changes: { description?: string; rate?: number; quantity?: number; gst_amount?: number | null; category?: ChargeCategory },
): Promise<Proforma> {
  const { data } = await client.patch(`/proformas/${proformaId}/line-items/${lineItemId}`, changes);
  return data;
}

/** Put back a removed document-derived line (key from `suppressed`), or add one by code (CD/SD/CFS/DO/EC). */
export async function restoreProformaLine(proformaId: number, key: string): Promise<Proforma> {
  const { data } = await client.post(`/proformas/${proformaId}/restore`, { key });
  return data;
}

export async function fillProformaFromShipment(
  proformaId: number,
): Promise<{ proforma: Proforma; added: string[]; updated: string[]; skipped: string[] }> {
  const { data } = await client.post(`/proformas/${proformaId}/fill-from-shipment`);
  return data;
}

export async function getInvoice(proformaId: number): Promise<InvoiceView> {
  const { data } = await client.get(`/proformas/${proformaId}/invoice`);
  return data;
}

/** Download the invoice as .xlsx or .pdf (named "{bill to} - {MBL} - {BE} - proforma…"). */
export async function downloadInvoice(proformaId: number, fmt: "xlsx" | "pdf"): Promise<void> {
  await saveBlob(`/proformas/${proformaId}/invoice.${fmt}`, `proforma-${proformaId}.${fmt}`);
}

/** Sent copies of a proforma kept when it was edited after sending (newest first). */
export async function getProformaHistory(proformaId: number): Promise<ProformaSnapshot[]> {
  const { data } = await client.get(`/proformas/${proformaId}/history`);
  return data;
}

export async function downloadProformaSnapshot(snapshotId: number): Promise<void> {
  await saveBlob(`/proforma-snapshots/${snapshotId}/invoice.pdf`, `proforma-sent-${snapshotId}.pdf`);
}

async function saveBlob(path: string, fallback: string): Promise<void> {
  const res = await client.get(path, { responseType: "blob" });
  const header = res.headers["x-filename"];
  const name = header ? decodeURIComponent(header) : fallback;
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** The proforma PDF as a File (phone: share it to WhatsApp / mail from the share sheet). */
export async function getInvoicePdfFile(proformaId: number): Promise<File> {
  const res = await client.get(`/proformas/${proformaId}/invoice.pdf`, { responseType: "blob" });
  const header = res.headers["x-filename"];
  const name = header ? decodeURIComponent(header) : `proforma-${proformaId}.pdf`;
  return new File([res.data], name, { type: "application/pdf" });
}

export async function updateProformaStatus(proformaId: number, status: ProformaStatus): Promise<Proforma> {
  const { data } = await client.patch(`/proformas/${proformaId}`, { status });
  return data;
}

export async function uploadDocument(shipmentId: number, documentType: string, file: File, driveAccessToken?: string) {
  const formData = new FormData();
  formData.append("document_type", documentType);
  formData.append("file", file);
  if (driveAccessToken) formData.append("drive_access_token", driveAccessToken);
  const { data } = await client.post(`/shipments/${shipmentId}/documents`, formData, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export default client;

export async function listPorts(): Promise<Port[]> {
  const { data } = await client.get("/ports");
  return data;
}

export async function renameClient(oldName: string, newName: string): Promise<{ updated: number }> {
  const { data } = await client.post("/shipments/rename-client", { old_name: oldName, new_name: newName });
  return data;
}

export async function listTrackerColumns(): Promise<TrackerColumn[]> {
  const { data } = await client.get("/tracker-columns");
  return data;
}

export async function addTrackerColumn(label: string, data_type: ColumnDataType): Promise<TrackerColumn> {
  const { data } = await client.post("/tracker-columns", { label, data_type });
  return data;
}

export async function deleteTrackerColumn(key: string): Promise<void> {
  await client.delete(`/tracker-columns/${key}`);
}

export async function removeBuiltinColumn(key: string, label: string): Promise<TrackerColumn> {
  const { data } = await client.post("/tracker-columns/remove-builtin", { key, label });
  return data;
}

export async function restoreBuiltinColumn(key: string): Promise<TrackerColumn> {
  const { data } = await client.post(`/tracker-columns/restore-builtin/${key}`);
  return data;
}

export async function addDocumentFromDrive(
  shipmentId: number,
  documentType: string,
  fileId: string,
  accessToken?: string, // none: the server reads it with its own Drive connection
) {
  const { data } = await client.post(`/shipments/${shipmentId}/documents/from-drive`, {
    document_type: documentType,
    file_id: fileId,
    ...(accessToken ? { access_token: accessToken } : {}),
  });
  return data;
}

export interface DriveFolderHit {
  id: string;
  name: string;
  url: string;
}
/** Does the server have its own Google Drive connection (no Google sign-in needed)? */
export async function getDriveStatus(): Promise<{ server: boolean }> {
  const { data } = await client.get("/drive/status");
  return data;
}
export async function searchServerDriveFolders(terms: string[]): Promise<DriveFolderHit[]> {
  const params = new URLSearchParams();
  terms.forEach((t) => params.append("q", t));
  const { data } = await client.get(`/drive/folders?${params}`);
  return data;
}
export async function listDriveFolderPdfs(folderId: string): Promise<{ id: string; name: string }[]> {
  const { data } = await client.get(`/drive/folders/${encodeURIComponent(folderId)}/pdfs`);
  return data;
}

export type FolderFileStatus =
  | "added" | "attached" | "not_attached" | "ignored" | "unrecognised" | "duplicate" | "removed" | "error";
export interface FolderFile {
  file_id: string;
  name: string;
  link: string;
  guess: string | null; // the reader's guess from the file name
  mark: string | null; // a document type, "ignore", or null = the reader decides
  status: FolderFileStatus;
  document_id: number | null;
  document_type: string | null;
  error?: string;
}

/** PDFs in the shipment's Drive folder and where each stands (names only — quick). */
export async function getFolderFiles(shipmentId: number) {
  const { data } = await client.get<FolderFile[]>(`/shipments/${shipmentId}/drive-folder/files`);
  return data;
}

/** Read the folder: attach what's not attached yet and fill in the shipment's details. */
export async function syncFolder(shipmentId: number) {
  const { data } = await client.post<{ files: FolderFile[]; updated: string[]; notes: string[] }>(
    `/shipments/${shipmentId}/drive-folder/sync`,
  );
  return data;
}

/** Mark a folder file as a document type, "ignore", or null (back to the reader's guess). */
export async function markFolderFile(shipmentId: number, fileId: string, documentType: string | null, fileName: string) {
  await client.put(`/shipments/${shipmentId}/drive-folder/marks/${encodeURIComponent(fileId)}`, {
    document_type: documentType,
    file_name: fileName,
  });
}

export async function rereadDocument(shipmentId: number, documentId: number) {
  const { data } = await client.post(`/shipments/${shipmentId}/documents/${documentId}/reread`);
  return data;
}

export async function removeDocument(shipmentId: number, documentId: number): Promise<void> {
  await client.delete(`/shipments/${shipmentId}/documents/${documentId}`);
}

export async function billShipment(id: number): Promise<Shipment> {
  const { data } = await client.post(`/shipments/${id}/bill`);
  return data;
}

export async function unbillShipment(id: number): Promise<Shipment> {
  const { data } = await client.post(`/shipments/${id}/unbill`);
  return data;
}

/** Shipping line invoice -> cost inclusion: leave charge lines out, type the figure, or reset to the rule. */
export async function setCostInclusion(
  shipmentId: number,
  documentId: number,
  body: { excluded: number[] } | { before_tax: string; gst: string } | { reset: true },
): Promise<ShipmentDocument> {
  const { data } = await client.patch(`/shipments/${shipmentId}/documents/${documentId}/cost-inclusion`, body);
  return data;
}

export async function correctInvoiceAmounts(
  shipmentId: number,
  documentId: number,
  amountBeforeTax: string,
  gstAmount: string,
): Promise<ShipmentDocument> {
  const { data } = await client.patch(`/shipments/${shipmentId}/documents/${documentId}/amounts`, {
    amount_before_tax: amountBeforeTax,
    gst_amount: gstAmount,
  });
  return data;
}

export async function deleteDraftProforma(proformaId: number): Promise<void> {
  await client.delete(`/proformas/${proformaId}`);
}

// --- Daily updates: duty challans + organization repository ---

export async function getDailyStatus(): Promise<DailyStatus> {
  const { data } = await client.get("/daily-updates");
  return data;
}

export async function uploadChallans(file: File): Promise<ChallanUploadResult> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post("/duty-challans/upload", form);
  return data;
}

export async function addChallan(payload: { be_no: string; due_amount: number; challan_no?: string }): Promise<ChallanUploadResult> {
  const { data } = await client.post("/duty-challans", payload);
  return data;
}

export async function listOrganizations(): Promise<Organization[]> {
  const { data } = await client.get("/organizations");
  return data;
}

export async function createOrganization(payload: OrganizationInput): Promise<Organization> {
  const { data } = await client.post("/organizations", payload);
  return data;
}

export async function updateOrganization(id: number, payload: OrganizationInput): Promise<Organization> {
  const { data } = await client.put(`/organizations/${id}`, payload);
  return data;
}

export async function importOrganizations(file: File): Promise<{ created: number; updated: number }> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await client.post("/organizations/import", form);
  return data;
}

// --- Recently deleted (admin) ---
export interface DeletedItem {
  kind: "shipment" | "document" | "proforma" | "final_invoice" | "payment" | "container";
  id: number;
  label: string;
  shipment_id: number | null;
  shipment: string | null;
  shipment_deleted: boolean;
  deleted_at: string;
  deleted_by: string | null;
}

export async function listDeleted(): Promise<DeletedItem[]> {
  const { data } = await client.get("/deleted");
  return data;
}

export async function restoreDeleted(kind: DeletedItem["kind"], id: number): Promise<void> {
  await client.post(`/deleted/${kind}/${id}/restore`);
}

/** Open a stored document's PDF in a new tab (the file needs the login header). */
export async function openDocumentFile(shipmentId: number, documentId: number): Promise<void> {
  const tab = window.open("", "_blank"); // opened now, while the click still counts
  const { data } = await client.get(`/shipments/${shipmentId}/documents/${documentId}/file`, { responseType: "blob" });
  const url = URL.createObjectURL(data);
  if (tab) tab.location.href = url;
  else window.location.href = url;
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

export interface BackupHealth {
  enabled: boolean;
  last_ok_at: string | null;
  last_ok_age_hours: number | null;
  last_ok_name: string | null;
  in_drive: boolean;
  warnings: string[];
}
export async function getBackupHealth(): Promise<BackupHealth> {
  const { data } = await client.get("/health/backups");
  return data;
}

// --- users (admin controls every password) ---
export async function listUsers(): Promise<User[]> {
  const { data } = await client.get("/auth/users");
  return data;
}
export async function createUser(payload: { email: string; full_name: string; role: UserRole; password: string }): Promise<User> {
  const { data } = await client.post("/auth/users", payload);
  return data;
}
export async function updateUser(id: number, payload: Partial<Pick<User, "full_name" | "role" | "is_active" | "read_only">>): Promise<User> {
  const { data } = await client.patch(`/auth/users/${id}`, payload);
  return data;
}
export async function setUserPassword(id: number, newPassword: string): Promise<User> {
  const { data } = await client.post(`/auth/users/${id}/password`, { new_password: newPassword });
  return data;
}
export async function forgotPassword(email: string): Promise<void> {
  await client.post("/auth/forgot-password", { email });
}

/** Admin switches (e.g. e-invoicing applies to the company). Admin changes them. */
export interface CompanySettings {
  name: string;
  address_lines: string[];
  gstin: string;
  pan: string;
  cin: string;
  state_code: string;
  state: string;
  email: string;
  phone: string;
}
export interface AppSettings {
  e_invoicing: boolean;
  tds_rate_editable: boolean;
  company: CompanySettings;
  bank: [string, string][];
  final_terms: string[];
  proforma_notes: string[];
}
export interface SystemStatus {
  storage: string;
  drive_folders: Record<string, string | null>;
  backups: { enabled: boolean; last_ok_at: string | null; last_ok_age_hours: number | null; in_drive: boolean; warnings: string[] };
  environment: string;
  public_url: string | null;
}
/** Admin: read the interest (INT) on OOC copies uploaded before it was read (one-off, safe to repeat). */
export async function backfillOocInterest(): Promise<{ checked: number; with_interest: number; duty_fixed: number; failed: number }> {
  const { data } = await client.post("/settings/ooc-interest");
  return data;
}

export async function getSystemStatus(): Promise<SystemStatus> {
  const { data } = await client.get("/settings/system");
  return data;
}
export async function getSettings(): Promise<AppSettings> {
  const { data } = await client.get("/settings");
  return data;
}
/** Switches every signed-in user's screens need. */
export async function getPublicSettings(): Promise<{ tds_rate_editable: boolean }> {
  const { data } = await client.get("/settings/public");
  return data;
}
export async function setSetting<K extends keyof AppSettings>(key: K, value: AppSettings[K]): Promise<AppSettings> {
  const { data } = await client.put(`/settings/${key}`, { value });
  return data;
}

/** Invoice register: every final invoice across shipments (the Invoices page). */
export interface RegisterRow {
  id: number;
  kind: "tax" | "reimbursement";
  status: "draft" | "issued" | "cancelled";
  number: string | null;
  seq: number | null;
  fy: string | null;
  invoice_date: string | null;
  customer: string;
  gstin: string;
  shipment_id: number;
  proforma_id: number | null;
  job: string | null;
  mbl: string | null;
  be_no: string | null;
  not_applicable: boolean;
  taxable: string;
  non_gst: string;
  gst: string;
  net_payable: string;
  irn: string | null;
  received: string;
  outstanding: string;
}
export interface RegisterFilters {
  fy?: string;
  month?: string;
  kind?: string;
  status?: string;
  client?: string;
  q?: string;
}
const clean = (f: RegisterFilters) => Object.fromEntries(Object.entries(f).filter(([, v]) => v));
export async function getInvoiceRegister(f: RegisterFilters): Promise<{ invoices: RegisterRow[]; financial_years: string[]; drafts: number }> {
  const { data } = await client.get("/final-invoices", { params: clean(f) });
  return data;
}
export async function downloadInvoicesPdf(ids: number[]): Promise<void> {
  await downloadBlob(`/final-invoices/export.pdf?ids=${ids.join(",")}`, "invoices.pdf");
}
export async function downloadInvoiceRegister(f: RegisterFilters): Promise<void> {
  const qs = new URLSearchParams(clean(f) as Record<string, string>).toString();
  await downloadBlob(`/final-invoices/register.xlsx${qs ? `?${qs}` : ""}`, "invoice-register.xlsx");
}

/** Proforma register: every proforma across shipments (Invoices page → Proformas). */
export interface ProformaRegisterRow {
  id: number;
  shipment_id: number;
  job: string | null;
  mbl: string | null;
  be_no: string | null;
  version: number;
  name: string | null;
  status: "draft" | "sent" | "superseded";
  role: string | null;
  bill_to: string | null;
  date: string | null;
  grand_total: string;
}
export async function getProformaRegister(f: RegisterFilters): Promise<{ proformas: ProformaRegisterRow[]; financial_years: string[] }> {
  const { data } = await client.get("/proformas", { params: clean(f) });
  return data;
}
export async function downloadProformasPdf(ids: number[]): Promise<void> {
  await downloadBlob(`/proformas/export.pdf?ids=${ids.join(",")}`, "proformas.pdf");
}

/** Payments & outstanding (P1). */
export interface OpenInvoice {
  id: number;
  number: string | null;
  kind: "tax" | "reimbursement";
  invoice_date: string | null;
  customer: string;
  gstin: string;
  shipment_id: number;
  job: string | null;
  be_no: string | null;
  mbl: string | null;
  tds_expected: boolean; // tax invoice of a shipment whose client cuts TDS (switch on the proforma)
  tds_estimate: string; // ~2% of the taxable value, until TDS is recorded
  net_payable: string;
  paid: string;
  tds: string;
  outstanding: string;
  pay_status: string;
  age_days: number;
  bucket: string;
}
export interface ClientReceivable {
  key: string; // exactly this client (gstin:… / name:…)
  party: string;
  gstin: string;
  billed: string;
  received: string;
  tds: string;
  outstanding: string;
  on_account: string;
  tds_estimate: string;
  net_due: string; // outstanding − on account − expected TDS
  buckets: Record<string, string>;
  oldest_days: number;
  invoices: OpenInvoice[];
}
export interface PaymentRecord {
  id: number;
  received_on: string;
  party: string;
  party_gstin: string | null;
  amount: string;
  mode: string | null;
  reference: string | null;
  notes: string | null;
  key: string;
  allocations: {
    invoice_id: number;
    number: string | null;
    shipment_id: number | null;
    job: string | null;
    be_no: string | null;
    mbl: string | null;
    amount: string;
    tds: string;
  }[];
  unallocated: string;
}
export async function getReceivables(client?: string, includePaid = false): Promise<{ as_of: string; clients: ClientReceivable[] }> {
  const { data } = await client_get("/receivables", { client: client || undefined, include_paid: includePaid || undefined });
  return data;
}
export async function listPayments(party?: string): Promise<PaymentRecord[]> {
  const { data } = await client_get("/payments", { party: party || undefined });
  return data;
}
export async function recordPayment(body: {
  received_on: string;
  party: string;
  party_gstin?: string | null;
  amount: string;
  mode?: string;
  reference?: string;
  notes?: string;
  allocations: { invoice_id: number; amount: string; tds: string }[];
}): Promise<PaymentRecord> {
  const { data } = await client.post("/payments", body);
  return data;
}
export async function deletePayment(id: number): Promise<void> {
  await client.delete(`/payments/${id}`);
}
/** Set money already on account against invoices. */
export async function allocatePayment(id: number, allocations: { invoice_id: number; amount: string; tds: string }[]): Promise<PaymentRecord> {
  const { data } = await client.post(`/payments/${id}/allocate`, { allocations });
  return data;
}
/** `key` = the client's key, so the statement is exactly that client. */
export async function downloadStatement(key: string): Promise<void> {
  await downloadBlob(`/receivables/statement.pdf?client=${encodeURIComponent(key)}`, "statement.pdf");
}
function client_get(path: string, params: Record<string, unknown>) {
  return client.get(path, { params });
}


/** Containers of a shipment + arrival at the FPOD (inland free days). */
export interface ShipmentContainer {
  id: number;
  container_no: string;
  status: string | null;
  arrival_date: string | null;
  arrival_status: string | null;
  tracking_status: string | null; // typed, e.g. "On rail"
  source: "icegate" | "manual" | "do";
  is_manual: boolean;
  arrival_from_inw: boolean; // sea port, nothing typed: the shipment's INW stands in as the arrival
  free_days: number; // this container's free days (typed, or the standard 14)
  free_days_typed: boolean;
  do_valid_until: string | null; // read from the DO: the actual last free date (typing by hand clears it)
  day: number | null;
  last_free_day: string | null;
  days_left: number | null;
}

export async function listContainers(shipmentId: number): Promise<ShipmentContainer[]> {
  const { data } = await client.get(`/shipments/${shipmentId}/containers`);
  return data;
}
export async function addContainer(shipmentId: number, body: { container_no: string; arrival_date?: string | null }): Promise<ShipmentContainer> {
  const { data } = await client.post(`/shipments/${shipmentId}/containers`, body);
  return data;
}
export async function editContainer(
  shipmentId: number,
  id: number,
  body: {
    container_no?: string;
    arrival_date?: string | null;
    clear_arrival?: boolean;
    tracking_status?: string;
    free_days?: number;
    free_until?: string;
    clear_free_days?: boolean;
    clear_do?: boolean;
    do_valid_until?: string; // History "Put back" only
  },
): Promise<ShipmentContainer> {
  const { data } = await client.patch(`/shipments/${shipmentId}/containers/${id}`, body);
  return data;
}
export async function removeContainer(shipmentId: number, id: number): Promise<void> {
  await client.delete(`/shipments/${shipmentId}/containers/${id}`);
}

export interface IcegateSummary {
  inland: boolean;
  sea_found: boolean;
  icd_found: boolean;
  changed: Record<string, [string | null, string]>;
  notes: string[];
  looked_up_as?: string; // HMM typed without HDMU: the number ICEGATE was searched with
  hint?: string; // e.g. "HMM MBL without its HDMU prefix — ICEGATE needs HDMU…"
  differences?: { field: string; igm: string; icd: string }[];
  containers?: { added: number; updated: number; kept_manual: number };
}
/** On command: sea IGM (+ ICD BL status for inland) → IGM details, FPOD ICD BL details, container arrivals. */
export async function refreshIcegate(shipmentId: number): Promise<{ summary: IcegateSummary; shipment: import("./types").Shipment }> {
  const { data } = await client.post(`/shipments/${shipmentId}/icegate/refresh`);
  return data;
}

/** The BE / OOC / gate pass copies customs mail holds for this shipment, put on it now. */
export async function attachBeFromMail(shipmentId: number): Promise<{ added: number; notes: string[] }> {
  const { data } = await client.post(`/shipments/${shipmentId}/icegate-mails/attach-be`);
  return data;
}

export interface IcegateStatus {
  last_run: { at: string; checked: number; filled: number; not_found: number; errors: number; jobs: string[] } | null;
  every_hours: number;
  due_now: { id: number; job: string | null; mbl: string | null; port: string | null }[];
  final_due: { id: number; job: string | null; mbl: string | null; port: string | null }[];
}
/** Settings: last automatic ICEGATE run + what the next one would read (admin). */
export async function getIcegateStatus(): Promise<IcegateStatus> {
  const { data } = await client.get("/icegate/status");
  return data;
}

// Settings → Google Sheets copy of the tracker (view-only, every 15 minutes)
export interface SheetsMirror {
  sheet_id?: string | null;
  link: string | null;
  share_with: string | null;
  every_minutes: number;
  last_run?: string | null;
  last_error?: string | null;
  rows?: number;
}
export async function getSheetsMirror(): Promise<SheetsMirror> {
  const { data } = await client.get("/sheets-mirror");
  return data;
}
export async function setSheetsMirror(link: string): Promise<SheetsMirror> {
  const { data } = await client.put("/sheets-mirror", { link });
  return data;
}
export async function runSheetsMirror(): Promise<SheetsMirror> {
  const { data } = await client.post("/sheets-mirror/run");
  return data;
}

// ICEGATE mails (customs mail feed, shipment timeline)
export interface IcegateMail {
  live: boolean; // on a live tracker shipment (or recent, not matched yet)
  port_of_shipment: string | null;
  id: number;
  received_at: string | null;
  kind: string;
  label: string;
  summary: string | null;
  be_no: string | null;
  be_date: string | null;
  job_no: string | null;
  port: string | null;
  mbl: string | null;
  detail: Record<string, unknown> | null;
  notes: string[] | null;
  shipment_id: number | null;
  shipment_job: string | null;
  shipment_mbl: string | null;
  shipment_be_no: string | null;
  client: string | null;
  document_id: number | null;
  attention: boolean;
  resolved_at: string | null;
  resolved_note: string | null;
}
export interface MailImportResult {
  read: number;
  new: number;
  duplicates: number;
  ignored: number;
  matched: number;
  attention: number;
}
export interface MailFilters {
  attention?: boolean;
  unmatched?: boolean;
  scope?: "live" | "history" | "all"; // live = on a live tracker shipment (default); history = old / gone
  source?: "icegate" | "odex";
  kind?: string; // comma-separated
  port?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
}
export async function listIcegateMails(params: MailFilters = {}): Promise<IcegateMail[]> {
  const { data } = await client.get("/icegate-mails", { params });
  return data;
}
export async function icegateMailKinds(): Promise<{ kind: string; label: string }[]> {
  const { data } = await client.get("/icegate-mails/kinds");
  return data;
}
export async function shipmentIcegateMails(shipmentId: number): Promise<IcegateMail[]> {
  const { data } = await client.get(`/shipments/${shipmentId}/icegate-mails`);
  return data;
}
export async function importIcegateMails(files: File[]): Promise<MailImportResult> {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  const { data } = await client.post("/icegate-mails/import", form);
  return data;
}
export async function resolveIcegateMail(id: number, note?: string): Promise<IcegateMail> {
  const { data } = await client.post(`/icegate-mails/${id}/resolve`, { note });
  return data;
}
export async function linkIcegateMail(id: number, shipmentId: number): Promise<IcegateMail> {
  const { data } = await client.post(`/icegate-mails/${id}/link`, { shipment_id: shipmentId });
  return data;
}

// Settings → ICEGATE mailbox (read automatically, read-only)
export interface MailboxStatus {
  mailbox: string | null;
  connected: boolean;
  connected_at: string | null;
  last_run: string | null;
  last_error: string | null;
  last_new: number | null;
  paused?: string | null;
  waiting?: number;
  instant: boolean;
  push_wanted: boolean; // the admin's switch
  push_available: boolean; // the server has a Pub/Sub topic
  push_error: string | null;
  watch_expires: string | null;
  ready: boolean;
}
export async function setMailboxPush(enabled: boolean): Promise<MailboxStatus> {
  const { data } = await client.put("/gmail-reader/push", { enabled });
  return data;
}

// Automatic update rules (Settings → Automatic rules)
export interface CustomRule {
  id?: string;
  source: "mail" | "be_queue";
  kind?: string;
  contains?: string;
  queue?: string;
  field: string | null;
  attention: boolean;
  enabled: boolean;
}
export interface AutoRules {
  builtin: { id: string; when: string; then: string; enabled: boolean }[];
  custom: CustomRule[];
  history_days: number;
  fields: { field: string; label: string }[];
  kinds: { kind: string; label: string }[];
}
export async function getAutoRules(): Promise<AutoRules> {
  const { data } = await client.get("/auto-rules");
  return data;
}
export async function saveAutoRules(body: { off: string[]; custom: CustomRule[]; history_days: number }): Promise<AutoRules> {
  const { data } = await client.put("/auto-rules", body);
  return data;
}
export async function getMailbox(): Promise<MailboxStatus> {
  const { data } = await client.get("/gmail-reader");
  return data;
}
export async function mailboxConnectUrl(loginHint?: string): Promise<string> {
  const { data } = await client.get("/gmail-reader/connect", { params: loginHint ? { login_hint: loginHint } : {} });
  return data.url;
}
export async function syncMailbox(): Promise<MailboxStatus> {
  const { data } = await client.post("/gmail-reader/sync");
  return data;
}
export async function disconnectMailbox(): Promise<MailboxStatus> {
  const { data } = await client.post("/gmail-reader/disconnect");
  return data;
}

// Change history (the audit log, readable)
export interface HistoryEntry {
  id: number;
  at: string;
  who: string | null; // null + automatic: the ERP itself (ICEGATE, mails, invoices read)
  automatic: boolean;
  table: string;
  kind: string; // Shipment / Container / Document / …
  record_id: number;
  field: string;
  label: string;
  old: string | null;
  new: string | null;
  about?: string | null; // container no / document name
  undo?: Record<string, unknown> | null; // shipment field (or container field + container_id) that can be put back
  shipment_id?: number;
  job?: string | null;
  mbl?: string | null;
  be_no?: string | null;
}
export async function shipmentHistory(id: number): Promise<HistoryEntry[]> {
  const { data } = await client.get(`/shipments/${id}/history`);
  return data;
}
export async function allHistory(params: { who?: string; kind?: string; date_from?: string; date_to?: string; q?: string; limit?: number }): Promise<HistoryEntry[]> {
  const { data } = await client.get("/history", { params });
  return data;
}
export async function historyFilters(): Promise<{ users: { id: number; name: string }[]; kinds: { kind: string; label: string }[] }> {
  const { data } = await client.get("/history/filters");
  return data;
}
