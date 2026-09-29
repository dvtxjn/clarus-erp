"""Fill pdf_kind (digital / partly / scanned) for documents added before it existed.

    .venv/bin/python scripts/backfill_pdf_kind.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from app import models  # noqa: E402,F401
from app import storage  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.extraction.pdf_kind import pdf_kind  # noqa: E402
from app.models.document import ShipmentDocument  # noqa: E402

with SessionLocal() as db:
    docs = db.query(ShipmentDocument).execution_options(include_deleted=True).filter(ShipmentDocument.pdf_kind.is_(None)).all()
    counts: dict[str, int] = {}
    for d in docs:
        try:
            d.pdf_kind = pdf_kind(storage.local_path(d))
        except FileNotFoundError:
            d.pdf_kind = "unreadable"
        counts[d.pdf_kind] = counts.get(d.pdf_kind, 0) + 1
    db.commit()
    print(f"{len(docs)} documents: {counts}")
