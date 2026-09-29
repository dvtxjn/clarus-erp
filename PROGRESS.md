# Build Progress Log

> **Code repository:** private GitHub repo `github.com/dvtxjn/clarus-erp` (branch `main`), pushed from this Mac with a repo-only deploy key (`~/.ssh/id_ed25519_clarus_erp`, set via `git config core.sshCommand` in this repo). Commit + push after every piece of work. Never in git (see `.gitignore`): `.env` files, `.local-credentials`, the database, `backend/storage/` (uploaded documents), `reference/` (client files). Data backups are separate — see DEPLOYMENT_PLAN.md phases 7-8.

> Read this first if you're picking this project up in a new session (Cursor,
> a fresh Claude conversation, or a human dev). It says exactly what's built,
> what's tested, and what's next — so you can continue without re-deriving
> decisions already made. `ERP_Spec.md` is the full requirements doc; this
> file is the "where are we right now" companion to it.

Last updated: this session (backend: dashboard/document-checklist/proforma
endpoints added and live-tested; frontend: Dashboard, Shipment Detail,
Document Manager, and Proforma & Billing views built on top of the existing
login + tracker grid).

**Full-stack verification (this session):** ran backend (`uvicorn`, :8000)
and frontend (`vite build` + `vite preview`, :4173) together. Frontend
builds with zero TypeScript errors. Backend `/health` and frontend root
both responded correctly. The OOC auto-naming/tracker-sync test below was
re-run and reconfirmed against a fresh SQLite DB.

---

## ✅ Find each shipment's Drive folder automatically (2026-09-29)

Client: staff name folders `JOB <job number> - <MBL/HBL>`; the ERP should find and link them instead of doing it by hand, verified against the job number.

- `src/folderMatch.ts` (pure rules): parse "JOB 129 - CSX26…" (also "JOB-129", "Job No 129", any case/spaces); a folder is **verified** (MBL or HBL in the name AND the same job number — `JOB 1290` ≠ 129), **no-job** (MBL/HBL, no job number), **job-differs** (MBL/HBL, other job number — flagged), **job-only** (job number but not the MBL/HBL — flagged). Linked automatically only when exactly ONE folder is verified; everything else is shown to choose.
- `googleDrive.ts`: `searchDriveFolders` (Drive API files.list, folders only, My Drive + Shared Drives, `name contains` each MBL / HBL / "JOB <n>") and `findFolderFor(shipment)`. The Google sign-in now also asks for **drive.metadata.readonly** (see names only — cannot open, change or delete anything) on top of drive.file; first use shows Google's consent again.
- Documents tab (no folder linked): **Find in Drive** → links the verified folder, or lists candidates with the reason and a Link button.
- Tracker toolbar: **Link Drive folders** → checks every shipment without a folder (3 searches at a time), links the verified ones (PATCH with base = still unlinked, so a folder someone just set is never replaced), and lists "to check" (with candidates), "not found", "failed".
- BE reader fix the same day: Gate Pass layout printed headings "/MAWBDT", "/HAWBDT" where the values go and they were taken as MBL/HBL — now rejected (must contain a digit, no MAWB/HAWB/DATE). Shipment 58's HBL cleared and nine local file names corrected.

---

## ✅ Documents: Commercial Invoice, digital vs scanned, background adding, duplicate invoices (2026-09-29)

- **Commercial Invoice** document type (prefix `CI`), required on every HS code's checklist (migration 0030; seed updated). Name guess: COMMERCIAL / CI / INV (after the CFS/line rules).
- **Digital or scanned** (`extraction/pdf_kind.py`, migration 0031 `shipment_documents.pdf_kind`): per page, ≥25 readable characters = text page → `digital` (all pages), `partly`, `scanned` (none), `unreadable`. Shown as a badge on every document and in the progress tray. Symbol-font PDFs (Navkar, U+F0xx glyphs) count as digital — `clean_pdf_text` decodes them. Backfill: `scripts/backfill_pdf_kind.py` (run: 10 digital, 5 scanned). **Scanned documents can't be read yet — the client is working on a fix (OCR later).**
- **Background adding** (`src/uploadQueue.tsx`, provider in App): uploads, single Drive picks and "pick from folder" all go into one queue (3 at a time), the dialog closes at once, a tray bottom-right shows progress / Digital-Scanned / errors with links to the shipment; the Documents tab refreshes when its files finish; closing the tab mid-way asks first. (Queue lives in the tab — a server-side queue would survive closing the tab; later if needed.)
- **Same invoice added twice counts once** (client: a CFS tax invoice was counted twice): `extraction/invoice_number.py` reads the invoice number (`Invoice No :`, `Proforma :`, `Bill No`) and the e-invoice IRN from CFS and shipping line invoices; `cfs_totals.duplicates()` keys on IRN, else type + number; repeats are left out of the CFS / line totals and marked `extraction.duplicate_of` → "Duplicate — counted once" badge + a note in the upload result. `scripts/backfill_invoice_numbers.py` ran: shipment 58 CFS total 94,400 → 47,200. Test in test_document_sync.

---

## 🟡 Launch Phase 7 — Google Drive storage (2026-09-29, branch `storage/phase-7`) — built, waiting for the real Shared Drive

**Client rule (2026-09-29): the ERP may only READ and SAVE in Google Drive — NEVER delete.** Enforced twice: the service account is a **Contributor** on the Shared Drive (Google refuses deletes/trash/moves), and `app/storage/drive_client.py` has no delete/trash/move method and refuses DELETE requests or any body setting `trashed`. Remove document = Drive file renamed `[removed] …` (restore renames back). Backups (Phase 8) are never pruned by the app. DEPLOYMENT_PLAN updated (Golden Rule 0, H4, Phase 7 item 4, Phase 8 item 3).

