import io
import math
from decimal import Decimal

from openpyxl import load_workbook

from tests.conftest import be_pdf, cfs_pdf


def _setup(client, h, port_consignee="Earthman - Mahrishi"):
    """Mundra HSS shipment, 2 containers, examined, OOC + CFS paid by us."""
    sid = client.post("/shipments", json={"mbl": "MEDU1234567890", "consignee": port_consignee, "container": "2",
                                          "cfs_paid_by_us": True}, headers=h).json()["id"]
    ooc_table = [(300, 20, "OOC COPY"), (63, 486, "1.EVENT"), (63, 500, "Submission"), (124, 500, "31-AUG-26"),
                 (63, 509, "Examination"), (124, 509, "10-SEP-26"), (186, 509, "16:27"),
                 (63, 518, "OOC"), (124, 518, "10-09-2026")]
    client.post(f"/shipments/{sid}/documents", data={"document_type": "ooc_bill_of_entry"},
                files={"file": ("ooc.pdf", be_pdf(be_no="7770001", extra=ooc_table), "application/pdf")}, headers=h)
    client.post(f"/shipments/{sid}/documents", data={"document_type": "cfs_tax_invoice"},
                files={"file": ("cfs.pdf", cfs_pdf(before="40,000.00", gst="7,200.00", after="47,200.00"),
                                "application/pdf")}, headers=h)
    return sid


def test_fill_from_shipment_and_totals(client, admin_headers):
    h = admin_headers
    sid = _setup(client, h)
    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert s["port"] == "INNSA1" and s["under_examination"] is True  # synthetic BE is Nhava Sheva
    pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "buyer"}, headers=h).json()["id"]
    r = client.post(f"/proformas/{pid}/fill-from-shipment", headers=h).json()
    lines = {li["description"]: li for li in r["proforma"]["line_items"]}
    # Agency 7000 x 2 + 18% ; Exam 18000 x 2 + 18%
    assert float(lines["Agency Charges"]["total"]) == 16520.0
    assert float(lines["Examination Charges"]["total"]) == 42480.0
    # Customs duty: total = BE duty 61500, IGST 45000 shown as GST
    cd = lines["Customs Duty"]
    assert (float(cd["amount"]), float(cd["gst_amount"]), float(cd["total"])) == (16500.0, 45000.0, 61500.0)
    # Stamp duty INNSA1 = CEILING(0.1% x (250000 + 61500)) = 312
    assert float(lines["Stamp Duty"]["total"]) == 312.0
    assert float(lines["CFS Charges"]["total"]) == 47200.0
    assert any("Shipping line" in x for x in r["skipped"])
    # HSS: royalty 0.75/kg on the BE gross weight, + 18%, rounded up
    roy = lines["Royalty"]
    # not rounded per line any more — only the grand total is (so both HSS copies match)
    assert float(roy["rate"]) == 0.75 and abs(float(roy["total"]) - float(roy["amount"]) * 1.18) < 0.01
    # grand total excludes cost inclusion
    # HSS with BE figures in: a bill rate is suggested, which may add a GST Difference line
    assert r["proforma"]["bill_rate"] is not None
    gstd = float(lines["GST Difference"]["total"]) if "GST Difference" in lines else 0.0
    # Royalty and the GST Difference don't come to Clarus: out of the grand total, in the match total
    assert float(r["proforma"]["grand_total"]) == 16520 + 42480 + 61500 + 312 + 47200
    assert float(r["proforma"]["match_total"]) == math.ceil(16520 + 42480 + 61500 + 312 + 47200 + float(roy["total"]) + gstd)
    # filling again adds nothing
    again = client.post(f"/proformas/{pid}/fill-from-shipment", headers=h).json()
    assert again["added"] == []

    inv = client.get(f"/proformas/{pid}/invoice", headers=h).json()
    # Bill To = the importer printed on the BE
    # copies are marked by the party's first name, not "buyer / seller copy"
    assert inv["bill_to"]["party"] == "ACME TYRES PRIVATE LIMITED" and inv["copy_label"].startswith("For Acme")
    assert inv["disclaimer"] is None
    assert inv["reference"]["containers"] == 2 and inv["reference"]["exam_applicable"] == "YES"
    titles = [sec["title"] for sec in inv["sections"]]
    assert titles == ["Billed by Clarus", "Reimbursement (at actuals)", "Royalty", "GST Difference", "Cost Inclusion"]


