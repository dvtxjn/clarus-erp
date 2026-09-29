#!/usr/bin/env bash
# First deploy only (Cloud Run Job "erp-import"): restore the newest encrypted backup from
# Drive into the new, empty database. If the database already has tables it does nothing
# (restore.py refuses) — so re-running setup never overwrites live data.
set -euo pipefail
cd "$(dirname "$0")/.."
if python -c "
import sqlalchemy as sa; from app.core.database import engine
raise SystemExit(1 if sa.inspect(engine).get_table_names() else 0)"; then
  python scripts/restore.py --from-drive latest --into "$DATABASE_URL"
else
  echo "database already has data: nothing imported"
fi
