"""
Background jobs inside the app (DEPLOYMENT_PLAN Phase 1 item 4): each run first takes a
Postgres advisory lock, so with several app instances only one runs a job at a time.
JOBS_ENABLED=0 turns them all off (tests, one-off scripts).
"""
import asyncio
import logging
import os
from typing import Callable

from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.core.database import engine

log = logging.getLogger("jobs")


def run_locked(name: str, fn: Callable[[], object]) -> bool:
    """Run fn unless another instance is already running `name`. True if it ran."""
    if engine.dialect.name != "postgresql":
        fn()
        return True
    with engine.connect() as c:
        if not c.execute(text("SELECT pg_try_advisory_lock(hashtext(:n))"), {"n": f"job:{name}"}).scalar():
            return False
        try:
            fn()
        finally:
            c.execute(text("SELECT pg_advisory_unlock(hashtext(:n))"), {"n": f"job:{name}"})
            c.commit()
    return True


async def _every(name: str, seconds: int, fn: Callable[[], object]) -> None:
    while True:
        await asyncio.sleep(seconds)
        try:
            await run_in_threadpool(run_locked, name, fn)
        except Exception:  # a failing job must never stop the others or the app
            log.exception("job %s failed", name)


def start() -> None:
    if os.getenv("JOBS_ENABLED", "1") == "0":
        return
    from app import storage

    from app import backups

    asyncio.create_task(_every("drive-retry", 300, storage.retry_pending))
    asyncio.create_task(_every("backup", 3600, backups.backup_if_due))  # 12-hourly, checked hourly
    from app.igm import batch

    asyncio.create_task(_every("icegate", 6 * 3600, batch.run_auto))  # IGM / ICD read-out, every 6 h
    from app import sheets_mirror

    asyncio.create_task(_every("sheets-mirror", 900, sheets_mirror.run_job))  # view-only Sheets copy, 15 min


JOBS = {"backup": "app.backups:backup_if_due", "drive-retry": "app.storage:retry_pending",
        "icegate": "app.igm.batch:run_auto", "sheets-mirror": "app.sheets_mirror:run_job"}


def run_named(name: str) -> bool:
    """Run one job by name now (Cloud Scheduler -> POST /internal/jobs/<name>)."""
    import importlib

    module, fn = JOBS[name].split(":")
    return run_locked(name, getattr(importlib.import_module(module), fn))
