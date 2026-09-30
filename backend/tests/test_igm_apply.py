"""IGM lookup -> shipment fields, with the sheet script's cross-checks (no network here)."""
from datetime import date
from types import SimpleNamespace

from app.igm.apply import plan

FILED = {"status": "IGM Filed", "line_no": "153", "mbl_no": "HLCUGOA260793271", "mbl_date": "29-Apr-2026",
         "hbl_no": None, "hbl_date": None, "gross_weight": "28150", "unit_weight": "KGS", "total_package": "33",
         "package_code": "BLS", "igm_no": "1204232", "igm_date": "23-Jul-2026", "inw_date": "01-Aug-2026",
         "voyage_no": "6129", "containers": [{"container": "CXDU2273540", "status": "FCL"}]}


def ship(**kw):
    return SimpleNamespace(**{"igm": None, "hbl": None, "container": "1", "gross_wt": "28.150 MTS", **kw})


def test_fields_and_dates():
    values, notes = plan(ship(), FILED)
    assert values["igm"] == "1204232" and values["igm_date"] == date(2026, 7, 23)
    assert values["inw"] == "01-Aug-2026" and values["mbl_date"] == date(2026, 4, 29)
    assert values["cont"] == "1" and values["gw"] == "28150" and "hbl_date" not in values
    assert notes == []


def test_mismatches_are_notes_not_overwrites():
    values, notes = plan(ship(container="2", gross_wt="30 MTS", hbl="ABC"), {**FILED, "hbl_no": "XYZ"})
    assert "container" not in values and "gross_wt" not in values and "hbl" not in values
    assert any("Containers differ" in n for n in notes)
    assert any("Weight differs" in n for n in notes)
    assert any("HBL differs" in n for n in notes)


def test_not_filed():
    assert plan(ship(), {"status": "IGM Not Filed"}) == ({}, ["IGM not filed yet on ICEGATE"])
