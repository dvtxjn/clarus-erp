"""Load the sandbox's showcase data (P4). Only works on a sandbox:
    SANDBOX=1 DATABASE_URL=postgresql+psycopg2://…/erp_sandbox python scripts/seed_sandbox.py
It refuses unless SANDBOX=1 and the database name contains "sandbox"."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.sandbox import DEMO_EMAIL, reset  # noqa: E402

print(reset(), "— log in as", DEMO_EMAIL)
