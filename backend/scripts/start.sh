#!/usr/bin/env bash
# Production start (Render / Docker): back up + migrate, check settings, then serve.
set -euo pipefail
cd "$(dirname "$0")/.."
export AUTO_MIGRATE=0
# 1. dump the database, verify the dump, then run the migrations (stops on any failure)
BACKUP_DIR="${BACKUP_DIR:-/tmp/erp-backups}/pre-migration" PYTHON=python scripts/pre_migration_backup.sh
# 2. refuse unsafe settings (JWT secret, default admin, storage, keys ...)
python -c "from app.core.production import check_or_exit; check_or_exit()"
# 3. serve; live streams stay open, so don't wait forever on shutdown / deploy
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --proxy-headers --forwarded-allow-ips='*' \
     --timeout-graceful-shutdown 3
