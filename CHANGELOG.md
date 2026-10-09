# Release notes

## v1.7.7 — 9 Oct 2026

**Stamp duty reading, tested on 44 real receipts from Drive: 40 read, the other 4 ask for the amount.**
- Phone-camera scans (pages 3–5× normal size) are shrunk before reading. They read better and use less memory.
- Files holding several certificates (one payment, several jobs) are read page by page. The one for this job's BE is used.
- OCR quirks handled: "1.035" for 1,035, and the amount printed above its label.
- No amount is ever guessed: when the figure and the words disagree, it asks.

## v1.7.6 — 9 Oct 2026

**Stamp duty is checked against the receipt.**
- Upload the stamp duty receipt and the ERP reads the amount paid and the BE number.
  - Nhava Sheva MH challan: read from the PDF text.
  - Mundra SHCIL certificate (always a scan): read with free OCR on our own server. No outside service sees it.
- The amount counts only when the figure and the amount in words agree. Otherwise you're asked to type it.
- Duty tab → **Stamp duty**: Calculated vs Paid (receipt), with Edit for a misread amount.
- The reimbursement invoice won't issue until the receipt is attached, it's for this BE, paid = calculated, and the invoice's Stamp Duty line = paid.
- A mismatch is flagged on upload as well.

## v1.7.5 — 2026-10-09
- **Fixed invoice sections.** Bond and documentation charges always go under Billed by Clarus (taxable). Customs duty and stamp duty always go under Reimbursement. CFS can still go either way per shipment. The section picker is greyed out for these charges on proformas and on the Rates screen.
- The old "Bond Charges (Reimbursement)" charge is switched off; use Bond Charges. Existing proforma lines are not changed.

## v1.7.4 — 2026-10-09
- Settings → Invoicing: **Read interest on older OOC copies**. One click reads the INT figure on OOC copies uploaded before v1.7.2 and takes the interest out of the customs duty. Hand corrections stay.
- Fixed a test that failed after 6:30 pm IST: it stored a challan time in local time instead of UTC. The app itself was not affected.

## v1.7.3 — 08 Oct 2026

- Deploy: instant rollback. `bash deploy/gcp/rollback.sh` sends the ERP back to the previous version in seconds, with no rebuild. Every deploy now ends by printing which version is on standby and the exact rollback command.

## v1.7.2 — 08 Oct 2026

- Customs Duty is always the OOC copy's total duty, with no exceptions:
  - On the proforma it is filled from the OOC and can't be edited by hand.
  - On the reimbursement invoice the amount is locked to the OOC total. Any other figure is reset to it.
  - A reimbursement invoice with Customs Duty can't be issued until the OOC copy is attached.
  - Stamp Duty and the other lines stay editable.
- Interest is read from the OOC copy's own INT column. Duty without interest = OOC total − INT.
  - OOC copies uploaded before today: press Re-read on the OOC in Documents to pick up the interest.
- Charges tab: Customs duty is in two columns (Bill of entry on the left; licence and BE copies on the right). The tab fits on one screen.
- New "BE copies" section:
  - Shows whether the Assessed BE, OOC copy and Gate pass are attached.
  - "Upload BE" uploads a copy.
  - "Get from customs mail" attaches any BE PDFs already in customs mail for this job.
- CFS / Shipping line: once an invoice is attached, "+ Upload another invoice" adds more.
- Every green confirmation box across the app disappears after 3 seconds. Red errors stay until the next action.
- "BE location" (an ICD-internal code) is no longer shown.

## v1.7.1 — 08 Oct 2026

- Containers: the green confirmation ("Copied as an image…", "Saved…", "Set … days free…") disappears after 3 seconds. Red errors stay until the next action.

## v1.7.0 — 08 Oct 2026

- Shipment page: Customs duty, CFS and Shipping line are now one tab, "Charges", stacked top to bottom in that order.
- The Overview's status links (Duty "Details", CFS / Liner "Charges") open the Charges tab at that section.
- Old links to the separate tabs still work and land on Charges.

## v1.6.7 — 08 Oct 2026

- IGM & ICD details: the Vessel row (vessel code · IMO) is no longer shown. ICEGATE still reads it; it is just hidden.

## v1.6.6 — 08 Oct 2026

- Containers: the table is open by default everywhere, including the half-view panel from the tracker (it was folded there).
- Containers: "Reset all to 14" and the days box are the same size as the text around them.
- Shipment & movement: long IGM values wrap at the " · ", not in the middle of a date.

## v1.6.5 — 08 Oct 2026

- Customs duty tab: every row has the same copy button as Shipment & movement. Amounts copy as plain numbers (e.g. 189979.00), ready to paste.
- Customs duty tab: the duty shows in three rows, in order: Duty (without interest), Interest, Duty (with interest).

## v1.6.4 — 08 Oct 2026