def test_edit_line_and_downloads(client, admin_headers):
    h = admin_headers
    sid = _setup(client, h, port_consignee="Divine")
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    p = client.post(f"/proformas/{pid}/fill-from-shipment", headers=h).json()["proforma"]
    agency = next(li for li in p["line_items"] if li["description"] == "Agency Charges")
    p = client.patch(f"/proformas/{pid}/line-items/{agency['id']}", json={"rate": "6500", "description": "Agency"},
                     headers=h).json()
    agency = next(li for li in p["line_items"] if li["id"] == agency["id"])
    assert (agency["description"], float(agency["amount"]), float(agency["total"])) == ("Agency", 13000.0, 15340.0)

    x = client.get(f"/proformas/{pid}/invoice.xlsx", headers=h)
    assert x.status_code == 200 and x.content[:2] == b"PK"
    assert "ACME TYRES PRIVATE LIMITED - MEDU1234567890 - 7770001 - proforma.xlsx" in x.headers["content-disposition"].replace("%20", " ")
    ws = load_workbook(io.BytesIO(x.content)).active
    texts = [c.value for row in ws.iter_rows() for c in row if isinstance(c.value, str)]
    assert "GRAND TOTAL — ACME TYRES PRIVATE LIMITED PAYS CLARUS LOGISTICS LLP" in texts and "Agency" in texts
    pdf = client.get(f"/proformas/{pid}/invoice.pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"

    # a sent invoice is edited in place: the sent copy goes to history, the invoice is a draft again
    client.patch(f"/proformas/{pid}", json={"status": "sent"}, headers=h)
    r = client.patch(f"/proformas/{pid}/line-items/{agency['id']}", json={"rate": "1"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "draft" and r.json()["revisions"] == 1
    hist = client.get(f"/proformas/{pid}/history", headers=h).json()
    assert len(hist) == 1
    old = client.get(f"/proforma-snapshots/{hist[0]['id']}/invoice.pdf", headers=h)
    assert old.status_code == 200 and old.content[:4] == b"%PDF"


def test_sample_hss_invoice_matches_client_sheet(client, admin_headers):
    """Client's own sheet 'MAHRISHI RECYCLERS - OOLU2331734970 - 3496326': Nhava Sheva HSS,
    5 containers, 95,800 kg, duty challan interest 247, royalty 0.75/kg, bill rate 15."""
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "OOLUTEST0001", "consignee": "HKR - Mahrishi", "container": "5"},
                      headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={
        "be_no": "9496326", "port": "INNSA1", "gross_wt": "95.800 MTS", "assessable_value": "971248",
        "duty_amount": "325893", "igst_amount": "194055"}, headers=h)
    r = client.post("/duty-challans", json={"be_no": "9496326", "due_amount": "326140"}, headers=h).json()
    assert r["matched"][0]["shipment_id"] == sid and float(r["matched"][0]["interest"]) == 247.0

    pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "buyer"}, headers=h).json()["id"]
    fill = client.post(f"/proformas/{pid}/fill-from-shipment", headers=h).json()
    lines = {li["description"].split(" (")[0]: li for li in fill["proforma"]["line_items"]}
    cd = lines["Customs Duty"]
    assert (float(cd["amount"]), float(cd["gst_amount"]), float(cd["total"])) == (132085.0, 194055.0, 326140.0)
    assert "interest ₹247.00" in cd["description"]
    assert float(lines["Stamp Duty"]["total"]) == 1298.0          # CEILING(0.1% x (971248 + 326140))
    roy = lines["Royalty"]
    assert (float(roy["amount"]), float(roy["gst_amount"]), float(roy["total"])) == (71850.0, 12933.0, 84783.0)

    charges = {c["code"]: c["id"] for c in client.get("/charge-master", headers=h).json()}
    # Other Charges (20,000 x 5 + 0.25 x 95,800 = 1,23,950) comes from the Mahrishi buyer-copy pricing rule
    assert float(lines["Other Charges"]["amount"]) == 123950.0
    for code, rate in (("EC", 10000), ("SBOND", 2000), ("DC", 2000), ("CFS", 40000)):
        client.post(f"/proformas/{pid}/line-items", json={"charge_master_id": charges[code], "rate": rate, "quantity": 1},
                    headers=h)
    p = client.patch(f"/proformas/{pid}", json={"bill_rate": "15"}, headers=h).json()
    gstd = next(li for li in p["line_items"] if li["description"] == "GST Difference")
    assert float(gstd["total"]) == 13341.0                       # 18% x 15 x 95800 - 245319
    assert float(p["match_total"]) == 676843.0                   # the sheet's grand total
    assert float(p["grand_total"]) == 676843.0 - 84783.0 - 13341.0  # payable to Clarus

    inv = client.get(f"/proformas/{pid}/invoice", headers=h).json()
    v = inv["value"]
    assert (float(v["value_of_goods"]), float(v["gst_input"]), float(v["value_per_kg"])) == (1389431.0, 245319.0, 14.5)
    assert float(v["gst_output"]) == 258660.0 and inv["customs_duty"]["challan_today"] is True

    # bill rate cleared -> back to the automatic rate (the rules), not "no rate" (client, 2026-09-30)
    p = client.patch(f"/proformas/{pid}", json={"bill_rate": None}, headers=h).json()
    assert p["bill_rate_manual"] is False and float(p["bill_rate"]) == float(inv["value"]["suggested_bill_rate"])


