import type { Shipment } from "./types";

/**
 * How an import clearance moves, and what the shipment is waiting on right now (UX pass, 2026-09-30).
 *
 *   IGM filed (by the line) → BE filed → assessed (or a query to answer) → duty paid (challan)
 *   → examination, if marked → OOC → line paid → DO → CFS invoice → Cleared Date (gate-out) → invoice
 *
 * Line payment, DO and the CFS invoice can happen alongside the customs steps, so once customs is
 * past, whatever is still open is listed together. A pending customs query always comes first,
 * because nothing moves until it's answered.
 */
export type NextStep = { title: string; detail: string; blocked: boolean; also: string[] };

export function nextStep(s: Shipment): NextStep | null {
  const q = s.icegate?.be_status;
  const openQuery = !!q?.query && !q?.query_reply;
  const commercial: [string, boolean][] = [
    ["Line paid", s.line_paid],
    ["DO", s.do],
    ["CFS invoice", s.cfs_inv_received],
  ];
  const openCommercial = commercial.filter(([, done]) => !done).map(([label]) => label);
  const step = (title: string, detail: string, blocked = false, also: string[] = []): NextStep => ({ title, detail, blocked, also });

  if (s.is_billed) return null;
  if (openQuery) return step("Reply to the customs query", q!.query!, true);
  if (!s.igm) return step("Waiting for the IGM", "The shipping line files the IGM. The BE can be filed once the IGM number is in.");
  if (!s.be_no) return step("File the Bill of Entry", "IGM is in. File the BE in LiveImpex, then enter the BE number here.");
  if (s.duty_amount == null) return step("Waiting for assessment", "BE is filed. Customs hasn't assessed it yet.", false, openCommercial);
  if (!s.duty_paid) return step("Pay the duty", "BE is assessed. Pay the challan, then tick Duty Paid.", false, openCommercial);
  if (!s.ooc) {
    return s.under_examination
      ? step("Examination in progress", "Duty is paid and the goods are marked for examination. OOC follows.", false, openCommercial)
      : step("Waiting for OOC", "Duty is paid. Tick OOC once customs gives the out-of-charge.", false, openCommercial);
  }
  if (openCommercial.length) {
    return step(
      `${openCommercial[0]} pending`,
      "Customs is done. These are still needed before the goods can leave the CFS.",
      false,
      openCommercial.slice(1),
    );
  }
  if (!s.cleared_date) return step("Enter the Cleared Date", "Everything is ticked. Enter the date the goods left the CFS.");
  return step("Cleared, waiting to be invoiced", "Customs, line, DO and CFS are all done.");
}
