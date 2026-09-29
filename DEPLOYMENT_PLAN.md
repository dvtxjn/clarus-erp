# Clarus ERP — Hosting, Data Safety & Multi-User Plan

> Put this file in the repo root next to `PROGRESS.md`.
> Claude Code: read `PROGRESS.md` first, then this file. Do ONE phase per session.

## START HERE — Launch scope (Claude Code: read this before anything else)

**Goal: a working, safe launch as soon as possible. Everything else waits.**

1. Work ONLY on the "Launch phases" below, in this order, one per session.
2. **Do NOT start Part B (Phases 11-19, everything about ICEGATE, email, Inbox, Playwright worker) until the Phase 10 go-live checklist is fully ticked and the human says so.** Do not build "foundations" for it early.
3. Always use the Fast Track scope for each phase (section "FAST TRACK").
4. If a phase seems to need something outside its scope, stop and ask.

| Order | Launch phases (Fast Track scope) | Approx. time |
|---|---|---|
| 1 | Phase 0: Postgres and data move | 2-4 hrs |
| 2 | Phase 1 (reduced): soft delete, locked invoices, pre-migration dump | 3-5 hrs |
| 3 | Phase 3: invoice numbering and one-shot actions | 2-4 hrs |
| 4 | Phase 2: conflict protection on tracker edits | 4-8 hrs |
| 5 | Phase 4 (reduced): locking for uploads, autofill, challans, final invoices | 6-8 hrs |
| 6 | Phase 6 (reduced): concurrency tests 1-5 | 3-5 hrs |
| 7 | Phase 7: Drive storage (see the storage option below) | 6-8 hrs |
| 8 | Phase 8 (reduced): 12-hourly encrypted backup and restore drill | 4-6 hrs |
| 9 | Phase 9: production readiness | 4-6 hrs |
| 10 | Phase 10: deploy, soft launch, go-live checklist | 4-8 hrs |

Skipped for launch: Phase 5 (hide Ctrl+Z undo instead), weekly/monthly backup tiers, Sheets mirror, staging, all of Part B.

**Storage option (the human decides, Claude Code never switches on its own):** if the client is slow to set up the Shared Drive (H3-H4), launch first with documents on a Render persistent disk and move to Drive within 1-2 weeks. Only allowed if (a) the human says so in writing in the session, (b) the disk is a paid persistent disk with snapshots, and (c) the Phase 8 backup also covers the files. Otherwise Phase 7 stays mandatory.

**After launch, in this order:** Phase 13 (Communicator CSV import; needs Phase 12 first) -> Phases 14-15 (email engine and Inbox) -> Phase 11 (end-to-end tests, alongside) -> Phases 16-18 (ICEGATE login, daily challan, IGM) -> Phase 19 (alerts, History, exports).

---

## Phase tracker (Claude Code: tick a box only when that phase's "Done when" passes)

| # | Phase | Status |
|---|---|---|
| 0 | Postgres locally + move existing data | [ ] |
| 1 | Data-safety rules (soft delete, locked invoices, permanent audit) | [ ] |
| 2 | Conflict protection on tracker edits | [ ] |
| 3 | Safe invoice numbering + one-shot actions | [ ] |
| 4 | Locking for uploads, autofill, challans, CSV import, proformas | [ ] |
| 5 | Safe undo + live-ish updates (polling) | [ ] |
| 6 | Concurrency tests | [ ] |
| 7 | Google Drive storage (Shared Drive) + invoice PDF saved on Issue | [ ] |
| 8 | Backups (12-hourly, weekly, monthly) + restore drill | [ ] |
| 9 | Production readiness | [ ] |
| 10 | Deploy on Render + domain + go-live | [ ] |
| | **Part B: after launch (do not start before the go-live checklist is ticked)** | |
| 11 | Safety net: end-to-end tests + real-PDF fixtures | [ ] |
| 12 | Automation foundations (events table, settings, kill switch, worker token) | [ ] |
| 13 | ICEGATE Communicator CSV import (manual upload, no login) | [ ] |
| 14 | Email engine (read-only mailbox reader + OTP) | [ ] |
| 15 | Inbox: auto-attach documents from email and drag-and-drop | [ ] |
| 16 | Automation worker (Playwright) + ICEGATE login with email OTP | [ ] |
| 17 | Daily duty challan download | [ ] |
| 18 | IGM update job (adapt the existing script) | [ ] |
| 19 | Alerts, daily digest, History tab, Excel export | [ ] |

---

## FAST TRACK — the minimum safe launch (use this when the human says "Fast Track")

Goal: go live as soon as possible WITHOUT risking data loss. Anything marked "Later" is done after go-live, in the order given in section 4. The go-live checklist in Phase 10 is never skipped.

| Phase | Needed before the first real invoice? | Scope for Fast Track |
|---|---|---|
| 0 | Yes | Full |
| 1 | Yes | Reduced: (a) soft delete only for shipments, documents, proformas and final invoices (no hard deletes of these); (b) database triggers locking issued invoices; (c) pre-migration dump script; (d) do NOT build the 7-day audit purge yet: keep all audit rows (nothing is deleted). Later: the `keep_forever` flag and purge job, soft delete for other tables |
| 2 | Yes | Full |
| 3 | Yes | Full |
| 4 | Yes | Reduced: use `locked_shipment` around document upload/re-read/remove/amount edits, autofill, challan upload, create final invoices and bill/unbill. Later: version + 409 on proforma lines, CSV import locking (build together with the CSV import UI) |
| 5 | No | Hide or disable Ctrl+Z undo until the compare-and-set undo is built. Keep the existing 5-minute refresh and refetch on tab focus. Later: 8-second polling and the change feed |
| 6 | Yes | Reduced: tests 1, 2, 3, 4 and 5 must pass. Later: tests 6, 7, 8 and the two-browser script |
| 7 | Yes | Full (Drive storage, folder lock, safety guard, invoice PDF saved on Issue). Files on the server disk are lost on redeploy, so never launch without this |
| 8 | Yes | Reduced: 12-hourly encrypted dump to Drive, 14-day retention, manifest, restore script, restore drill, red banner when the last backup is old. Within 2 weeks after launch: weekly and monthly tiers, second copy outside Google |
| 9 | Yes | Full |
| 10 | Yes | Full, plus a **soft launch**: 1-2 users for 2-3 days on real data while the Google Sheet stays as the reference, then set a cut-over date after which the sheet is read-only |

Accepted risks at launch (with under 5 users): two people editing the same proforma line at the same instant can overwrite each other (drafts only, fixed later); other people's changes appear on refresh, not instantly.

