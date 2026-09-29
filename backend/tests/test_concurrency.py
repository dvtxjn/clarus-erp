"""Launch Phase 6 (Fast Track: tests 1, 2, 5, 6): real parallel requests against Postgres.

The locks are what make these pass: `app.core.locking._race_pause` holds every locked
section open a little longer, so without FOR UPDATE the two requests would both read
the old row and one change would be lost. (Tests 3-4, invoice numbering, wait for
Phase 3.) Skipped on SQLite, which only allows one writer at a time anyway."""
import os
import threading

import pytest
from fastapi.testclient import TestClient

from app.core import locking
from app.main import app
from tests.conftest import be_pdf

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),
                                reason="concurrency tests need Postgres (TEST_DATABASE_URL)")


@pytest.fixture
def race(monkeypatch):
    monkeypatch.setattr(locking, "_race_pause", 0.3)


def parallel(*calls):
    """Start every call at the same moment, each with its own client; return results in order."""
    results = [None] * len(calls)
    gate = threading.Barrier(len(calls))

    def run(i, fn):
        c = TestClient(app)
        gate.wait()
        results[i] = fn(c)

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(calls)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    return results


def _ship(client, h, mbl, **kw):
    r = client.post("/shipments", json={"mbl": mbl, **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_1_same_field_one_wins_one_409(client, admin_headers, race):
    h = admin_headers
    s = _ship(client, h, "RACE0000001", remarks="start")
    patch = lambda text: lambda c: c.patch(f"/shipments/{s['id']}",  # noqa: E731
                                           json={"remarks": text, "base": {"remarks": "start"}}, headers=h)
    a, b = parallel(patch("A"), patch("B"))
    assert sorted([a.status_code, b.status_code]) == [200, 409]
    winner = "A" if a.status_code == 200 else "B"
    now = client.get(f"/shipments/{s['id']}", headers=h).json()
    assert now["remarks"] == winner and now["version"] == 2  # no lost update, one write


def test_2_different_fields_both_saved(client, admin_headers, race):
    h = admin_headers
    s = _ship(client, h, "RACE0000002")
    a, b = parallel(
        lambda c: c.patch(f"/shipments/{s['id']}", json={"remarks": "A", "base": {"remarks": None}}, headers=h),
        lambda c: c.patch(f"/shipments/{s['id']}", json={"poc": "B", "base": {"poc": None}}, headers=h),
    )
    assert a.status_code == 200 and b.status_code == 200
    now = client.get(f"/shipments/{s['id']}", headers=h).json()
    assert now["remarks"] == "A" and now["poc"] == "B" and now["version"] == 3


def test_5_autofill_racing_a_manual_line_edit_manual_wins(client, admin_headers, race):
    h = admin_headers
    cd_id = next(c["id"] for c in client.get("/charge-master", headers=h).json() if c["code"] == "CD")
    for round_ in range(3):  # several rounds: without the locks at least one loses the edit
        s = _ship(client, h, f"RACE00005{round_:02d}")
        client.patch(f"/shipments/{s['id']}", json={"duty_amount": "1000", "igst_amount": "0"}, headers=h)
        p = client.post(f"/shipments/{s['id']}/proformas", headers=h).json()
        cd = next(li for li in p["line_items"] if li["charge_master_id"] == cd_id)
        auto, manual = parallel(  # autofill recomputes Customs Duty from the new duty ...
            lambda c: c.patch(f"/shipments/{s['id']}", json={"duty_amount": "2000"}, headers=h),
            # ... while someone types their own figure into that line
            lambda c: c.patch(f"/proformas/{p['id']}/line-items/{cd['id']}", json={"rate": 5555}, headers=h),
        )
        assert auto.status_code == 200 and manual.status_code == 200
        line = next(li for li in client.get(f"/shipments/{s['id']}/proformas", headers=h).json()[0]["line_items"]
                    if li["id"] == cd["id"])
        assert line["is_manual"] and float(line["rate"]) == 5555.0, f"round {round_}: manual edit lost: {line}"


def test_6_document_upload_racing_a_manual_edit_both_survive(client, admin_headers, race):
    h = admin_headers
    s = _ship(client, h, "RACE0000006")
    up, edit = parallel(
        lambda c: c.post(f"/shipments/{s['id']}/documents", data={"document_type": "assessed_bill_of_entry"},
                         files={"file": ("be.pdf", be_pdf(be_no="7770006", mawb="RACE0000006"), "application/pdf")},
                         headers=h),
        lambda c: c.patch(f"/shipments/{s['id']}", json={"remarks": "typed by hand", "base": {"remarks": None}},
                          headers=h),
    )
    assert up.status_code == 201, up.text
    assert edit.status_code == 200, edit.text
    now = client.get(f"/shipments/{s['id']}", headers=h).json()
    assert now["remarks"] == "typed by hand" and now["be_no"] == "7770006"
