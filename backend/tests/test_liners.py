"""Shipping line from the BL number format (client's rules) + container number format."""
from app.liners import container_ok, identify


def test_client_rules_on_real_formats():
    cases = {
        "274014260": "Maersk", "HDMUBHMA01389200": "HMM", "BHMA05154200": "HMM", "ACLJEDNSA359426": "NAVIO",
        "CJHRUSF0211": "Chartering RORO", "OOLU2327911610": "OOCL", "LPL1530410": "CMA CGM",
        "CSX26JEDNSA018922": "Cordelia", "HLCUGOA260793271": "Hapag-Lloyd", "NAM8624705B": "CMA CGM",
        "CYP0122342": "CMA CGM", "ONEYRICGU1432400": "ONE",
    }
    for bl, line in cases.items():
        assert identify(bl)["line"] == line, bl


def test_notes_for_what_icegate_wont_find():
    assert identify("BHMA05154200")["note"].endswith("HDMUBHMA05154200")
    assert identify("BHMA05154200")["icegate_mbl"] == "HDMUBHMA05154200"
    assert identify("HDMUBHMA05154200")["icegate_mbl"] == "HDMUBHMA05154200"
    assert "HBL" in identify("CJHRUSF0211")["note"]
    assert identify("274014260")["note"] is None


def test_unknown_and_near_misses():
    assert identify("") is None and identify("XYZ123") is None
    assert identify("27401426") is None            # 8 digits isn't Maersk
    assert identify("2740142600") is None          # nor is 10


def test_container_format():
    assert container_ok("MRKU5032093") and container_ok("mrku 5032093")
    assert not container_ok("MRK5032093") and not container_ok("MRKU503209") and not container_ok("MRKU50320931")


def test_hmm_mbl_is_stored_with_hdmu(client, admin_headers):
    from app.liners import standard_mbl
    assert standard_mbl("bhma 05154200") == "HDMUBHMA05154200" and standard_mbl("HDMUBHMA05154200") == "HDMUBHMA05154200"
    assert standard_mbl("274014260") == "274014260"
    s = client.post("/shipments", json={"mbl": "BHMA77154200", "port": "INMUN1"}, headers=admin_headers).json()
    assert s["mbl"] == "HDMUBHMA77154200"
    r = client.patch(f"/shipments/{s['id']}", json={"mbl": "BHMA77154201"}, headers=admin_headers)
    assert r.json()["mbl"] == "HDMUBHMA77154201"
    assert any(x["id"] == s["id"] for x in client.get("/shipments?search=BHMA77154201", headers=admin_headers).json())