- Overview rows: the labels are bold and the values plain.
- Shipment & movement: every row has a copy button on its right that copies the value as shown. Gateway IGM, IGM, ICD IGM and SMTP have two buttons, "No." and "Date"; the date copies as dd/mm/yyyy (e.g. 07/09/2026).

## v1.6.3 — 08 Oct 2026

- Red alerts (backups) now show as a box in the sidebar, under the menu, instead of a strip across the top. The collapsed sidebar shows a red "!"; phones keep the top strip.
- Shipment key strip: on narrower windows it shows two rows of four, so BE numbers and dates no longer break across lines.

## v1.6.2 — 08 Oct 2026

- Overview status box: the labels (Duty, CFS, Liner) are bold, the values are regular. "Shipping line" reads "Liner".
- Containers: the show / hide toggle and the summary sit in the heading row; the free-days note and the "Days free, all" control share one line. The section is two rows shorter.

## v1.6.1 — 08 Oct 2026

- Proforma & Billing: the Billing settings switches were drawn as squares; they are round toggles again.

## v1.6.0 — 08 Oct 2026

- Shipment page: Customs duty, CFS and Shipping line are now their own tabs, next to Overview.
- Overview: Shipment & movement runs full width (notes and short remark sit inside it), with containers below.
- The progress chart and the Duty / CFS / Shipping line status box show only on Overview.
- Billing settings moved into the Proforma & Billing tab.
- The section tabs run across the full page width, also when the Proforma preview is open.
- Documents: the group boxes (Basic, CFS / yard, Customs, Shipping line) are stacked in one column.

## v1.5.11 — Overview: IGM & ICD details back, no empty holes
- IGM & ICD details are open again at every screen width (they were folded shut below 1600px wide). The "IGM & ICD details" toggle sits at the left of its line, not in the middle. Fetch stays on the right.
- Overview, wide screens: two columns that end on the same line. Left: Shipment & movement with the IGM & ICD details. Right: Customs duty, Notes and Billing settings. Containers run full width under both. No more empty block under a short card, and no full-width Billing settings with its controls spread across the page.

## v1.5.10 — ↗ (open job) locked at the far left
- Tracker: the ↗ column that opens a job in the side pane is always the first column, at the far left of every table. It can't be dragged or unpinned, and no column can be dropped in front of it. A column layout saved earlier that had it elsewhere is put right on load.

## v1.5.9 — no progress chart on Proforma & Billing
- Proforma & Billing tab: the "Next" step and the clearance progress chart are hidden, so the invoice controls start higher. The key strip and the Duty / CFS / Shipping line box stay. The other tabs are unchanged.

## v1.5.8 — job in the key strip, status beside Duty
- Shipment page and peek: the job number is the first box of the key strip (Job · Client · BL · BE No…). The top of the page is now just the back link and the section tabs.
- The shipment's status (e.g. "OOC Done") sits beside the duty amount in the Duty row.

## v1.5.7 — client in the key strip; no gap beside Customs duty
- Shipment page: the client is the first box in the key strip (next to BL, BE No, Port…), with the company name in bold and the contact under it. The line under the job now holds only the section tabs.
- Overview, medium-wide screens: Notes sits under Customs duty, beside the taller Shipment card, and Billing settings takes the full row under them. No empty space beside Shipment & movement.
- Key strip: "ETA → Inward" breaks only at the arrow, never inside a date.

## v1.5.6 — shipment header: tabs up beside the client
- Shipment page: the job number and its status sit on the top line, with space between them. Under them, the client, then the section tabs (Overview · Customs timeline · Documents · History · Proforma & Billing) on the same line. This saves a row, and the tabs stay at the top.
- Tabs have no boxes, only the underline on the open one. Where the line is too narrow (e.g. beside the invoice preview), the tabs move to their own line under the client.

## v1.5.5 — one live invoice; the invoice takes the right half
- Proforma: each shipment has one live invoice (one each for seller and buyer on HSS), edited in place. No v1 / v2, no "New version" and no "Delete draft": an invoice is always made, so it can't be deleted. A sent copy is still kept under "Sent copies" when it's edited again. Copies replaced before this change stay read only under "Earlier copies".
- Proforma & Billing tab, wide screens: the invoice preview fills the right half of the page, top to bottom, and stays in place while you scroll. The job's cards and the proforma controls are on the left.
- The invoice page is never cut off at the side. "100 %" is now "Fit width" (as wide as the pane, up to full size), and the edit column (section + ✕) fits on the page.
- The actions box: four buttons in two rows, with the note across the full width under them.

## v1.5.4 — design fixes, checked on screen
- Shipment Overview, wide screens: cards end where their content ends. Billing settings no longer has an empty block at its bottom.
- Checklist chips: an unticked chip's label is centred. Ticked and unticked chips are the same width, so nothing moves when you click one.

