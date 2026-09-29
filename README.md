# Customs Clearance ERP

A shipment tracker + document manager + proforma/billing engine for a
customs clearance agency, built around the client's confirmed workflow.

## Where to start
1. **`ERP_Spec.md`** — the full requirements spec. Read §0 first.
2. **`PROGRESS.md`** — what's actually built and tested vs. what's next.
3. **`reference/`** — the client's working reference tool
   (`be_expense_sheet.py`), invoice template (`.xlsm`), and charges export
   (`.csv`). Ground truth for Module 3's extraction/calculation logic.

## Stack
- Backend: Python, FastAPI, SQLAlchemy (Postgres in prod, SQLite for local dev)
- Frontend: React, TypeScript, Vite

## Structure
```
backend/    FastAPI app — models, routers, auth, extraction logic
frontend/   React app — login, shipment tracker grid
reference/  Client-provided source files (do not modify — read for logic)
ERP_Spec.md Full requirements document
PROGRESS.md Build status + next steps
```