Never skip, even on Fast Track: Postgres, atomic invoice numbers, locked issued invoices, Drive storage, encrypted backups with a passed restore drill, production hardening (Phase 9).

---

## 0. How the human uses this file

Paste this into Claude Code for each phase (change the number):

```
Read PROGRESS.md and DEPLOYMENT_PLAN.md. Do Phase N only, following the Golden Rules.
Write the tests first, then the code. Stop when "Done when" passes and tell me exactly
what I should click to check it. Then update PROGRESS.md and the phase tracker, and commit.
```

| Rule for the human | Why |
|---|---|
| One phase per Claude Code session | Small changes are easy to review and undo |
| Use Opus 5.5 for Phases 2, 4, 6. Any model is fine for the rest | Locking and timing bugs are subtle |
| `git commit` before and after each phase | You can roll back |
| Never start real billing before Phase 10's checklist is fully ticked | Data safety |
| If Claude Code asks "should I delete X?", answer NO unless you are sure | Data safety |

---

## 1. Decisions already made (do not re-debate)

| Topic | Decision |
|---|---|
| Users | Up to 5 at once now. Growth roadmap in section 7 |
| Volume | ~50 shipments/month now, up to ~250/month within a year |
| Hosting | Render, Docker web service, single instance. Frontend is built and served by the backend (one address, no CORS problems) |
| Database | Managed Postgres on Render, paid tier (point-in-time recovery). Postgres everywhere, including local dev (Docker). SQLite is no longer supported |
| Domain | `erp.claruslogistics.in`, one CNAME record at Dynadot. Never change the domain's nameservers (client email depends on it) |
| Documents | Google Drive **Shared Drive**, uploaded by the server using a service account. Local-disk storage kept only for dev |
| Login | Existing JWT login, hardened (Phase 9). Google sign-in is optional, later |
| Backups | Dump every 12 h kept 14 days, one per week kept 12 weeks, one per month kept 12 months, stored in Drive, plus Render point-in-time recovery, plus optional copy outside Google |
| Budget | About Rs 5,000-7,000 per month all-in. Do not add paid services without asking |
| Concurrency approach | Row `version`, field-level compare-and-set, row locks, atomic invoice numbers, 5-10 s polling. No websockets/SSE yet |

---

## 2. Golden Rules for Claude Code

1. **Tests first.** For every phase, write the failing tests, then the code. Tests run against real Postgres (Docker), never SQLite.
2. **Only touch what the phase needs.** Do not refactor unrelated files or change working features.
3. **Never delete or overwrite user data.** No `DROP`, `TRUNCATE`, hard `DELETE` of business data, or destructive migrations without asking the human first and showing a backup exists.
4. **Every schema change is an Alembic migration.** Never rely on `create_all()` for real data. Every migration must upgrade AND downgrade cleanly on Postgres.
5. **Never use `window.confirm/alert/prompt`.** Use the existing `ConfirmDialog` / `useConfirm()`.
6. **Never store shared data in browser storage.** Per-browser layout (localStorage) stays as it is.
7. **Keep audit logging** for every business change, exactly as today.
8. **Secrets never go in git.** Use environment variables. Update `.env.example` with names only.
9. **Lock order everywhere:** shipment -> proforma -> proforma line items -> documents. Never lock in another order (prevents deadlocks).
10. **Slow work outside transactions.** PDF reading and Drive calls happen before/after a short database transaction, never inside a long one.
11. **When unsure, stop and ask** with two concrete options instead of guessing.
12. **End of every session:** update `PROGRESS.md` (what changed, how to run, what to test), tick the phase tracker, run the full test suite, report results honestly (including anything not tested).

---

## 3. Human-only tasks (Claude Code cannot do these)

