"""
Database backups (launch Phase 8).

Every 12 hours (checked hourly, advisory-locked so one app instance runs it):
  pg_dump -Fc  ->  check it's readable (pg_restore --list)  ->  encrypt (Fernet, key from
  BACKUP_ENCRYPTION_KEY — never stored in Drive)  ->  write  erp-YYYY-MM-DD-HHMM.dump.enc
  + a manifest (.manifest.json: sizes, sha256, migration, row count per table)  ->  keep on
  this server (BACKUP_DIR)  and, with STORAGE_BACKEND=drive, upload both to Drive
  "Backups/<YYYY-MM>/" and verify the upload (size + md5) before calling it done.

Nothing is ever deleted — not old backups, not in Drive (client rule, 2026-09-29).
Restore: scripts/restore.py (into an empty database, row counts checked against the manifest).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import text

from app.core.database import DATABASE_URL, SessionLocal, engine

log = logging.getLogger("backups")

IST = timezone(timedelta(hours=5, minutes=30))
EVERY_HOURS = 12
STALE_HOURS = 26  # banner when the last good backup is older than this
SHRINK_ALERT = 0.40  # ...or when it's 40 % smaller than the one before


def backup_dir() -> Path:
    return Path(os.getenv("BACKUP_DIR", "./backups/auto"))


def pg_tool(name: str) -> str:
    """pg_dump / pg_restore: PG_BIN, then PATH, then Postgres.app."""
    for candidate in (Path(os.getenv("PG_BIN", "")) / name if os.getenv("PG_BIN") else None,
                      shutil.which(name),
                      Path("/Applications/Postgres.app/Contents/Versions/latest/bin") / name):
        if candidate and Path(candidate).exists():
            return str(candidate)
    raise RuntimeError(f"{name} not found — install the Postgres client tools or set PG_BIN")


def plain_url(url: str = DATABASE_URL) -> str:
    return url.replace("+psycopg2", "")


def fernet():
    from cryptography.fernet import Fernet

    key = os.getenv("BACKUP_ENCRYPTION_KEY", "").strip()
    if not key:
        raise RuntimeError("BACKUP_ENCRYPTION_KEY is not set (scripts/backup.py --new-key makes one)")
    return Fernet(key.encode())


def row_counts(url: Optional[str] = None) -> dict[str, int]:
    """Rows per table (soft-deleted rows included — a plain count)."""
    import sqlalchemy as sa

    eng = engine if url is None else sa.create_engine(url)
    with eng.connect() as c:
        tables = [t for t in sa.inspect(c).get_table_names() if t != "alembic_version"]
        return {t: c.execute(text(f'SELECT count(*) FROM "{t}"')).scalar() for t in sorted(tables)}


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name} failed: {r.stderr.strip()[:300]}")


def run_backup() -> "BackupRun":
    """Make one backup now. Never raises: the result is recorded in backup_runs."""
    from app import storage
    from app.models.backup import BackupRun

    now = datetime.now(IST)
    name = f"erp-{now:%Y-%m-%d-%H%M}.dump.enc"
    with SessionLocal() as db:
        run = BackupRun(name=name, status="running", started_at=now.replace(tzinfo=None))
        db.add(run)
        db.commit()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dump = Path(tmp) / "db.dump"
                _run([pg_tool("pg_dump"), "--format=custom", "--no-owner", "--file", str(dump), plain_url()])
                _run([pg_tool("pg_restore"), "--list", str(dump)])  # readable, not truncated
                raw = dump.read_bytes()
            enc = fernet().encrypt(raw)
            with engine.connect() as c:
                migration = c.execute(text("SELECT version_num FROM alembic_version")).scalar()
            manifest = {"name": name, "created_at": now.isoformat(), "dump_bytes": len(raw),
                        "encrypted_bytes": len(enc), "sha256": hashlib.sha256(enc).hexdigest(),
                        "migration": migration, "rows": row_counts()}
            folder = backup_dir() / f"{now:%Y-%m}"
            folder.mkdir(parents=True, exist_ok=True)
            (folder / name).write_bytes(enc)
            (folder / f"{name}.manifest.json").write_text(json.dumps(manifest, indent=2))
            run.local_path, run.size_bytes, run.sha256 = str(folder / name), len(enc), manifest["sha256"]

            client = storage.drive()
            if client is not None:
                try:
                    fid = storage.ensure_folder(f"Backups/{now:%Y-%m}")
                    meta = client.upload(fid, name, enc, "application/octet-stream")
                    got = client.get(meta["id"], "id,size,md5Checksum")
                    if int(got.get("size", -1)) != len(enc) or got.get("md5Checksum") != hashlib.md5(enc).hexdigest():
                        raise RuntimeError("the copy in Drive doesn't match (size / checksum)")
                    client.upload(fid, f"{name}.manifest.json", json.dumps(manifest, indent=2).encode(), "application/json")
                    run.drive_file_id = meta["id"]
                except Exception as e:  # noqa: BLE001 — the local copy is still good; the banner says Drive failed
                    run.error = f"Saved on the server, but not in Drive: {e}"[:300]
            run.status = "ok"
        except Exception as e:  # noqa: BLE001
            log.exception("backup failed")
            run.status, run.error = "failed", str(e)[:300]
        run.finished_at = datetime.now(IST).replace(tzinfo=None)
        db.commit()
        db.refresh(run)
        return run


def backup_if_due() -> None:
    """The hourly job: back up when the last good one is 12 hours old (or there is none)."""
    from app.models.backup import BackupRun

    if engine.dialect.name != "postgresql" or not os.getenv("BACKUP_ENCRYPTION_KEY"):
        return
    with SessionLocal() as db:
        last = (db.query(BackupRun).filter(BackupRun.status == "ok")
                .order_by(BackupRun.started_at.desc()).first())
    if last is None or datetime.now(IST).replace(tzinfo=None) - last.started_at >= timedelta(hours=EVERY_HOURS):
        run_backup()


def status() -> dict:
    """For the admin banner and GET /health/backups."""
    from app import storage
    from app.models.backup import BackupRun

    with SessionLocal() as db:
        ok = (db.query(BackupRun).filter(BackupRun.status == "ok")
              .order_by(BackupRun.started_at.desc()).limit(2).all())
        latest = db.query(BackupRun).order_by(BackupRun.started_at.desc()).first()
    warnings = []
    enabled = engine.dialect.name == "postgresql" and bool(os.getenv("BACKUP_ENCRYPTION_KEY"))
    if not enabled:
        warnings.append("Automatic backups are off (needs Postgres and BACKUP_ENCRYPTION_KEY).")
    last = ok[0] if ok else None
    age = (datetime.now(IST).replace(tzinfo=None) - last.started_at).total_seconds() / 3600 if last else None
    if enabled and (last is None or age > STALE_HOURS):
        warnings.append("No good backup in the last 26 hours." if last else "No backup has been made yet.")
    if len(ok) == 2 and ok[1].size_bytes and ok[0].size_bytes < ok[1].size_bytes * (1 - SHRINK_ALERT):
        warnings.append("The last backup is more than 40 % smaller than the one before — check nothing was lost.")
    if latest is not None and latest.status == "failed":
        warnings.append(f"The last backup failed: {latest.error}")
    if last is not None and storage.drive() is not None and not last.drive_file_id:
        warnings.append(last.error or "The last backup is only on the server, not in Drive.")
    return {"enabled": enabled, "last_ok_at": last.started_at.isoformat() if last else None,
            "last_ok_age_hours": round(age, 1) if age is not None else None,
            "last_ok_name": last.name if last else None, "in_drive": bool(last and last.drive_file_id),
            "warnings": warnings}
