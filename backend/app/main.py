import asyncio
import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError
from fastapi.middleware.cors import CORSMiddleware

from app.core import realtime
from app.core.migrate import run_migrations
from app import models  # noqa: F401 — populates Base.metadata
from app.routers import auth, shipments, documents, hs_codes, proforma, extraction, ports, tracker_columns, challans, final_invoices, tracker_import, deleted, realtime as realtime_router

app = FastAPI(title="Customs Clearance ERP API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(shipments.router)
app.include_router(documents.router)
app.include_router(hs_codes.router)
app.include_router(proforma.router)
app.include_router(extraction.router)
app.include_router(ports.router)
app.include_router(tracker_columns.router)
app.include_router(challans.router)
app.include_router(final_invoices.router)
app.include_router(tracker_import.router)
app.include_router(deleted.router)
app.include_router(realtime_router.router)


@app.exception_handler(StaleDataError)
def stale_write(_request: Request, _exc: StaleDataError):
    """A write based on an out-of-date copy of a shipment (someone saved in between)."""
    return JSONResponse(status_code=409, content={
        "detail": "Someone else saved this shipment at the same moment — reload and try again."})


@app.on_event("startup")
def on_startup():
    # Production sets AUTO_MIGRATE=0 and runs scripts/pre_migration_backup.sh instead,
    # so the database is dumped before every schema change.
    if os.getenv("AUTO_MIGRATE", "1") != "0":
        run_migrations()


@app.on_event("startup")
async def start_live_updates():
    realtime.start(asyncio.get_running_loop())


@app.get("/health")
def health_check():
    return {"status": "ok"}
