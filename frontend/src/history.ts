import { fmtDay, fmtWhen, MONTHS } from "./dates";
const INR = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
/** amounts, totals, duty, TDS, rates in ₹ — not GST/TDS percentages or quantities */
const isMoney = (f: string) =>
  !/(gst|tds)_rate$|quantity|pkg|package|count/.test(f) && /amount|^total$|_total$|grand_total|value|tds$|cost|received|rate$|duty$/.test(f);

/** How a recorded value reads on the page (the log keeps text: "True", "2026-09-29", "ShipmentStatus.OOC_DONE"). */
export function historyValue(v: string | null, field?: string): string {
  if (v == null || v === "" || v === "None") return "—";
  // weight reads like the tracker: "270.033 MTS"
  const w = field === "gross_wt" ? /^(\d+(?:\.\d+)?)(?:\s*MTS)?$/i.exec(v.trim()) : null;
  if (w) return `${Number(w[1]).toFixed(3)} MTS`;
  // IGM "GW" is in kg: 141715 -> "141.715 MTS"
  if (field === "gw" && /^\d+(?:\.\d+)?$/.test(v.trim())) return `${(Number(v) / 1000).toFixed(3)} MTS`;
  // printed times ("06-OCT-26 18:22", "03/09/2026 14:22") read like the rest: "06 Oct 2026, 18:22"
  const p = /^(\d{1,2})[-/ ]([A-Za-z]{3}|\d{1,2})[-/ ](\d{2}|\d{4})(?:[ T,]+(\d{1,2}:\d{2}))?$/.exec(v.trim());
  if (p) {
    const mon = /^\d+$/.test(p[2]) ? Number(p[2]) - 1 : MONTHS.findIndex((m) => m.toLowerCase() === p[2].toLowerCase());
    if (mon >= 0 && mon < 12) return `${p[1].padStart(2, "0")} ${MONTHS[mon]} ${p[3].length === 2 ? `20${p[3]}` : p[3]}${p[4] ? `, ${p[4].padStart(5, "0")}` : ""}`;
  }
  // money reads like everywhere else: "₹7,53,687.00"
  if (field && isMoney(field) && /^-?\d+(?:\.\d+)?$/.test(v)) return `₹${INR.format(Number(v))}`;
  if (v === "True") return "Yes";
  if (v === "False") return "No";
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if (d) return fmtDay(v);
  // a recorded moment ("2026-10-07T07:11:09.796365", "2026-09-27 17:12:51+00:00") reads like every other time
  if (/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(v)) return historyTime(v.replace(" ", "T"), true);
  const e = /^[A-Za-z]+\.([A-Z_]+)$/.exec(v);
  if (e) return e[1].replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
  return v;
}

export function historyTime(at: string, withYear = false): string {
  // the log stores UTC; a time without a zone is UTC too
  const d = new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(at) ? at : `${at}Z`);
  return fmtWhen(d.toISOString(), withYear);
}