def test_bill_rate_follows_the_costs(client, admin_headers):
    """Client, 2026-09-30: the HSS bill rate is always pre-filled by the rules and re-worked
    (up or down) when costs change; a rate typed by hand stays unless the costs pass it."""
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "RATETEST0001", "consignee": "HKR - Mahrishi", "container": "2"},
                      headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={"gross_wt": "50.000 MTS", "assessable_value": "500000"}, headers=h)
    pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "buyer"}, headers=h).json()["id"]
    client.post(f"/proformas/{pid}/fill-from-shipment", headers=h)
    charges = {c["code"]: c["id"] for c in client.get("/charge-master", headers=h).json()}
    rate = lambda: next(p for p in client.get(f"/shipments/{sid}/proformas", headers=h).json() if p["id"] == pid)  # noqa: E731

    first = rate()
    assert first["bill_rate"] is not None and first["bill_rate_manual"] is False   # pre-filled
    after = client.post(f"/proformas/{pid}/line-items", json={"charge_master_id": charges["DC"], "rate": 200000,
                                                                "quantity": 1}, headers=h).json()
    li = max((x for x in after["line_items"] if float(x["rate"]) == 200000), key=lambda x: x["id"])
    up = rate()
    assert float(up["bill_rate"]) > float(first["bill_rate"])                        # costs up: rate up
    client.delete(f"/proformas/{pid}/line-items/{li['id']}", headers=h)
    assert float(rate()["bill_rate"]) == float(first["bill_rate"])                   # and back down

    typed = float(first["bill_rate"]) + 5
    client.patch(f"/proformas/{pid}", json={"bill_rate": str(typed)}, headers=h)
    client.post(f"/proformas/{pid}/line-items", json={"charge_master_id": charges["SBOND"], "rate": 1000,
                                                       "quantity": 1}, headers=h)
    kept = rate()
    assert kept["bill_rate_manual"] is True and float(kept["bill_rate"]) == typed     # small change: kept
    client.post(f"/proformas/{pid}/line-items", json={"charge_master_id": charges["DC"], "rate": 900000,
                                                       "quantity": 1}, headers=h)
    raised = rate()
    assert float(raised["bill_rate"]) > typed                                          # costs passed it: raised