## v1.5.3 — no gap in the Overview on wide screens
- Shipment Overview, wide screens: Notes sits under Customs duty in the middle column, and Billing settings has the right column to itself. The short Duty card no longer leaves an empty space.

## v1.5.2 — thinner cell outline
- The selected cell's outline is a crisp 1px line again, like Excel. Text still doesn't move when a cell is selected.

## v1.5.1 — checklist chips stay inside their column
- Ticking a chip (Duty / CFS Inv / Line / OOC / DO) no longer makes it wider. The ✓'s room is always kept, so a column fitted to unticked chips doesn't overflow once they're ticked.

## v1.5.0 — go-live sweep (bagdu)
- Checklist chips (Duty / CFS Inv / Line / OOC / DO): turning one ON is still one click. Turning one OFF asks first, e.g. "Mark Shipping line as NOT paid? Job 142 will move back to Ongoing." So does a last tick that moves a job to Cleared. Cancel changes nothing.
- The toast after a chip change or a **Delete** in a cell has **Undo** for about 10 s. It floats at the bottom, over the peek too. Undo (and Ctrl/⌘+Z) still works after the peek opens or closes.
- Search finds a job by any container number, full or part ("CAAU7596246" or "AAU7596"). It shows "3 of 190" and has a ✕ to clear (Esc clears too).
- Dashboard "Needs attention": a newer accepted B/E closes an older B/E rejection / negative ack. The same ICEGATE mail received twice shows once, and the ICEGATE tab counts jobs, so its number matches the list.
- Views: Movement shows BE No. Clearance: the "ICEGATE status" heading keeps its room when the view is fitted to the screen.
- Duty: one line, "Duty due ₹3,97,810 (incl. interest ₹3,564)", instead of a separate Interest row. Display only.
- Day counts say what they count: "Since inward" (key strip) and "Since arrival at CFS" / "at FPOD" (containers). The containers summary uses the rows' words: "21 days over free days".
- History: field names in plain words (BE date, IGST, OOC done, Notes) and dates with the year ("06 Oct 2026, 18:22").
- Customs mail and timeline: dates read "06 Oct 2026", ICEGATE's ALL-CAPS text reads in sentence case, and error codes (791_ITEMS, 413_LICENCE) get a plain line saying where to look.
- Small: "ETA next 7 days" chip; the Exceptions chip and an exception row's job number say what's missing on hover; dashboard "Containers in progress"; peek Notes says "Saves when you click away"; an empty date column filter no longer shows a clipped "dd/mm/yy"; **More ▾** has a divider above Reset / Import / Admin tools.

## v1.4.9 — old versions let go of the database after a deploy
- Each tab's live-update stream now reconnects by itself every 10 minutes, without a "Live" blink. An open stream used to keep the previous version's server running, with its database connections, for up to an hour after a deploy, so the database still ran out of connections after v1.4.8. Old versions now shut down within about 10 minutes.
- The live-update listener closes a broken database connection before retrying.

## v1.4.8 — database connections
- Fixed random "couldn't load" errors, the blank Cleared count and failed live-presence updates. The database (smallest Cloud SQL size, about 22 connections) was running out of connections: each app instance could open up to 16. Each instance now keeps at most 5 (plus 1 for live updates), checks a connection before using it, and the app runs at most 2 instances.

## v1.4.7 — peek never shows the old job under a switch
- Peek, switching to a job not opened yet: the old job fades to 40% at once and nothing on it can be clicked. A load that takes over 150 ms then shows the new job's header (job no · BL · client, from the row you clicked) with a spinner over a skeleton. Fast loads and jobs already opened swap straight in, with no flicker.

## v1.4.6 — bagdu's pass on v1.4.5
- After a deploy, a normal refresh opens the new version. If the first load still gets the old copy, the page reloads itself once. The "new version" banner is only for tabs left open.
- Grid: hovering the ↗ heading shows "Open job".
- Opening or closing the peek or a menu: no grid tooltip for half a second, and none until the mouse moves, so nothing pops up over a neighbouring row.
- A load that hits a network blip or a server switching over (e.g. during a deploy) retries once by itself before showing "Couldn't load · Retry".
- Live presence: after a failed update it waits 30 s instead of retrying every few seconds. A view-only login stops sending updates.

## v1.4.5 — bagdu's pass on v1.4.4 (polish)
- Tooltips: none is left floating after the peek, a menu or the Columns panel opens or closes, on scroll or on Esc. Grid tooltips don't show while a menu is open over the grid.
- **More ▾** reads as a menu: plain text rows with a hover tint. Group by and the views stay on top, and **+ Add Shipment** is last, after a divider, still green.
- Peek header: ✕ and "New tab ↗" stay in the same spot for every job.
- Grid: the open-job column has a ↗ heading with the tooltip "Open job".

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
