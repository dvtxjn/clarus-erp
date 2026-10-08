# Release notes

## v1.4.4 — tracker toolbar and page link
- Tracker: **+ Add Shipment** stays a visible button. Only while the peek is open does it move into **More ▾**.
- Page link: `?peek=` always matches the job showing in the peek, even after fast clicks or arrow keys. A slow load from the previous job can no longer overwrite the current one.

## v1.4.3 — bagdu's pass on v1.4.2
- Tracker with the peek open: the toolbar is one row (Live · search · **More ▾** · + Add). Group by, the column views and the other buttons are in More. **More ▾** opens on top and the peek stays open.
- Grid: only one cell is ever outlined, across all client tables.
- Rows with no job number: the Job cell shows a muted "—". The cell bar reads "Job (none yet) · BL 275469216".
- Billing settings: "Line cost" stays on one line, with the select beside it or under it. "Line paid by us" now reads "Shipping line paid by us".
- History: package counts are plain numbers (no ₹). IGM GW reads "141.715 MTS". Examination time reads "06 Oct 2026, 18:22".
- Documents: each group reads "Required 5/5 · + 4 optional".
- Key strip: "ETA → Inward" wraps instead of being cut.

## v1.4.2 — bagdu's live pass
- Peek: moving to a cell in another row (click or arrows) switches the peek to that job. Dragging a grid scrollbar or header no longer selects text across the page.
- Line cost: the Billing card and the Charges drawer now read the same setting. A value that matches the client is "client default", not "overridden". The select is wide enough for "Include (client default)".
- Key strip: BL, BE and container numbers wrap instead of being cut. "ETA → Inward" reads "06 Oct → 06 Oct".
- History: amounts read "₹7,53,687.00".
- Proforma: **Delete draft…** sits last, after Mark as Sent.
- Money card: "Line" now reads "Shipping line".
- Tracker: the INW "Pending" badge is centred and starts at the left edge.

## v1.4.1 — fixes from bagdu's review
- Peek: clicking outside while typing saves the field and keeps the peek open. A second click closes it. It never closes mid-edit.
- **Delete** leaves Job, MBL, HBL, BE No and BE date alone.
- **Esc** in a box cancels only that box (invoice amounts, receipts). The next Esc closes the layer. The confirm dialog's Esc closes only the dialog.
- View-only logins: the shipment page has no Edit, Upload, Fetch, Put back, tick-boxes or switches, and doesn't show as "on this page" to others.
- Gross Wt: typing a number over 1000 asks "Looks like kg — save as … MTS?" first. History shows weights as "270.033 MTS".
- Dates: one format everywhere ("27 Sep, 22:42", never "Sept"). A typed date with no year takes the year nearest today. "39" is no longer read as 3 Sep.
- Drive folder reader: after 10 s it says "Drive is slow — still reading…" and shows files as they arrive. **Retry** appears only once the read has ended.
- Documents: each group reads "required 3/4 + 1 optional".
- Narrow tracker (peek open): Column filters, Columns, Reset, Import and Admin tools fold into **More ▾**.
- Smaller fixes: the Charges drawer moves focus in and back, menus stack correctly, admin pages load on demand, and a view-only login can't connect the Gmail reader.

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