def test_typed_bill_rate_needs_no_10_paise_margin(client, admin_headers):
    """Client, 2026-10-07: a rate typed by hand can be anything above the value per kg that
    leaves a GST difference above zero — no 10 paise margin, no 25 paise step."""
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "RATETEST0002", "consignee": "HKR - Mahrishi", "container": "2"},
                      headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={"gross_wt": "50.000 MTS", "assessable_value": "500000"}, headers=h)
    pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "buyer"}, headers=h).json()["id"]
    client.post(f"/proformas/{pid}/fill-from-shipment", headers=h)
    v = client.get(f"/proformas/{pid}/invoice", headers=h).json()["value"]
    per_kg = Decimal(v["value_per_kg"])

    ok = client.patch(f"/proformas/{pid}", json={"bill_rate": str(per_kg + Decimal("0.01"))}, headers=h)
    assert ok.status_code == 200 and ok.json()["bill_rate_manual"] is True
    assert Decimal(ok.json()["bill_rate"]) == per_kg + Decimal("0.01")              # 1 paisa over: kept
    for low in (per_kg, per_kg - 1):
        r = client.patch(f"/proformas/{pid}", json={"bill_rate": str(low)}, headers=h)
        assert r.status_code == 400 and "value per kg" in r.json()["detail"]        # not above: refused

    lowest = client.get(f"/proformas/{pid}/invoice", headers=h).json()["value"]["lowest_bill_rate"]
    best = client.patch(f"/proformas/{pid}", json={"bill_rate": lowest}, headers=h)
    assert best.status_code == 200                                                   # minimise: allowed
    assert Decimal(lowest) % Decimal("0.05") == 0                                    # a round 5 paise rate
    step_less = str(Decimal(lowest) - Decimal("0.05"))
    assert client.patch(f"/proformas/{pid}", json={"bill_rate": step_less}, headers=h).status_code == 400


def test_buyer_and_seller_share_the_bill_rate(client, admin_headers):
    """Client, 2026-10-07: a rate typed on one HSS copy goes on the other; a new version
    replaces the working invoice for that party (the old one becomes history)."""
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "RATETEST0003", "consignee": "Earthman - Mahrishi", "container": "2"},
                      headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={"gross_wt": "50.000 MTS", "assessable_value": "500000"}, headers=h)
    seller = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "seller"}, headers=h).json()
    buyer = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "buyer"}, headers=h).json()
    assert seller["party"] == "Earthman" and buyer["party"] == "Mahrishi"
    client.patch(f"/proformas/{buyer['id']}", json={"status": "sent"}, headers=h)
    rate = client.get(f"/proformas/{seller['id']}/invoice", headers=h).json()["value"]["lowest_bill_rate"]
    assert client.patch(f"/proformas/{seller['id']}", json={"bill_rate": rate}, headers=h).status_code == 200
    rows = {p["bill_to_role"]: p for p in client.get(f"/shipments/{sid}/proformas", headers=h).json()}
    assert rows["buyer"]["bill_rate"] == rows["seller"]["bill_rate"] == rate
    assert rows["buyer"]["status"] == "draft" and rows["buyer"]["revisions"] == 1   # sent copy kept

    again = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "buyer"}, headers=h).json()
    assert again["bill_rate"] == rate and again["bill_rate_manual"] is True
    old = next(p for p in client.get(f"/shipments/{sid}/proformas", headers=h).json() if p["id"] == buyer["id"])
    assert old["status"] == "superseded"


def test_bill_to_details_from_organization_repository(client, admin_headers):
    h = admin_headers
    org = client.post("/organizations", json={"name": "MAHRISHI RECYCLERS", "gstin": "27abcde1234f1z5",
                                              "address": "Plot 1, Bhiwandi", "state": "Maharashtra"},
                      headers=h).json()
    assert org["gstin"] == "27ABCDE1234F1Z5"
    sid = client.post("/shipments", json={"mbl": "ORGTEST0001", "consignee": "Earthman - Mahrishi"}, headers=h).json()["id"]
    pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "seller"}, headers=h).json()["id"]
    inv = client.get(f"/proformas/{pid}/invoice", headers=h).json()
    assert inv["bill_to"]["name"] == "MAHRISHI RECYCLERS" and inv["bill_to"]["party"] == "Mahrishi"
    assert inv["bill_to"]["organization"]["address"] == "Plot 1, Bhiwandi"
    status = client.get("/daily-updates", headers=h).json()
    assert status["organizations_updated_today"] is True


