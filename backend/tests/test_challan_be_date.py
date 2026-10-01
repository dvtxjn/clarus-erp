"""BE numbers are reused every year (client, 2026-09-30): a duty challan must follow the BE date too."""
import io
from datetime import date, datetime, timedelta, timezone
from itertools import count

from openpyxl import Workbook

from app.core.database import SessionLocal
from app.icegate_portal import sync
from app.invoice.build import challan_be_date, latest_challan
from app.models.challan import DutyChallan

BE = "9777001"


_tick = count()


def _xlsx(be_no, be_date, due, made=None):
    wb = Workbook()
    # ICEGATE stamps when the list was made; each test list gets its own time
    wb.properties.created = made or (datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
                                     - timedelta(hours=1) + timedelta(seconds=next(_tick)))
    ws = wb.active
    ws.append(["IEC", "Location Code", "Doc type", "Doc no.", "Doc date", "Challan no.", "Due Amount"])
    ws.append(["AAVFD7221R", "INNSA1", "BE", be_no, be_date, "2063300001", due])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _ship(client, h, mbl, be_dt):
    sid = client.post("/shipments", json={"mbl": mbl, "consignee": "HKR - Mahrishi", "port": "INNSA1", "be_no": BE,
                                          "be_dt": be_dt}, headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={"gross_wt": "20.000 MTS", "assessable_value": "500000",
                                            "duty_amount": "100000", "igst_amount": "60000"}, headers=h)
    return sid


def _invoice_duty(client, h, sid):
    pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "buyer"}, headers=h).json()["id"]
    client.post(f"/proformas/{pid}/fill-from-shipment", headers=h)
    return client.get(f"/proformas/{pid}/invoice", headers=h).json()["customs_duty"]


def test_challan_date_formats():
    assert challan_be_date("26.09.2026") == date(2026, 9, 26)
    assert challan_be_date("26/09/2026") == challan_be_date("2026-09-26") == challan_be_date("26-Sep-2026") == date(2026, 9, 26)
    assert challan_be_date(None) is None and challan_be_date("soon") is None


def test_same_be_number_in_two_years_gets_its_own_challan(client, admin_headers):
    h = admin_headers
    old = _ship(client, h, "CHYEAR-OLD", "2025-09-26")
    new = _ship(client, h, "CHYEAR-NEW", "2026-09-26")

    r = client.post("/duty-challans/upload", files={"file": ("old.xlsx", _xlsx(BE, datetime(2025, 9, 26), 100500))},
                    headers=h).json()
    assert [m["shipment_id"] for m in r["matched"]] == [old] and float(r["matched"][0]["interest"]) == 500.0
    # this year's list is uploaded later: it must not become last year's BE's figure
    r = client.post("/duty-challans/upload", files={"file": ("new.xlsx", _xlsx(BE, "26.09.2026", 100200))},
                    headers=h).json()
    assert [m["shipment_id"] for m in r["matched"]] == [new] and float(r["matched"][0]["interest"]) == 200.0

    assert float(_invoice_duty(client, h, old)["interest"]) == 500.0
    assert float(_invoice_duty(client, h, new)["interest"]) == 200.0

    db = SessionLocal()
    try:
        assert float(latest_challan(db, BE, date(2025, 9, 26)).due_amount) == 100500
        assert float(latest_challan(db, BE, date(2026, 9, 26)).due_amount) == 100200
        assert latest_challan(db, BE, date(2024, 9, 26)) is None  # only other years' challans on file
        assert float(latest_challan(db, BE).due_amount) == 100200  # no date: the latest row, as before
    finally:
        db.close()

    # a hand-entered figure is dated with the BE's latest shipment, so it corrects this year's only
    r = client.post("/duty-challans", json={"be_no": BE, "due_amount": "100300"}, headers=h).json()
    assert [m["shipment_id"] for m in r["matched"]] == [new]
    assert float(_invoice_duty(client, h, new)["interest"]) == 300.0
    assert float(_invoice_duty(client, h, old)["interest"]) == 500.0


def test_undated_challan_is_the_fallback():
    be = "9777002"
    db = SessionLocal()
    try:
        db.add(DutyChallan(be_no=be, due_amount=10, source="manual", uploaded_at=datetime(2026, 9, 1)))
        db.flush()
        assert float(latest_challan(db, be, date(2026, 9, 26)).due_amount) == 10
        db.add(DutyChallan(be_no=be, be_date="26.09.2026", due_amount=20, uploaded_at=datetime(2026, 8, 1)))
        db.flush()
        assert float(latest_challan(db, be, date(2026, 9, 26)).due_amount) == 20  # the dated row wins
        db.rollback()
    finally:
        db.close()


def test_icegate_challans_follow_the_be_date(client, admin_headers):
    h = admin_headers
    be = "9777003"
    ids = {}
    for mbl, be_dt in (("CHYEAR-ICE-OLD", "2025-09-20"), ("CHYEAR-ICE-NEW", "2026-09-20")):
        ids[be_dt[:4]] = client.post("/shipments", json={"mbl": mbl, "port": "INMUN1", "be_no": be, "be_dt": be_dt},
                                     headers=h).json()["id"]
    rows = [{"iecCode": "AAVFD7221R", "locationCode": "INMUN1", "boeNumber": int(be), "boeDate": d,
             "challanNumber": n, "dutyAmount": amt, "documentType": "BE"}
            for d, n, amt in (("20.09.2025", 111, 5000.0), ("20.09.2026", 222, 7000.0))]
    db = SessionLocal()
    try:
        assert sync.apply_challans(db, rows, datetime.now())["added"] == 2
        assert sync.apply_challans(db, rows, datetime.now())["added"] == 0  # each year compared with its own row
        assert latest_challan(db, be, date(2025, 9, 20)).challan_no == "111"
        assert latest_challan(db, be, date(2026, 9, 20)).challan_no == "222"
        db.commit()
    finally:
        db.close()
