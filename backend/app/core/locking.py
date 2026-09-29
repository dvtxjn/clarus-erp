"""
Row locks for anything that writes to a shipment (launch Phases 2 and 4).

Lock order (DEPLOYMENT_PLAN Golden Rule 9): shipment -> proforma -> lines -> documents.
Several shipments: always in id order. Slow work (reading a PDF) happens BEFORE the
lock; the locked part is one short transaction that ends with the request's commit.

On SQLite (dev fallback) FOR UPDATE is ignored — SQLite allows one writer at a time.
"""
from typing import Iterable, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.proforma import Proforma
from app.models.shipment import Shipment

# Tests set this to widen race windows, proving the locks are what prevents lost updates.
_race_pause: float = 0.0


def _pause() -> None:
    if _race_pause:
        import time

        time.sleep(_race_pause)


def locked_shipment(db: Session, shipment_id: int) -> Optional[Shipment]:
    """SELECT ... FOR UPDATE, and refresh the copy already in this session with the
    locked row (another request may have changed it while we waited)."""
    s = (db.query(Shipment).filter(Shipment.id == shipment_id)
         .with_for_update().populate_existing().first())
    _pause()
    return s


def locked_shipment_or_404(db: Session, shipment_id: int) -> Shipment:
    s = locked_shipment(db, shipment_id)
    if s is None:
        raise HTTPException(status_code=404, detail="Shipment not found")
    return s


def lock_shipments(db: Session, ids: Iterable[int]) -> list[Shipment]:
    """Lock several shipments, always in id order (no deadlocks)."""
    ids = sorted(set(ids))
    if not ids:
        return []
    rows = (db.query(Shipment).filter(Shipment.id.in_(ids)).order_by(Shipment.id)
            .with_for_update().populate_existing().all())
    _pause()
    return rows


def locked_proforma(db: Session, proforma_id: int) -> Proforma:
    """Every proforma write: lock the shipment, then the proforma (lock order), so
    autofill (run by document uploads / shipment edits under the same shipment lock)
    and hand edits never interleave. Hand-edited lines win: autofill skips is_manual."""
    proforma = db.query(Proforma).filter(Proforma.id == proforma_id).first()
    if proforma is None:
        raise HTTPException(status_code=404, detail="Proforma not found")
    locked_shipment(db, proforma.shipment_id)
    return (db.query(Proforma).filter(Proforma.id == proforma_id)
            .with_for_update().populate_existing().one())
