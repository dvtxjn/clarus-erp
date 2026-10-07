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


def test_hmm_mbl_with_or_without_hdmu_is_one_shipment(client, admin_headers):
    """The sheet may write an HMM MBL with the carrier prefix one day and without it before (client, 2026-09-30)."""
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "BHMA99154200", "port": "INMUN1"}, headers=h).json()["id"]
    data = _csv("990,HDMUBHMA99154200,,,c,Divine,INMUN1,,,,1,,,,,,,,,,,")
    p = _post(client, h, "preview", data).json()
    assert not p["new"] and any(u["shipment_id"] == sid and u["matched_by"] == "MBL" for u in p["updated"])
    _post(client, h, "apply", data)
    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert s["job"] == "990" and s["mbl"] == "HDMUBHMA99154200"


def test_hbl_typed_first_is_swapped(client, admin_headers):
    """'CJHRUSF0418/275957617': CJHR… is a Chartering RORO HBL (client's rule), so the Maersk number is the MBL."""
    h = admin_headers
    data = _csv("991,CJHRUSF9918/279957617,,,c,Divine,INMUN1,,,,1,,,,,,,,,,,")
    _post(client, h, "apply", data)
    s = next(x for x in client.get("/shipments", headers=h).json() if x["job"] == "991")
    assert (s["mbl"], s["hbl"]) == ("279957617", "CJHRUSF9918")


def test_cleared_shipments_moved_to_fnf_sheets_are_not_flagged(client, admin_headers):
    """Cleared / billed shipments leave the tracker for the monthly FNF sheets (client, 2026-10-07)."""
    h = admin_headers
    done = client.post("/shipments", json={"mbl": "FNFDONE001", "cleared_date": "2026-09-29"}, headers=h).json()["id"]
    live = client.post("/shipments", json={"mbl": "FNFLIVE001"}, headers=h).json()["id"]
    p = _post(client, h, "apply", _csv("992,OTHER00001,,,c,Divine,INMUN1,,,,1,,,,,,,,,,,")).json()
    ids = {m["shipment_id"] for m in p["missing"]}
    assert live in ids and done not in ids and p["cleared"] >= 1
    assert client.get(f"/shipments/{done}", headers=h).json()["missing_from_sheet_at"] is None


def test_blank_igm_detail_columns_keep_app_data(client, admin_headers):
    """The sheet no longer fills MBL date / GW / voyage …: a blank cell must not wipe the IGM lookup's data."""
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "IGMKEEP001", "voyage": "638W", "gw": "141715"}, headers=h).json()["id"]
    data = ("Job,MBL,Consignee,Voyage,GW\n993,IGMKEEP001,Divine,,\n").encode()
    p = _post(client, h, "preview", data).json()
    assert not any(c["field"] in ("voyage", "gw") for u in p["updated"] for c in u["changes"])
    _post(client, h, "apply", data)
    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert (s["voyage"], s["gw"]) == ("638W", "141715")
