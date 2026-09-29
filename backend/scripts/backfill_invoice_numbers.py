"""Read the invoice number / IRN on CFS and shipping line invoices added before that was
read, then recompute each shipment's totals (a repeated invoice now counts once).

    .venv/bin/python scripts/backfill_invoice_numbers.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

import pdfplumber  # noqa: E402

from app import models  # noqa: E402,F401
from app import storage  # noqa: E402
from app.core.database import SessionLocal  # noqa: E402
from app.core.locking import locked_shipment  # noqa: E402
from app.extraction.be_pdf import read_pdf  # noqa: E402
from app.extraction.cfs_totals import INVOICE_DOC_TYPES, recompute_invoice_totals  # noqa: E402
from app.extraction.invoice_number import invoice_identity  # noqa: E402
from app.invoice.autofill import refresh_draft_proformas  # noqa: E402
from app.models.document import ShipmentDocument  # noqa: E402

with SessionLocal() as db:
    docs = db.query(ShipmentDocument).filter(ShipmentDocument.document_type.in_(INVOICE_DOC_TYPES)).all()
    touched = set()
    for d in docs:
        ext = dict(d.extraction or {})
        fields = dict(ext.get("fields") or {})
        if fields.get("invoice_no") and "irn" in fields:
            continue
        try:
            with pdfplumber.open(storage.local_path(d)) as pdf:
                pages, _ = read_pdf(pdf)
        except Exception as e:  # noqa: BLE001
            print(f"doc {d.id}: couldn't read ({e})")
            continue
        ident = invoice_identity("\n".join(pages))
        fields["invoice_no"] = fields.get("invoice_no") or ident["invoice_no"]
        fields["irn"] = ident["irn"]
        ext["fields"] = fields
        d.extraction = ext
        touched.add(d.shipment_id)
        print(f"doc {d.id} (shipment {d.shipment_id}): invoice {fields['invoice_no']} irn {'yes' if ident['irn'] else 'no'}")
    db.flush()
    for sid in sorted(touched):
        s = locked_shipment(db, sid)
        before = s.cfs_amount_total
        recompute_invoice_totals(db, s, None)
        refresh_draft_proformas(db, s)
        print(f"shipment {sid}: CFS total {before} -> {s.cfs_amount_total}")
    db.commit()
