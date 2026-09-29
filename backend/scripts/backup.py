"""
    .venv/bin/python scripts/backup.py --new-key   # make an encryption key (save it in a password manager!)
    .venv/bin/python scripts/backup.py             # back up now (same as the 12-hourly job)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

if "--new-key" in sys.argv:
    from cryptography.fernet import Fernet

    print(Fernet.generate_key().decode())
    sys.exit(0)

from app import models  # noqa: E402,F401
from app.backups import run_backup  # noqa: E402

run = run_backup()
print(f"{run.status}: {run.name}  {run.size_bytes or 0} bytes  local={run.local_path}  drive={run.drive_file_id or '-'}")
if run.error:
    print(f"note: {run.error}")
sys.exit(0 if run.status == "ok" else 1)
