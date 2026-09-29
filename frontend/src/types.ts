// Mirrors backend/app/core/enums.py and backend/app/schemas/*.py.
// Keep these in sync manually for now — generating from the OpenAPI schema
// (e.g. via openapi-typescript) is a reasonable follow-up once the API
// stabilizes. See PROGRESS.md.

export type ShipmentStatus =
  | "to_be_filed"
  | "igm_filed"
  | "be_filed"
  | "be_assessed"
  | "duty_paid"
  | "under_ooc"
  | "ooc_done"
  | "cleared"
  | "billed";

export const SHIPMENT_STATUS_LABELS: Record<ShipmentStatus, string> = {
  to_be_filed: "To be Filed",
  igm_filed: "IGM Filed",
  be_filed: "BE Filed",
  be_assessed: "BE Assessed",
  duty_paid: "Duty Paid",
  under_ooc: "Under OOC",
  ooc_done: "OOC Done",
  cleared: "Cleared",
  billed: "Billed",
};

export type UserRole = "admin" | "import_manager" | "export_manager" | "accountant";

export interface User {
  id: number;
  email: string;
  full_name: string;
  role: UserRole;
  can_access_billing: boolean;
}

export interface Shipment {
  id: number;
  job: string;
  mbl: string;
  hbl: string | null;
  be_no: string | null;
  be_dt: string | null;
  be_description: string | null;
  eta: string | null;
  inw: string | null;
  license: string | null;
  client: string | null;
  consignee: string | null;
  pod: string | null;
  container_status: string | null;
  cfs: string | null;
  container: string | null;
  gross_wt: string | null;
  poc: string | null;
  cleared_date: string | null;
  igm: string | null;
  delivery_status: string | null;
  remark: string | null;
  mbl_date: string | null;
  hbl_date: string | null;
  gw: string | null;
  total_pkg: string | null;
  pkg_code: string | null;
  line_no: string | null;
  igm_date: string | null;
  voyage: string | null;
  cont: string | null;
  shipping_line: string | null;
  custom_fields: Record<string, string | number | boolean | null>;
  duty_paid: boolean;
  cfs_inv_received: boolean;
  line_paid: boolean;
  ooc: boolean;
  do: boolean;
  cfs_paid_by_us: boolean;
  cfs_billed_as: "reimbursement" | "taxable"; // CFS paid by us: at actuals, or Billed by Clarus with our GST
  line_paid_by_us: boolean; // shipping line normally paid by the client -> Cost Inclusion
  tds_deducted: boolean;
  tds_on_cfs: boolean;
  drive_folder_id: string | null;
  drive_folder_link: string | null;
  cfs_tds_amount: string | null; // 2% of CFS basic, when we pay the CFS and cut TDS
  cfs_payment_after_tds: string | null; // basic + GST - TDS
  remarks: string | null;
  is_stuck: boolean;
  status: ShipmentStatus;
  port: string | null;
  hs_code_id: number | null;
  is_billed: boolean;
  billed_at: string | null;
  // HSS (high sea sale): consignee "SELLER - BUYER"; each party gets its own invoice
  is_hss: boolean;
  hss_seller: string | null;
  hss_buyer: string | null;
  is_archived: boolean;
  days: string; // computed server-side: today - INW + 1, or "Pending"
  // Cleared = Cleared Date + Duty, CFS Inv, Line, OOC, DO all ticked
  is_fully_cleared: boolean;
  missing_for_clearance: string[];
  missing_from_sheet_at: string | null; // not in the last tracker CSV import (flagged, never deleted)
  // read from uploaded documents (decimals arrive as strings)
  assessable_value: string | null;
  igst_amount: string | null;
  duty_amount: string | null;
  cfs_amount_before_tax: string | null;
  cfs_gst_amount: string | null;
  cfs_amount_total: string | null;
  line_amount_before_tax: string | null; // sum of shipping line destination charges invoices
  line_gst_amount: string | null;
  line_amount_total: string | null;
  ooc_date: string | null;
  under_examination: boolean | null;
  examination_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export type DocumentType =
  | "cfs_proforma_invoice"
  | "cfs_tax_invoice"
  | "assessed_bill_of_entry"
  | "ooc_bill_of_entry"
  | "gatepass_bill_of_entry"
  | "bl_copy"
  | "hbl_copy"
  | "packing_list"
  | "insurance"
  | "shipping_line_invoice"
  | "shipping_line_proforma"
  | "shipping_line_receipt"
  | "cfs_receipt"
  | "do_letter"
  | "empty_letter"
  | "do_empty_letter"
  | "hss_agreement"
  | "stamp_duty"
  | "hss_stamp_duty"
  | "certificate_of_origin"
  | "fta_certificate_of_origin"
  | "form_6_9"
  | "form_6"
  | "form_9"
  | "other";

export const DOCUMENT_TYPE_LABELS: Record<DocumentType, string> = {
  cfs_proforma_invoice: "CFS Proforma Invoice",
  cfs_tax_invoice: "CFS Tax Invoice",
  cfs_receipt: "CFS Receipt",
  assessed_bill_of_entry: "Assessed Bill of Entry",
  ooc_bill_of_entry: "OOC Bill of Entry",
  gatepass_bill_of_entry: "Gatepass Bill of Entry",
  bl_copy: "BL Copy",
  hbl_copy: "HBL Copy",
  packing_list: "Packing List",
  insurance: "Insurance",
  shipping_line_proforma: "Shipping Line Proforma (destination charges)",
  shipping_line_invoice: "Shipping Line Tax Invoice (destination charges)",
  shipping_line_receipt: "Shipping Line Receipt",
  do_letter: "DO Letter",
  empty_letter: "Empty Letter",
  do_empty_letter: "DO + Empty Letter (one file)",
  hss_agreement: "HSS Agreement",
  stamp_duty: "Stamp Duty",
  hss_stamp_duty: "HSS & Stamp Duty (old combined type)",
  certificate_of_origin: "Certificate of Origin",
  fta_certificate_of_origin: "FTA Certificate of Origin",
  form_6_9: "Form 6 & 9",
  form_6: "Form 6 (old)",
  form_9: "Form 9 (old)",
  other: "Other",
};

/** Old types kept only so earlier uploads still display — not offered for new uploads. */
export const LEGACY_DOCUMENT_TYPES: DocumentType[] = ["hss_stamp_duty", "form_6", "form_9"];

export interface DocumentExtraction {
  fields: Record<string, unknown>;
  updated: string[];
  notes: string[];
}

export interface ShipmentDocument {
  id: number;
  shipment_id: number;
  document_type: DocumentType;
  original_filename: string;
  generated_filename: string;
  file_path: string;
  tracker_sync_applied: boolean;
  uploaded_at: string;
  extraction: DocumentExtraction | null;
  drive_link: string | null;
  // CFS invoices only (decimals as strings)
  amount_before_tax: string | null;
  gst_amount: string | null;
  amount_total: string | null;
  amounts_edited: boolean;
  // Shipping line invoices: the cost inclusion part (null = whole invoice)
  cost_before_tax: string | null;
  cost_gst: string | null;
  cost_excluded: number[] | null; // indices into extraction.fields.charges
  cost_manual: boolean;
}

/** One charge line read from a shipping line invoice (extraction.fields.charges). */
export interface InvoiceCharge {
  description: string;
  sac: string | null;
  currency: string;
  quantity: number | null;
  rate: number | null;
  amount: number | null; // INR
  gst: number | null;
  in_cost_inclusion: boolean; // billed in INR and not a freight head
  review: boolean; // INR but named like freight
}

export interface DocumentChecklistItem {
  document_type: DocumentType;
  required: boolean;
  optional: boolean;
  uploaded: boolean;
  document: ShipmentDocument | null;
  documents: ShipmentDocument[];
}

export interface HSCode {
  id: number;
  code: string;
  description: string;
  required_document_types: DocumentType[];
}

export type ChargeCalculationBasis = "flat" | "per_container" | "per_kg";

export interface ChargeMasterEntry {
  id: number;
  name: string;
  code: string;
  sac_code: string;
  gst_rate: number;
  calculation_basis: ChargeCalculationBasis;
  category: ChargeCategory;
  default_rate: number | null; // standard rate: fills new proforma lines (editable per line)
  is_active: boolean;
}

export type ProformaStatus = "draft" | "sent" | "superseded";

export interface ProformaLineItem {
  id: number;
  proforma_id: number;
  charge_master_id: number;
  description: string | null;
  rate: number;
  quantity: number;
  amount: number;
  sac_code: string;
  gst_rate: number;
  gst_amount: number;
  total: number;
  category: ChargeCategory;
  gst_is_actual: boolean;
  is_manual: boolean; // edited by hand: automatic updates leave it alone
}

// Invoice sections: Billed by Clarus / Reimbursement (at actuals) / Cost Inclusion (not in the total)
export type ChargeCategory = "service" | "reimbursement" | "royalty" | "cost_inclusion";

/** HSS pricing rule: lines Fill puts on the seller or buyer copy when the BE importer matches.
 *  amount = per_container x containers + per_kg x weight (kg) + flat. */
export interface PricingRuleLine {
  code: string;
  per_container?: number | string | null;
  per_kg?: number | string | null;
  flat?: number | string | null;
  category?: ChargeCategory | null;
}
/** Licence (belongs to the BE importer): charges pre-filled on its proformas.
 *  A row may be limited to a seller (HSS) and/or a port; the most specific match wins. */
export interface LicenceRate extends PricingRuleLine {
  seller?: string | null;
  port?: string | null;
}
export interface Licence {
  id: number;
  number: string;
  importer_name: string | null;
  rates: LicenceRate[];
  is_active: boolean;
  notes: string | null;
}

export interface PricingRule {
  id: number;
  name: string;
  importer_name: string; // buyer = BE importer
  seller_name: string | null; // null = any seller
  bill_to_role: "seller" | "buyer";
  lines: PricingRuleLine[];
  is_active: boolean;
}

export interface InvoiceLine {
  id: number;
  description: string | null;
  sac_code: string;
  rate: string;
  quantity: string;
  amount: string;
  gst_rate: string;
  gst_amount: string;
  gst_is_actual: boolean;
  is_manual: boolean;
  total: string;
}

export interface InvoiceView {
  company: { name: string; address: string; tax_line: string; contact_line: string };
  title: string;
  copy_label: string | null;
  disclaimer: string | null; // HSS seller copy: "<seller> to pay <buyer>"
  bill_to: {
    name: string | null;
    party: string | null; // the tracker's name, e.g. "Mahrishi" (after the '-' on HSS)
    organization: (Pick<Organization, "id" | "name" | "address" | "state" | "gstin" | "pan" | "iec" | "email" | "phone">) | null;
    bl_consignee: string | null; // organization holding the BE's AD code (else the tracker's consignee)
    bl_consignee_ad_code: string | null;
    be_importer: string | null;
    hss: { seller: string | null; buyer: string | null } | null;
  };
  details: { invoice_date: string; be_no: string | null; be_date: string | null; port: string | null; job: string; version: number; name: string | null; status: string };
  reference: { assessable_value: string | null; mbl: string | null; hbl: string | null; hss: string; containers: number | null; weight_kgs: string | null; exam_applicable: string };
  sections: { category: ChargeCategory; title: string; lines: InvoiceLine[]; subtotal: string; counts_in_total: boolean }[];
  grand_total: string;
  grand_total_label: string;
  round_off: string; // grand total is rounded to the rupee; this is the +/− paise // "<seller> pays <buyer> pays CLARUS LOGISTICS LLP"
  is_hss: boolean;
  customs_duty: { interest: string; total: string; source: "challan" | "ooc" | "be"; challan_uploaded_at: string | null; challan_today: boolean } | null;
  value: {
    value_of_goods: string;
    gst_input: string;
    value_per_kg: string | null;
    suggested_bill_rate: string | null; // value/kg + ≥10 paise, GST difference > 0, next 25 paise step
    bill_rate: string | null;
    gst_output: string | null;
    gst_difference: string | null;
  };
  notes: string[];
  bank: [string, string][];
}

export interface Proforma {
  id: number;
  shipment_id: number;
  version_number: number;
  name: string | null;
  bill_to: string | null;
  bill_to_role: "seller" | "buyer" | null; // HSS shipments: one invoice per party
  bill_to_org_id: number | null;
  bill_rate: number | null; // HSS bill rate per kg -> GST Difference
  suppressed: string[] | null; // document-derived lines removed by hand, e.g. "DO:Liner Inv"
  status: ProformaStatus;
  extracted_data: Record<string, unknown> | null;
  generated_filename: string | null;
  created_at: string;
  line_items: ProformaLineItem[];
  grand_total: number;
}

export interface DashboardSummary {
  total_live: number;
  stuck_count: number;
  cleared_this_month: number;
  cleared_this_month_unbilled: number;
  clearance_exceptions: number;
  by_status: Record<ShipmentStatus, number>;
  by_port: Record<string, number>;
  upcoming_etas: { id: number; job: string; mbl: string; consignee: string | null; eta: string | null; port: string | null }[];
}

export interface ShipmentCreateInput {
  job: string;
  mbl: string;
  hbl?: string;
  be_no?: string;
  port?: string;
  client?: string;
  consignee?: string;
}

export interface Port {
  id: number;
  code: string;
  name: string;
}

export type ColumnDataType = "text" | "date" | "number" | "boolean";

export interface TrackerColumn {
  key: string;
  label: string;
  data_type: ColumnDataType;
  is_custom: boolean;
  is_removed: boolean;
}

export interface Organization {
  id: number;
  name: string;
  short_names: string | null; // names the tracker uses, comma-separated (e.g. "Mahrishi")
  ad_code: string | null;
  gstin: string | null;
  pan: string | null;
  iec: string | null;
  address: string | null;
  state: string | null;
  email: string | null;
  phone: string | null;
  is_active: boolean;
  updated_at: string | null;
}

export type OrganizationInput = Omit<Organization, "id" | "updated_at">;

export interface DailyStatus {
  challans_last_uploaded_at: string | null;
  challans_updated_today: boolean;
  challans_in_last_upload: number;
  organizations: number;
  organizations_last_updated_at: string | null;
  organizations_updated_today: boolean;
  awaiting_challan: { id: number; job: string | null; mbl: string; be_no: string }[];
}

export interface ChallanUploadResult {
  rows: number;
  matched: { be_no: string; shipment_id: number; job: string | null; mbl: string; due_amount: string; interest: string | null }[];
  unmatched: string[];
  note: string | null;
}

/** Final invoice (tax / reimbursement) made from a proforma; editable while draft, locked once issued. */
export interface FinalInvoiceLine {
  sr?: number;
  description: string;
  sub_description?: string | null;
  sac?: string | null;
  tax_type: "T" | "P" | "E" | "R" | "N";
  non_gst_value: string;
  taxable_value: string;
  gst_rate: string;
  tax?: string;
  cgst?: string | null;
  sgst?: string | null;
  igst?: string | null;
  total?: string;
}
export interface FinalInvoice {
  id: number;
  kind: "tax" | "reimbursement";
  title: string;
  status: "draft" | "issued" | "cancelled";
  number: string | null;
  invoice_date: string | null;
  due_date: string | null;
  customer: { name?: string; address?: string; pan?: string; gstin?: string; state_code?: string; state_name?: string };
  place_of_supply: string;
  intra_state: boolean;
  header: Record<string, string | null>;
  header_fields: [string, string][];
  lines: FinalInvoiceLine[];
  remarks: string | null;
  irn: string | null;
  ack_no: string | null;
  ack_date: string | null;
  totals: Record<string, string>;
  proforma_id: number | null;
  shipment_id: number;
}