- `app/storage/__init__.py` (service) + `drive_client.py` (Drive v3 over httpx, service-account JWT via python-jose, Shared Drive flags). `STORAGE_BACKEND=local|drive` (local default; nothing changes until the keys are set).
- Every file is written locally first (working copy for the PDF readers), then saved to Drive: `Documents/<Client>/<MBL or Job>/<generated name>.pdf`. Generated PDFs: a proforma when marked **Sent** → `Invoices/Proformas/<FY>/`; a final invoice when **issued** → `Invoices/<FY>/` (`stored_files` table, one per kind+id, first saved copy is never replaced; local mode keeps them under `storage/generated/`).
- Folders: `drive_folders` registry (unique path), each level created in its own short transaction under `pg_advisory_xact_lock` → two simultaneous uploads for a new client make one folder (tested with threads on Postgres).
- Guard: every write names a parent that must be inside DRIVE_ROOT/INVOICES/BACKUPS (walks `parents`, caches proven folders); otherwise `OutsideRoot`.
- Drive failure never loses an upload: document saved + read as usual, marked `drive_sync_pending` with `drive_error`; `app/core/jobs.py` runs `storage.retry_pending` every 5 min (advisory-locked: one instance). Documents panel shows "not in Drive yet — retrying".
- A wiped local disk (redeploy) is fine: `storage.local_path(doc)` fetches the file back from Drive (view + re-read).
- New `GET /shipments/{id}/documents/{doc}/file` + **View** button (documents could not be opened in the app before).
- The old per-shipment "save to my Drive folder" (user's own Google token) now runs only when server storage is local.
- `scripts/check_drive.py`: checks key, three folders, Shared Drive, that the account can add but NOT delete/trash, and that the code refuses deletes.
- Migration 0028 (drive_folders, stored_files, document drive_sync_pending/drive_error). Tests `tests/test_drive_storage.py` (fake Drive; real guard + refusal). 109 pass on Postgres.
- Dev server must run with `--timeout-graceful-shutdown 3` (live streams keep connections open; without it a reload/deploy waits forever). Same flag for the production start command (Phase 10).

- **Staff-made shipment folders (client, 2026-09-29):** staff create each shipment's Drive folder by hand (ERP-created folders come later). Documents tab → linked folder bar → **Pick files from this folder**: Google Picker opens inside that folder with multi-select; a dialog lists the picked PDFs with a document type pre-guessed from each name (`src/docTypeGuess.ts`: OOC, BE/assessed, CFS PI/TI/receipt, SL invoice/PI/receipt, DO, empty, BL/HBL, PL, insurance, stamp, HSS, COO/FTA, Form 6/9; unsure → user picks, "Skip" ignores) and shows which required documents are still missing; "Add N documents" adds each via `/documents/from-drive` (read like an upload). Such documents are `drive_picked` (migration 0029): the ERP links to the staff's original — never uploads a second copy, never renames it (also on Remove). Needs the browser Google keys (`frontend/.env`: VITE_GOOGLE_CLIENT_ID, VITE_GOOGLE_API_KEY, VITE_GOOGLE_APP_ID — OAuth client "Web", origin http://localhost:5173, API key restricted to Picker API + the site, project number); without them the Drive buttons stay greyed out.

**To switch on** (client's Google setup, see chat 2026-09-29): Shared Drive `Clarus ERP` with `Documents`, `Invoices`, `Backups`; Cloud project with Drive + Sheets APIs; service account `erp-storage` → JSON key into `backend/secrets/` (gitignored); add it to the Shared Drive as **Contributor**; put the three folder IDs + key path in `backend/.env`; run `scripts/check_drive.py`; set `STORAGE_BACKEND=drive`. Existing local documents are not copied yet — a one-time upload script is still to write.

---

## ✅ Live tracker, Google-Sheets style (2026-09-29, branch `concurrency/phases-2-4-5-6`)

Client: "ideally it should work exactly like google sheets". Replaces DEPLOYMENT_PLAN Phase 5's 8-second polling with push.

- **Backend (`app/core/realtime.py`, `app/routers/realtime.py`):** a session `after_flush` hook turns every shipment change into `{t:"s", id, port, v, del, by}`. Postgres: `pg_notify('erp_changes')` inside the same transaction (sent only on commit, reaches every app instance); a LISTEN thread per instance feeds an in-process hub. SQLite: published after commit. `get_current_user` records the user on the session, so events say who changed it.
  - `GET /realtime/stream` — server-sent events, auth by header (fetch stream; token never in a URL), short-lived DB session (a stream never holds a connection), 15 s pings, port-scoped users only get their ports, `{t:"resync"}` on listener reconnect / overflow.
  - `POST /realtime/presence {shipment_id, field, editing, tab}` → `{t:"p", …}` broadcast.
- **Frontend (`src/live.ts`, ShipmentGridPage):** one stream per tab, auto-reconnect (then full reload). A change from someone else → fetch that row (API keeps port scoping) → replace in place if its `version` is newer → flash the changed cells. A row I'm typing in is left alone until I finish, then updated. Deleted → row disappears. Presence: my cell is sent on every move/edit + every 10 s (and cleared when the tab hides/closes); others show as a coloured outline on their cell (tinted while editing) and a name chip in the "● Live" bar; people fade after 25 s of silence. The 5-minute full refresh stays as a fallback.
- Conflicts: with live rows a clash needs two commits on the same cell within ~1 s; the Keep mine / Use theirs dialog stays for that case (switch to silent last-write-wins is one line if the client prefers pure Sheets behaviour).
- Tests `tests/test_realtime.py` (commit broadcasts with author, rollback and 409 broadcast nothing, presence, stream auth, port filter). 101 pass on Postgres. Checked live with two tabs: an edit in A appeared in B without reload; B showed A's cursor outline + name.
- Not live yet: shipment detail page / proforma panel (they refresh on open); the tracker is the shared sheet.

---

## ✅ Launch Phases 2, 4 (reduced), 6 (reduced) — multi-person editing (2026-09-29, branch `concurrency/phases-2-4-5-6`)

Client priority: several people editing at once must never lose each other's work.

- **Phase 2 — conflicts on tracker edits.** `shipments.version` (migration 0027, SQLAlchemy `version_id_col`: bumped on every write; a write based on a stale copy raises StaleDataError → global 409 handler, never a silent overwrite). `PATCH /shipments/{id}` accepts `base` = the values the user saw for the fields it changes (`base.custom_fields` per key). Inside the shipment lock: a field whose value moved since (and isn't already the new value) → 409 `{message, conflicts:[{field,current,yours,base,changed_by,changed_at}], version, shipment}`; nothing is written. Different fields never conflict; blank == null and 1500 == "1500.00". Without `base` = old behaviour (scripts).
  - Frontend: `useSaveShipment()` (src/useSaveShipment.ts) sends `base` from what the user saw and on 409 asks **Keep mine / Use theirs** (ConfirmDialog got `cancelLabel`). Used by the grid (cells + checklist chips), the shipment Overview (toggles, CFS billed-as, HSS, BE amounts), the exam reminder and the Drive folder bar.
  - **Undo/redo is now safe** (was Phase 5 item 1): it sends the value the change left as `base`; if someone changed the cell since → "…was changed by X since — not undone", and the entry is dropped.
- **Phase 4 — locks** (`app/core/locking.py`: `locked_shipment`, `lock_shipments` (id order), `locked_proforma` (shipment, then proforma); lock order per Golden Rule 9). Used by: shipment PATCH / delete / bill / unbill; document upload + from-Drive (file saved and PDF read BEFORE the lock, then one short locked transaction), re-read (read first), remove, amounts, cost inclusion; every proforma write (create, lines add/edit/remove, fill, restore, PATCH, delete) so autofill and hand edits never interleave; create final invoices; challan refresh (all matched shipments, id order); tracker CSV apply (`pg_advisory_xact_lock` + every shipment row locked in id order); bulk client/consignee rename; custom column delete.
  - Not done (Later per Fast Track): `version` + 409 on proforma lines (two people editing the same proforma line at the same instant — accepted risk, drafts only); CSV preview returning per-row versions.
- **Phase 6 — tests.** `tests/test_conflicts.py` (6, both DBs). `tests/test_concurrency.py` (Postgres only, real threads, `locking._race_pause` widens the race): 1 same field → one 200 + one 409, no lost update; 2 different fields → both saved; 5 autofill vs manual line edit → manual wins; 6 document upload vs manual edit → both survive. **Proved real:** with FOR UPDATE removed, 2, 5, 6 fail; with FOR UPDATE and the version check both removed, 1 fails. Tests 3-4 (invoice numbers) wait for Phase 3. Suite: 96 pass on Postgres; 92 + 4 skipped on SQLite.
- `docs/TWO_BROWSER_TEST.md`: 10-step manual check for two windows.
- Checked live in the browser: conflict dialog, Use theirs, Keep mine, undo refused after a colleague's change (test values put back).

---

## ⏸ Launch Phase 3 — deferred (2026-09-29)

Client: final invoices are issued through another software (LiveImpex) for now, so safe invoice numbering is not a concern yet. **Do Phase 3 before the app issues a real final invoice number.** Design already worked out: in one transaction lock the proforma row (`FOR UPDATE`, serialises a tax/reimbursement pair), lock the invoice and require `draft` (else 409), reuse the pair's seq or take `UPDATE invoice_counters SET next_seq = next_seq + 1 ... RETURNING`, then one guarded `UPDATE ... WHERE status='draft'` that sets status + number together (the Phase 1 trigger forbids changing a row after it is issued). Unique (fy, seq, kind). Same compare-and-set for cancel, bill/unbill, proforma Sent, create final invoices (lock the proforma).

---

## ✅ Launch Phase 1 (Fast Track) — data-safety rules (2026-09-29, branch `safety/phase-1`)

- **Invoicing is admin-only, including viewing** (client, 2026-09-29: "nobody else can even access view"). `require_billing_access` now means role = admin; the per-user `can_access_billing` flag grants nothing. Applied at router level to `proforma`, `final_invoices`, `challans`, `extraction` (orgs) — every route, reads included. Frontend hides Rates, Recently deleted, the Proforma & Billing tab and the Daily updates (challans / organisations) cards for non-admins; `/rates` and `/deleted` redirect them.
- **Soft delete** (`app/models/soft_delete.py`): `deleted_at` / `deleted_by_id` on shipments, shipment_documents, proformas, final_invoices. A session-wide `do_orm_execute` filter hides deleted rows from every ORM query, relationship load and `db.get`; `.execution_options(include_deleted=True)` to see them. `soft_delete(db, obj, user)` flushes and expires the session (already-loaded collections held the row).
  - Delete shipment / Remove document / Delete draft proforma / Delete draft final invoice (and drafts replaced on re-create) all soft-delete + audit. Removed files still move to `storage/_removed/<shipment>/` and `file_path` follows them.
  - Proforma version numbers count deleted drafts (never reused).
  - Tracker CSV import: a row matching a deleted shipment is skipped with a note (not re-created, not flagged missing).
- **Recently deleted** (admin): `GET /deleted`, `POST /deleted/{kind}/{id}/restore` + page `/deleted`. A document/proforma/invoice of a deleted shipment needs the shipment restored first; a draft invoice can't come back if its proforma already has a draft/issued one of that kind. Restoring an invoice document recalculates CFS / line totals and refreshes drafts.
- **Issued invoices locked in the database** (migration 0026): Postgres trigger `final_invoice_guard` / SQLite triggers. DELETE always refused (drafts too — they soft-delete). Issued: only `irn`, `ack_no`, `ack_date` change, plus issued → cancelled. Cancelled: frozen. Cancel records `cancelled_at`, `cancelled_by_id`, `cancel_reason` (reason box in the cancel dialog).
- **`backend/scripts/pre_migration_backup.sh`**: `pg_dump` → check non-empty + `pg_restore --list` → `alembic upgrade head`; stops on any failure. `AUTO_MIGRATE=0` turns off migrate-on-startup (production must set it). `backups/` is gitignored.
- **Audit log:** nothing purges it (Fast Track: keep every row). Not built yet (Later): `keep_forever` + purge job, APScheduler, soft delete for other tables.
- Note: 0026 reached the local `erp_db` via the dev server's auto-reload before a dump was taken (additive only; dump taken right after in `backend/backups/manual/`). Lesson: write migrations to the scratchpad, stop or dump, then move them in.
- Tests: `tests/test_data_safety.py` (8). 86/86 pass on SQLite and Postgres.

---

## ✅ Launch Phase 0 — Postgres locally + data moved (2026-09-29, branch `infra/postgres`)

- **Local Postgres:** Postgres.app (v18) on this Mac. Role `erp`, databases `erp_db` (the app) and `erp_test` (wiped by every test run). `backend/.env` now points `DATABASE_URL` at `erp_db`; `erp_dev.db` (SQLite) is kept untouched as a fallback. `docker-compose.yml` (Postgres 16) is there for machines with Docker.
- **Safety copy before the move:** `ERP CLAUDE/safety-copies/2026-09-29-pre-postgres/` (SQLite file + `storage/`), outside the repo.
- **Migrations fixed for Postgres (old files edited, unavoidable — a fresh Postgres failed before any new migration could run):**
  - raw SQL wrote booleans as `1`/`0` → `TRUE`/`FALSE` (0005, 0006, 0012, 0013, 0015, 0017, 0020, 0025);
  - enums are stored as plain text (`native_enum=False, length=40`) in 0001, 0014 and the models, exactly like SQLite already did. Adding a new document type / category never needs a migration. Longest value today is 25 chars.
- **`backend/scripts/sqlite_to_postgres.py <sqlite file> <postgres url>`:** opens SQLite read-only, refuses a target with any tables, refuses if SQLite isn't at the code's head migration or has unknown columns, builds the schema via the migrations, clears migration-seeded rows, copies every table in FK order, resets sequences, prints per-table counts (exit 1 on any difference). Run result: all 18 tables match (67 shipments, 99 orgs, 395 audit rows, 4 proformas, 21 lines, 2 final invoices, ...).
- **Tests on Postgres:** `TEST_DATABASE_URL=postgresql://erp:erp-local-only@localhost:5432/erp_test .venv/bin/python -m pytest` (database name must contain "test"; schema is dropped first). 78/78 pass on Postgres and on SQLite.
- **Checked live:** login, tracker (34 active + 33 billed), proforma PDF + Excel, final invoice PDF.
- `requirements.txt` gained `pypdfium2` (the Excel logo needed it but it was missing).

---

## 📝 Client feedback backlog (2026-09-27) — to prioritise, then build ONE BY ONE

Context: live tracker CSV imported locally (`python -m app.import_tracker_csv <csv>`,
re-runnable, upserts by MBL). Feedback after testing with it:

| # | Note (client) | Suggestion |
|---|---|---|
| A | **VERY IMPORTANT — tracker must have ALL CSV columns and work like Excel**: every cell editable inline, filters, no formulas except Days. No way to edit a shipment today. | Use **AG Grid Community** (free/MIT): inline editing, per-column filters/sort, column hide/reorder/resize, Excel-like keyboard nav + copy/paste. Each edit → `PATCH /shipments/{id}` (already audit-logged). Add missing columns: remark (separate from remarks), mbl date, hbl date, gw, total pkg, pkg code, line no, igm date, voyage, cont, billed?, shipping line. **Days** = computed, not stored: matches sheet as `today − INW + 1`, "Pending" if INW isn't a date (sheet shows "Pending" for some rows with an INW date, e.g. jobs 166/167/172 — confirm rule). Needs a small DB migration → set up Alembic now. |
| B | Status updates automatically when evidence is added (e.g. IGM no entered → IGM Filed); conditions will change; Playwright will verify later. | One `derive_status()` rule table (IGM no → IGM Filed, BE no → BE Filed, Duty paid → Duty Paid, OOC → OOC Done, container OUT/gatepass → Cleared), run on every edit/upload, forward-only (never moves status backwards on its own). Keep rules in one file so they're easy to change. Manual override still allowed. |
| C | Grid views + dashboard creation — tracker fully customisable. | Builds on A: save AG Grid column/filter/sort state as named **per-user views** (spec §2.5), switchable from a dropdown. Dashboards: user-created widget boards (count/breakdown/list widgets over any saved view). Do views first, dashboards after. |
| D | Ports: show names alongside codes. | `ports` lookup table (code → name, admin-editable), shown as "INMUN1 · Mundra". Seed: INMUN1 Mundra, INNSA1 Nhava Sheva, INDWN6 Panipat, INGHR6 Garhi — confirm names. |
| E | Rename "Upcoming ETAs" → **"UPCOMING SHIPMENTS"**. | Trivial. (Already fixed: excludes cleared + past ETAs.) |
| F | Doesn't understand how "Stuck" works. | Today: a manual yes/no flag + remarks text; stuck rows are highlighted and counted on the dashboard. Suggest either (a) drop it, or (b) make it a column toggle in the grid with a required "reason", optionally auto-flag (e.g. no status change in N days after ETA). Client to decide. |
| G | Uploaded documents must save to **Google Drive** — existing Drive, create a new subfolder for the app and clean it. | Today files save on the server disk: `backend/storage/documents/<shipment id>/<generated name>.pdf`. Approach: one dedicated app subfolder (e.g. `Clarus ERP/`) inside the existing Drive, with `/<Client>/<MBL or Job>/` folders under it; upload via the Google Drive API using a **service account** (or OAuth as a company Google account) that is shared only on that subfolder — so the app can never touch the rest of the Drive. Store Drive file ID + link on the document record; storage behind one interface so local-disk still works for dev. Client needs: which Google account/Workspace, and admin to share the folder. Don't "clean"/delete anything in the existing Drive from the app. |
| H | **Proforma: a tweakable, Excel-like view** where almost everything can be altered. (Notes only — don't start.) | After A (reuse the same grid tech): live invoice preview matching the .xlsm look, editable line items/rates/qty/descriptions/header fields, then export to .xlsx/PDF. |

**Agreed order:** E+D → A → B (✅ done, see below) → F decision → C (views) → G (Drive) → H (proforma view) → C (dashboards).

**B — status from evidence ✅** (`app/core/status_rules.py`, one RULES table): IGM no → IGM Filed · BE no → BE Filed · duty amount → BE Assessed · Duty Paid → Duty Paid · OOC → OOC Done · Cleared Date → Cleared. Adding evidence moves status forward (can skip steps); removing the evidence behind the current status moves it back to what's still proven; Billed untouched; a status set by hand in the same edit wins; Under OOC is manual-only. Applied on PATCH, on create, and after document uploads (forward only). Tracker toast shows "· Status → X". Existing data: only jobs 173 and 159 differed (had Cleared Date) → set to Cleared (audit-logged). Playwright/ICEGATE verification = later.

**Clearance rule (client, 2026-09-27):** Cleared = Cleared Date AND Duty, CFS Inv, Line, OOC, DO all ticked (`Shipment.is_fully_cleared` / `missing_for_clearance`, `CLEARANCE_FLAGS` in models/shipment.py; status rule + tabs + dashboard all use it). Cleared Date with anything missing = **clearance exception**: stays in Ongoing, amber row + "Missing: …" badge, banner on the detail page, dashboard card. Currently jobs 121 and 159 (both ticked Billed by the client — left as Billed).
**OOC detection:** BE uploads check for the "OOC COPY" marking. Uploaded as Assessed but is an OOC copy → refiled as OOC BE (type + file renamed) and processed as OOC. Tagged OOC but no marking (and text readable) → OOC not ticked + warning.
**F — Stuck: dropped** for now (column, filter, dashboard card, banner removed; `is_stuck` DB field kept).
**Proformas:** `DELETE /proformas/{id}` deletes DRAFT versions only (sent/superseded kept as history), audit-logged; "Delete draft" button. Template (`reference/…flexible.xlsm`) splits charges into "Billed by Clarus" (Agency/Other/Exam/Bond/Documentation + 18% GST) vs "Reimbursement (actuals)" (Custom Duty, Stamp Duty with per-port formula INMUN1 = ROUNDDOWN(0.1% × assessable), INNSA1 = CEILING(0.1% × (assessable + duty)), CFS rounded up, Royalty, Insurance, GST Difference from HSS bill rate), plus Cost Inclusion (shipping line). That's the taxable-vs-pure-agent split to build into H.

**Shipping line destination charges invoice (imports):** new doc type `SHIPPING_LINE_INVOICE` ("SL-DSC"), required on the checklist (migration 0012). Per-invoice amounts like CFS (best-effort read — no sample yet; editable); shipment `line_amount_*` = sum → the proforma's "Cost Inclusion: Shipping Line". Totals logic generalised in `extraction/cfs_totals.py::recompute_invoice_totals`.
**Confirm dialogs:** `window.confirm` was blocked in the client's browser (Delete draft silently did nothing) → `ConfirmDialog.tsx` (`useConfirm()`), used for delete draft / remove document / delete column / merge clients. Don't use window.confirm/prompt/alert.
**HSS:** `Shipment.is_hss / hss_seller / hss_buyer` (migration 0013, backfilled: 28 shipments — Earthman/Earthstar/HKR → Mahrishi). Rule: consignee with '-' = HSS, seller = before, buyer = after; re-derived when consignee changes (edit, rename-value, import) unless HSS fields set explicitly; switch + editable parties on Overview; HSS column in tracker. Proformas on HSS shipments must be for "seller" or "buyer" (`bill_to_role`, `bill_to`) — "+ Seller invoice" / "+ Buyer invoice"; normal shipments bill the consignee.
**H — Proforma invoice ✅ (2026-09-28):** charges carry a section (`ChargeCategory`: service = "Billed by Clarus", reimbursement = "Reimbursement (at actuals)", cost_inclusion = shown, NOT in the grand total) on the charge master and each line (migration 0014; lines also `gst_is_actual`, `sort_order`). `app/invoice/` — `build.py` (invoice JSON in the template layout: bill to, details, reference block, 3 sections + subtotals, grand total, notes, bank), `xlsx.py` (openpyxl), `pdf.py` (reportlab, now a runtime dependency), `company.py` (issuer/bank/notes/colours from the template). Endpoints: `GET /proformas/{id}/invoice` (JSON), `/invoice.xlsx|.pdf` (file named "{bill to} - {MBL} - {BE} - proforma[ (buyer copy)].ext", `X-Filename` header), `PATCH /proformas/{id}/line-items/{li}` (description/rate/qty/GST/section; GST null = back to rate × amount), `POST /proformas/{id}/fill-from-shipment` (Agency + Exam per container at default rates, Customs Duty = duty − IGST with IGST as GST, Stamp Duty by port formula, CFS if paid by us (total rounded up), shipping line as cost inclusion; returns added/skipped). UI (`ProformaPanel.tsx`): invoice sheet in the template look, draft cells click-to-edit (Enter/Esc), move line between sections, remove, Fill from shipment, Download Excel/PDF, Mark as Sent. **Bill To = BE importer** — for HSS always the buyer (after the "-"), both seller and buyer copies. Open: taxable vs pure-agent per charge (client's bills), royalty per kg / GST difference lines, saving the generated file when Sent (and to Drive).
**Proforma calc rules + daily updates ✅ (2026-09-28, from the client's sample "MAHRISHI RECYCLERS - OOLU2331734970 - 3496326 - expense sheet.xlsm" — `test_sample_hss_invoice_matches_client_sheet` reproduces its grand total ₹6,76,843 exactly):**
- Customs Duty total = BE total duty + interest; interest = latest duty challan Due Amount − BE duty (never < 0); GST column = IGST; basic = total − IGST; description shows the interest.
- Stamp Duty: INMUN1 ROUNDDOWN(0.1% × assessable); INNSA1 CEILING(0.1% × (assessable + customs duty total incl. interest)); any other port (ICDs / dry ports) = none (skipped with a note).
- Royalty (`ROY`, per kg of BE gross weight, default ₹0.75/kg, 18% GST, total rounded up) — HSS shipments only (hidden / refused otherwise). CFS & Royalty totals round up.
- Value section (template rows 37-38) on screen + Excel + PDF: value of goods = assessable + every line's basic (incl. cost inclusion, excl. GST Difference); GST input = all GST; value/kg; bill rate (per proforma, `Proforma.bill_rate`, typed in); GST output = 18% × bill rate × weight; GST Difference = max(0, output − input) → automatic `GSTD` line in Reimbursement (removed when bill rate is cleared).
- "Fill / refresh from shipment" also REFRESHES existing Customs Duty / Stamp Duty lines (new challan → new interest) and reports them.
- **Duty challans** (`duty_challans` table, `routers/challans.py`): dashboard card — upload the daily ICEGATE pending-challan .xlsx (IEC, Location Code, Doc type, Doc no., Doc date, Challan no., Due Amount) or enter one BE by hand; every upload kept, latest row per BE wins, matched to shipments by BE no at read time. Amber reminder when not uploaded today; proforma shows whether its interest is from today's challan. **Need a real challan export from the client to confirm columns.**
- **Organization repository** extended (short names, GSTIN, PAN, IEC, address, state, email, phone; AD code optional; `updated_at`): dashboard card to add / edit / import; Bill To shows the org's details, matched by name/short name/prefix (e.g. "Mahrishi" → "MAHRISHI RECYCLERS") or picked per proforma (`bill_to_org_id`); "Add details" right from the invoice.
- Colour scheme: Clarus orange #D26B21 on warm neutrals across the app, AG Grid and the invoice (Excel/PDF: charcoal bars, peach headers, orange grand total).
- **Bill To (client, corrected 2026-09-28): always the BE importer** (importer name read from the latest Assessed/OOC BE; tracker buyer/consignee only until a BE is read); details from the org repo matched on that name (loose: case, punctuation, PVT/PRIVATE, LTD/LIMITED, M/S) or picked per proforma. **BL consignee = the org holding the BE's AD code** (else the tracker consignee). **Seller copy** (HSS) carries a highlighted line under the title: "<BL consignee> to pay <BE importer>".
- Open: "Other Fees" = 0.25 × weight + 1,00,000 in the sample (entered by hand for now).

**Shipping line invoices + customs duty source ✅ (2026-09-28, samples: Maersk tax invoices HR27IN3500038423 / …39011 for BL 274014260 — two invoices per BL is normal — and a Cordelia proforma):**
- `extraction/shipping_line_pdf.py`: carrier, invoice no, proforma?, BL, totals (Maersk "Total Base Amount / Total taxes / Total Payable Amount", Cordelia "Taxable Amount / SGST+CGST lines / Total Amount", generic fallbacks) and charge lines (Maersk row layout, Cordelia amount-first layout) with currency, INR amount, GST. Add patterns per new line as samples come ("training" = adding layouts; learning-from-corrections still an option).
- **Cost inclusion rule (client):** a charge counts only if BOTH: billed in INR AND charge head isn't freight (FREIGHT/BAS/BAF/bunker/PSS/GRI/LSS/origin…). Inland haulage counts. INR-but-freight-named lines are left out and flagged "check". Per invoice `ShipmentDocument.cost_before_tax/cost_gst/cost_excluded/cost_manual` (migration 0016); shipment `line_amount_*` = sum of each invoice's cost inclusion. Overview: tick charge lines in/out, "Type figure" (manual override), "Reset". `PATCH /shipments/{id}/documents/{doc}/cost-inclusion`.
- Upload notes: BL mismatch vs tracker; lines left out; lines to check; charge lines not adding up.
- **Customs duty source:** 1) duty challan (BE duty + interest), 2) no challan → OOC copy's total (final paid; interest = OOC − assessed), 3) BE duty. Shown on the proforma notice.
- **No challan and no OOC = the user must be told** (client): red "Upload the duty challan" alert on the proforma, "ACTION NEEDED" in Fill/refresh results, a confirm before Mark as Sent, and the Dashboard challan card lists every ongoing BE without a challan or OOC copy (`/daily-updates` → `awaiting_challan`). Automatic challan fetching = Playwright job, later.

**Receipts, shipping line proformas, paid-by-us rules ✅ (2026-09-28):** new document types Shipping Line Proforma (SL-PI), Shipping Line Receipt (SL-RCPT), CFS Receipt (CFS-RCPT) — optional on the checklist (migration 0017); "Shipping Line Destination Charges Invoice" is now labelled Tax Invoice. Shipping line totals follow the CFS rule (tax invoices, else proformas). Receipts = amount actually paid (`extraction/receipt_pdf.py`, best effort — no sample yet; editable), listed under each Overview group; a shipping line receipt ticks Line Paid. **Shipping line always Cost Inclusion unless `line_paid_by_us`** (then Reimbursement). **CFS paid by us** → `cfs_billed_as`: "reimbursement" (at actuals, CFS invoice GST) or "taxable" (Billed by Clarus, our 18% GST on the basic). Toggles on the Overview.

**Draft proformas update themselves ✅ (2026-09-28, `app/invoice/autofill.py`, migration 0018):** after any document upload / re-read / removal / amount or cost-inclusion edit, duty challan upload, or shipment edit of a proforma input (paid-by-us switches, CFS billed as, duty figures, port, BE no, containers, under examination), every DRAFT proforma of the shipment refreshes its derived lines: Customs Duty, Stamp Duty, CFS, Shipping Line, and Examination (added to Billed by Clarus while under examination, removed when not). Lines edited by hand (`is_manual`, ✎ on screen) are never touched; removed derived lines are remembered (`Proforma.suppressed`) until "Fill / refresh" is pressed. Agency / Royalty only via the button. **Shipping line = ONE line: total of the selected charges of all counted liner invoices, SAC column "Liner Inv"** (client, 2026-09-28). Grand total label (every HSS shipment): seller invoice "<seller> pays <buyer>", buyer invoice "<buyer> pays CLARUS LOGISTICS LLP" (seller = AD-code org, else HSS seller); non-HSS "<importer> pays CLARUS LOGISTICS LLP". Line helpers moved to `app/invoice/lines.py`.

**Proforma usability ✅ (2026-09-28):** removed document-derived lines are listed on the draft with **Restore** (`POST /proformas/{id}/restore {key}`); the add-line form offers **Add from documents** for Shipping Line / Customs Duty / Stamp Duty / CFS / Examination; charge list shows standard rates ("std ₹7,000 / container") and picking a charge fills its standard rate (editable). Stored `Proforma.bill_to` kept = BE importer on every refresh. **Tracker undo:** own undo/redo stack (Ctrl/⌘+Z, Ctrl/⌘+Shift+Z or Ctrl+Y; last 50 saved cell edits + checklist chips; re-saves the old value, audit-logged) — AG Grid's built-in undo was lost on every row refresh. Not click-tested (grid doesn't paint in a background tab).

**Standard rates screen ✅ (2026-09-28):** top-nav **Rates** (`RatesPage.tsx`, billing users see it, admin edits): every charge's section, basis, SAC, GST %, standard rate, active/retired, edited in place (saves on Enter / leaving the box, audit-logged); "+ Add charge". Document-derived charges (CD/SD/CFS/DO/GSTD) show where their figure comes from instead of a rate. API: `GET /charge-master?include_inactive=true`, `PATCH /charge-master/{id}`, `POST /charge-master` (admin). Standard rates now: Agency 7,000/container, Examination 18,000/container, Bond (SBOND) 1,500, Documentation (DC) 1,500 (migration 0019), Royalty 0.75/kg. Existing proforma lines keep the rate they were made with.

**HSS rules + Royalty section ✅ (2026-09-28, migrations 0020–0021):** new invoice section **Royalty** (between Reimbursement and Cost Inclusion; counts in the grand total; hidden when empty) — the royalty is paid by the seller to the buyer. `PricingRule` (`pricing_rules`): per seller → buyer pair (buyer = BE importer; seller blank = any seller, a seller-specific rule wins) and per copy (seller / buyer), lines of ₹/container × containers + ₹/kg × weight + flat (+ optional section). "Fill / refresh" uses the matching rule instead of the standard Royalty rate. Rates page → **HSS rules**: both copies side by side, editable, with a same-total check for a sample containers/weight. Seeded Mahrishi rule (client): seller copy Royalty 1/kg + Other Charges 20,000/container; buyer copy Royalty 0.75/kg + Other Charges 20,000/container + 0.25/kg (same total; reproduces the client's sample sheet). API `GET/POST/PUT/DELETE /pricing-rules`.

**Licence rates + pre-filled proformas + suggested bill rate ✅ (2026-09-28, migration 0022):** `Licence` (`licences`, belongs to the BE importer): rate rows {code, seller?, port?, per_container, per_kg, flat, category?}; per charge the most specific row wins (seller+port > seller > port > any); seller = HSS seller (rates follow the seller on HSS). Closed licence → standard rates. **New proformas are created already filled** (licence rates, HSS rule, documents) with a "review" note; Examination at the licence rate while under examination; an HSS rule's lines win over the licence's for the same charge. Rates page → **Licences** editor; API `GET/POST/PUT /licences`. Client rates: 111022154 MAHRISHI (Agency 7,000/cntr; Exam per container INNSA1 2,000 / INMUN1 3,000 / INDWN6 3,000; Bond + Doc 2,000 each for HKR, 1,000 each for Earthman / Earthstar; Other per HSS rule) · 111035337 Devine (Agency 7,000/cntr; Exam 3,000 flat) · 111035316 Earthman (Agency 7,000/cntr; Exam by port as above) · 111021955 Home Zone (Agency 7,000/cntr; Other 20,000/cntr; Exam 3,000 flat) · 111021207 Devine — closed. Client confirmed: Agency 7,000 per container; port exam rates per container ("flat 3,000" licences left flat). **Suggested bill rate** (`suggest_bill_rate`): ≥ value/kg + ₹0.10 and GST difference > 0, rounded up to the next ₹0.25 (11.80→12.00, 12.15→12.25); pre-filled on HSS proformas once the BE figures are in, "Use" link otherwise.

**Invoice output ✅ (2026-09-28):** PDF always ONE A4 page (whole invoice in a KeepInFrame that scales down if needed), no word ever split (long values shrink their font instead; `splitLongWords=0`), compact layout (one charges table with section bars, notes beside bank details), Clarus logo (vector wordmark + arrow) in the header of the PDF and the Excel (rasterised via pypdfium2); Excel prints fit-to-one A4 page with wider amount columns. HSS copies are labelled by the party's first name — "PROFORMA INVOICE — FOR HAREKRISHNA" / "FOR MAHRISHI", file "… proforma (for Harekrishna).pdf" (`build.copy_for`) — not seller/buyer copy. **Grand total rounded to the rupee** with a "Round off" line (`build.round_off`); lines keep exact paise; Royalty no longer rounded up per line (only CFS is), so both HSS copies end on the same amount (job 129: ₹7,20,403 on both).

**Final invoices ✅ (2026-09-28, migration 0023; samples CL/200/26-27 + RI/CL/200/26-27 in the client's Downloads):** from any proforma, "Create final invoices" makes DRAFT **Tax Invoice** (only Billed by Clarus lines, T, our GST — IGST inter-state / CGST+SGST when customer state = 27) and **Reimbursement Invoice** (only Reimbursement lines = paid by us, P pure agent, no GST, full amount incl. GST paid; GST Difference excluded). Royalty + Cost Inclusion not invoiced by Clarus. Content as the client's invoices: customer (name, address, PAN, GSTIN, state), place of supply, invoice/due date, job no (IMP/0165/26-27 from tracker job + FY), job type, shipment block (BE no/date/type, MBL/HBL + dates, consignment, packages, weights, custom house, vessel/voyage, origin, customer ref, supplier invoice no/date/value/terms, CIF / assess value, total duty, shipper, BE heading, containers), lines with SAC + tax type + non-GST / taxable / GST, SAC summary, totals (before tax, GST, invoice value, less advance, round-off UP, net payable, reverse charge), amount in words (Lakh/Crore), bank, terms (4), company CIN, IRN/ACK. Draft = every field editable (audit-logged); **Issue** = number from the FY series (pair shares n; `invoice_counters`, next = 201 for 26-27, editable on Rates page) + lock (IRN/ACK still editable); **Cancel** (admin) keeps the record, number never reused. PDF one A4 page (`app/invoice/final_pdf.py`). Files: `models/final_invoice.py`, `invoice/final.py`, `routers/final_invoices.py`, `FinalInvoicesPanel.tsx`. Shipment block trimmed (client): BE No, BE Date, MBL, HBL, No. of Containers, Port of Origin (typed in; not on the BE read yet). Proforma print: no Rate × Qty column; grand total always rounded UP to the next rupee.

**Client decisions — pending, don't build yet (2026-09-28):** client will send an updated organisation list with full details (addresses etc.) to import; invoice numbering to be designed with a dedicated Invoices section where all final invoices live, in order.

**Google Sheets tracker CSV re-import ✅ (2026-09-28, migration 0025; `app/tracker_import.py`, `routers/tracker_import.py`, `TrackerImportPanel.tsx`):** Shipments page → "Import sheet CSV" (admin) → preview (new / updated field old→new / kept / missing / unknown columns; nothing saved) → Apply (same file). Sheet wins over app edits; **BE data wins** (with an uploaded Assessed/OOC BE: BE No, BE Dt, port, MBL, HBL, containers, gross wt kept; OOC copy keeps OOC / Duty Paid ticked); app-only data untouched; shipments not in the CSV get `missing_from_sheet_at` ("not in sheet" badge in the MBL cell) — never deleted, cleared when they reappear. Matching MBL → HBL → BE No → Job (last two marked "check"). "MBL/HBL" cells split at "/"; an HBL column in the sheet is used if present; existing 13 combined cells split by the migration and the HBL tracker column restored. "billed?": Yes bills, explicit No un-bills, **blank = leave billing alone** (the sheet's billed? is mostly blank). Status via the evidence rules; every change audit-logged. Old 27-Sep CSV previewed against the app: 63 unchanged, 4 would revert app edits (not applied).

**Organisation list import fixed (2026-09-28, migration 0024):** reads the filing software's real export (OrganizationRepository_*.xlsx: header on row 3; Branch AD1-3 + City + State + Postal Code + Country → address; ALIAS → short names; IE CODE NO, PAN NO, GSTIN, Email, Telephone/Contact Mobile, Is Active); all rows imported (not only those with AD codes), matched by name; AD code no longer unique (Earthman + Earthstar share 0511029 — BL consignee picks the one matching the HSS seller). Imported: 99 orgs, all with addresses, 36 with GSTIN.

**Proforma names:** `Proforma.name`, "Rename" button; `PATCH /proformas/{id}` now takes any of status / name / bill_to (audit-logged).

**Done (2026-09-27):**
- **E+D** — dashboard says "Upcoming Shipments" (excludes cleared/past, shows MBL when no job no). New `ports` table + `GET/POST/PUT /ports`, seeded INMUN1 Mundra / INNSA1 Nhava Sheva / INDWN6 Panipat / INGHR6 Garhi (confirm names); shown as "INMUN1 · Mundra" on dashboard, grid, detail.
- **A** — `ShipmentGridPage.tsx` rebuilt on AG Grid Community: all sheet columns in sheet order (+ HBL, Port, Stuck), double-click to edit any cell, saves per cell via PATCH (audit-logged), reverts on error, Ctrl/⌘+Z undo, per-column filters + sort, search-all box, column width/order/sort remembered per browser (localStorage — becomes saved views in C). Day is computed (`Shipment.days`), read-only. New columns: remark, mbl_date, hbl_date, gw, total_pkg, pkg_code, line_no, igm_date, voyage, cont, shipping_line. Job may be blank.
  - Not in AG Grid Community (Enterprise-only): multi-cell paste, fill handle, column chooser sidebar, set (checkbox-list) filters. Revisit if needed.
  - **Views:** "By client" (default — one table per client, A–Z, heading bar per client, earliest ETA first, blank ETAs last) and "All shipments" (one table). Built from free AG Grid parts: a sticky header-only grid holds the column titles/filters/sort and copies them to every client table; all tables are `alignedGrids` so widths/order/horizontal scroll stay in sync. Choice remembered per browser. Named custom views = item C.
  - **Ongoing / Cleared tabs:** Ongoing = no Cleared Date (and not archived) — client/all views as above. Cleared = has a Cleared Date (incl. billed/archived), one table per clearance month (oldest first), sorted by Cleared Date, NOT by client; Cleared Date + Billed? moved next to MBL; each month bar shows "N billed". Removing a Cleared Date moves the row back to Ongoing. Dashboard "Ongoing shipments" + "Cleared this month · N not billed" card (links to Cleared tab). Layout saved per tab.
  - **Columns panel** (`ColumnsPanel.tsx`): hide/show per user (saved in layout); admin can add custom columns (text/date/number/yes-no → `Shipment.custom_fields` JSON, `tracker_columns` table, migration 0003), delete custom columns (deletes their values), remove built-in columns for everyone (data kept, restorable). API: `/tracker-columns` (GET/POST), `PATCH|DELETE /tracker-columns/{key}`, `POST /tracker-columns/remove-builtin`, `POST /tracker-columns/restore-builtin/{key}`. Custom values edited via `PATCH /shipments/{id}` `{"custom_fields": {key: value}}` (merged, audit-logged as `custom:<key>`). Removed per client request: **BE Description, HBL** (HBL goes in the MBL cell after a slash; MBL cell now wraps so nothing is cut).
  - **Compact layout** (~3,850px → ~2,470px wide, no columns removed): tighter widths + 12px font, two-line wrapped headers, short dates (27-Aug-26), Day shown as a badge inside the INW cell, POD+Port merged into one "POD" column (port select with names; raw `pod` text kept in DB, not shown), the 5 Yes/No flags shown as one "Checklist" column of click-to-toggle chips (filter e.g. `OOC:N`). Copyable identifiers (MBL, BE No, IGM, Cntr…) stay single-value cells. **Ctrl/⌘+C copies the focused cell** (clipboard API with execCommand fallback).
  - **Add Shipment form:** Client and Consignee are dropdowns of existing names (case-insensitive de-dupe) with "+ Add new…" → text box.
  - Also removed (client request, restorable): MBL Date, HBL Date, GW, Total Pkg, Pkg Code, Line No, IGM Date, Voyage, Cont.
  - **Document reading on upload** (`extraction/document_extract.py` + rewritten `tracker_sync.py`): Assessed/OOC/Gatepass BE → BE no/date, port, MBL, (HBL), containers, gross wt fill BLANKS only (mismatches reported, never overwritten; MBL-contained-in-'MBL/HBL' counts as match; gross wt/containers never flagged — tracker uses MTS, BE uses kg), assessable value/IGST/duty always updated. OOC BE → OOC ✓, Duty Paid ✓, OOC date, examination from the **'H. PROCESSING DETAILS' table read by word position** (Examination row has a date = examined; plain text is scrambled by the watermark) — verified on a real OOC copy (job 121). CFS proforma/tax → CFS amounts (+ sanity check); tax invoice → CFS Inv ✓. DO / DO+Empty → DO ✓. Gatepass → Cleared + Cleared Date. Status only moves forward. Upload response + UI banner show what changed and any warnings; stored on `ShipmentDocument.extraction`. Migration 0004.
  - **Document checklist changes:** new types Form 6 & 9 (merged), HSS Agreement, Stamp Duty (separate), DO + Empty Letter (one file, satisfies both rows); old HSS&Stamp / Form 6 / Form 9 kept as legacy (hidden from upload). `RequiredDocument.optional`: Empty Letter, Insurance, HBL Copy, HSS Agreement, Stamp Duty, FTA COO, CFS Proforma, CFS Tax Invoice are optional (listed, not flagged missing). Migrations 0005/0006 update existing HS codes.
  - **Shipment detail page:** BL No and BE No · BE Date shown as the two big key cards; flags show red ✗ "Pending"; new Duty & CFS amounts card; OOC date + Examination; page reloads after an upload.
  - **Grid:** every column wraps (row grows) so nothing is cut; INW·Day and Checklist widgets wrap inside their cell.
  - **Data fix:** consignees merged to "Earthman - Mahrishi" (14) / "Earthstar - Mahrishi" (3); `POST /shipments/rename-value` (client|consignee); CSV importer normalises hyphen spacing in names.
  - **CFS / TDS flags:** `cfs_paid_by_us`, `tds_deducted` (TDS cut on the shipment), `tds_on_cfs` (we cut TDS on the CFS payment) — migration 0007. Tracker "CFS / TDS" chip column (filter e.g. `TDS:Y`), switches on the detail page. CFS paid by us ⇒ CFS Tax Invoice becomes required on that shipment's checklist.
  - **Logo:** `ClarusLogo.tsx` (vector recreation of the client's wordmark, brand orange #D26B21, Inter 800) in the top bar + login; orange ↗ favicon; page title "Clarus ERP". Swap in the original SVG/PNG when the client sends the file.
  - **Choose from Google Drive** (Documents tab): Google Picker in the browser with a `drive.file` token (app can only open the files the user picks) → `POST /shipments/{id}/documents/from-drive {document_type, file_id, access_token}` → backend (`integrations/google_drive.py`) fetches the PDF once (token not stored), then same naming/reading/tracker-update as an upload; `ShipmentDocument.drive_file_id/drive_link` kept (migration 0008), "open in Drive ↗" link in the checklist. Button is disabled until configured. **Setup needed (client's Google account):** Google Cloud project → enable Drive API + Google Picker API → OAuth consent screen (Internal if Workspace) → OAuth client ID (Web, authorised JS origin http://localhost:5173 + prod URL) → API key (restrict to Picker API + those origins) → put `VITE_GOOGLE_CLIENT_ID`, `VITE_GOOGLE_API_KEY`, `VITE_GOOGLE_APP_ID` (project NUMBER) in `frontend/.env`, restart `npm run dev`. Auto-saving uploads into Drive = backlog item G.
  - **Gross weight:** the BE's GW is always taken as correct and overwrites the tracker, converted to the sheet's format (kg → "84.885 MTS", half-up to 3 dp).
  - **CFS payment after TDS** (`Shipment.cfs_tds_amount` / `cfs_payment_after_tds`, computed): only when CFS is paid by us — TDS = 2% of basic (when "TDS on CFS" is on; switching "CFS paid by us" on turns it on by default), payment = basic + GST − TDS. Not paid by us → detail page says "invoice only". Rate constant `CFS_TDS_RATE` in `models/shipment.py`.
  - **Shipment Drive folder** (`drive_folder_id/link`, migration 0009): Documents tab bar — "Choose folder" (Drive picker; this grants the app write access under drive.file) or paste a folder link (stored + shown, but saving into it needs the folder chosen via the picker). Uploads are then also saved into that folder with the generated name (`google_drive.upload_pdf`, token sent per upload, never stored); a Drive failure never loses the upload — it's noted in the result banner. "Choose from Google Drive" opens in the shipment's folder.
  - **Proforma examination reminder:** banner on the Proforma & Billing tab — under examination (from the OOC copy's exam date, or switched on by hand there) → "add the Examination charge" + button that pre-selects charge code EC with its default rate; turns green once an EC line is on the proforma. `under_examination` is PATCH-able.
  - **Symbol-font PDFs fixed:** "Microsoft Print to PDF" invoices (e.g. Navkar CFS tax invoice) store every character shifted into U+F020–U+F0FF, so pdfplumber saw no readable text. `be_pdf.clean_pdf_text` / `read_pdf` shift them back; used by every PDF reader (BE, CFS, batch scan, upload). A CFS invoice with no readable amounts now shows a warning instead of silently doing nothing. New `POST /shipments/{id}/documents/{doc_id}/reread` + "Re-read" link in the checklist to re-process an existing upload.
  - **Remove document** (admin only): `DELETE /shipments/{id}/documents/{doc_id}` — file moved to `<storage>/_removed/<shipment id>/`, not destroyed; removal audit-logged; shipment fields it filled are left as-is; Drive copy untouched. "Remove" link in the checklist. Used once: removed job 129's duplicate CFS proforma (same file as its tax invoice).
  - **Under examination switch** also on the Overview tab (Status card); shows "Yes (marked by hand)" when set without an OOC exam date.
  - **Correcting misread figures:** BE amounts (assessable value, IGST, duty) editable on the Overview (PATCH shipment). CFS amounts live **per invoice** (`ShipmentDocument.amount_before_tax/gst_amount/amount_total`, migration 0010 with backfill); `PATCH /shipments/{id}/documents/{doc_id}/amounts` — total always = basic + GST, marks `amounts_edited` (a later re-read never overwrites a hand correction), audit-logged.
  - **Multiple CFS invoices:** any number of CFS proformas/tax invoices per shipment. Shipment CFS totals = sum of tax invoices, or of proformas until a tax invoice exists (`extraction/cfs_totals.py`, recomputed on upload/re-read/edit/remove). Overview lists each invoice (not-counted proformas greyed); checklist rows list every file (`DocumentChecklistItem.documents`).
  - **Billed? checkbox works:** tick → `POST /bill` (billing access), untick → `POST /unbill` (admin only; restores the status from before billing via the audit log). Both audit-logged. Ongoing/Cleared is now decided ONLY by Cleared Date (billing no longer hides a shipment; dashboard "ongoing" likewise). `billed_at` returned by the API.
  - **Per-container charges:** Agency (AC) and Examination (EC) are `PER_CONTAINER` (migration 0011 + seed). Adding one to a proforma without a quantity uses the shipment's container count (Cntr); UI pre-fills it and shows "× N containers = ₹… + GST". Error if the shipment has no container count. **Open (client will share bills):** which charges are taxable vs pure-agent reimbursements (CFS, bond, documentation etc. vary) — affects GST on proforma lines.
  - **Rename client:** "Rename" on each client bar → `POST /shipments/rename-client` renames every shipment with that client (audit-logged per row, port-scoped; renaming onto an existing name merges after a confirm).
  - **Auto-refresh:** tracker refetches every 5 min and whenever the tab becomes visible again (skipped while a cell is being edited); edits re-sort rows immediately.
  - **Day** now follows the client's sheet formula exactly: blank/not a date → Pending; diff = today − INW; +1 if diff ≥ 0 (future INW stays negative); "1 day"/"N days".
  - **Alembic set up** (`backend/alembic/`, 0001 baseline + 0002). Migrations run automatically on startup/seed/import; pre-Alembic DBs are auto-stamped at 0001. New schema change = `.venv/bin/alembic revision --autogenerate -m "..."`.


---

## ✅ Session update — local setup fixes + extraction port (backend)

**Setup fixes:** `.env` was never loaded (no dotenv) — added `python-dotenv`,
loaded in `core/database.py` + `core/security.py`. `.env.example`'s Postgres
`DATABASE_URL` would break a local run, so local `.env` leaves it unset
(SQLite). Python 3.9 compat (`from __future__ import annotations` in
`extraction/naming.py`, `tracker_sync.py`). Added `POST /auth/change-password`
(min 12 chars). Seeded admin password has been rotated locally — stored in
`backend/.local-credentials` (git-ignored). `backend/.gitignore` added.

**Extraction port (spec §5.1/§5.1a) — `backend/app/extraction/`:**
- `be_pdf.py` — BE fields (port, BE no/date, importer 3-tier, AD code,
  MAWB/HAWB + PKG/GW by word position, container count, assessable value /
  IGST / total duty). Regexes/offsets verbatim from the reference; PDF now
  opened once instead of 3×.
- `cfs_pdf.py` — CFS invoice fields + before-tax+GST=after-tax sanity check,
  CFS→BE row matching (BE no, then BL=MAWB), BE/CFS scored classification.
- `excel_imports.py` — challan list → `{BE no: Due Amount}`, Organization
  List import, name-mismatch rule (YES/NO/N/A), interest split.
- `batch.py` — mixed-batch pipeline: classify → scan → match CFS → name
  check → duplicate flags (within batch; and BE already on a shipment =
  "previously processed", replacing the reference's CSV log).
- New `OrganizationEntry` model (AD code registry, spec §5.1).
- Endpoints (`routers/extraction.py`): `POST /extraction/scan` (multi-file),
  `POST /extraction/challan`, `GET/POST/PUT/DELETE /organizations`,
  `POST /organizations/import` (xlsx). Scan/challan = billing access;
  org edits = admin. Endpoints are stateless — nothing saved to shipments yet.

**Tests (new — first automated tests in the repo):** `backend/tests/`,
19 passing (`.venv/bin/python -m pytest`). Uses reportlab-generated
synthetic BE/CFS PDFs. ⚠️ These prove the ported logic runs as written, NOT
that it matches real ICEGATE/CFS layouts — **get 3-5 real (redacted) BE +
CFS PDFs from the client and add them as fixtures.**

**Still to do for Module 3 extraction:** batch fee-entry UI on top of
`/extraction/scan` (create/update shipments + proformas from rows), per-
importer fee memory + fee presets, admin UI for the org registry, OOC-date
extraction on document upload (spec §3.3).

---

## ✅ Session update — Dashboard, Shipment Detail, Document Manager, Proforma views

**Why:** the frontend previously had only Login + the shipment grid — no UI
for the backend logic that already existed (documents, HS-code checklist,
proforma/billing data model). This was flagged directly by the client
looking at the preview ("this is basically just an excel").

**Backend additions (new, tested live against a seeded SQLite DB, not just
written):**
- `GET /shipments/summary/dashboard` (`app/routers/shipments.py`) — live
  shipment count, stuck count, counts by status, counts by port, next 5
  upcoming ETAs. Reuses the same port-scoping as the grid endpoint.
- `app/routers/hs_codes.py` (new) — `GET /hs-codes`, `GET /hs-codes/{id}`,
  returning each HS code's required-document list.
- `GET /shipments/{id}/documents/checklist` (`app/routers/documents.py`) —
  cross-references a shipment's HS code required-docs against what's
  actually been uploaded; drives the Document Manager checklist UI.
- `app/routers/proforma.py` (new) — `GET /charge-master`,
  `GET`/`POST /shipments/{id}/proformas`, `POST`/`DELETE
  /proformas/{id}/line-items/...`, `PATCH /proformas/{id}` (status).
  GST/SAC are copied onto the line item at creation time from the charge
  master, per spec §5.3, so a later master edit can't rewrite a past bill.
  Gated by the existing `require_billing_access` dependency.
- New schemas: `HSCodeOut`, `DocumentChecklistItem` (in `schemas/document.py`);
  `ChargeMasterOut`, `ProformaOut`, `ProformaLineItemOut`,
  `ProformaLineItemCreate`, `ProformaStatusUpdate` (new `schemas/proforma.py`).
- All four new routers registered in `main.py`.

**Tested live this session:** started the server against a fresh seeded DB,
logged in, created a shipment against the tyre HS code, then hit every new
endpoint end-to-end: dashboard summary returned correct counts; checklist
returned all 16 required doc types as "missing"; created a proforma, added
a line item (₹1000 rate × qty 2 → ₹2000, +18% GST = ₹360, total ₹2360 —
verified correct), then marked it Sent.

**Frontend additions (new files, `npm run build` verified clean):**
- `AppLayout.tsx` — shared top nav (Dashboard | Shipments) + logout, now
  wraps all authenticated routes instead of each page having its own header.
- `DashboardPage.tsx` (route `/dashboard`, now the post-login landing page)
  — stat cards (live count, stuck count, ports active), a clickable status
  pipeline row (links into the grid pre-filtered by that status via
  `?status=`), by-port breakdown, upcoming ETAs.
- `ShipmentDetailPage.tsx` (route `/shipments/:id`) — full shipment detail
  with Overview / Documents / Proforma & Billing tabs. Job row in the grid
  now links here.
- `DocumentManagerPanel.tsx` — required-doc checklist table (missing rows
  highlighted like stuck shipments) + an upload form; shows an explicit
  warning if the shipment has no HS code assigned yet.
- `ProformaPanel.tsx` — version tabs (draft/sent/superseded), add/remove
  line items from the charge master with live GST calc, running grand
  total, "Mark as Sent" action.
- `ShipmentGridPage.tsx` — updated to read `?status=` from the URL (for the
  dashboard's pipeline links), dropped its own header/logout (now in
  `AppLayout`), Job cell links to the detail page.
- `types.ts` / `api.ts` — extended with `DocumentType`, `HSCode`,
  `ChargeMasterEntry`, `Proforma`/`ProformaLineItem`, `DashboardSummary`
  types and the matching API calls, kept in sync with the new endpoints.
- `index.css` — new styles for the top nav, dashboard cards/pipeline,
  detail-page sections/tabs, document checklist, and proforma table —
  same design tokens as the existing grid/login styling, nothing new
  introduced.

**Not done yet (see updated Next Steps below):** no HS-code *picker* on the
shipment detail page yet (hs_code_id can only be set via the create-shipment
API/form right now, not edited afterward from the UI) — flagged as a
follow-up. Proforma PDF generation (spec §5.5's "generated_filename"/
"file_path" columns) is still unset — the model supports it, nothing writes
to it yet.

---

## ✅ What's built and verified working

### Backend (`backend/`) — FastAPI + SQLAlchemy, Python
Runs against SQLite by default (zero setup) or Postgres via `DATABASE_URL`.

- **Auth**: JWT login (`POST /auth/login`), current-user endpoint, admin-only
  user creation. Role model (Admin/Import Manager/Export Manager/Accountant)
  and port-scoping are implemented in `app/core/deps.py`.
- **Shipments** (`app/routers/shipments.py`): full CRUD, port-scoped listing,
  search, status/stuck filters, bill/unbill endpoints. All field updates go
  through an audit-log hook (`app/core/audit.py`) per the 7-day version
  history requirement (purge job NOT yet built — see Next Steps).
- **Documents** (`app/routers/documents.py`): upload + tag in one call.
  Auto-generates the filename per the confirmed two-state naming rule
  (`app/extraction/naming.py`) and runs the doc-type → tracker-field
  auto-sync (`app/extraction/tracker_sync.py`).
- **Data model**: `app/models/` — Shipment (full 26-field set), User,
  HSCode/RequiredDocument, ShipmentDocument, ChargeMasterEntry, Proforma/
  ProformaLineItem (versioned, dynamic line items), AuditLogEntry.
- **Seed data** (`app/seed.py`): tyre HS code + its required-doc checklist,
  the full 17-entry charge master with SAC codes as resolved in our
  conversation, one admin user.

**Actually tested this session, not just written** — ran the server,
logged in, created a shipment, uploaded a PDF tagged as OOC Bill of Entry,
and confirmed both:
1. The generated filename was exactly right: `OOC - MBL12345 - BE7788.pdf`
2. The tracker auto-update fired: `ooc: false→true`,
   `status: to_be_filed→ooc_done` — automatically, from the upload alone.

This is the one mechanic the client described most precisely in the original
conversation, so proving it works end-to-end (not just "looks right in the
code") was the priority for this session.

Also fixed along the way: a real `passlib`/`bcrypt` version incompatibility
(newer bcrypt removed an attribute passlib 1.7.4 expects) — pinned
`bcrypt==4.0.1` in `requirements.txt` so this doesn't break for whoever runs
this next.

### Frontend (`frontend/`) — Vite + React + TypeScript
- Scaffolded, dependencies installed, **production build verified clean**
  (`npm run build` — zero TypeScript errors).
- `src/types.ts` / `src/api.ts` — typed API client matching the backend
  schemas exactly (kept in sync manually; consider generating from the
  OpenAPI schema once the API stabilizes).
- `src/AuthContext.tsx` — auth state, token persistence in localStorage.
- `src/LoginPage.tsx` — working login screen.
- `src/AppLayout.tsx` — shared top nav (Dashboard | Shipments) + logout,
  wraps all authenticated routes.
- `src/DashboardPage.tsx` — Tracker Dashboard: stat cards, clickable status
  pipeline, by-port breakdown, upcoming ETAs. Post-login landing page.
- `src/ShipmentGridPage.tsx` — the core tracker grid: search, stuck-only
  filter, status pills, quick-add form, `?status=` filter from the
  dashboard. Wired to the real API, not mocked. Job cell links to detail.
- `src/ShipmentDetailPage.tsx` — full shipment detail, Overview / Documents
  / Proforma & Billing tabs.
- `src/DocumentManagerPanel.tsx` — HS-code required-doc checklist + upload.
- `src/ProformaPanel.tsx` — versioned proforma line items, GST calc, totals.
- `src/App.tsx` — routing with a protected-route wrapper.

**⚠️ This is a functional scaffold, not the aesthetic pass.** The client's
brief explicitly requires the app to be aesthetic (spec §1) — current styling
(`src/index.css`) is a clean, readable baseline (decent spacing, restrained
palette, no glaring "AI slop" defaults) but has NOT been through a proper
design pass. Before this ships, run it through the `frontend-design` skill's
plan → review → build → critique process properly: pick a real palette/type
system grounded in the subject matter (a logistics/customs ops tool, not a
generic SaaS dashboard), and apply it consistently across every screen —
not just the grid.

---

## 🚧 Not started yet (in priority order)

1. ~~**PDF/Excel extraction port**~~ — backend DONE (see top); UI/fee-memory/real-PDF fixtures remain. Original note: `reference/be_expense_sheet.py` has the
   working extraction logic (BE/CFS classification, AD-code lookup,
   duplicate detection, etc. — see `ERP_Spec.md` §5.1/§5.6) but NONE of it
   has been ported into `backend/app/extraction/` yet. This is the biggest
   remaining chunk of work — budget real time for it, and read the
   reference script directly rather than working from the spec summary
   alone (per the spec's own §0 instruction).
2. **HS-code picker on the shipment detail page** — the Overview tab
   displays fields but there's no way to set/change `hs_code_id` from the
   UI yet; it can currently only be set via the create-shipment API/form.
   Needed before the Document Manager checklist is usable for a shipment
   created without one.
3. **Proforma PDF generation** — `Proforma.generated_filename`/`file_path`
   columns exist (spec §5.5 naming syntax) but nothing writes to them; the
   Proforma & Billing UI only manages line items and status in-app so far.
4. **Charge master management UI** — seed data exists in the DB, no admin
   screen to create/edit charges yet (the Proforma panel only *reads* it).
5. **HS-code management UI** — same story: seeded + readable via API, no
   admin screen to add new HS codes or edit their required-doc lists.
6. **Audit-log 7-day purge job** — entries are being written correctly;
   nothing deletes them after 7 days yet. A simple scheduled task (cron,
   APScheduler, or a Celery beat job) is enough.
7. **Delete-approval flow** — spec says non-admins can't delete without
   admin approval. Current API just blocks non-admins outright (403) with
   no request/approval mechanism. Needs its own small model + endpoints.
8. **Daily duty challan Playwright job** (spec §5.1a/§4) — explicitly the
   one automation kept in v1 scope. Not started.
9. **Everything marked Phase 2 in the spec** (ICEGATE/CFS scraping,
   LiveImpex integration decision) — correctly out of scope, don't start
   these without checking with the client first.

---

## Known rough edges / things to double check

- `TYRE_HS_CODE = "40040000"` in `app/seed.py` — confirmed with client.
- `DOC_TYPE_ABBREVIATIONS` in `app/extraction/naming.py` are reasonable
  guesses (PL, OOC, BL, etc.) — spec §6 flags that the client has 2 existing
  Python scripts with the canonical abbreviations, not yet shared. Swap
  these in once available.
- `ChargeMasterEntry.calculation_basis` is seeded as `FLAT` for everything —
  spec §5.6 notes the reference tool uses per-container and per-kg bases for
  some charges (Agency, Royalty). Confirm which of the 17 charges need a
  non-flat basis.
- CORS is wide open (`allow_origins=["*"]`) in `app/main.py` — fine for dev,
  tighten before any real deployment.
- No Alembic migrations generated yet — `Base.metadata.create_all()` on
  startup is a dev convenience only, not a migration strategy. Run
  `alembic revision --autogenerate` once the schema is stable enough to
  stop churning.

---

## How to run this locally

**Backend:**
```bash
cd backend
cp .env.example .env      # then comment out DATABASE_URL for SQLite, set a real JWT_SECRET_KEY
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m app.seed        # creates tables + seed data
.venv/bin/python -m uvicorn app.main:app --reload
.venv/bin/python -m pytest          # tests
```
Default admin login: `admin@example.com` / `changeme` — **change this
immediately**, it's a seeded placeholder.

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```
Visit the printed localhost URL, log in with the admin credentials above.

---

## 🎨 Design backlog — do LAST, after the launch phases (client note, 2026-09-29; no action yet)

- Layout feels too vertical. Wanted: a **left sidebar** for navigation and **full 1920×1080 use** (wide, dense screens) so less scrolling is needed.
- Design language like **linear.app**: very clean, minimal, quiet typography, lots of restraint.
- Maybe **change the orange** accent (open question — show options first).
- Design-only work (frontend); not a backend change. Keep behind the launch work.

---

## 💡 Feature ideas from other software (client will send, 2026-09-29) — collect here, prioritise later

The client will pick features they like from other software and feed them in. Record each one here with where it came from and why it's useful; don't build until prioritised.

- (none yet)

---

## 📋 Where we are / what's left (2026-09-29, end of session)

**Branches:** `main` has everything up to the live tracker. `storage/phase-7` (pushed) has Drive storage, pick-from-folder, auto folder finding, Commercial Invoice, digital/scanned, background adding, duplicate invoices, BE heading fix — **merge into main after the client checks folder finding**.

**Waiting on the client**
1. Try **Link Drive folders** (tracker) and **Find in Drive** / **Pick files from this folder** (Documents tab) with Google sign-in; report linked / to-check counts.
2. Google service account (for server-side Drive saving + backups): Shared Drive or existing drive? key JSON file → `backend/secrets/`, share the drive/folder with it as **Contributor** (never Content manager), folder IDs → `backend/.env`, run `scripts/check_drive.py`.
3. Scanned documents: client working on a fix (OCR). 5 of 15 current documents are scanned.
4. Receipt samples (shipping line / CFS), redacted real PDFs (H8), Dynadot/Render accounts (H1, H2), backup encryption key.

**Next to build (launch path)**
- Phase 7 finish: switch `STORAGE_BACKEND=drive` once the key exists; a one-time upload of existing local documents; server uploads should go into the shipment's linked staff folder (not a separate ERP tree) — confirm with client.
- Phase 8 backups: encrypted 12-hourly `pg_dump` to Drive `Backups` (no pruning — never delete), manifest, restore script + drill, red banner when stale.
- Phase 9 production readiness: CORS lock-down, secure settings check, login rate limit, `AUTO_MIGRATE=0` + `pre_migration_backup.sh` on deploy, uvicorn `--timeout-graceful-shutdown 3`.
- Phase 10 deploy on Render + domain + soft launch (Google Sheet stays reference, then cut-over).
- Phase 3 (deferred): safe invoice numbering — before the app issues real invoice numbers (LiveImpex for now).

**Improvements noted (not started)**
- Google Sheets mirror of the tracker (client wanted the tracker also saved in Sheets).
- ERP-created shipment Drive folders (later; staff create them for now).
- Live updates on the shipment detail page / proforma panel (tracker is live already); proforma line version + 409.
- Server-side document queue (survives closing the tab); OCR for scanned PDFs.
- Invoices section + numbering (September through LiveImpex).
- Design refresh: left sidebar, full 1920×1080 use, Linear-like minimal look, maybe a new accent colour.
- Feature ideas from other software (client will send).
- Test/cleanup: SQLite still works as a fallback; `docs/TWO_BROWSER_TEST.md` for manual multi-user checks.

**Drive setup decision (2026-09-29):** the client's shipment folders are in a normal Drive folder (synced to desktops offline via Google Drive for desktop). Moving to a Shared Drive is planned **later** (process explained: create Shared Drive, members, move folders — IDs/links kept, desktop paths change and "Available offline" must be re-ticked, sync must be complete before moving). **For now:** service account gets **Viewer** on the shipments parent folder (read only — can find/read, cannot touch staff files) and **Editor** on a separate `Clarus ERP – system` folder (backups, generated proforma/invoice PDFs; the code never deletes). Waiting for: key file name, both folder links.

**Drive connected, 2026-09-29:** service account `erp-storage@clarus-erp.iam.gserviceaccount.com`, key at `backend/secrets/service-account.json` (gitignored, chmod 600). "Clients" (staff shipment folders, id 1EwV0EbRmmg7puGahIM7577WkJE2VFNpK) = read only; "CLARUS ERP - System" (10fJO7u4zYP_HcWhdsdpAToBBS1ONrDcn) = add/edit, cannot delete. `check_drive.py` passes, BUT Google refuses file uploads: **"Service Accounts do not have storage quota"** — a service account can't own files in My Drive. **Fix: put the System folder in a Shared Drive** (a small Shared Drive just for ERP saves; staff folders can stay where they are), service account as Contributor, then set the new folder id(s) and `STORAGE_BACKEND=drive`. Until then `STORAGE_BACKEND=local` (backend/.env). Alternative if no Shared Drives: domain-wide delegation impersonating one user (Workspace admin).

---

## ✅ Drive switched on + Launch Phase 8 backups (2026-09-29, branch `backups/phase-8`)

- **Shared Drive** (id 0AKuNLP5kPCuaUk9PVA, service account = Contributor: Google reports it cannot delete or trash). The ERP made `Documents`, `Invoices`, `Backups` in it (ids in backend/.env). `STORAGE_BACKEND=drive`; `check_drive.py` passes; real upload works. The 4 older computer-uploaded documents were pushed; picked staff files stay links. Staff "Clients" folder = Viewer (read only). The earlier "CLARUS ERP - System" My Drive folder is unused (service accounts can't own files in My Drive).
- **Backups** (`app/backups.py`): pg_dump -Fc → `pg_restore --list` check → Fernet-encrypted (`BACKUP_ENCRYPTION_KEY`, in backend/.env — **client must also save it in a password manager**) → `erp-YYYY-MM-DD-HHMM.dump.enc` + `.manifest.json` (sizes, sha256, migration, row counts) → server `backups/auto/<YYYY-MM>/` and Drive `Backups/<YYYY-MM>/`, upload verified by size + md5. Hourly job (advisory-locked) backs up when the last good one is ≥12 h old. **Never deleted** (client rule). `backup_runs` table (migration 0032). `GET /health/backups` (admin) + red banner for the admin: none in 26 h, 40 % smaller than the previous, last failed, or not in Drive.
- `scripts/backup.py` (`--new-key`), `scripts/restore.py <file> --into <empty db>` (refuses a non-empty target unless `--i-am-sure`, compares row counts with the manifest). **Restore drill passed** 2026-09-29 (every table matched, 67 shipments). `docs/RESTORE_RUNBOOK.md`.
- Tests `tests/test_backups.py` (Postgres). 115 pass on Postgres.
- Render note for Phase 10: the server needs `pg_dump`/`pg_restore` (Docker image with postgresql-client, or PG_BIN).

**Client notes 2026-09-29 (to do next):**
- **Harekrishna Rubber: shipping line invoices are NOT added to cost inclusion** — confirm: when HKR is the BE importer, the HSS seller, or on any shipment involving HKR? Build as a per-organisation setting.
- One shipping line invoice was read wrongly → collect shipping line samples and improve reading.
- **"HKR" = Harekrishna Rubber** (same party). Use the organisation list's Alias column so short names (HKR) match everywhere (licence / HSS rules, bill-to, tracker), instead of separate client codes — decide with client.

---

## ✅ Shipping line in cost inclusion: client default + shipment switch (2026-09-29)

- Client: for **Harekrishna Rubber** shipping line invoices are **not** added to cost inclusion, but a shipment must be able to add it when needed.
- `organizations.line_in_cost_inclusion` (default true) — checkbox "Shipping line invoices NOT in cost inclusion" in the organisation form. `shipments.line_cost_inclusion`: null = **Auto** (client's setting), `include`, `exclude` — "Shipping line in cost inclusion" select on the Overview under "Shipping line paid by us" (disabled when paid by us: that is always Reimbursement). Migration 0033.
- `autofill.line_excluded_by()`: the shipment's switch wins; on Auto, any party on the shipment (BE importer, consignee, HSS seller or buyer) whose organisation is set to "not included" leaves it out; the proforma's "skipped" list says why. Changing the switch refreshes draft proformas.
- Harekrishna Rubber Industries Pvt Ltd set: short names "HKR, Harekrishna" (the existing short-names field = aliases, so HKR matches everywhere; no client codes needed), not in cost inclusion → 11 shipments' drafts refreshed (jobs 129, 130, 134–138, 145, 151, 152, 181). "Any party" rule — narrow it (e.g. only as BE importer / HSS seller) if the client says so.
- Tests: `test_line_cost_inclusion_client_default_and_shipment_switch`. 116 pass on Postgres.

**Incident, same day:** after `STORAGE_BACKEND=drive` was set in backend/.env, two test runs read it and saved ~74 test files/folders and one test-database backup into the real Shared Drive (10:35–10:38). The app can't delete, so they were renamed `TEST – delete me – …` for the client to remove by hand. Fixed: `tests/conftest.py` now forces local storage, blanks every DRIVE_* / key setting and uses a temp BACKUP_DIR. Real data untouched.

---

## ✅ Launch Phase 9 — production readiness (2026-09-29, branch `prod/phase-9`)

- `app/core/production.py`: with `APP_ENV=production` the app **refuses to start** (clear list) when: JWT secret default/short; DATABASE_URL not Postgres; PUBLIC_URL not https; STORAGE_BACKEND not drive; any Drive id / service-account key / BACKUP_ENCRYPTION_KEY missing; AUTO_MIGRATE ≠ 0; any active user with the default login (admin@example.com or password "changeme"); database unreachable. Checked on this Mac: refuses (PUBLIC_URL, AUTO_MIGRATE, default admin).
- `scripts/create_admin.py` (ADMIN_EMAIL / ADMIN_PASSWORD ≥ 12) — production has no default admin.
- Login throttle (`app/core/ratelimit.py`): 5 attempts/min per IP+email → 429; 10 wrong passwords in 15 min locks the email 15 min (even with the right password). In memory, one instance.
- `app/core/web.py`: security headers (nosniff, DENY frames, referrer, permissions, HSTS on https), request size limit (MAX_UPLOAD_MB 30 → 413), CORS = PUBLIC_URL only (dev: Vite), and the backend **serves the built screens**: a page load (GET accepting text/html) gets index.html, API calls (JSON) still reach the API on the same paths; `/assets/*` cached forever. `/docs` off in production. Logs to stdout. `/health` checks the database (503 if not).
- Frontend: `VITE_API_BASE_URL` "" in production (same address; `??` not `||`). Verified: a production-style build served from the backend on :8010 — page reload on /shipments/58, data, live tracker all worked.
- `Dockerfile` (node build stage → python:3.11-slim + postgresql-client-17 + DejaVu fonts, non-root user, healthcheck), `.dockerignore` (no .env / secrets / data), `scripts/start.sh` (dump + migrate → settings check → uvicorn with proxy headers and graceful-shutdown 3 s), `render.yaml` (Docker web service + Postgres 17, Singapore; secrets `sync: false`). **Docker isn't installed on this Mac — the image hasn't been built yet** (first build on Render or after installing Docker Desktop).
- README rewritten; `.env.example` has the production settings. Sentry: skipped (optional).
- **GST rule (client, same day):** CFS and shipping line invoices, and the BE duty (IGST), always have GST; stamp duty doesn't. None found → note in the upload result + red "GST not found" badge (`fields.gst_missing`). Existing documents checked: 1 flagged — shipment 65 `SL-PI - OOLU2333975920` (likely the misread shipping line invoice; samples zip coming).
- Tests `tests/test_production.py` (6) + GST test. 123 pass on Postgres.

**Next: Phase 10 — deploy.** Needs: Render account in the client's name (H2), domain DNS at Dynadot (H1: auto-renew + 2FA), then: create services from render.yaml, set secrets, move the data (pg_dump → Render Postgres), create the real admin, add `https://erp.<domain>` to the Google OAuth origins and API-key websites, soft launch.

---

## ✅ Users: admin controls every password (2026-09-29)

- Client: logins — **divit@claruslogistics.in = Admin (boss)**, **impdoc@claruslogistics.in = Import Manager**; sub-accounts later. Passwords are set by the admin only; users can't change their own; "Forgot password" just flags the account.
- Backend (`routers/auth.py`): `/auth/change-password` → 403; `POST /auth/forgot-password` (always 204, rate-limited) sets `users.password_reset_requested_at`; admin: `GET/POST /auth/users`, `PATCH /auth/users/{id}` (name, role, on/off — can't switch off or demote yourself), `POST /auth/users/{id}/password` (clears the request). Emails stored lower-case, login case-insensitive, `last_login_at`. Everything audit-logged. Migration 0034. Tests `tests/test_users.py`.
- Frontend: **Users** page (admin nav) — add user with a suggested 14-character password to hand over, role select, Set password, Switch off/on, "Reset requested" badge + banner; login page **Forgot password?** and clear lock-out messages.
- Production: create divit@ with `scripts/create_admin.py` on Render, then add impdoc@ from the Users page. Remove / never create admin@example.com there (the production check refuses it).

**Render (Phase 10) status:** client is creating the account (Google sign-up; workspace "Clarus Logistics"; impdoc@ created it — invite divit@ as Admin, ownership can be transferred on the Members page or by Render support). Next: New → Blueprint from `dvtxjn/clarus-erp`, secrets pasted by the client, data moved, DNS `erp.claruslogistics.in`.

**Client wish (2026-09-29): generate proforma invoices on the phone.** Proforma screens are desktop-sized today → mobile layout for the proforma panel (create, fill, check totals, download PDF / share) — add to the design work.

---

## 🟡 Launch Phase 10 — hosting moved from Render to Google Cloud (2026-09-29, branch `deploy/gcp`)

- **Decision (client):** Google Cloud instead of Render — **Indian GST invoices in INR** (Google Cloud India Pvt Ltd; GSTIN on the billing account → input tax credit), trusted, same Google project (`clarus-erp`) and Workspace logins. $300 / 90-day free credit on the new billing account — **click "Activate full account" before it ends** (else resources pause); set a ₹3,000/month budget alert in Billing. Data in India not required.
- **Region: Singapore (`asia-southeast1`)** — Cloud Run custom domains aren't available in Mumbai; billing is Indian regardless.
- **Pieces:** Cloud Run service `clarus-erp` (1 vCPU / 1 GiB, 0–3 instances, 60-min request timeout for the live streams — browsers reconnect), Cloud SQL `clarus-erp-db` PostgreSQL 18 `db-f1-micro` (daily backups 02:00 IST, PITR, 14 kept) — estimated ₹1,000–2,000/month + GST; Secret Manager (database-url, jwt-secret, job-token, backup-key, drive-sa-key mounted as a file, vite-google-api-key, first-admin-password → delete after first login); Cloud Scheduler `erp-backup` hourly (makes one every 12 h) and `erp-drive-retry` every 15 min → `POST /internal/jobs/{name}` with `X-Job-Token` (Cloud Run gives CPU only during requests, so `JOBS_ENABLED=0` there; production check requires a JOB_TOKEN then).
- **Releases:** migrations run as Cloud Run Job `erp-migrate` (`scripts/migrate.sh`: encrypted backup to Drive first — skipped on an empty database — then `alembic upgrade head`); the web service no longer migrates on start (`MIGRATE_ON_START=1` for single-server hosts).
- **Data move:** Cloud Run Job `erp-import` (`scripts/import_from_drive.sh`) restores the newest Drive backup into the empty Cloud SQL database (`restore.py --from-drive latest`; tested on this Mac — every table matched). Take a fresh backup on the Mac (`scripts/backup.py`) right before running setup. `create_admin.py DISABLE_DEFAULT_USERS=1` switches off admin@example.com / importmanager@example.com (not deleted).
- Image now has `postgresql-client-18` (same major as Cloud SQL 18 and Postgres.app 18). `render.yaml` removed.
- **Waiting on the client:** billing account (India, Business, GSTIN) linked to `clarus-erp`; then run setup in Cloud Shell; then the DNS record at the domain provider; then add `https://erp.claruslogistics.in` to the OAuth client's JavaScript origins and the API key's websites.

## ✅ Live on Google Cloud (2026-09-29)
- App: https://clarus-erp-46om5fompq-as.a.run.app → https://erp.claruslogistics.in (domain verified in Search Console,
  CNAME `erp` → ghs.googlehosted.com at Dynadot; Google issues the certificate automatically).
- Data copied from the newest encrypted Drive backup; divit@ is admin; test logins switched off; impdoc@ added.
- Fixes found on the way: `backend/.gitignore` `storage/` hid `app/storage/` from git (now `/storage/`);
  base image pinned to `python:3.11-slim-bookworm` (pg client 18 repo); `--no-invoker-iam-check` because the
  Workspace org policy blocks `allUsers`.
- Picker origins + API key restrictions include both addresses.
- To do: delete `first-admin-password` secret · rotate `job-token` (was printed in the setup output) ·
  ₹3,000/month budget alert · soft launch alongside the sheet.

## 🟡 Design refresh (2026-09-29, branch `design/refresh` — not deployed yet)
- Shell: left sidebar (collapsible to icons), full-width pages, Inter, Linear-style neutrals, softer orange, accent trial dots.
- Shipment page: BL + BE left / clearance chips right; Shipment & movement block (+ remarks) across the top; Customs duty + Status | CFS | Shipping line; invoices scroll inside their box; cost-inclusion charges in an overlay.
- Documents: groups Basic / Customs / Line / CFS with small markers, two columns.
- Proforma: options in the sidebar, invoice in a preview pane (Whole page / 100 %).
- Dashboard: containers + gross weight (by ETA and by Cleared Date, per port), pies, containers/weight switch.
- Rates: tabs; licences as rows that open.
- Tracker: one line per row (cut with …, hover for full value — widths to tune), short dates (BE Dt with year, INW 19 Sep),
  shorter headers, column views (Clearance / Movement / Billing / Full grid), side panel (peek), status edge colours,
  client bar = containers + weight, HBL / FTA buttons on the MBL (FTA split from MBL: migration 0035 + CSV import),
  calendar on date cells, "d" deadline on ETA (ETA − 4 days, migration 0036), Excel-style autosize,
  removed from the grid: HBL, HSS, CFS/TDS, Status, Line, Billed (ongoing), Client (by-client view); Cleared last; Wt (MTS).
- Next: column widths; Remark / POC / Remarks (client to decide); filter chips; group by; Recently deleted page; phone proforma.

## 📝 Next session — client notes (2026-09-29, start here)
1. **Documents table:** show only the type is marked (✓ + small kind badge); the file name moves to a hover view —
   file names take unpredictable width, the table should be uniform.
2. **Proforma & Billing — rework:**
   - Moving options into the sidebar was not a good call: font / button sizes inconsistent. Undo it.
   - Full-screen layout: split pane — data / options uniformly on the **left**, the invoice on the **right**.
   - Section is too cluttered overall — simplify.
   - The PDF download format is perfect; keep it.
   - Move the "value of goods / GST input …" block up next to the assessable value on the invoice (it confuses people).
   - Always pre-apply the suggested bill rate, AND adjust it by our rules when costs change (add / subtract) so the
     value follows — the rules should be smart.
   - If CFS is switched to taxable, it shows in the tax invoice as the final invoice.
3. **Invoice numbering (Phase 3 revisited) — decided:** tax and reimbursement invoices always share the same number.
   When a shipment has no reimbursement, a reimbursement invoice is **still issued** with that number: all the usual
   details (party, shipment, references) but **no charge heads**, and **"BILL CANCELLED — NOT APPLICABLE"** in bold
   across the bill so it's obvious. The chain never breaks.
4. **One final-invoice interface:** tax + reimbursement are two invoices, but finalised together in **one** screen,
   one action (not twice the manual work). Export on demand: one PDF with both sheets, or two separate PDFs.
5. **Invoicing starts in October 2026** — the above must be ready by then.
6. **(P5) Delhi / non-sea-port shipments:** INW = sea-port inward; there's also an arrival date at FPOD, from which
   the free days start. The tracker's Day count is wrong for these (free days haven't started). Needs an FPOD arrival
   date and Day counted from it.
