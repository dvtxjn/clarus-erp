"""ODeX mails (DO / line invoices) and the admin's automatic rules. Mails built here in the shape of the real
ODeX notifications (never a real mailbox)."""
import io
import zipfile
from datetime import datetime, timezone
from email.message import EmailMessage

from app.core.database import SessionLocal
from app.icegate_mail.parse import parse
from app.models.shipment import Shipment
from tests.test_icegate_mail import ack, mail

ODEX = "notification@odexservices.com"


def odex(subject, html_body, date="Wed, 30 Sep 2026 11:18:05 +0000"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = ODEX, "updates@example.com", subject
    m.set_content("see html")
    m.add_alternative(html_body, subtype="html")
    return f"Date: {date}\n".encode() + m.as_bytes()


def do_released(bl, do_no="26093001834", do_date="30-09-2026", date="Wed, 30 Sep 2026 11:18:05 +0000"):
    return odex(f"ODeX: DO Released for {bl}",
                f"<p>Dear Sir/Madam,</p><p>DO has been uploaded successfully for BL No. {bl}.</p>"
                f"<table><tr><td>DO Number</td><td>DO date</td></tr><tr><td>{do_no}</td><td>{do_date}</td></tr></table>"
                "<p>Above notification on behalf of CMA CGM AGENCIES INDIA PRIVATE LIMITED</p>", date)


def rejected(bl, date="Sat, 19 Sep 2026 00:02:00 +0530"):
    return odex(f"ODeX: Notification Mail for Rejecting of DO Request for BL No. {bl} by CMA CGM AGENCIES INDIA PRIVATE LIMITED",
                f"<p>CMA CGM AGENCIES INDIA PRIVATE LIMITED has sent you below remarks for Rejecting DO Request of BL No. {bl}</p>"
                f"<table><tr><td>BL No.</td><td>Remarks</td></tr><tr><td>{bl}</td><td>Consignee is under Finance HOLD.</td></tr></table>"
                "<p>Note: This is a system generated e-mail.</p>", date)


def invoices(bl):
    return odex(f"ODeX: Invoices Received for {bl}",
                f"<p>Invoices released for {bl},</p><p>Type Of Delivery: Factory Destuff</p><p>IGM No.: </p>"
                "<table><tr><td>Invoice No.</td><td>Invoice Type</td><td>Total Invoice Amt.</td><td>Bill to Party</td></tr>"
                "<tr><td>INIUPC27027302</td><td>NON FREIGHT</td><td>708265.5</td><td>DIVINE INDUSTRIES</td></tr></table>")


def upload(client, h, *raws):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, r in enumerate(raws):
            z.writestr(f"{i}.eml", r)
    return client.post("/icegate-mails/import", files=[("files", ("m.zip", buf.getvalue(), "application/zip"))], headers=h).json()


def test_parse_odex_kinds():
    e = parse(do_released("LPL1543012"))
    assert (e["kind"], e["mbl"], e["detail"]["do_no"], e["detail"]["do_date"]) == ("odex_do_released", "LPL1543012", "26093001834", "30-09-2026")
    e = parse(invoices("LPL1543012"))
    assert e["kind"] == "odex_invoice_received" and e["detail"]["invoices"][0]["amount"] == "708265.5"
    e = parse(rejected("CYP0122342"))
    assert e["kind"] == "odex_do_rejected" and e["attention"] and "Finance HOLD" in e["detail"]["remarks"]
    # KYC-pending mails are spam for the office: not read at all
    assert parse(odex("ODeX: KYC OR Registration Pending", "<p>Consignee : DIVINE INDUSTRIES</p>")) is None
    # a person's reply to an ODeX mail isn't ODeX's own mail
    assert parse(mail("Re: ODeX: Notification Mail for Rejecting of DO Request", "pls check", sender="someone@cma-cgm.com")) is None


def test_do_released_ticks_do_and_settles_the_rejection(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "ODEXBL0001", "port": "INMUN1"}, headers=h).json()["id"]
    upload(client, h, rejected("ODEXBL0001", date="Tue, 29 Sep 2026 10:00:00 +0530"))
    open_ = [x for x in client.get("/icegate-mails?attention=true", headers=h).json() if x["mbl"] == "ODEXBL0001"]
    assert len(open_) == 1 and open_[0]["shipment_id"] == sid
    upload(client, h, do_released("ODEXBL0001"), invoices("ODEXBL0001"))
    assert client.get(f"/shipments/{sid}", headers=h).json()["do"] is True
    assert not [x for x in client.get("/icegate-mails?attention=true", headers=h).json() if x["mbl"] == "ODEXBL0001"]
    tl = client.get(f"/shipments/{sid}/icegate-mails", headers=h).json()
    assert {x["kind"] for x in tl} == {"odex_do_rejected", "odex_do_released", "odex_invoice_received"}
    assert {x["kind"] for x in client.get("/icegate-mails?source=odex&scope=all", headers=h).json()} >= {"odex_do_released"}
    assert not [x for x in client.get("/icegate-mails?source=icegate&scope=all", headers=h).json() if x["kind"].startswith("odex")]


