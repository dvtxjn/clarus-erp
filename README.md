# Clarus ERP

Customs-clearance ERP for Clarus Logistics: live shipment tracker, documents (read from PDFs,
linked to Google Drive), proformas and invoices, duty challans, backups.
Status and every decision: **PROGRESS.md**. Launch plan: **DEPLOYMENT_PLAN.md**.

## Run on this Mac (development)
1. Postgres.app running (databases `erp_db`, `erp_test`, user `erp`).
2. Backend: `cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000 --timeout-graceful-shutdown 3`
3. Frontend: `cd frontend && npm run dev` → http://localhost:5173
4. Settings: `backend/.env` and `frontend/.env` (copy the `.env.example` files; never commit them).

## Tests
- SQLite: `cd backend && .venv/bin/python -m pytest -q`
- Postgres (includes the concurrency and backup tests):
  `TEST_DATABASE_URL=postgresql://erp:erp-local-only@localhost:5432/erp_test .venv/bin/python -m pytest -q`
- Tests never touch the real Google Drive or real backups.

## Production (Google Cloud — decided 2026-09-29: Indian GST billing in INR)
- Cloud Run (the app, Singapore `asia-southeast1` so the custom domain works) + Cloud SQL PostgreSQL 18
  (`db-f1-micro`, daily backups + point-in-time recovery) + Secret Manager + Cloud Scheduler (backup / Drive-retry timers).
- **First time:** Cloud Shell → `gh auth login` → `gh repo clone dvtxjn/clarus-erp ~/clarus-erp` → upload the service-account key →
  `bash deploy/gcp/setup.sh ~/<key>.json`. It creates everything, copies the data in from the newest Drive backup,
  makes divit@ the admin (test logins switched off), deploys, sets the timers and prints the DNS record.
- **Every release:** `cd ~/clarus-erp && git pull && bash deploy/gcp/deploy.sh` (build → encrypted backup to Drive + migrate → deploy).
- `Dockerfile` builds the screens and serves them from the backend on one address; `scripts/start.sh` checks the settings
  (refuses unsafe ones) and starts. Settings (non-secret) in `deploy/gcp/config.sh`; secrets only in Secret Manager.
- Backups: every 12 h to Drive `Backups/` (+ Cloud SQL's own); restore: `docs/RESTORE_RUNBOOK.md`.
- Google Drive: read and save only — the ERP never deletes anything there.
