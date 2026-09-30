"""Inland shipments: containers + arrival at the FPOD from ICEGATE's ICD BL status (faked here, no network)."""
from datetime import date

import httpx
import pytest

from app.igm import icd

BL = [{"igmRTN": "4372925", "igmDT": "03 SEP 2026", "lineNo": "211", "subLineNo": "0", "mawbNo": "274014260",
       "portDest": "INDWN6", "portREP": "INMUN1", "fileName": "INDWN6", "inwDT": "03 SEP 2026", "smtpNo": "2724782",
       "smtpDT": "03 SEP 2026", "totalPackage": "253", "packageCode": "PKG", "grossWeight": "269699", "uqc": "KGS"}]
CONT = [
    {"contNo": "MRKU5032093", "contStatus": "FCL", "arrDT": "21 SEP 2026", "arrStatus": "I", "errCode": "40|41"},
    {"contNo": "MRSU4711430", "contStatus": "FCL", "arrDT": "21 SEP 2026", "arrStatus": "I", "errCode": "00"},
    {"contNo": "MRKU5032093", "contStatus": "FCL", "arrDT": "21 SEP 2026", "arrStatus": "I", "errCode": "00"},
    {"contNo": "TCNU4951934", "contStatus": "FCL", "arrDT": "N.A.", "arrStatus": "N.A.", "errCode": "00"},
]


def fake_icegate(bl=BL, cont=CONT):
    def handler(req: httpx.Request):
        if req.url.path.endswith("publicblstatus-action"):
            return httpx.Response(200, json=bl)
        return httpx.Response(200, json=cont)
    return httpx.Client(transport=httpx.MockTransport(handler), headers=icd.HEADERS)


def test_parse_and_merge_duplicates():
    d = icd.fetch("274014260", client=fake_icegate())
    assert d["found"] and d["bls"][0]["smtp_no"] == "2724782" and d["bls"][0]["inward_date"] == date(2026, 9, 3)
    got = {c["container_no"]: c["arrival_date"] for c in d["containers"]}
    assert got == {"MRKU5032093": date(2026, 9, 21), "MRSU4711430": date(2026, 9, 21), "TCNU4951934": None}


def test_not_found():
    assert icd.fetch("X", client=fake_icegate(bl=[])) == {"found": False}


@pytest.fixture
def inland(client, admin_headers):
    r = client.post("/shipments", json={"mbl": "ICDTEST0001", "port": "INDWN6", "job": "T-ICD"}, headers=admin_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_refresh_keeps_hand_typed_dates(client, admin_headers, inland, monkeypatch):
    real_fetch = icd.fetch
    monkeypatch.setattr(icd, "fetch", lambda mbl: real_fetch(mbl, client=fake_icegate()))
    base = f"/shipments/{inland}/containers"

    r = client.post(f"{base}/refresh-icd", headers=admin_headers)
    assert r.status_code == 200 and r.json()["added"] == 3
    rows = {c["container_no"]: c for c in r.json()["containers"]}
    assert rows["MRKU5032093"]["day"] is not None and rows["MRKU5032093"]["last_free_day"] == "2026-10-04"

    # someone types a different arrival for one container
    cid = rows["MRSU4711430"]["id"]
    r = client.patch(f"{base}/{cid}", json={"arrival_date": "2026-09-23"}, headers=admin_headers)
    assert r.json()["is_manual"] and r.json()["last_free_day"] == "2026-10-06"

    # fetching again leaves the typed date alone and adds nothing twice
    r = client.post(f"{base}/refresh-icd", headers=admin_headers).json()
    assert r["added"] == 0 and r["kept_manual"] == 1
    assert {c["container_no"]: c["arrival_date"] for c in r["containers"]}["MRSU4711430"] == "2026-09-23"


def test_add_and_remove_by_hand(client, admin_headers, inland):
    base = f"/shipments/{inland}/containers"
    r = client.post(base, json={"container_no": "abcu 1234567", "arrival_date": "2026-09-25"}, headers=admin_headers)
    assert r.status_code == 201 and r.json()["container_no"] == "ABCU1234567"
    assert client.post(base, json={"container_no": "ABCU1234567"}, headers=admin_headers).status_code == 409
    assert client.delete(f"{base}/{r.json()['id']}", headers=admin_headers).status_code == 204
    assert client.get(base, headers=admin_headers).json() == []
