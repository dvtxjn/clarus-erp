import pytest


def _new(tc, h, **kw):
    return tc.post("/shipments", json={"mbl": "CHK0001", **kw}, headers=h)


def _edit(tc, h, sid, **kw):
    return tc.patch(f"/shipments/{sid}", json=kw, headers=h)


def test_billing_needs_clearance(client, admin_headers):
    h = admin_headers
    sid = _new(client, h, mbl="CHKBILL1").json()["id"]
    r = client.post(f"/shipments/{sid}/bill", headers=h)
    assert r.status_code == 422 and "Cleared date" in r.json()["detail"]
    assert _edit(client, h, sid, status="billed").status_code == 422  # only via the Bill button


@pytest.mark.duplicates
def test_duplicate_bl_and_job(client, admin_headers):
    h = admin_headers
    a = _new(client, h, mbl="HDMUBHMA09990001", job="901").json()["id"]
    assert _new(client, h, mbl=" bhma09990001 ").status_code == 422  # same BL, other spelling
    assert _new(client, h, mbl="HDMUBHMA09990001", hbl="HBL-2").status_code == 201  # another HBL is fine
    b = _new(client, h, mbl="CHKDUP2").json()["id"]
    r = _edit(client, h, b, job=" 901 ")
    assert r.status_code == 422 and "901" in r.json()["detail"]
    assert _edit(client, h, a, job="901").status_code == 200  # its own number


@pytest.mark.parametrize("field,value", [
    ("eta", "2099-01-01"), ("eta", "1990-01-01"), ("cleared_date", "2099-01-01"), ("inw", "31-Dec-2099"),
    ("inw", "soon"), ("mbl", "  "), ("port", "XXXXX"), ("be_no", "12A4567"), ("be_no", "123456789012345"),
    ("igm", "IGM12"), ("gross_wt", "-5"), ("gross_wt", "heavy"), ("container", "-1"), ("total_pkg", "ten"),
    ("status", "cleared"), ("be_dt", "2026-09-01"),
])
def test_nonsense_is_refused(client, admin_headers, field, value):
    h = admin_headers
    sid = _new(client, h, mbl=f"CHKBAD{field}{abs(hash(value)) % 10000}", client="ACME").json()["id"]
    r = _edit(client, h, sid, **{field: value})
    assert r.status_code == 422, (field, value, r.text)


def test_good_values_are_tidied(client, admin_headers):
    h = admin_headers
    sid = _new(client, h, mbl="CHKGOOD1", eta="2026-09-01").json()["id"]
    s = _edit(client, h, sid, job=" 951 ", be_no="1234567", be_dt="2026-09-03", igm="2345678", port="inmun1",
              gross_wt="24.500 MTS", container="2", total_pkg="120", inw="05-oct-2026").json()
    assert (s["job"], s["port"], s["inw"]) == ("951", "INMUN1", "05-Oct-2026")
    assert _edit(client, h, sid, cleared_date="2026-08-01").status_code == 422  # before the ETA
    assert _edit(client, h, sid, client="").status_code == 200  # never set, so it may stay empty
