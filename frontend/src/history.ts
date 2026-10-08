import { fmtDay, fmtWhen } from "./dates";
const INR = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
/** amounts, totals, duty, TDS, rates in ₹ — not GST/TDS percentages or quantities */
const isMoney = (f: string) => !/(gst|tds)_rate$|quantity/.test(f) && /amount|total|value|tds|cost|received|rate|duty/.test(f);

/** How a recorded value reads on the page (the log keeps text: "True", "2026-09-29", "ShipmentStatus.OOC_DONE"). */
export function historyValue(v: string | null, field?: string): string {
  if (v == null || v === "" || v === "None") return "—";
  // weight reads like the tracker: "270.033 MTS"
  const w = field === "gross_wt" ? /^(\d+(?:\.\d+)?)(?:\s*MTS)?$/i.exec(v.trim()) : null;
  if (w) return `${Number(w[1]).toFixed(3)} MTS`;
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
