# Restoring the ERP database (plain steps)

Backups are made every 12 hours: `erp-YYYY-MM-DD-HHMM.dump.enc` (+ `.manifest.json`), kept on
the server (`backend/backups/auto/<YYYY-MM>/`) and in the Shared Drive `Backups/<YYYY-MM>/`.
They are encrypted — you need the **backup encryption key** (password manager; also in
`backend/.env` as `BACKUP_ENCRYPTION_KEY`). Nothing is ever deleted automatically.

## Check a backup (restore drill — do this monthly)
1. Download the newest `.dump.enc` and its `.manifest.json` from Drive `Backups/…` into one folder.
2. Make an empty database: `psql -h localhost -d postgres -c "CREATE DATABASE erp_restore_check OWNER erp"`
3. `cd backend && .venv/bin/python scripts/restore.py <path>/erp-….dump.enc --into postgresql://erp:…@localhost:5432/erp_restore_check`
4. It prints every table's row count against the backup and ends with **"Restore check passed"**.

## Really restore (data lost / database broken)
1. Stop the app. Take a fresh backup of whatever is left (`scripts/backup.py`) — never skip this.
2. Restore into a NEW empty database (steps 2–3 above) and check the counts.
3. Point `DATABASE_URL` at the new database and start the app. Log in and open a few shipments.
4. The script refuses a database that already has tables; `--i-am-sure` overrides that — only if you
   really mean to restore over an existing database.

## On Render (after go-live)
Render's Postgres also has point-in-time recovery (Dashboard → the database → Recovery). Use it for
"undo the last hours"; use the Drive dumps if the Render account itself is lost.
