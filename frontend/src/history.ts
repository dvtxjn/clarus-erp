/** How a recorded value reads on the page (the log keeps text: "True", "2026-09-29", "ShipmentStatus.OOC_DONE"). */
export function historyValue(v: string | null): string {
  if (v == null || v === "" || v === "None") return "—";
  if (v === "True") return "Yes";
  if (v === "False") return "No";
  const d = /^(\d{4})-(\d{2})-(\d{2})$/.exec(v);
  if (d) return new Date(`${v}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" });
  const e = /^[A-Za-z]+\.([A-Z_]+)$/.exec(v);
  if (e) return e[1].replace(/_/g, " ").toLowerCase().replace(/^\w/, (c) => c.toUpperCase());
  return v;
}

export function historyTime(at: string): string {
  const d = new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(at) ? at : `${at}Z`);
  return d.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" });
}
