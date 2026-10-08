import { fmtWhen, MONTHS } from "./dates";
/** Shared bits for ICEGATE mail screens. Times are shown in India time (client: GMT+5:30), with the year: "06 Oct 2026, 18:22". */
export const istTime = (iso: string | null) => fmtWhen(iso, true);

/** A printed date inside ICEGATE's text ("06-OCT-26", "06/10/2026", "2026-10-06") -> "06 Oct 2026". */
function readableDates(t: string): string {
  return t
    .replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, (_, y, m, d) => (Number(m) >= 1 && Number(m) <= 12 ? `${d} ${MONTHS[Number(m) - 1]} ${y}` : _))
    .replace(/\b(\d{1,2})[-/ ]([A-Za-z]{3}|\d{1,2})[-/ ](\d{4}|\d{2})\b/g, (all, d, m, y) => {
      const mon = /^\d+$/.test(m) ? Number(m) - 1 : MONTHS.findIndex((x) => x.toLowerCase() === m.toLowerCase());
      return mon >= 0 && mon < 12 && Number(d) <= 31 ? `${String(d).padStart(2, "0")} ${MONTHS[mon]} ${y.length === 2 ? `20${y}` : y}` : all;
    });
}

/**
 * ICEGATE's text, easier to read: dates as "06 Oct 2026", and ALL-CAPS sentences in sentence case. Words with a
 * digit or an underscore (BE / job numbers, CACHI01, 791_ITEMS) and short forms (BE, IGM, OOC…) stay as they are.
 */
export function readableCustoms(text: string | null | undefined): string {
  const t = readableDates((text ?? "").trim());
  const letters = t.replace(/[^A-Za-z]/g, "");
  if (letters.length < 8 || letters.replace(/[^A-Z]/g, "").length / letters.length < 0.8) return t; // not shouting
  const KEEP = /^(?:BE|B\/E|BL|MBL|HBL|IGM|OOC|DO|CFS|ICD|IEC|GST|IGST|CHA|ICEGATE|ODEX|HSN|CTH|PAN|UTC|IST)$/;
  const lower = t.replace(/\S+/g, (tok) => (/[\d_]/.test(tok) || MONTHS.includes(tok) || KEEP.test(tok.replace(/^[^A-Za-z]+|[^A-Za-z]+$/g, "")) ? tok : tok.toLowerCase()));
  // capital after the start and after a sentence end
  return lower.replace(/(^|[.!?:]\s+|\n\s*)([a-z])/g, (_, p, c) => p + c.toUpperCase()).replace(/\bi\b/g, "I").replace(/\b(?:ODEX|Odex|odex)\b/g, "ODeX");
}

/** What the area named in an ICEGATE error code is about ("791_ITEMS" -> "the item lines"). */
const ERROR_AREAS: Record<string, string> = {
  ITEMS: "the item lines",
  ITEM: "the item lines",
  LICENCE: "the licence details",
  LICENSE: "the licence details",
  INVOICE: "the invoice details",
  IEC: "the importer's IEC",
  CTH: "the tariff (CTH) codes",
  HSN: "the tariff (HSN) codes",
  IGM: "the IGM / line number",
  BOND: "the bond details",
  CONTAINER: "the container details",
  NOTIFICATION: "the exemption notification",
  DUTY: "the duty details",
  PORT: "the port code",
  SVB: "the SVB details",
  CERTIFICATE: "the certificate details",
};

/**
 * A plain line for each error code in an ICEGATE rejection ("791_ITEMS", "413_LICENCE"): which part of the filing
 * ICEGATE complained about. The exact rule is in the full mail; this only says where to look.
 */
export function errorCodeLines(text: string | null | undefined): string[] {
  const out: string[] = [];
  for (const m of (text ?? "").matchAll(/\b(\d{2,4})_([A-Z][A-Z_]*)\b/g)) {
    const area = m[2].split("_").map((w) => ERROR_AREAS[w]).find(Boolean) ?? `the ${m[2].replace(/_/g, " ").toLowerCase()} details`;
    const line = `Error ${m[1]} (${m[0]}): ICEGATE found a problem in ${area} — check them and file again.`;
    if (!out.includes(line)) out.push(line);
  }
  return out;
}