def test_rules_switch_off_and_custom_rules(client, admin_headers):
    h = admin_headers
    rules = client.get("/auto-rules", headers=h).json()
    assert any(r["id"] == "odex.do_released" and r["enabled"] for r in rules["builtin"])
    assert not next(r for r in rules["builtin"] if r["id"] == "odex.cfs_fill")["enabled"]  # off unless asked
    # bad rules refused
    assert client.put("/auto-rules", json={"custom": [{"source": "mail", "kind": "be_ack"}]}, headers=h).status_code == 422
    assert client.put("/auto-rules", json={"custom": [{"source": "mail", "kind": "nope", "field": "do"}]}, headers=h).status_code == 422
    # switch DO-released off; add: IF line invoices received THEN Needs attention; IF queue APR THEN tick duty paid
    r = client.put("/auto-rules", json={"off": ["odex.do_released", "odex.cfs_fill"], "history_days": 45, "custom": [
        {"source": "mail", "kind": "odex_invoice_received", "attention": True},
        {"source": "mail", "kind": "be_ack", "contains": "Accepted", "field": "line_paid"},
        {"source": "be_queue", "queue": "apr", "field": "duty_paid"}]}, headers=h)
    assert r.status_code == 200 and len(r.json()["custom"]) == 3 and r.json()["custom"][2]["queue"] == "APR"

    sid = client.post("/shipments", json={"mbl": "ODEXBL0002", "port": "INMUN1", "job": "7702"}, headers=h).json()["id"]
    upload(client, h, do_released("ODEXBL0002"), invoices("ODEXBL0002"),
           mail("Job number 7702_CACHI01_Success", "ok", "devfilingtest@icegate.gov.in",
                [("1.ack", ack("INMUN1", "7702", "8877702", "29092026"))]))
    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert s["do"] is False                      # the built-in rule is off
    assert s["line_paid"] is True                # the custom mail rule ticked it
    assert s["be_no"] == "8877702"               # other built-in rules still on
    att = [x for x in client.get("/icegate-mails?attention=true", headers=h).json() if x["mbl"] == "ODEXBL0002"]
    assert [x["kind"] for x in att] == ["odex_invoice_received"]

    # queue rule on ICEGATE's BE status
    from app.icegate_portal import sync
    from tests.test_icegate_portal import RUNNING

    db = SessionLocal()
    try:
        ship = db.get(Shipment, sid)
        ship.be_dt = ship.be_dt or datetime(2026, 9, 29).date()
        apr = {**RUNNING, "currentStatusModel": [{**RUNNING["currentStatusModel"][0], "currentQueue": "APR", "pymtDate": "N.A."}]}
        ship.duty_paid = False
        sync.apply_be_status(db, ship, apr, datetime.now(timezone.utc))
        assert ship.duty_paid is True
    finally:
        db.rollback()
        db.close()
    client.put("/auto-rules", json={"custom": [], "off": ["odex.cfs_fill"]}, headers=h)  # back to the defaults


def test_instant_push_switch(client, admin_headers, monkeypatch):
    h = admin_headers
    monkeypatch.delenv("GMAIL_PUBSUB_TOPIC", raising=False)
    r = client.put("/gmail-reader/push", json={"enabled": False}, headers=h).json()
    assert r["push_wanted"] is False and r["instant"] is False
    r = client.put("/gmail-reader/push", json={"enabled": True}, headers=h).json()
    assert r["push_wanted"] is True and "isn't set up" in (r["push_error"] or "")
