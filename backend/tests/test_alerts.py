"""Dashboard alerts: "d" deadlines, free days at the POD, documents before BE filing."""
from datetime import date
from types import SimpleNamespace

from app import alerts
from app.core.enums import DocumentType as D

TODAY = date(2026, 9, 30)


def ship(**kw):
    base = dict(id=1, job="178", mbl="MBL1", be_no=None, client="C", consignee="X", port="INMUN1",
                eta=None, eta_is_deadline=False, inw=None)
    return SimpleNamespace(**{**base, **kw})


# --- "d" deadline: ETA − 4 days ---
def test_deadline_only_when_marked():
    assert alerts.deadline_alert(ship(eta=date(2026, 10, 5)), TODAY) is None


def test_deadline_window_and_wording():
    # ETA 5 Oct -> move by 1 Oct = tomorrow
    a = alerts.deadline_alert(ship(eta=date(2026, 10, 5), eta_is_deadline=True), TODAY)
    assert a["days_left"] == 1 and a["severity"] == "urgent" and "01 Oct" in a["text"]
    # ETA 8 Oct -> move by 4 Oct, 4 days away: not yet
    assert alerts.deadline_alert(ship(eta=date(2026, 10, 8), eta_is_deadline=True), TODAY) is None
    # ETA 1 Oct -> was due 27 Sep
    late = alerts.deadline_alert(ship(eta=date(2026, 10, 1), eta_is_deadline=True), TODAY)
    assert late["severity"] == "overdue" and "3 days ago" in late["text"]


# --- free days: 14 at the POD, INW = day 1 ---
def test_free_days_counting_is_inclusive():
    # INW 17 Sep -> today is day 14, the last free day
    a = alerts.free_days_alert(ship(inw="17-Sep-2026"), TODAY)
    assert a["days_left"] == 0 and a["text"].startswith("Day 14: last free day")
    # INW 21 Sep -> day 10, 4 days left: no alert yet
    assert alerts.free_days_alert(ship(inw="21-Sep-2026"), TODAY) is None
    # INW 20 Sep -> day 11, 3 days left
    assert alerts.free_days_alert(ship(inw="2026-09-20"), TODAY)["days_left"] == 3
    # INW 10 Sep -> day 21, a week over
    over = alerts.free_days_alert(ship(inw="10-Sep-2026"), TODAY)
    assert over["severity"] == "overdue" and "7 days over" in over["text"]


def test_free_days_only_at_sea_ports():
    # Panipat (ICD): the INW is the sea-port inward; free days start after the rail leg
    assert alerts.free_days_alert(ship(port="INDWN6", inw="10-Sep-2026"), TODAY) is None
    assert alerts.free_days_alert(ship(port="INNSA1", inw="10-Sep-2026"), TODAY) is not None


def test_free_days_ignores_pending_and_future():
    assert alerts.free_days_alert(ship(inw="Pending"), TODAY) is None
    assert alerts.free_days_alert(ship(inw="05-Oct-2026"), TODAY) is None


# --- documents missing before the BE is filed ---
REQ = [(D.BL_COPY, False), (D.COMMERCIAL_INVOICE, False), (D.INSURANCE, True), (D.CFS_TAX_INVOICE, False)]


def test_documents_missing_close_to_eta():
    a = alerts.documents_alert(ship(eta=date(2026, 10, 3)), REQ, {D.BL_COPY}, TODAY)
    # optional insurance and the non-basic CFS invoice don't count
    assert a["missing"] == ["commercial_invoice"] and "ETA in 3 days" in a["text"]


def test_documents_quiet_when_far_filed_or_complete():
    assert alerts.documents_alert(ship(eta=date(2026, 10, 20)), REQ, set(), TODAY) is None
    assert alerts.documents_alert(ship(eta=date(2026, 10, 3), be_no="123"), REQ, set(), TODAY) is None
    done = {D.BL_COPY, D.COMMERCIAL_INVOICE}
    assert alerts.documents_alert(ship(eta=date(2026, 10, 3)), REQ, done, TODAY) is None


def test_documents_after_arrival_are_urgent():
    a = alerts.documents_alert(ship(eta=date(2026, 9, 20), inw="21-Sep-2026"), REQ, set(), TODAY)
    assert a["severity"] == "urgent" and "arrived" in a["text"]


def test_sorting_overdue_first():
    rows = [
        {"severity": "soon", "days_left": 2, "job": "1"},
        {"severity": "overdue", "days_left": -3, "job": "2"},
        {"severity": "urgent", "days_left": 0, "job": "3"},
    ]
    assert [r["job"] for r in alerts.sort_alerts(rows)] == ["2", "3", "1"]


def test_fpod_free_days_per_container():
    s = ship(port="INDWN6")
    # Panipat: 21 days. Arrived 12 Sep -> free until 02 Oct (2 days left); 20 Sep -> 10 Oct (fine)
    boxes = [("A", date(2026, 9, 12), None), ("B", date(2026, 9, 20), None), ("C", None, None)]
    a = alerts.fpod_alert(s, boxes, TODAY)
    assert a["kind"] == "free_days" and a["days_left"] == 2 and a["text"].startswith("1 of 2 containers")
    # a typed shorter free time makes it overdue
    late = alerts.fpod_alert(s, [("A", date(2026, 9, 12), 10)], TODAY)
    assert late["severity"] == "overdue" and "past free days" in late["text"]
    assert alerts.fpod_alert(s, [("B", date(2026, 9, 20), None)], TODAY) is None
    assert alerts.fpod_alert(ship(port="INMUN1"), boxes, TODAY) is None   # sea ports: POD rule instead
