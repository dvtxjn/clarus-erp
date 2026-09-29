"""
Restore an encrypted backup into an EMPTY database and check the row counts.

    .venv/bin/python scripts/restore.py backups/auto/2026-09/erp-2026-09-29-2000.dump.enc \\
        --into postgresql://erp:...@localhost:5432/erp_restore_check

The key comes from BACKUP_ENCRYPTION_KEY (backend/.env, or the password manager). Refuses a
target that already has tables unless --i-am-sure (never restore over the live database
by accident). The manifest (<file>.manifest.json next to it) is used to compare row counts.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import sqlalchemy as sa  # noqa: E402

from app.backups import fernet, pg_tool, plain_url, row_counts  # noqa: E402


def main(args: list[str]) -> int:
    if len(args) < 3 or args[1] != "--into":
        print(__doc__)
        return 2
    src, target = Path(args[0]), plain_url(args[2])
    if not target.startswith("postgresql"):
        print("The target must be a postgresql:// URL")
        return 2
    tables = sa.inspect(sa.create_engine(target)).get_table_names()
    if tables and "--i-am-sure" not in args:
        print(f"Refusing: the target has {len(tables)} tables. Use an empty database (or --i-am-sure).")
        return 1
    data = fernet().decrypt(src.read_bytes())
    with tempfile.NamedTemporaryFile(suffix=".dump") as f:
        f.write(data)
        f.flush()
        r = subprocess.run([pg_tool("pg_restore"), "--no-owner", "--dbname", target, f.name], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"pg_restore reported problems:\n{r.stderr[:2000]}")
    manifest_file = src.with_name(src.name + ".manifest.json")
    if not manifest_file.exists():
        print("Restored. (No manifest found next to the file — row counts not compared.)")
        return 0 if r.returncode == 0 else 1
    expected = json.loads(manifest_file.read_text())["rows"]
    got = row_counts(target)
    bad = {t: (n, got.get(t)) for t, n in expected.items() if got.get(t) != n}
    print(f"{'table':<26}{'backup':>8}{'restored':>10}")
    for t, n in expected.items():
        print(f"{t:<26}{n:>8}{str(got.get(t)):>10}{'   <-- DIFFERENT' if t in bad else ''}")
    print("\nRestore check passed: every table matches." if not bad else "\nROW COUNTS DIFFER.")
    return 0 if not bad and r.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
