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

## Production (Render, Docker)
- `Dockerfile` builds the screens and serves them from the backend on one address; `render.yaml` describes
  the web service + Postgres. Secrets go in the Render dashboard (list in DEPLOYMENT_PLAN.md section 6).
- Start: `scripts/start.sh` → dump + migrate (`pre_migration_backup.sh`) → settings check → uvicorn.
- First admin: `ADMIN_EMAIL=… ADMIN_PASSWORD=… python scripts/create_admin.py` (Render shell).
- Backups: every 12 h to Drive `Backups/`; restore: `docs/RESTORE_RUNBOOK.md`.
- Google Drive: read and save only — the ERP never deletes anything there.
