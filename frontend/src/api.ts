import axios from "axios";
import type {
  Shipment,
  ShipmentCreateInput,
  User,
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
} from "./types";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

const client = axios.create({ baseURL: API_BASE_URL });

client.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
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
}

export async function listShipments(filters: ShipmentFilters = {}): Promise<Shipment[]> {
  const { data } = await client.get("/shipments", { params: filters });
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

export async function downloadFinalInvoice(id: number): Promise<void> {
  const res = await client.get(`/final-invoices/${id}.pdf`, { responseType: "blob" });
  const header = res.headers["x-filename"];
  const name = header ? decodeURIComponent(header) : `invoice-${id}.pdf`;
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function getInvoiceCounters(): Promise<{ counters: { fy: string; next_seq: number }[] }> {
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
  const res = await client.get(`/proformas/${proformaId}/invoice.${fmt}`, { responseType: "blob" });
  const header = res.headers["x-filename"];
  const name = header ? decodeURIComponent(header) : `proforma-${proformaId}.${fmt}`;
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
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
  accessToken: string,
) {
  const { data } = await client.post(`/shipments/${shipmentId}/documents/from-drive`, {
    document_type: documentType,
    file_id: fileId,
    access_token: accessToken,
  });
  return data;
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
  kind: "shipment" | "document" | "proforma" | "final_invoice";
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
