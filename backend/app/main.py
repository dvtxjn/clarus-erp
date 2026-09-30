import asyncio
import hmac
import logging
import os
import sys

from fastapi import Depends, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm.exc import StaleDataError
from fastapi.middleware.cors import CORSMiddleware

from app import backups
from sqlalchemy import text

from app.core import jobs, realtime, web
from app.core.database import engine
from app.core.production import check_or_exit, is_production
from app.core.deps import require_admin
from app.models.user import User
from app.core.migrate import run_migrations
from app import models  # noqa: F401 — populates Base.metadata
from app.routers import auth, shipments, documents, hs_codes, proforma, extraction, ports, tracker_columns, challans, final_invoices, tracker_import, deleted, realtime as realtime_router, settings as settings_router, receivables as receivables_router, containers as containers_router

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), stream=sys.stdout,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Customs Clearance ERP API", version="0.1.0",
              docs_url=None if is_production() else "/docs", redoc_url=None)

web.install(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=web.cors_origins(),  # production: PUBLIC_URL only
    allow_credentials=False,  # the login token travels in a header, never a cookie
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Filename"],
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
app.include_router(settings_router.router)
app.include_router(receivables_router.router)
app.include_router(containers_router.router)
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
    check_or_exit()  # APP_ENV=production: refuse unsafe settings
    # Production sets AUTO_MIGRATE=0 and runs scripts/pre_migration_backup.sh instead,
    # so the database is dumped before every schema change.
    if os.getenv("AUTO_MIGRATE", "1") != "0":
        run_migrations()


@app.on_event("startup")
async def start_live_updates():
    realtime.start(asyncio.get_running_loop())
    jobs.start()


@app.get("/health/backups")
def backup_health(_admin: User = Depends(require_admin)):
    """Admin: when the last good backup was made, and anything to worry about."""
    return backups.status()


@app.post("/internal/jobs/{name}", include_in_schema=False)
def run_job(name: str, x_job_token: str = Header(default="")):
    """Cloud Run only gives the app CPU while it answers a request, so Cloud Scheduler calls
    this instead of the in-app timers (JOBS_ENABLED=0 there). Needs the JOB_TOKEN secret."""
    expected = os.getenv("JOB_TOKEN", "")
    if not expected or not hmac.compare_digest(x_job_token, expected):
        return JSONResponse(status_code=403, content={"detail": "forbidden"})
    if name not in jobs.JOBS:
        return JSONResponse(status_code=404, content={"detail": "no such job"})
    return {"job": name, "ran": jobs.run_named(name)}


@app.get("/health")
def health_check():
    """For Render / uptime checks: the app is up AND the database answers."""
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "database unreachable"})
    from app.sandbox import is_sandbox

    if is_sandbox():  # the app shows a "sandbox" banner; the login itself is handed out by the admin
        return {"status": "ok", "sandbox": True}
    return {"status": "ok", "sandbox": False}