def test_bl_consignee_by_ad_code_and_seller_disclaimer(client, admin_headers):
    h = admin_headers
    # BE importer (Bill To) details matched by name, despite 'PVT LTD' vs 'PRIVATE LIMITED'
    r = client.post("/organizations", json={"name": "Acme Tyres Pvt. Ltd.", "gstin": "27ACME0000A1Z5"}, headers=h)
    assert r.status_code == 201, r.text
    # the org holding the BE's AD code (6390001 on the synthetic BE) is the BL consignee
    orgs = client.get("/organizations", headers=h).json()
    holder = next((o for o in orgs if o["ad_code"] == "6390001"), None)
    if holder is None:
        holder = client.post("/organizations", json={"name": "EARTHMAN RUBBER INDUSTRIES", "ad_code": "6390001"},
                             headers=h).json()
    sid = _setup(client, h)
    pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "seller"}, headers=h).json()["id"]
    inv = client.get(f"/proformas/{pid}/invoice", headers=h).json()
    bt = inv["bill_to"]
    assert bt["organization"] is not None and "ACME TYRES" in bt["name"].upper()
    assert bt["bl_consignee"] == holder["name"] and bt["bl_consignee_ad_code"] == "6390001"
    assert inv["disclaimer"] == f"{holder['name']} to pay {bt['name']}"
    assert inv["copy_label"] == "For " + holder["name"].split()[0].title()   # seller copy: for the seller
    from urllib.parse import unquote
    assert "proforma (for " in unquote(client.get(f"/proformas/{pid}/invoice.pdf", headers=h).headers["x-filename"])
    pdf = client.get(f"/proformas/{pid}/invoice.pdf", headers=h)
    assert pdf.status_code == 200


def test_org_name_matching_is_loose():
    from app.invoice.build import _norm
    assert _norm("Acme Tyres Pvt. Ltd.") == _norm("M/S ACME TYRES PRIVATE LIMITED")


def test_hss_pricing_rule_seller_and_buyer_copies(client, admin_headers):
    """Mahrishi rule: seller copy Royalty 1/kg + Other 20,000/cntr; buyer copy Royalty 0.75/kg +
    Other 20,000/cntr + 0.25/kg — same total. Royalty is its own section."""
    h = admin_headers
    rules = client.get("/pricing-rules", headers=h).json()
    assert {r["bill_to_role"] for r in rules if r["importer_name"] == "MAHRISHI RECYCLERS"} == {"seller", "buyer"}
    sid = client.post("/shipments", json={"mbl": "RULETEST0001", "consignee": "HKR - Mahrishi", "container": "5"},
                      headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={"gross_wt": "95.800 MTS"}, headers=h)
    totals = {}
    for role in ("seller", "buyer"):
        pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": role}, headers=h).json()["id"]
        lines = client.post(f"/proformas/{pid}/fill-from-shipment", headers=h).json()["proforma"]["line_items"]
        roy = next(li for li in lines if li["description"] == "Royalty")
        other = next(li for li in lines if li["description"] == "Other Charges")
        assert roy["category"] == "royalty" and other["category"] == "service"
        totals[role] = float(roy["total"]) + float(other["total"])
        if role == "seller":
            assert (float(roy["amount"]), float(other["amount"])) == (95800.0, 100000.0)
        else:
            assert (float(roy["amount"]), float(other["amount"])) == (71850.0, 123950.0)
        inv = client.get(f"/proformas/{pid}/invoice", headers=h).json()
        sec = {x["category"]: x for x in inv["sections"]}
        assert sec["royalty"]["title"] == "Royalty" and not sec["royalty"]["counts_in_total"]
        assert inv["match_total"] is not None
        assert client.get(f"/proformas/{pid}/invoice.pdf", headers=h).status_code == 200
    assert totals["seller"] == totals["buyer"] == 231044.0


