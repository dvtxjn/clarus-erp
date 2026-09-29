#!/usr/bin/env bash
# One-off before each release (Cloud Run Job "erp-migrate"): back up to Drive, then migrate.
# A brand-new empty database has nothing to back up — the backup is skipped then.
set -euo pipefail
cd "$(dirname "$0")/.."
if python -c "
import sqlalchemy as sa; from app.core.database import engine
raise SystemExit(0 if 'alembic_version' in sa.inspect(engine).get_table_names() else 1)"; then
  python scripts/backup.py            # encrypted, saved in Drive; stops the release if it fails
else
  echo "empty database: no backup needed"
fi
python -m alembic upgrade head
echo "migrations done"
