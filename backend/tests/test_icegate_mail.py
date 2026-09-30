"""ICEGATE mails -> events -> shipments. Mails are built here in the shape of the real ones (never a real mailbox)."""
import io
import zipfile
from email.message import EmailMessage

from app.icegate_mail.parse import parse
from tests.conftest import be_pdf

G = "\x1d"


def mail(subject, body, sender="no-replyregistration@icegate.gov.in", att=None, date="Tue, 29 Sep 2026 13:22:01 +0530"):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, "office@example.com", subject
    m.set_content(body)
    for name, data in att or []:
        m.add_attachment(data, maintype="application", subtype="octet-stream", filename=name)
    return f"Date: {date}\n".encode() + m.as_bytes()  # raw: ICEGATE's dates aren't always RFC dates


def ack(port, job, be, be_dt):
    return f"HREC{G}ZZ{G}{port}{G}\nF{G}{port}{G}{job}{G}15092026{G}{be}{G}{be_dt}{G}{G}5{G}MAIN{G}\nTREC{G}1\n<START-SIGNATURE>x".encode()


def nak(port, job):
    return f"HREC{G}ZZ\nF{G}{port}{G}{job}{G}22092026{G}{G}{G}{G}496{G}{G}INFO_TYPE{G}\nTREC{G}1\n".encode()


def test_parse_kinds():
    e = parse(mail("Job number 975_CACHI01_Success", "Dear X\nFile Validation – Success", "devfilingtest@icegate.gov.in",
                   [("1.ack", ack("INNSA1", "975", "9088606", "29092026"))]))
    assert (e["kind"], e["job_no"], e["be_no"], e["port"], str(e["be_date"])) == ("be_ack", "975", "9088606", "INNSA1", "2026-09-29")
    e = parse(mail("Job number 983_CACHI01_Failed", "File Validation - Failed", "devfilingtest@icegate.gov.in",
                   [("1.nak", nak("INMUN1", "983"))]))
    assert e["kind"] == "be_nak" and e["attention"] and "496" in e["summary"]
    e = parse(mail("Bill of Entry Examination Instructions",
                   "Your Bill of Entry No 9041785 dated 26/09/2026 filed at INMUN1 has been registered successfully with "
                   "following examination instructions:\nExamination Order :\nAssessment and Examination has not been "
                   "prescribed for this BE.\nCCR Examination Instruction :\n", "no-reply@icegate.gov.in",
                   date="29-SEP-2026 13:34:49"))
    assert e["kind"] == "exam_order" and e["detail"]["prescribed"] is False and e["port"] == "INMUN1"
    assert e["received_at"] is not None
    e = parse(mail("Outbound file generated", "processed", "devfilingtest@icegate.gov.in",
                   [("C.out", f"HREC{G}ZZ\nF{G}INNSA1{G}9952741{G}23092026{G}1{G}27092026{G}EIR AND TYRE PLS\nTREC\n".encode())]))
    assert e["kind"] == "be_query" and e["detail"]["query"] == "EIR AND TYRE PLS"
    e = parse(mail("OTP for email verification of ICEGATE ID ABC", "Dear user, 482913 is the OTP for your transaction"))
    assert e["kind"] == "otp" and e["detail"]["otp"] == "482913"
    assert parse(mail("Hello", "x", sender="someone@gmail.com")) is None
    assert parse(mail("S/B Acknowledgement", "x"))["kind"] == "other"  # every ICEGATE mail is kept


