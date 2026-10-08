export const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** One date style everywhere (UI pass v2): "03 Sep 2026". Accepts "YYYY-MM-DD" or an ISO time. */
export function fmtDay(v: string | null | undefined): string {
  if (!v) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(v);
  if (!m) return v;
  return `${m[3]} ${MONTHS[Number(m[2]) - 1]} ${m[1]}`;
}

/** "2026-09-03" -> "03 Sep" (cards, chips — where the year is understood). */
export function fmtDayShort(v: string | null | undefined): string {
  if (!v) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(v);
  if (!m) return v;
  return `${m[3]} ${MONTHS[Number(m[2]) - 1]}`;
}

/** The IST calendar parts of a moment (numeric, so no locale spells September "Sept"). */
function istParts(iso: string): { y: string; m: number; d: string; hh: string; mm: string } | null {
  const t = new Date(iso);
  if (Number.isNaN(t.getTime())) return null;
  const p = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Kolkata",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(t)
      .map((x) => [x.type, x.value]),
  );
  return { y: p.year, m: Number(p.month), d: p.day, hh: p.hour, mm: p.minute };
}

/** A moment, in IST, 24-hour: "07 Oct, 07:43" — or "07 Oct 2026, 07:43" with the year. */
export function fmtWhen(iso: string | null | undefined, withYear = false): string {
  if (!iso) return "—";
  const p = istParts(iso);
  if (!p) return iso;
  return `${p.d} ${MONTHS[p.m - 1]}${withYear ? ` ${p.y}` : ""}, ${p.hh}:${p.mm}`;
}

/** The IST day of a moment: "07 Oct" (or "07 Oct 2026" with the year). */
export function fmtWhenDay(iso: string | null | undefined, withYear = false): string {
  if (!iso) return "—";
  const p = istParts(iso);
  if (!p) return iso;
  return `${p.d} ${MONTHS[p.m - 1]}${withYear ? ` ${p.y}` : ""}`;
}

/** Just the IST time: "07:43". */
export function fmtTime(iso: string): string {
  const p = istParts(iso);
  return p ? `${p.hh}:${p.mm}` : "";
}

/** Today in IST, "YYYY-MM-DD". */
export function istToday(): string {
  const p = istParts(new Date().toISOString())!;
  return `${p.y}-${String(p.m).padStart(2, "0")}-${p.d}`;
}
