#!/usr/bin/env bash
# Production start. Migrations run separately before each release (scripts/migrate.sh —
# Cloud Run Job), so starting is fast. MIGRATE_ON_START=1: back up + migrate here instead
# (single-server hosts).
set -euo pipefail
cd "$(dirname "$0")/.."
export AUTO_MIGRATE=0
if [ "${MIGRATE_ON_START:-0}" = "1" ]; then
  scripts/migrate.sh
fi
# refuse unsafe settings (JWT secret, default admin, storage, keys ...)
python -c "from app.core.production import check_or_exit; check_or_exit()"
# live streams stay open, so don't wait forever on shutdown / deploy
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}" --proxy-headers --forwarded-allow-ips='*' \
     --timeout-graceful-shutdown 3
