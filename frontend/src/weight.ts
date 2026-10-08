/**
 * Gross Wt is kept in MTS ("270.033 MTS"). A plain number over 1000 is almost certainly kg typed into
 * the MTS field — invoice lines priced per kg would then be 1000× — so we ask before saving it.
 * Returns the MTS figure to offer ("270.033"), or null when the value looks fine.
 */
export function kgLooking(value: string | null | undefined): string | null {
  const m = /^(\d+(?:\.\d+)?)(?:\s*MTS)?$/i.exec((value ?? "").trim());
  if (!m) return null;
  const n = Number(m[1]);
  return n > 1000 ? (n / 1000).toFixed(3) : null;
}