| # | Task | Who | Needed before |
|---|---|---|---|
| H1 | Turn on auto-renew and two-factor login for the domain at Dynadot | You/client | Phase 10 |
| H2 | Create the Render account **in the client's name** (add yourself as a member) | Client | Phase 10 |
| H3 | Google Workspace admin: create a **Shared Drive** named `Clarus ERP` (if the Workspace edition has no Shared Drives, tell Claude Code and use the fallback in Phase 7) | Client admin | Phase 7 |
| H4 | Google Cloud project (client's): enable Drive API, create a **service account**, download its JSON key, add the service account as *Content manager* on the Shared Drive only | Client admin + you | Phase 7 |
| H5 | Create folders in the Shared Drive: `Documents`, `Invoices`, `Backups`. Give Claude Code the folder IDs | You | Phase 7 |
| H6 | Add `https://erp.claruslogistics.in` to the OAuth authorised JavaScript origins (Drive picker) | You | Phase 10 |
| H7 | Optional: a storage bucket (any S3-compatible, about $1-3/month) for a second backup copy outside Google | You | Phase 8 (optional) |
| H8 | Supply 3-5 real (redacted) BE + CFS + shipping-line PDFs for test fixtures | Client | Any time |
| H9 | ICEGATE user ID and password for the automation (ideally a dedicated user), stored only as Render secrets | Client | Phase 16 |
| H10 | Read-only access to the mailbox that receives ICEGATE OTPs and BE/gatepass mails (Gmail API read-only scope or IMAP app password; never the main password) | Client admin | Phase 14 |
| H11 | Real samples: the ICEGATE Communicator CSV, 2-3 emails of each message type in section 10, one downloaded duty challan Excel | You | Phases 13, 14, 17 |
| H12 | The existing IGM update Playwright script | You | Phase 18 |
| H13 | Client's OK to automate ICEGATE access, and who to call if the ICEGATE account gets locked | Client | Phase 16 |

Confirm with the client: is Google Workspace on `claruslogistics.in`? (Only matters for the optional Google sign-in.)

---

## 4. Phases

### Phase 0 — Postgres locally, and move the existing data (about 2-4 hrs)

**Goal:** the app runs on Postgres with all current local data intact.

**Do:**
1. Create branch `infra/postgres`. Copy the current SQLite file and `backend/storage/` to a folder OUTSIDE the repo as a safety copy.
2. Add `docker-compose.yml` (Postgres 16, named volume, port 5432). Add the Postgres driver to `requirements.txt`. Update `.env.example` with a Postgres `DATABASE_URL`.
3. Run `alembic upgrade head` on an empty Postgres. Fix everything that breaks (SQLite-only batch operations, booleans, JSON columns, defaults). Do not edit old migrations that already ran anywhere unless unavoidable. If needed, add a new baseline migration and explain.
4. Write `backend/scripts/sqlite_to_postgres.py`: copies every table in foreign-key order, resets sequences, then verifies **row counts per table** and prints a comparison. It must refuse to run if the target has data, and must never modify the source.
5. Make the test suite run against Postgres (separate test database). All existing tests must pass.

**Don't:** change features. Don't touch the frontend.

**Done when:** `alembic upgrade head` works from zero; migrated data has identical row counts per table; `pytest` passes on Postgres; the app starts.

**Human checks:** log in; the tracker shows the same number of shipments as before; open 3 shipments; open a document; download one proforma PDF.

---

### Phase 1 — Data-safety rules (about 3-5 hrs)

**Goal:** important data cannot be casually destroyed, even by a bug.

**Do:**
1. **Soft delete:** add `deleted_at`, `deleted_by` to shipments, shipment documents, proformas, proforma line items, organisations, licences, pricing rules, charge master entries. All normal queries exclude deleted rows. Delete endpoints (including "Delete draft" and "Remove document") set the fields instead of deleting. Admin can restore. Files removed from a shipment are marked deleted, never erased.
2. **Locked invoices (database level):** Alembic migration adding Postgres triggers on final invoices and their lines:
   - `DELETE` is always blocked.
   - After status is `issued`: block changes to number, customer, amounts, lines, dates. Allowed: IRN/ACK fields, and the `issued -> cancelled` transition (with cancelled_at/by/reason).
   - Draft rows stay fully editable.
3. **Audit log:** add `keep_forever` flag. Set it for invoice issue/cancel, bill/unbill, user create/role/password change, and soft-delete/restore of invoices/proformas. Build the 7-day purge job (item 6 in PROGRESS "Not started") so it never touches `keep_forever` rows.
4. **Scheduler:** add APScheduler inside the app. Every scheduled job first takes a Postgres advisory lock so only one instance runs it.
5. `scripts/pre_migration_backup.sh`: runs `pg_dump` before any `alembic upgrade` on deploy. If the dump fails, the deploy must stop.

**Done when (tests):** deleting via API only soft-deletes and the row can be restored; a raw SQL `DELETE` or `UPDATE` on an issued invoice fails; purge removes old normal audit rows but keeps `keep_forever` rows.

**Human checks:** delete a draft proforma, then restore it as admin; try "Remove document" and confirm the record is recoverable.

---

### Phase 2 — Conflict protection on tracker edits (about 4-8 hrs)

**Goal:** two people editing at once never silently overwrite each other.

**Do:**
1. Add integer `version` (default 1) to `shipments`; increment on every write. Add `updated_at` if missing. Include both in API output and `types.ts`.
2. Lock helper in `app/core`: `locked_shipment(db, id)` = `SELECT ... FOR UPDATE`.
3. `PATCH /shipments/{id}`: keep the current body, add optional `base` (the values the client saw for the fields it is changing, and for custom fields per key). Inside one transaction: lock the row, compare each changed field's current value to `base`. If all match: apply, run `derive_status` and checklist rules in the SAME transaction, bump `version`, write audit, return the new row. If any differ: change nothing and return **HTTP 409** with `{"conflicts":[{"field","current","yours","changed_by","changed_at"}],"version":N}`.
4. Changing different fields on the same row must NOT conflict.
5. Frontend (`ShipmentGridPage.tsx`): always send `base`. On 409 show a `ConfirmDialog`-style prompt "Someone changed this cell to X. Keep mine / Use theirs". "Use theirs" updates the cell; "Keep mine" re-sends with the fresh base.

**Done when (tests):** same field from two clients -> one 200 and one 409; different fields -> both 200; status rules still fire correctly; grid shows the conflict dialog.

**Human checks:** open the tracker in two browsers; edit the same cell in both; confirm the second one gets the dialog.

---

### Phase 3 — Safe invoice numbering and one-shot actions (about 2-4 hrs)

**Goal:** no duplicate or skipped invoice numbers; no double issue.

**Do:**
1. Issue in ONE transaction: guarded transition `UPDATE final_invoices SET status='issued', ... WHERE id=:id AND status='draft'` (0 rows updated -> return 409 "already issued"). Allocate the number with `UPDATE invoice_counters SET next_number = next_number + 1 WHERE fy=:fy RETURNING next_number - 1`. Keep the current rule that a tax + reimbursement pair shares one number. Cancelled numbers are never reused.
2. Add a unique constraint on (financial year, number, invoice kind).
3. Same guarded-transition pattern for: Cancel, Bill, Unbill, Mark proforma as Sent, Create final invoices (must not create the pair twice).
4. UI: disable the button while the request runs, and show a friendly message on 409.

**Done when (tests):** 20 parallel Issue calls on 20 drafts give unique numbers with no gaps; 2 parallel Issue calls on one draft -> exactly one succeeds.

**Human checks:** double-click Issue rapidly on a test invoice; confirm only one number is used.

---

### Phase 4 — Locking for multi-step writers (about 6-8 hrs)

**Goal:** background-style actions can't race with people editing.

**Do (all using the lock order in Golden Rule 9):**

| Writer | Change |
|---|---|
| Document upload / re-read / remove / amount edit / cost-inclusion edit | Extract PDF text first (no lock). Then one short transaction: lock shipment, re-check "fill blanks only" inside the lock, apply, derive status, refresh draft proformas |
| `app/invoice/autofill.py` | Runs inside the same transaction and lock. Never touches lines with `is_manual`. Respects `Proforma.suppressed` |
| Duty challan upload | Lock each affected shipment in id order, then refresh drafts |
| Proforma edit | Add `version` to proformas and line items. Line PATCH accepts `base` for changed fields, same 409 pattern as Phase 2 |
| Create final invoices | Lock the shipment and proforma first |
| Tracker CSV re-import (when built) | Take `pg_advisory_lock(hash('tracker-import'))`. Preview returns each row's `version`. Apply rejects rows changed since preview and lists them again |

**Done when (tests):** see Phase 6 list items 5-8.

**Human checks:** upload a document to a shipment while a colleague edits a cell on the same shipment; both changes survive.

---

### Phase 5 — Safe undo and near-live updates (about 3-5 hrs)

**Goal:** undo can't clobber a colleague, and everyone sees changes within seconds.

**Do:**
1. **Undo:** each undo entry stores `{shipment, field, before, after}`. Undo applies only if the current value still equals `after` (send it as `base`). Otherwise show "Changed by X since, not undone".
2. **Change feed:** `GET /shipments/changes?since=<timestamp>` (port-scoped, includes soft-deleted ids) returning changed rows with `version`. Add an index on `updated_at`.
3. **Frontend polling:** every 8 seconds while the tab is visible (pause when hidden, refetch on focus). Apply changes with AG Grid transactions, briefly flash changed cells, and never overwrite a cell currently being edited (flag it as a pending conflict instead). Keep the existing 5-minute full refresh as a fallback.
4. Also poll the shipment detail page and proforma panel for their own `version` and show a "This was changed by X, reload" banner.

**Done when:** a change in browser A appears in browser B within ~10 s; undo refuses to overwrite a newer change.

---

### Phase 6 — Concurrency tests (about 3-5 hrs)

**Goal:** prove the design with tests that fail if the locking is removed.

Write these as pytest tests against real Postgres using threads:

| # | Test | Expected |
|---|---|---|
| 1 | Two PATCHes of the same field | one 200, one 409, no lost update |
| 2 | Two PATCHes of different fields, same row | both 200, both values present |
| 3 | 20 parallel Issue on 20 drafts | unique consecutive numbers |
| 4 | 2 parallel Issue on the same draft | exactly one succeeds |
| 5 | Autofill racing a manual line edit | manual edit wins, nothing lost |
| 6 | Document upload racing a manual edit | both survive; blanks-only rule respected |
| 7 | CSV apply when a row changed after preview | that row is rejected |
| 8 | 200 random mixed operations across 5 threads | no deadlocks, no errors, versions strictly increasing |

Also add `docs/TWO_BROWSER_TEST.md`: a 10-step manual script a non-developer can follow with two browser windows.

**Done when:** all pass, and temporarily removing a lock makes at least tests 1, 3 and 5 fail (prove the tests are real, then restore the lock).

---

### Phase 7 — Google Drive storage (about 6-8 hrs)

**Goal:** every document and issued invoice PDF is saved in the client's Shared Drive by the server.

**Do:**
1. `DocumentStorage` interface with `LocalStorage` (dev) and `DriveStorage`. Selected by `STORAGE_BACKEND=local|drive`.
2. `DriveStorage` uses the service account (env `GOOGLE_SERVICE_ACCOUNT_JSON`), Shared Drive flags (`supportsAllDrives=true`, `includeItemsFromAllDrives=true`) and env `DRIVE_ROOT_FOLDER_ID` (`Documents` folder), `DRIVE_INVOICES_FOLDER_ID`, `DRIVE_BACKUPS_FOLDER_ID`.
3. Folder structure: `Documents/<Client>/<MBL or Job>/<generated name>.pdf`. Store the Drive folder ID in a `drive_folders` table (unique on path). Create folders under `pg_advisory_xact_lock` so two simultaneous uploads never create duplicates.
4. **Safety guard:** before any Drive call, verify the target's ancestry is inside the configured root folders. Refuse otherwise. The app never deletes Drive files (except backup retention in Phase 8, and only files it created with the `erp-` prefix). "Remove document" moves the file to a `_removed` folder.
5. Upload flow: browser -> backend (extract, name, tracker update) -> Drive -> save `drive_file_id` + link. A Drive failure never loses the upload: keep the file, mark `drive_sync_pending`, retry via a scheduled job, and show the warning in the result banner (as today).
6. On **Issue**, generate the final invoice PDF and save it to `Invoices/<FY>/` in Drive; store the file id on the invoice.
7. Keep the existing Drive picker ("Choose from Google Drive") for reading existing PDFs.
8. **Fallback** if Shared Drives are not available: existing folder + domain-wide delegation impersonating one dedicated user; keep the same ancestry guard. Ask the human before switching.

**Done when:** in dev with a real test Shared Drive, uploading a PDF creates the right folder and file; two simultaneous uploads for a new client create one folder; issuing an invoice saves its PDF; a request to write outside the root is refused.

**Human checks:** upload a document; find it in Drive; issue a test invoice; find its PDF.

---

### Phase 8 — Backups and restore drill (about 4-6 hrs)

**Goal:** no data loss even if the host account or database is lost.

**Do:**
1. `backend/scripts/backup.py`: `pg_dump -Fc`, encrypt (key from env `BACKUP_ENCRYPTION_KEY`, never stored in Drive), write a small manifest JSON (timestamp, size, row count per table), upload dump + manifest to Drive `Backups`, verify the upload (size/checksum) before finishing.
2. **Schedule (inside the app, advisory-locked):** every 12 hours, e.g. 06:00 and 20:00 IST.
3. **Retention (delete only after a newer backup is verified):** keep all from the last 14 days; keep the Sunday 06:00 one for 12 weeks; keep the 1st-of-month one for 12 months. Only delete files this job created (name prefix `erp-`). Name: `erp-YYYY-MM-DD-HHMM.dump.enc`.
4. **Alerts:** admin dashboard shows a red banner if the last verified backup is older than 26 hours or its size dropped more than 40% from the previous one. Endpoint `GET /health/backups`. Send an email if SMTP env vars are configured.
5. `backend/scripts/restore.py <file> --into <empty database url>`: decrypt, restore into a scratch database and print row counts against the manifest. Never restore over a live database without an explicit `--i-am-sure` flag.
6. Optional (H7): if `EXTRA_BACKUP_S3_*` env vars exist, also upload the weekly dump to that bucket.
7. `docs/RESTORE_RUNBOOK.md`: plain-language steps for Render point-in-time recovery AND for restoring from a Drive dump.

**Done when:** a backup runs, appears in Drive, restores into a scratch database with matching row counts; retention deletes only what it should (tested with fake dates); the alert banner appears when the last backup is faked old.

**Human checks:** open the `Backups` folder, see the file; run the restore script once using the runbook.

---

### Phase 9 — Production readiness (about 4-6 hrs)

**Do:**
1. Backend serves the built frontend (`frontend/dist`) with a catch-all route for the SPA. CORS is restricted to `PUBLIC_URL` only (no `*`).
2. Refuse to start in production if: `JWT_SECRET_KEY` is missing/default, the admin password is still `changeme`, or required env vars are missing. Print a clear message.
3. No default admin in production. Add a one-off command to create the first admin with a password from the environment.
4. Login rate limit (5 attempts/min per IP+email) and temporary lockout. Password minimum stays 12.
5. Security headers, request size limit for uploads, log to stdout, `/health` (checks the database).
6. `Dockerfile` (Python slim + `postgresql-client` + fonts needed by reportlab; frontend built in a first stage) and `render.yaml`. Run `alembic upgrade head` on start, after the pre-migration dump (Phase 1).
7. Update `.env.example` (see section 6) and README run instructions.
8. Optional: Sentry (free tier) if an env var is set.

**Done when:** `docker compose up` runs the whole app locally from a clean checkout; health and login limits work; the app refuses to boot with unsafe settings.

---

### Phase 10 — Deploy on Render, domain, go-live (about 4-8 hrs, plus waiting on the client)

**Human steps first:** H1, H2, H6 done. Render account belongs to the client.

**Do (Claude Code guides; human clicks):**
1. Render: create the Postgres instance (paid tier, Recovery page shows point-in-time recovery) and the Docker web service. Region: check the list and choose the closest to India (Singapore is likely). Set every env var from section 6 as a Render secret.
2. Add the custom domain `erp.claruslogistics.in` in Render; add the CNAME at Dynadot; wait for the certificate.
3. Copy local data to production **once**: run `sqlite_to_postgres.py` (or a `pg_restore` of the Phase 0 database) against the production database from the developer's laptop, then verify row counts. Only if the production database is empty.
4. Run the first backup manually; run the restore drill into a scratch database.
5. Create real users (no shared logins). Rotate the admin password.
6. Smoke test on production: log in, edit a cell, upload a test PDF, issue a **test** invoice, confirm Drive files, confirm conflict dialog with two browsers.
7. Delete the test data properly (soft delete) or clearly mark it as test.

**Go-live checklist (all must be ticked before real invoices):**

- [ ] Point-in-time recovery visible on the Render database Recovery page
- [ ] A backup file exists in Drive `Backups`, and a restore drill passed this week
- [ ] Row counts after restore matched the manifest
- [ ] Backup alert banner tested (fake an old backup)
- [ ] Issued-invoice lock tested (cannot edit or delete via API)
- [ ] Two-browser conflict test passed on production
- [ ] Domain auto-renew and 2FA on at Dynadot
- [ ] Render and Google accounts are in the client's name, with a recovery contact
- [ ] Every user has their own login; default admin password gone
- [ ] `RESTORE_RUNBOOK.md` printed or saved where the client can find it

---

## 4B. Part B phases — after launch (Phases 11-19)

> **Do not start Part B until the Phase 10 go-live checklist is fully ticked.** The human will be present for every Part B session because real credentials, real emails and a government portal are involved.
> Same prompt as section 0, plus: "This is Part B. Read section 9 (Automation Golden Rules) and section 10 (ICEGATE legend) first."

### Decisions for Part B (do not re-debate)

| Topic | Decision |
|---|---|
| Sources of truth for status | (1) ICEGATE Communicator emails and CSV, (2) ICEGATE reports downloaded by Playwright. Both feed one `shipment_events` table |
| Mailbox | The mailbox that receives the ICEGATE login OTP is the **same** mailbox that receives BE copies, gatepass copies, acknowledgements and so on. One email engine serves both jobs |
| Access level | Read-only. The engine never sends, deletes, moves or marks mail as read |
| Automation runs where | A **separate Render background worker** (Docker, Playwright + Chromium), not inside the web service. It talks to the app through the API with a worker token |
| Shipping-line ETA tracking | **Will not be built.** Carrier websites detect scrapers and stop loading. ETAs stay manual |
| Automation never wins over a human | Automation only fills blanks and moves status forward. It never overwrites a value a person typed, and it takes `locked_shipment` like any other writer |
| Doubt goes to a person | If a message or row cannot be matched to exactly one shipment, it goes to the Inbox as "needs review". Never guess |

---

### Phase 11 — Safety net: end-to-end tests and real-PDF fixtures (about 4-6 hrs)

**Goal:** every later change (including everything in Phases 12-19) is caught if it breaks the basics.

**Do:**
1. Add Playwright test project `e2e/` (separate from the automation worker). Runs against a local Docker stack with a seeded test database.
2. Tests: login; edit a tracker cell; two-browser conflict dialog; upload a document; create and edit a proforma; issue an invoice; issued invoice cannot be edited.
3. `backend/tests/fixtures/pdfs/`: the redacted real PDFs from H8, each with an `expected.json` (fields the reader must extract). A test compares actual vs expected. Add a **"needs review" flag** when the reader is unsure of a field, and show it in the UI.
4. CI command (or a single script) that runs backend tests + e2e tests. Document it in README.

**Done when:** e2e suite passes on a clean checkout; breaking a locking rule or a field extractor makes a test fail.

**Human checks:** run the e2e command once and watch it pass; deliberately break something small on a branch and see it fail.

---

### Phase 12 — Automation foundations (about 4-6 hrs)

**Goal:** one safe place for everything automated to write to, with an off switch.

**Do:**
1. Tables (Alembic): `shipment_events` (id, source `email|csv|portal|manual`, event_type, shipment_id nullable, external_ref, dedupe_key UNIQUE, payload JSON, status `applied|needs_review|ignored|failed`, applied_at, created_at), `automation_settings` (key, value, updated_by), `automation_runs` (job name, started, finished, result, error, screenshot path).
2. **Kill switch:** settings `automation_enabled` (global) and one flag per job. Every job checks it at start and between steps. Admin page toggles them. Default OFF.
3. **Actor:** audit rows written by automation use user `automation` with the source and event id in the note. Give it its own role with only the permissions it needs (no invoice issue, no delete, no user management).
4. **Worker token:** `WORKER_TOKEN` env var; endpoints under `/worker/*` accept only that token (constant-time compare), rate limited, and cannot be called with a normal user JWT.
5. `apply_event(event)` function: the ONLY way automation changes shipments. Takes `locked_shipment`, follows "fill blanks / move forward only", derives status, writes audit, marks the event `applied`. Idempotent: applying the same `dedupe_key` twice does nothing.
6. Admin "Automation" page: list of events (filter by status), runs, and the kill switches. Read-only for non-admins.

**Done when (tests):** duplicate event is ignored; event cannot overwrite a human-entered value; kill switch off means jobs refuse to run; a normal JWT is refused on `/worker/*`.

**Human checks:** toggle the switch; confirm a fake event appears in the list and can be marked ignored.

---

### Phase 13 — ICEGATE Communicator CSV import (about 4-6 hrs)

**Goal:** get the ICEGATE message history into the ERP by manual upload, with no login and no automation. This also proves the matching rules before anything runs unattended.

**Human supplies first:** the Communicator CSV (not yet in the repo — H11). **Claude Code's first step is to read the CSV and report back** the column names, a sample of each message type present, date format, and which column could identify the shipment (BE number, job number, MBL). Stop and confirm the mapping with the human before writing the importer.

**Do:**
1. Upload endpoint + UI (under an "ICEGATE" or "Inbox" area): choose CSV, **preview** first (rows found, message types, how many match a shipment, how many need review, how many are duplicates), then Apply.
2. Classify each row using the legend in section 10. Unknown message types are kept and shown as `unknown`, never dropped.
3. Match to a shipment using the identifiers the CSV actually has (confirmed in step 1). Exactly one match: create event. Zero or several: `needs_review`.
4. `dedupe_key` from stable fields (message type + reference + timestamp), so re-uploading the same CSV creates nothing new.
5. Apply through `apply_event` (Phase 12). Only the mapping approved in section 10 changes the tracker; everything else is stored as history only.
6. Import is atomic per file: either all rows are recorded or none, with a summary at the end.

**Done when (tests):** the real CSV imports; a second import of the same file changes nothing; an ambiguous row lands in `needs_review`; a human-entered value is never overwritten.

**Human checks:** import the CSV; open 3 shipments and compare their status with what ICEGATE shows.

---

### Phase 14 — Email engine: read-only mailbox reader and OTP (about 6-8 hrs)

**Goal:** the ERP can read the ICEGATE mailbox safely, fetch a fresh login OTP on request, and record incoming ICEGATE messages.

**Human supplies first (H10):** read access to the mailbox. Prefer the Gmail API with the **read-only scope** if it is Google Workspace; otherwise IMAP with an app password. Ask the human which it is. Do not ask for the mailbox's main password.

**Do:**
1. `MailboxReader` interface with one implementation (Gmail API or IMAP). Read-only: use `BODY.PEEK` (IMAP) or the read-only scope so nothing is marked as read. No send, delete or move code exists in the class at all.
2. Poll every 2-5 minutes (advisory-locked scheduler job, kill-switch aware). Remember the last processed message with its Message-ID, so nothing is processed twice. First run only looks back N days (setting, default 30).
3. **Store, do not interpret, first:** for each email save sender, subject, received time, Message-ID, and attachments (through `DocumentStorage`, under a `Mail/` area). Then classify by subject using the legend in section 10. Claude Code must ask the human for 2-3 real sample emails of each type before writing parsers (H11). Never invent a regex from memory.
4. **OTP function:** `get_latest_otp(after=<timestamp>, timeout=120s)`. Accepts only mail from the ICEGATE sender, received after the login attempt started, and not used before. Marks each OTP as consumed. Returns nothing (and alerts) on timeout. Never logs the OTP or writes it to events, audit or screenshots.
5. Emails create `shipment_events` via the same matching as Phase 13.
6. Health: `GET /health/mailbox` (last successful poll, last message time). Red banner if the poll has failed for more than 2 hours.

**Done when (tests, using recorded sample emails):** each known type is classified; the same email twice creates one event; an OTP older than the login attempt is refused; a second use of the same OTP is refused; the reader class has no write methods.

**Human checks:** send yourself a test mail; see it appear; confirm the mailbox still shows it as unread.

---

### Phase 15 — Inbox: auto-attach documents and drag-and-drop (about 6-8 hrs)

**Goal:** documents arriving by email or dropped into the browser attach themselves to the right shipment. This is the biggest time saver in the plan.

**Do:**
1. **Inbox page:** a list of unmatched or unsure items (emails with attachments, dropped PDFs, `needs_review` events). Each shows a suggested shipment with the reason (e.g. "BE number matches"). One click to accept, or pick another shipment.
2. **Drag-and-drop:** drop one or many PDFs anywhere on the Inbox; the existing batch-scanning backend reads them and proposes matches. Nothing is attached until the item is either an exact single match on a strong identifier, or a person accepts it.
3. **Auto-attach rules (strict):** only auto-attach when the identifier is exact and unique (BE number, Gate Pass number, Out-of-Charge reference). Everything else waits in the Inbox. Attachments go through the normal document upload path, so Phase 4 locking and Drive storage apply.
4. Attaching a document from email triggers the same "fill blanks + derive status" as a manual upload.
5. Show on each shipment which documents came from email (source and time) so staff can see it was automatic.

**Done when (tests):** an exact match auto-attaches once (re-processing does nothing); an ambiguous item stays in the Inbox; accepting a suggestion attaches and updates the shipment; a duplicate PDF is detected by checksum.

**Human checks:** drop 5 real PDFs; check that each goes where you expect; check that the doubtful ones wait for you.

---

### Phase 16 — Automation worker and ICEGATE login with email OTP (about 6-10 hrs)

**Goal:** a separate Playwright worker that can log in to ICEGATE unattended, using the email engine for the OTP. It does no business work yet; Phases 17 and 18 add jobs.

**Human supplies first (H9, H13):** the ICEGATE user ID and password (ideally a dedicated user for the ERP), and confirmation that the client is comfortable with automated access.

**Do:**
1. New service `worker/` (own Dockerfile: Python + Playwright + Chromium) and a `render.yaml` background worker entry. Needs at least **2 GB RAM**. Secrets: `ICEGATE_USER`, `ICEGATE_PASSWORD`, `WORKER_TOKEN`, `APP_BASE_URL`.
2. **Job runner:** the worker asks the app for the next job (`/worker/next-job`), runs it, reports result and evidence (`/worker/report`). One job at a time. A job that fails leaves the system unchanged and alerts; jobs are never retried in a tight loop (max 3 attempts, then wait for a human).
3. **ICEGATE login routine:** open login, enter ID and password, ask the app for the OTP (Phase 14 function), enter it, confirm the logged-in page. Save a screenshot on every failure (with the OTP and password fields hidden).
4. **If a CAPTCHA, a blocked-IP page or an unexpected screen appears: stop, alert, and wait for a human.** Do not build CAPTCHA solving or any bypass.
5. Behave like a polite user: no parallel sessions, a random pause of a few seconds between steps, one login attempt per run, back off for at least 1 hour after a failed login (repeated failures can lock the ICEGATE account).
6. Never write the password, OTP or session cookies to logs, audit, events or screenshots.

**Done when:** a manual "test login" job from the admin page logs in, reads the logged-in username, logs out, and reports success; a wrong OTP produces one alert, not a retry storm; the kill switch stops the worker between steps.

**Human checks:** press "Test ICEGATE login" and watch the run appear with its result.

---

### Phase 17 — Daily duty challan download (about 6-10 hrs)

**Goal:** every day the worker logs in to ICEGATE, downloads the duty challan report as **Excel** (more reliable than reading the on-screen table), picks out the challans and feeds them into the existing challan import.

**Human supplies first:** one real downloaded Excel report, and which report/menu path is used in ICEGATE. Claude Code must not guess the menu path; record it with the human once.

**Do:**
1. Job `daily_duty_challan` (scheduled once a day at a time chosen by the human, kill-switch aware, advisory-locked).
2. Steps: login (Phase 16) -> open the report -> set the date range (yesterday and today, so nothing is missed) -> download Excel -> pick out challan rows -> send the file and parsed rows to the app.
3. **Parsing lives in the backend, not the worker.** Reuse the existing duty challan upload logic where possible (Phase 4 locking: lock each affected shipment in id order, then refresh drafts). Confirm the Excel columns against the sample; the challan column question in PROGRESS.md is resolved here.
4. Dedupe by challan number + date, so running the job twice, or overlapping date ranges, never doubles amounts.
5. Store the downloaded Excel in Drive under `Documents/_ICEGATE/challans/` for audit. Rows that match no shipment go to the Inbox (`needs_review`).
6. Job result shows: rows downloaded, matched, applied, needs review. Alert if 0 rows come back on a working day, or if the file layout changed.

**Done when (tests, using the real sample Excel):** parse gives the expected rows; a second run adds nothing; layout change raises an alert and applies nothing.

**Human checks:** run the job manually once; compare with the ICEGATE screen for 5 challans.

---

### Phase 18 — IGM update job (adapt the existing script) (about 4-8 hrs)

**Goal:** the IGM update Playwright script that already exists runs as a worker job, with the same login, safety and reporting as the other jobs.

**Human supplies first (H12):** the existing script. **Claude Code's first step is to read it and explain in plain words what it does**, which sites it visits, what it changes, and what it could break. Stop and confirm before altering anything.

**Do:**
1. Wrap the script as job `igm_update` using the shared login routine and the job runner. Replace any hard-coded credentials, waits or file paths. No behaviour change beyond that in the first version.
2. Input comes from the app (list of shipments needing IGM update, chosen by an explicit rule the human approves). Output goes back through `apply_event`.
3. If the script **submits or changes anything on ICEGATE**, run it in "dry run" mode first (fills the form, takes a screenshot, does not submit). Real submission is behind its own kill switch, default OFF, and needs the human to enable it after reviewing dry runs.
4. Keep a full record: which shipments, what was sent, what ICEGATE replied, screenshots on failure.

**Done when:** dry run works for 3 real shipments and the screenshots match expectations; a failure leaves the shipment untouched.

**Human checks:** review the dry-run screenshots before switching submission on.

---

### Phase 19 — Alerts, daily digest, History tab, Excel export (about 8-12 hrs)

**Goal:** the app tells staff what needs attention, shows who changed what, and exports data.

**Do:**
1. **Daily digest** (email via SMTP, plus a dashboard panel): missing documents, challans not uploaded, cleared shipments not yet billed, `needs_review` items in the Inbox, B/E Query and Negative Acknowledgement events not yet handled, failed automation runs.
2. **Alert rules** are plain settings the human can switch on/off. No alert without a way to acknowledge it.
3. **History tab** on each shipment: audit rows and events in one time-ordered list, showing who or what (user, automation, email, CSV), what changed, when.
4. **Excel export:** tracker, unbilled list, monthly billing report, per-client statement. Respect port scoping and roles.
5. Delete-approval flow only if non-admin roles will delete (see section 9 backlog).

**Done when (tests):** digest contains a known set of seeded problems; History shows both human and automation changes; exports open in Excel with correct totals.

---

## 5. Cost target (USD/month, estimates; verify before quoting)

| Item | About |
|---|---|
| Render web service, Standard | 25 |
| Render Postgres, Basic-1gb (point-in-time recovery) | 19 |
| Render Professional workspace, 1 seat (7-day recovery window) | 19 |
| Optional second backup copy outside Google | 1-3 |
| Part B: Render background worker for Playwright, 2 GB RAM (verify plan and price) | ~25 |
| Optional staging copy later | 13 |
| **Total without staging** | **~64-66** at launch; **~90** once the Part B worker runs (add 18% GST if billed in India) |

Domain already owned (Dynadot). Drive API, Drive storage and Google sign-in cost nothing extra.

## 6. Environment variables (names only; values go in Render secrets, never in git)

| Name | Purpose |
|---|---|
| `DATABASE_URL` | Postgres connection |
| `JWT_SECRET_KEY` | Login tokens (long random string) |
| `PUBLIC_URL` | `https://erp.claruslogistics.in` |
| `STORAGE_BACKEND` | `drive` in production, `local` in dev |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Service account key |
| `DRIVE_ROOT_FOLDER_ID`, `DRIVE_INVOICES_FOLDER_ID`, `DRIVE_BACKUPS_FOLDER_ID` | Shared Drive folders |
| `BACKUP_ENCRYPTION_KEY` | Encrypts dumps. Also keep a copy in a password manager, NOT in Drive |
| `SMTP_*` (optional) | Alert emails |
| `EXTRA_BACKUP_S3_*` (optional) | Second backup copy |
| `SENTRY_DSN` (optional) | Error alerts |
| `WORKER_TOKEN` (Part B) | Lets the automation worker call `/worker/*` |
| `ICEGATE_USER`, `ICEGATE_PASSWORD` (Part B, worker only) | ICEGATE login |
| `MAILBOX_*` (Part B) | Read-only mailbox access (Gmail API credentials or IMAP host/user/app password) |
| `VITE_GOOGLE_CLIENT_ID`, `VITE_GOOGLE_API_KEY`, `VITE_GOOGLE_APP_ID` | Existing Drive picker settings (frontend build) |

## 7. Growth roadmap (only when a trigger happens)

| Trigger | Change | Extra cost (rough) |
|---|---|---|
| 6-10 users at once | Replace polling with SSE (Postgres LISTEN/NOTIFY), show "who is viewing" | $0-20 |
| 10-25 users | Bigger server, PDF reading as background jobs, connection pool tuning | $30-60 |
| 25-50 users | Two or more servers, standby database with failover, monitoring alerts | $100-200 |
| 50+ users or ~10,000+ shipments | Read-only reports database, job queue, pagination/archiving in tracker, load tests before releases | varies |
| Drive storage runs low | Client upgrades Workspace storage | client cost |

## 8. Parked (do not build until asked)

| Item | Note |
|---|---|
| Read-only Google Sheets mirror of key tables | One-way (app -> Sheet), locked view, no passwords, batched writes, excluded from restore plans |
| Staging environment | Restore a recent backup into a second small deployment to test releases |
| Google sign-in restricted to the company domain | Keep roles in the database |
| Daily duty challan Playwright job | Moved into Part B, Phase 17 (separate worker, at least 2 GB RAM) |
| Automated shipment ETA tracking | Will not be built (section 9) |
| Tracker CSV re-import from the UI | Already designed in PROGRESS.md; must follow Phase 4 rules when built |

---

## 9. ERP improvement backlog and Automation Golden Rules

### Automation Golden Rules (in addition to section 2; apply to Phases 12-19)

1. **Read-only first.** Every new integration starts read-only or dry-run. Anything that submits, sends or changes data outside the ERP has its own kill switch, default OFF.
2. **Automation is an ordinary writer.** It uses `apply_event`, `locked_shipment`, the audit log and the lock order from Golden Rule 9. No back doors.
3. **Fill blanks and move forward only.** Never overwrite a human-entered value; never move a status backwards.
4. **Idempotent.** Every event has a `dedupe_key`; running any job twice is harmless.
5. **Exact match or ask.** Attach or apply only on one exact, unique match; otherwise `needs_review`.
6. **Real samples before parsers.** Claude Code must ask for real emails, CSVs, Excel files and PDFs and write tests from them. Never invent formats from memory.
7. **Secrets stay secret.** ICEGATE password, OTPs, mailbox credentials and session cookies never appear in git, logs, audit, events, screenshots or error messages.
8. **No bypassing.** If a CAPTCHA, block page or unexpected screen appears, stop and alert. No CAPTCHA solving, proxy rotation or stealth tricks.
9. **Gentle on external sites.** One session at a time, human-like pauses, back off after failures.
10. **Fail loud, change nothing.** A failed run leaves data untouched, saves evidence, and alerts.

### What we will not build

| Item | Reason |
|---|---|
| Automated shipment ETA tracking from shipping-line websites | These sites detect scrapers and stop loading; it would break constantly. ETAs stay manual (or come from documents the client already receives) |
| CAPTCHA solving or bot-detection evasion | Risks getting the ICEGATE account blocked |

### Improvement backlog (first pass from PROGRESS.md; code and live app not reviewed)

| Area | What was noticed | Suggested improvement | When | Phase |
|---|---|---|---|---|
| Automated UI tests | Parts of the app were not click-tested | Playwright tests for login, edit a cell, upload, proforma, issue invoice | Launch week | 11 |
| PDF accuracy | Receipt reading has "no sample yet"; challan columns not confirmed | Folder of real PDFs with expected results; "needs review" flag when unsure | Before launch (main types) | 11, 17 |
| Invoice correctness | Taxable vs pure-agent is partly open; IRN/ACK typed by hand; numbering design pending | Accountant reviews 5-10 real invoices from the app; confirm whether e-invoicing applies | Before first real invoice | H-task, not code |
| Two sources of truth | The client still uses the Google Sheet | Pick a cut-over date after which the sheet is read-only | Launch week | 10 |
| Login security | No password reset or 2FA noted | Login rate limit now (Phase 9); admin password reset and Google sign-in later | Launch / month 1 | 9 |
| Document intake | Backend batch scanning has no UI | Drag-and-drop Inbox that matches PDFs to shipments; email intake | Month 1-2 (biggest time saver) | 14, 15 |
| Alerts | Nothing pushes problems to staff | Daily digest: missing documents, challan not uploaded, unbilled cleared shipments | Month 1-2 | 19 |
| History | No audit viewer | Per-shipment History tab | Month 1 | 19 |
| Reports | Only the dashboard | Excel export, monthly billing report, unbilled list, per-client statement | Month 2+ | 19 |
| Delete approval | Spec asks for it; currently a plain 403 | Build only if non-admin roles will delete | Month 1 | 19 |
| ICEGATE status | Staff check ICEGATE by hand | Communicator CSV import, then email engine, then daily challan and IGM jobs | Month 1-3 | 13-18 |

---

## 10. ICEGATE Communicator message legend

These are the message types that appear in the ICEGATE Communicator CSV and in ICEGATE emails. Claude Code uses this table to classify messages. **The "ERP effect" column is a proposal: at Phase 13, Claude Code reads PROGRESS.md, maps each effect to the existing statuses and fields, and the human confirms every row before anything is applied.** Rows marked "history only" are stored and shown but change nothing.

Import and export are both present. Which ones matter depends on the client's business; the human marks the unused families as "ignore".

### Bill of Entry (import) — most important

| Message type | Meaning | Proposed ERP effect |
|---|---|---|
| Submit B/E | BE filed | History only |
| Submit B/E (Amendment) | BE amendment filed | History only |
| B/E Acknowledgement | ICEGATE accepted the BE | Record BE number/date if blank |
| B/E Acknowledgement(Amendment) | Amendment accepted | History only |
| B/E Negative Acknowledgement | BE rejected | **Alert**; needs review |
| B/E Negative Acknowledgement(Amendment) | Amendment rejected | **Alert**; needs review |
| Processed B/E | BE processed | Attach copy; status forward if a matching status exists |
| B/E Query | Customs raised a query | **Alert**; unhandled until acknowledged |
| B/E Query Reply | Reply sent | History only; clears the query alert |
| B/E Appr Status | Assessment/approval status | History only (store the text) |
| B/E Examination Order | Goods ordered for examination | **Alert**; note on shipment |
| Gate Pass | Gate pass issued | Attach copy; status forward |
| Out of Charge | Cleared by customs | Status forward to cleared; feeds "unbilled cleared shipments" alert |

### Shipping Bill (export)

| Message type | Meaning | Proposed ERP effect |
|---|---|---|
| Submit S/B | SB filed | History only |
| Submit S/B (Amendment) | SB amendment filed | History only |
| S/B Acknowledgement | SB accepted | Record SB number/date if blank |
| S/B Negative Acknowledgement | SB rejected | **Alert** |
| S/B Query | Customs query | **Alert** |
| S/B Query Reply | Reply sent | Clears the query alert |
| Submit GR | GR filed | History only |
| GR Acknowledgement | GR accepted | History only |
| Assessed SB Copy | Assessed copy issued | Attach copy |
| eGatepass SB Copy | e-Gatepass issued | Attach copy |
| LEO SB Copy | Let Export Order | Attach copy; status forward |

### CIM / CIM ESD (customs interface messages)

| Message type | Proposed ERP effect |
|---|---|
| Submit CIM, Submit CIM ESD | History only |
| CIM Acknowledgement, CIM ESD Acknowledgement, CIM Submission Acknowledgement | History only |
| CIM Negative Acknowledgement, CIM ESD Failure | **Alert** |

### SCMTR (cargo movement)

| Message type | Proposed ERP effect |
|---|---|
| Submit SCMTR | History only |
| SCMTR Acknowledgement | History only |
| SCMTR Negative Acknowledgement, SCMTR Structure Failure | **Alert** |

### Rules for using the legend

1. Classification is by exact message type text. Anything not in this list is `unknown`: stored, shown in the Inbox, never dropped, never applied.
2. Every "Negative Acknowledgement", "Failure" and "Query" is an alert that stays open until a person acknowledges it.
3. Claude Code adds one test per row above using a real sample (H11). A row with no sample is marked "untested" in `PROGRESS.md` and applies nothing automatically.
4. New message types that ICEGATE adds later go through the same path: `unknown` first, then mapped by the human.

