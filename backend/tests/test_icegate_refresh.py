"""One read of ICEGATE per shipment: sea IGM → IGM details; inland also ICD BL status → FPOD ICD BL details
(repeats left out, differences listed) + container arrivals. ICEGATE faked here."""
from datetime import date

import pytest

from app.igm import icd, refresh, sea

SEA = {"status": "IGM Filed", "line_no": "211", "sub_line_no": "0", "mbl_no": "274014260", "mbl_date": "21-Jul-2026",
       "hbl_no": None, "hbl_date": None, "gross_weight": "269699", "unit_weight": "KGS", "total_package": "253",
       "package_code": "PKG", "cargo_movement": "TI", "port_dest": "INDWN6", "goods": "TYRE SCRAP",
       "igm_no": "1208791", "igm_date": "24-Aug-2026", "inw_date": "03-Sep-2026", "voyage_no": "633E",
       "vessel_code": "OWWS2", "imo_no": "9245756", "containers": [{"container": "CAAU9103800", "status": "FCL"}]}
ICD = {"found": True, "bls": [{
    "igm_no": "4372925", "igm_date": date(2026, 9, 3), "line_no": "211", "icd": "INDWN6", "gateway_port": "INMUN1",
    "inward_date": date(2026, 9, 3), "smtp_no": "2724782", "smtp_date": date(2026, 9, 3), "total_package": "253",
    "package_code": "PKG", "gross_weight": "269699", "unit": "KGS", "sub_line_no": "0", "mbl_date": date(2026, 7, 21),
    "cargo_movement": "TI", "goods": "TYRE SCRAP", "importer": "EARTHMAN", "be_location": "4"}],
    "containers": [{"container_no": "CAAU9103800", "status": "FCL", "arrival_date": date(2026, 9, 21), "arrival_status": "I"}]}


@pytest.fixture
def fake(monkeypatch):
    calls = {}
    def sea_fetch(mbl, port):
        calls["sea_port"] = port
        return dict(SEA)
    monkeypatch.setattr(sea, "fetch", sea_fetch)
    monkeypatch.setattr(icd, "fetch", lambda mbl: ICD)
    return calls


def make(client, h, **kw):
    r = client.post("/shipments", json={"mbl": "274014260", **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_inland_reads_both_and_keeps_the_icd_igm(client, admin_headers, fake):
    sid = make(client, admin_headers, port="INDWN6", igm="4372925", container="1", gross_wt="269.699 MTS")
    r = client.post(f"/shipments/{sid}/icegate/refresh", headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    s = body["shipment"]
    assert fake["sea_port"] == "INMUN1"                         # sea IGM read at the gateway the ICD names
    assert s["igm"] == "4372925"                                 # tracker's ICD IGM untouched
    assert s["icegate"]["gateway_igm"]["no"] == "1208791"
    assert s["line_no"] == "211" and s["voyage"] == "633E" and s["igm_date"] == "2026-08-24"
    icd_extra = s["icegate"]["icd"]
    assert icd_extra["smtp_no"] == "2724782" and icd_extra["icd_igm_no"] == "4372925"
    assert "line_no" not in icd_extra and "total_package" not in icd_extra  # repeats left out
    assert s["icegate"]["differences"] == []
    cont = client.get(f"/shipments/{sid}/containers", headers=admin_headers).json()
    assert cont[0]["arrival_date"] == "2026-09-21"


def test_differences_are_listed(client, admin_headers, fake, monkeypatch):
    monkeypatch.setattr(icd, "fetch", lambda mbl: {**ICD, "bls": [{**ICD["bls"][0], "total_package": "250"}]})
    sid = make(client, admin_headers, port="INDWN6")
    s = client.post(f"/shipments/{sid}/icegate/refresh", headers=admin_headers).json()["shipment"]
    assert s["icegate"]["differences"] == [{"field": "Packages", "igm": "253", "icd": "250"}]


def test_sea_port_reads_only_the_sea_igm(client, admin_headers, fake, monkeypatch):
    monkeypatch.setattr(icd, "fetch", lambda mbl: pytest.fail("no ICD read for a sea port"))
    sid = make(client, admin_headers, port="INMUN1")
    s = client.post(f"/shipments/{sid}/icegate/refresh", headers=admin_headers).json()["shipment"]
    assert fake["sea_port"] == "INMUN1" and s["igm"] == "1208791" and "icd" not in s["icegate"]