def test_pricing_rule_for_a_specific_seller_wins(client, admin_headers):
    h = admin_headers
    lines = [{"code": "ROY", "per_kg": "0.5"}]
    r = client.post("/pricing-rules", json={"name": "Earthman → Mahrishi (seller copy)", "importer_name": "MAHRISHI RECYCLERS",
                                            "seller_name": "Earthman", "bill_to_role": "seller", "lines": lines}, headers=h)
    assert r.status_code == 201
    sid = client.post("/shipments", json={"mbl": "RULETEST0002", "consignee": "Earthman - Mahrishi", "container": "2"},
                      headers=h).json()["id"]
    client.patch(f"/shipments/{sid}", json={"gross_wt": "10.000 MTS"}, headers=h)
    pid = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": "seller"}, headers=h).json()["id"]
    got = client.post(f"/proformas/{pid}/fill-from-shipment", headers=h).json()["proforma"]["line_items"]
    roy = next(li for li in got if li["description"] == "Royalty")
    assert float(roy["rate"]) == 0.5 and not any(li["description"] == "Other Charges" for li in got)
    assert client.post("/pricing-rules", json={**r.json(), "lines": [{"code": "NOPE"}]}, headers=h).status_code == 400
    client.delete(f"/pricing-rules/{r.json()['id']}", headers=h)


def test_licence_rates_prefill_new_proforma(client, admin_headers):
    """Client licence rates: 111022154 (Mahrishi HSS) — Agency 7,000/cntr; Examination by port
    (INNSA1 2,000, INMUN1 / INDWN6 3,000); Bond + Documentation 2,000 each for seller HKR,
    1,000 for Earthman / Earthstar; Other Charges from the HSS rule."""
    h = admin_headers

    def new(consignee, port, licence, role="buyer", exam=True, mbl=None):
        sid = client.post("/shipments", json={"mbl": mbl or f"LIC{consignee[:3]}{port}{role}".replace(" ", ""),
                                              "consignee": consignee, "container": "5"}, headers=h).json()["id"]
        client.patch(f"/shipments/{sid}", json={"port": port, "license": licence, "gross_wt": "95.800 MTS",
                                                "under_examination": exam}, headers=h)
        p = client.post(f"/shipments/{sid}/proformas", json={"bill_to_role": role} if " - " in consignee else {},
                        headers=h).json()
        return {li["description"]: li for li in p["line_items"]}

    hkr = new("HKR - Mahrishi", "INNSA1", "111022154")
    assert float(hkr["Agency Charges"]["amount"]) == 35000.0            # created already filled
    assert float(hkr["Examination Charges"]["amount"]) == 10000.0   # 2,000 x 5 containers
    assert float(hkr["Bond Charges"]["amount"]) == float(hkr["Documentation Charges"]["amount"]) == 2000.0
    assert float(hkr["Other Charges"]["amount"]) == 123950.0             # HSS rule (buyer copy)

    em = new("Earthman - Mahrishi", "INDWN6", "111022154", role="seller")
    assert float(em["Examination Charges"]["amount"]) == 15000.0         # Panipat 3,000 x 5
    assert float(em["Bond Charges"]["amount"]) == 1000.0 and float(em["Documentation Charges"]["amount"]) == 1000.0

    home = new("Homezone", "INNSA1", "111021955")
    assert float(home["Other Charges"]["amount"]) == 100000.0 and float(home["Examination Charges"]["amount"]) == 3000.0
    assert "Bond Charges" not in home

    closed = new("Divine", "INDWN6", "111021207", exam=False)
    assert float(closed["Agency Charges"]["amount"]) == 35000.0          # standard rate (licence closed)


def test_suggested_bill_rate():
    from decimal import Decimal as D
    from app.invoice.build import suggest_bill_rate
    wt = D("95800")
    assert suggest_bill_rate(D("11.80"), D("0"), wt) == D("12.00")
    assert suggest_bill_rate(D("12.15"), D("0"), wt) == D("12.25")
    assert suggest_bill_rate(D("14.50"), D("245319"), wt) == D("14.75")   # client's Mahrishi sheet (they used 15)
    # GST difference must stay positive: break-even 245319 / (0.18 x 95800) = 14.23 > value/kg + 0.10
    assert suggest_bill_rate(D("13.00"), D("245319"), wt) == D("14.25")


def test_grand_total_rounded_up_to_the_rupee():
    from decimal import Decimal as D
    from app.invoice.build import round_off
    # never rounded down (client): +0.60, not -0.40
    assert round_off(D("720403.40")) == (D("720404"), D("0.60"))
    assert round_off(D("231043.50")) == (D("231044"), D("0.50"))
    assert round_off(D("231044.00")) == (D("231044"), D("0.00"))
