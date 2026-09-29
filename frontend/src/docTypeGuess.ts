import type { DocumentType } from "./types";

/**
 * Best guess of a document's type from its file name, e.g. "OOC - 271603972.pdf",
 * "CFS TAX INV 3401995.pdf", "Maersk DO.pdf". Returns null when unsure — the user picks.
 * Order matters: more specific names first.
 */
const RULES: [RegExp, DocumentType][] = [
  [/\bOOC\b|OUT OF CHARGE/, "ooc_bill_of_entry"],
  [/GATE ?PASS/, "gatepass_bill_of_entry"],
  [/ASSESS|\bBOE\b|\bB\.?E\.?\b|BILL OF ENTRY/, "assessed_bill_of_entry"],
  [/CFS.*(RCPT|RECEIPT)|CFS-RCPT/, "cfs_receipt"],
  [/CFSTI|CFS.*(TAX|\bTI\b)/, "cfs_tax_invoice"],
  [/CFSPI|CFS.*(PRO|\bPI\b)/, "cfs_proforma_invoice"],
  [/SL-RCPT|(\bSL\b|LINER|LINE).*(RCPT|RECEIPT)/, "shipping_line_receipt"],
  [/SL-PI|(\bSL\b|LINER|DSC|DESTINATION).*(PRO|\bPI\b)/, "shipping_line_proforma"],
  [/SL-DSC|\bDSC\b|LINER INV|DESTINATION CHARGE/, "shipping_line_invoice"],
  [/DO.{0,3}EMPTY|EMPTY.{0,3}DO/, "do_empty_letter"],
  [/\bDO\b|DELIVERY ORDER/, "do_letter"],
  [/EMPTY/, "empty_letter"],
  [/\bHBL\b/, "hbl_copy"],
  [/\bMBL\b|\bBL\b|\bB\/L\b|BILL OF LADING/, "bl_copy"],
  [/PACKING|\bPL\b/, "packing_list"],
  [/INSUR|\bINS\b/, "insurance"],
  [/STAMP/, "stamp_duty"],
  [/\bHSS\b|HIGH SEA/, "hss_agreement"],
  [/FTA|AIFTA|ASEAN/, "fta_certificate_of_origin"],
  [/\bCOO\b|CERTIFICATE OF ORIGIN/, "certificate_of_origin"],
  [/FORM ?6|FORM ?9/, "form_6_9"],
];

export function guessDocType(fileName: string): DocumentType | null {
  const name = fileName.replace(/\.pdf$/i, "").replace(/[_]+/g, " ").toUpperCase();
  return RULES.find(([re]) => re.test(name))?.[1] ?? null;
}
