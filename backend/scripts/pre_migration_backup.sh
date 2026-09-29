#!/usr/bin/env bash
# Dump the database, check the dump is readable, THEN run the migrations.
# Used on every deploy (with AUTO_MIGRATE=0 on the app). If the dump fails the
# script exits non-zero before touching the schema, so the deploy stops.
#
#   DATABASE_URL=postgresql://... [BACKUP_DIR=...] scripts/pre_migration_backup.sh
set -euo pipefail

: "${DATABASE_URL:?DATABASE_URL is not set}"
case "$DATABASE_URL" in
  postgresql*) ;;
  *) echo "pre_migration_backup: DATABASE_URL must be a postgresql:// URL" >&2; exit 1 ;;
esac
URL="${DATABASE_URL/+psycopg2/}"   # pg_dump wants a plain postgresql:// URL

BACKEND_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${BACKUP_DIR:-$BACKEND_DIR/backups/pre-migration}"
mkdir -p "$DIR"
OUT="$DIR/pre-migration-$(date -u +%Y%m%dT%H%M%SZ).dump"

pg_dump --format=custom --no-owner --file "$OUT" "$URL"
[ -s "$OUT" ] || { echo "pre_migration_backup: dump is empty" >&2; exit 1; }
pg_restore --list "$OUT" > /dev/null   # readable, not truncated
echo "pre_migration_backup: saved $OUT ($(du -h "$OUT" | cut -f1))"

cd "$BACKEND_DIR"
"${PYTHON:-python3}" -m alembic upgrade head
echo "pre_migration_backup: migrations done"
