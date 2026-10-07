import { fmtDay, fmtWhen } from "./dates";
/** How a recorded value reads on the page (the log keeps text: "True", "2026-09-29", "ShipmentStatus.OOC_DONE"). */
export function historyValue(v: string | null): string {
  if (v == null || v === "" || v === "None") return "—";
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
  if (withYear) return fmtWhen(d.toISOString(), true);
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Kolkata" });
}
