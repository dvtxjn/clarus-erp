"""Challan freshness goes by when ICEGATE made the list (stamped in the .xlsx), not when it was uploaded
(client, 2026-10-01: yesterday's list uploaded today must not count as today's)."""
from datetime import datetime, timedelta, timezone

from app.extraction.excel_imports import challan_list_time
from app.invoice.build import latest_challan
from app.core.database import SessionLocal
from tests.test_challan_be_date import _xlsx

BE = "9778001"


def _utc_naive(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)


def test_list_time_is_read_from_the_file():
    made = datetime(2026, 9, 28, 8, 41, 18)
    assert challan_list_time(_xlsx(BE, "26.09.2026", 1, made=made)) == made.replace(tzinfo=timezone.utc)


def test_yesterdays_list_is_not_today(client, admin_headers):
    h = admin_headers
    old = _utc_naive(datetime.now(timezone.utc) - timedelta(days=2))
    r = client.post("/duty-challans/upload", files={"file": ("old.xlsx", _xlsx(BE, "26.09.2026", 100, made=old))},
                    headers=h)
    assert r.status_code == 200, r.text
    assert "not today's" in r.json()["note"]

    # the same file again is caught
    r = client.post("/duty-challans/upload", files={"file": ("old.xlsx", _xlsx(BE, "26.09.2026", 100, made=old))},
                    headers=h)
    assert r.status_code == 409

    new = _utc_naive(datetime.now(timezone.utc)) - timedelta(seconds=187)  # clear of other tests' lists
    r = client.post("/duty-challans/upload", files={"file": ("new.xlsx", _xlsx(BE, "26.09.2026", 200, made=new))},
                    headers=h)
    assert r.status_code == 200
    assert client.get("/daily-updates", headers=h).json()["challans_updated_today"] is True

    # an older list uploaded afterwards doesn't replace the newer amount
    older = new - timedelta(days=1)
    r = client.post("/duty-challans/upload", files={"file": ("older.xlsx", _xlsx(BE, "26.09.2026", 50, made=older))},
                    headers=h)
    assert "newer list" in r.json()["note"]
    db = SessionLocal()
    try:
        assert float(latest_challan(db, BE).due_amount) == 200
    finally:
        db.close()
    assert client.get("/daily-updates", headers=h).json()["challans_updated_today"] is True

