"""Upload the Google Sheets tracker CSV: preview what changes, then apply (see app/tracker_import.py)."""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.audit import record_change
from app.core.database import get_db
from app.core.deps import require_admin
from app.models.user import User
from app.tracker_import import apply, parse_csv, plan

router = APIRouter(prefix="/tracker-import", tags=["tracker import"])

MAX_BYTES = 10 * 1024 * 1024


async def _rows(file: UploadFile):
    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File is larger than 10 MB")
    if not (file.filename or "").lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Upload the tracker as a .csv (File → Download → CSV in Google Sheets)")
    rows, unknown, skipped = parse_csv(data)
    if not rows:
        raise HTTPException(status_code=400, detail="No shipment rows found (need an MBL column).")
    return rows, unknown, skipped


@router.post("/preview")
async def preview(file: UploadFile = File(...), db: Session = Depends(get_db), _admin: User = Depends(require_admin)):
    """What the import would do — nothing is saved."""
    rows, unknown, skipped = await _rows(file)
    p = plan(db, rows)
    return {**p, "unknown_columns": unknown, "skipped": skipped + p.pop("deleted")}


@router.post("/apply")
async def apply_import(file: UploadFile = File(...), db: Session = Depends(get_db),
                       admin: User = Depends(require_admin)):
    """Apply the same file that was previewed: sheet wins, BE data kept, missing flagged."""
    rows, unknown, skipped = await _rows(file)
    result = apply(db, rows, admin.id)
    record_change(db, "shipments", 0, "tracker CSV import", None,
                  f"{file.filename}: {len(result['new'])} new, {len(result['updated'])} updated, "
                  f"{len(result['missing'])} flagged missing", admin.id)
    db.commit()
    return {**result, "unknown_columns": unknown, "skipped": skipped + result.pop("deleted")}
