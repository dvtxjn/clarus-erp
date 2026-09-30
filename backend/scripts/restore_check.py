"""
Backup restore test (client, 2026-09-30): restore the newest Drive backup into the scratch database
erp_restore_check (same server, never the live one) and compare row counts with the backup's manifest.
Run by the Cloud Run job erp-restore-test (deploy/gcp/restore_test.sh). Only reads Drive.
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy.engine import make_url  # noqa: E402

SCRATCH = "erp_restore_check"


def scratch_url(live: str) -> str:
    """The live DATABASE_URL with the database swapped for the scratch one."""
    url = make_url(live)
    if url.database == SCRATCH:
        raise SystemExit("DATABASE_URL already points at the scratch database")
    return url.set(database=SCRATCH).render_as_string(hide_password=False)


if __name__ == "__main__":
    from restore import main

    sys.exit(main(["--from-drive", "latest", "--into", scratch_url(os.environ["DATABASE_URL"])]))