def test_import_matches_fills_and_attention(client, admin_headers):
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "MAILTEST1", "job": "975", "port": "INNSA1"}, headers=h).json()["id"]
    other = client.post("/shipments", json={"mbl": "MAILTEST2", "job": "983", "port": "INMUN1"}, headers=h).json()["id"]
    mails = [
        mail("Job number 983_CACHI01_Failed", "Failed", "devfilingtest@icegate.gov.in", [("1.nak", nak("INMUN1", "983"))],
             date="Sat, 26 Sep 2026 15:47:58 +0530"),
        mail("Electronic first copy of BoE  for Bill of Entry No9088606Dt29092026", "Please find attached",
             "noreply@icegate.gov.in", [("908860629092026INNSA1BE0290920261321.pdf", be_pdf(be_no="9088606", mawb="MAILTEST1").getvalue())],
             date="Tue, 29 Sep 2026 13:21:21 +0530"),
        mail("Job number 975_CACHI01_Success", "ok", "devfilingtest@icegate.gov.in",
             [("1.ack", ack("INNSA1", "975", "9088606", "29092026"))], date="Tue, 29 Sep 2026 13:15:42 +0530"),
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, m in enumerate(mails):
            z.writestr(f"{i}.eml", m)
        z.writestr("otp.eml", mail("OTP for email verification", "Dear user, 111222 is the OTP for your transaction"))
    r = client.post("/icegate-mails/import", files=[("files", ("attachments.zip", buf.getvalue(), "application/zip"))], headers=h)
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["new"] == 4 and res["ignored"] == 0
    otp = next(x for x in client.get("/icegate-mails", headers=h).json() if x["kind"] == "otp")
    assert "otp" not in otp["detail"] and otp["detail"]["otp_expired"]  # 2026 mail: long expired

    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert s["be_no"] == "9088606" and s["status"] in ("be_filed", "be_assessed")  # Ack filled the BE, then the copy matched
    docs = client.get(f"/shipments/{sid}/documents", headers=h).json()
    assert any(d["document_type"] == "assessed_bill_of_entry" for d in docs)
    tl = client.get(f"/shipments/{sid}/icegate-mails", headers=h).json()
    assert [x["kind"] for x in tl] == ["be_ack", "processed_be"]

    att = client.get("/icegate-mails?attention=true", headers=h).json()
    nk = next(x for x in att if x["shipment_id"] == other)
    assert nk["kind"] == "be_nak"
    alerts = client.get("/shipments/alerts", headers=h).json()
    assert any(a["shipment_id"] == other and a["kind"] == "icegate" for a in alerts)

    # same zip again: nothing new
    r = client.post("/icegate-mails/import", files=[("files", ("a.zip", buf.getvalue(), "application/zip"))], headers=h)
    assert r.json()["new"] == 0 and r.json()["duplicates"] == 4

    # filed again and accepted -> the Neg Ack closes itself
    client.post("/icegate-mails/import", files=[("files", ("x.eml", mail(
        "Job number 983_CACHI01_Success", "ok", "devfilingtest@icegate.gov.in",
        [("2.ack", ack("INMUN1", "983", "9041785", "26092026"))], date="Sat, 26 Sep 2026 17:00:00 +0530"), "message/rfc822"))], headers=h)
    assert not any(x["id"] == nk["id"] for x in client.get("/icegate-mails?attention=true", headers=h).json())

    r = client.post(f"/icegate-mails/{nk['id']}/resolve", json={"note": "checked"}, headers=h)
    assert r.status_code == 200


def test_old_mail_is_history_only(client, admin_headers):
    """Mails older than 45 days (the old inbox moved over) go on the timeline but change nothing."""
    h = admin_headers
    sid = client.post("/shipments", json={"mbl": "OLDMAIL1", "job": "977", "port": "INNSA1"}, headers=h).json()["id"]
    old = [mail("Job number 977_CACHI01_Success", "ok", "devfilingtest@icegate.gov.in",
                [("1.ack", ack("INNSA1", "977", "8870001", "10062026"))], date="Wed, 10 Jun 2026 11:00:00 +0530"),
           mail("Job number 978_CACHI01_Failed", "Failed", "devfilingtest@icegate.gov.in", [("1.nak", nak("INNSA1", "978"))],
                date="Wed, 10 Jun 2026 11:05:00 +0530")]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, m in enumerate(old):
            z.writestr(f"{i}.eml", m)
    client.post("/icegate-mails/import", files=[("files", ("old.zip", buf.getvalue(), "application/zip"))], headers=h)
    s = client.get(f"/shipments/{sid}", headers=h).json()
    assert s["be_no"] is None  # nothing filled from an old mail
    tl = client.get(f"/shipments/{sid}/icegate-mails", headers=h).json()
    assert tl and "timeline only" in tl[0]["notes"][0]
    assert not [x for x in client.get("/icegate-mails?attention=true", headers=h).json() if x["job_no"] == "978"]
