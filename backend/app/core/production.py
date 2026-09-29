"""
Production safety (launch Phase 9). With APP_ENV=production the app refuses to start —
with a clear message listing every problem — when a setting is unsafe or missing.
"""
from __future__ import annotations

import os
import sys

from sqlalchemy import text

DEFAULT_SECRETS = {"", "change-me-to-a-long-random-string", "dev-secret-change-me-before-production", "test-secret"}


def is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() == "production"


def problems() -> list[str]:
    """Everything that makes this configuration unsafe for real data (empty = fine)."""
    from app.core.database import DATABASE_URL, engine
    from app.core.security import verify_password

    out = []
    secret = os.getenv("JWT_SECRET_KEY", "")
    if secret in DEFAULT_SECRETS or len(secret) < 32:
        out.append("JWT_SECRET_KEY is missing, a default, or shorter than 32 characters")
    if not DATABASE_URL.startswith("postgresql"):
        out.append("DATABASE_URL must be a postgresql:// URL (not SQLite)")
    if not os.getenv("PUBLIC_URL", "").startswith("https://"):
        out.append("PUBLIC_URL must be the site's https:// address (CORS and links use it)")
    if os.getenv("STORAGE_BACKEND", "local") != "drive":
        out.append("STORAGE_BACKEND must be 'drive' (a server's own disk is wiped on every deploy)")
    for k in ("GOOGLE_SERVICE_ACCOUNT_JSON", "DRIVE_ROOT_FOLDER_ID", "DRIVE_INVOICES_FOLDER_ID",
              "DRIVE_BACKUPS_FOLDER_ID", "BACKUP_ENCRYPTION_KEY"):
        if not os.getenv(k, "").strip():
            out.append(f"{k} is not set")
    if os.getenv("JOBS_ENABLED", "1") == "0" and len(os.getenv("JOB_TOKEN", "")) < 24:
        out.append("JOBS_ENABLED=0 needs a JOB_TOKEN (24+ characters) so Cloud Scheduler can run backups")
    if os.getenv("AUTO_MIGRATE", "1") != "0":
        out.append("AUTO_MIGRATE must be 0 (scripts/start.sh backs up, then migrates)")
    try:
        from app.models.user import User
        from app.core.database import SessionLocal

        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        with SessionLocal() as db:
            for u in db.query(User).filter(User.is_active.is_(True)).all():
                if u.email == "admin@example.com" or verify_password("changeme", u.hashed_password):
                    out.append(f"User {u.email} has the default login — change the password / remove it "
                               "(scripts/create_admin.py makes a real admin)")
    except Exception as e:  # noqa: BLE001
        out.append(f"Can't reach the database: {str(e)[:200]}")
    return out


def check_or_exit() -> None:
    if not is_production():
        return
    found = problems()
    if found:
        print("\nREFUSING TO START — unsafe production settings:\n  - " + "\n  - ".join(found) + "\n", file=sys.stderr)
        sys.exit(1)
