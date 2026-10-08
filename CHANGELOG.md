# Release notes

## v1.4.0 — Delete key, view-only logins
- Tracker: **Delete** clears the focused cell, like Excel. **Ctrl/⌘+Z** puts it back. Tick-box and Billed columns are left alone.
- View-only logins: the tracker and shipment page don't open editors, and Users hides passwords, roles and switches. A banner says the login is view-only. The server already refuses every change.
- Gross Wt on the shipment page: typing a plain number saves it as MTS, the same as the tracker cell.

## v1.3.1 — small fixes
- Documents tab: the count reads "Required 4/6 · + 2 optional", so optional papers don't look like gaps.
- Drive folder reader: stops waiting after 10 s and shows **Retry** instead of spinning forever.
- Proforma: **Delete draft…** is now a quiet red text button at the end of the draft actions (still asks to confirm). Billing logic is unchanged.

## v1.3.0 — UX amendment A
- Tracker works like Excel: **Space** opens the peek, **Enter** edits, **Esc** cancels or closes. Focus returns to the job cell.
- Peek: clicking outside closes it (clicking another row keeps it open). Jobs you've already opened show instantly from cache.
- Status pills are neutral with a coloured dot. Stepper icons are clean, and tabs are taller with a plain underline.
- Popovers animate in and sit above everything else.
- Long values that are cut off show the full text on hover (after 0.3 s).

## v1.2.0 — Money card and charge drawer
- The shipment page shows one **Money** card with Duty, CFS and Shipping line. Each row has a status dot and its total.
- **Charges** opens a drawer showing each invoice, with tick-boxes per charge, live totals, receipts and CFS TDS.
- "Not attached" rows have a one-click **Upload** that opens Documents with the right type picked.
- Line cost is pre-set to the client's setting: **Include / Leave out**, marked "(client default)" or "(override)".
- The tracker's open arrow is a small, quiet icon.

## v1.1.0 — front-end audit
- Every failed load says so and offers **Retry**. Nothing silently shows "nothing here".
- Dates use one format everywhere (03 Sep 2026), and you can type "3/9" or "3 sep".
- Esc closes only the top layer. Clicking outside closes menus. Key columns stay pinned.
