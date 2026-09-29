"""Google Sheets tracker CSV re-import: preview, sheet wins, BE data kept, missing flagged,
MBL/HBL split, blank billed? ignored."""
from tests.conftest import be_pdf

HEAD = "Job,MBL,ETA,License,Client,Consignee,POD,Cntr Status,BE No,BE Dt,Cntr,Gross Wt,Remarks,Cleared Date," \
       "Duty paid?,CFS Inv?,Line Paid?,OOC?,DO?,IGM,Billed?,Line\n"


def _csv(*rows):
    return (HEAD + "".join(r + "\n" for r in rows)).encode()


def _post(client, h, path, data):
    return client.post(f"/tracker-import/{path}", files={"file": ("tracker.csv", data, "text/csv")}, headers=h)


def test_tracker_csv_reimport(client, admin_headers):
    h = admin_headers
    # in the app: one plain shipment, one with an uploaded BE (its BE No / MBL must win), one not in the sheet
    a = client.post("/shipments", json={"mbl": "SHEETA0001", "job": "501", "client": "old client"}, headers=h).json()["id"]
    b = client.post("/shipments", json={"mbl": "SHEETB0001", "job": "502"}, headers=h).json()["id"]
    client.post(f"/shipments/{b}/documents", data={"document_type": "assessed_bill_of_entry"},
                files={"file": ("be.pdf", be_pdf(be_no="8880001", mawb="SHEETB0001"), "application/pdf")}, headers=h)
    gone = client.post("/shipments", json={"mbl": "NOTINSHEET001", "job": "503"}, headers=h).json()["id"]

    data = _csv(
        "501,SHEETA0001/HBLA99,01-Oct-2026,111,new client,Divine,INNSA1 - Nhava Sheva,,,,2,,note,,Yes,,,,,,,MSC",
        "502,SHEETB0001,,,x,Divine,INMUN1,,9990001,,5,,,,,,,,,,Yes,",
        "504,NEWMBL0001/NEWHBL1,,,c,HKR - Mahrishi,INDWN6,,,,1,,,,,,,,,,,",
    )
    p = _post(client, h, "preview", data).json()
    assert [n["mbl"] for n in p["new"]] == ["NEWMBL0001"]
    upd = {u["shipment_id"]: u for u in p["updated"]}
    assert {c["field"] for c in upd[a]["changes"]} >= {"client", "hbl", "duty_paid", "shipping_line", "port"}
    assert any(k["field"] == "be_no" and k["why"] == "kept from BE" for k in upd[b]["kept"])
    assert gone in {m["shipment_id"] for m in p["missing"]}
    assert client.get(f"/shipments/{a}", headers=h).json()["client"] == "old client"   # preview saves nothing

    r = _post(client, h, "apply", data).json()
    sa = client.get(f"/shipments/{a}", headers=h).json()
    assert (sa["client"], sa["hbl"], sa["duty_paid"], sa["port"], sa["status"]) == ("new client", "HBLA99", True, "INNSA1", "duty_paid")
    sb = client.get(f"/shipments/{b}", headers=h).json()
    assert sb["be_no"] == "8880001" and sb["is_billed"] is True                       # BE wins; explicit Yes bills
    assert client.get(f"/shipments/{gone}", headers=h).json()["missing_from_sheet_at"] is not None  # flagged, not deleted
    new = next(s for s in client.get("/shipments", headers=h).json() if s["mbl"] == "NEWMBL0001")
    assert new["hbl"] == "NEWHBL1" and new["is_hss"] and new["hss_buyer"] == "Mahrishi"

    # blank "billed?" leaves billing alone; the shipment coming back clears its flag
    data2 = _csv("502,SHEETB0001,,,x,Divine,INMUN1,,9990001,,5,,,,,,,,,,,", "503,NOTINSHEET001,,,,,,,,,,,,,,,,,,,,")
    _post(client, h, "apply", data2)
    assert client.get(f"/shipments/{b}", headers=h).json()["is_billed"] is True
    assert client.get(f"/shipments/{gone}", headers=h).json()["missing_from_sheet_at"] is None
