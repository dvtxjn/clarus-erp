import io

from openpyxl import Workbook

from tests.conftest import be_pdf, cfs_pdf


def test_scan_requires_auth(client):
    assert client.post("/extraction/scan", files=[("files", ("a.pdf", be_pdf(), "application/pdf"))]).status_code == 401


def test_mixed_batch(client, admin_headers):
    r = client.post("/organizations", json={"ad_code": "6390001", "name": "ACME TYRES PVT LTD"}, headers=admin_headers)
    assert r.status_code == 201

    files = [
        ("files", ("cfs1.pdf", cfs_pdf(), "application/pdf")),
        ("files", ("be1.pdf", be_pdf(), "application/pdf")),
        ("files", ("be2.pdf", be_pdf(be_no="3456789", mawb="MSCU5555555555"), "application/pdf")),
        ("files", ("be1-again.pdf", be_pdf(), "application/pdf")),
        ("files", ("cfs2.pdf", cfs_pdf(be_no="0000000", bl_no="MSCU5555555555"), "application/pdf")),
        ("files", ("orphan.pdf", cfs_pdf(be_no="7777777", bl_no="NOPE00000000"), "application/pdf")),
        ("files", ("junk.pdf", io.BytesIO(b"nope"), "application/pdf")),
    ]
    r = client.post("/extraction/scan", files=files, headers=admin_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {row["filename"]: row for row in body["rows"]}

    assert rows["be1.pdf"]["cfs"]["matched_by"] == "BE Number"
    assert rows["be2.pdf"]["cfs"]["matched_by"] == "BL Number"
    assert rows["be1-again.pdf"]["duplicate_in_batch"] is True
    assert rows["be1.pdf"]["duplicate_in_batch"] is False
    # registered name differs from BE name -> mismatch, bill under registered name
    assert rows["be1.pdf"]["name_mismatch"] == "YES"
    assert rows["be1.pdf"]["billing_name"] == "ACME TYRES PVT LTD"
    assert "error" in rows["junk.pdf"] and rows["junk.pdf"]["error"]
    assert [c["filename"] for c in body["unmatched_cfs"]] == ["orphan.pdf"]


def test_previously_processed_be_flagged(client, admin_headers):
    r = client.post("/shipments", json={"job": "J-1", "mbl": "M-1", "be_no": "4567890"}, headers=admin_headers)
    assert r.status_code in (200, 201), r.text
    sid = r.json()["id"]
    r = client.post("/extraction/scan", files=[("files", ("x.pdf", be_pdf(be_no="4567890"), "application/pdf"))],
                    headers=admin_headers)
    assert r.json()["rows"][0]["existing_shipment_id"] == sid


def test_challan_endpoint(client, admin_headers):
    wb = Workbook()
    wb.active.append(["Doc type", "Doc no.", "Due Amount"])
    wb.active.append(["BE", "2345678", 62000])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/extraction/challan", files={"file": ("c.xlsx", buf.getvalue())}, headers=admin_headers)
    assert r.status_code == 200 and r.json()["due_amounts"] == {"2345678": 62000.0}


def test_org_import_and_non_admin_blocked(client, admin_headers):
    wb = Workbook()
    ws = wb.active
    ws.title = "Organization List"
    ws.append(["Organization", "AD Code"])
    ws.append(["ACME TYRES PRIVATE LIMITED", "6390001"])
    ws.append(["BETA RUBBER LTD", "6390005"])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/organizations/import", files={"file": ("o.xlsx", buf.getvalue())}, headers=admin_headers)
    assert r.json() == {"created": 1, "updated": 1}

    client.post("/auth/users", json={"email": "im@example.com", "password": "x" * 12, "full_name": "IM"},
                headers=admin_headers)
    tok = client.post("/auth/login", data={"username": "im@example.com", "password": "x" * 12}).json()["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/organizations", headers=h).status_code == 403
    assert client.post("/extraction/scan", files=[("files", ("a.pdf", be_pdf(), "application/pdf"))],
                       headers=h).status_code == 403
