"""The ICEGATE self-updater, fed ICEGATE's real answers (captured 2026-09-30) through a fake portal — never the real one."""
from datetime import date, datetime, timezone

from app.core.database import SessionLocal
from app.icegate_portal import client as pc
from app.icegate_portal import sync
from app.models.shipment import Shipment

RUNNING = {"beDetailsModel": [{"iec": "AAVFD7221R", "typ": "H", "firstCheck": "N", "sec48": "N", "appraisingGroup": "2H", "totalDuty": "68630"}],
           "currentStatusModel": [{"appraisement": "SYSTEM", "currentQueue": "SUP", "queryRaised": "N.A.", "queryReply": "N.A.",
                                   "replyDate": "N.A.", "apprDate": "2026-09-26 16:51:11.0", "assessDate": "2026-09-26 16:51:11.0",
                                   "pymtDate": "N.A.", "examDate": "N.A.", "oocDate": "N.A."}],
           "paymentDetailsModel": [{"challaNo": "2063391411", "dutyAmt": "68630", "interestAmt": "28", "totalDuty": "68658.0", "dutyPaid": "N.A."}],
           "beAmendmentModel": [], "edocValidityModel": [{"docDescription": "Bill of Entry Copy on Assessment", "validity": "Y"}]}
CLEARED = {"beDetailsModel": [{"iec": "ABWFM1429J", "typ": "H", "firstCheck": "N", "sec48": "N", "appraisingGroup": "2H", "totalDuty": "252294"}],
           "currentStatusModel": [{"appraisement": "SYSTEM", "currentQueue": "N.A.", "queryRaised": "Q",
                                   "queryReply": "RESPECTED SIR UPLOADED EIR AND CPCB PLEASE OOC", "replyDate": "2026-09-28 00:00:00.0",
                                   "apprDate": "2026-09-23 13:25:38.0", "assessDate": "2026-09-23 13:25:38.0",
                                   "pymtDate": "2026-09-29 16:51:51.0", "examDate": "N.A.", "oocDate": "2026-09-29 20:50:09.0"}],
           "paymentDetailsModel": [{"challaNo": "2063314874", "totalDuty": "252709.0", "dutyPaid": "252709.0", "modeOfPymt": "EPAYMENT"}],
           "beAmendmentModel": [{"boeNo": "3952741", "amendmentDate": "2026-09-28", "amendmentStatus": "Approved"}],
           "edocValidityModel": [{"docDescription": "GatePass OOC Copy on Clearance", "validity": "Y"}]}


class FakePortal:
    def __init__(self, statuses, queries=(), challans=()):
        self.statuses, self._q, self._c, self.session = statuses, list(queries), list(challans), {"token": "t", "sessionId": "s"}

    def keep_alive(self):
        pass

    def be_status(self, port, be_no, be_dt):
        return self.statuses.get((port, be_no, be_dt))

    def queries(self):
        return self._q

    def challans(self):
        return self._c


def test_password_encryption_matches_the_portal():
    # AES-ECB/PKCS7 with the portal's key, base64 — same as its login page (CryptoJS)
    assert pc.encrypt_password("abc") == "6Fv0KsVsNIpIGvHWhPY81Q=="  # = Node crypto aes-128-ecb


def test_label_and_evidence(client, admin_headers, monkeypatch):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode())
    h = admin_headers
    run_id = client.post("/shipments", json={"mbl": "PORTAL-RUN", "port": "INMUN1", "be_no": "9042224", "be_dt": "2026-09-26"}, headers=h).json()["id"]
    clr_id = client.post("/shipments", json={"mbl": "PORTAL-CLR", "port": "INNSA1", "be_no": "9952741", "be_dt": "2026-09-23"}, headers=h).json()["id"]
    old_id = client.post("/shipments", json={"mbl": "PORTAL-OLD", "port": "INNSA1", "be_no": "9952741", "be_dt": "2025-01-10"}, headers=h).json()["id"]
    fake = FakePortal({("INMUN1", "9042224", date(2026, 9, 26)): RUNNING, ("INNSA1", "9952741", date(2026, 9, 23)): CLEARED},
                      queries=[{"beNo": "9952741", "beDt": "2026-09-23", "location": "INNSA1", "queryNumber": "1", "queryText": "EIR AND TYRE EPRA PLS",
                                "queryDt": "2026-09-27", "reply": "N.A."}])
    db = SessionLocal()
    try:
        st = sync.run(db, "status", portal=fake, force=True)
        assert st["last_error"] is None, st
        r, c, o = db.get(Shipment, run_id), db.get(Shipment, clr_id), db.get(Shipment, old_id)
        assert r.icegate["be_status"]["label"] == "Assessed 26-Sep (system) · with SUP" and not r.duty_paid
        assert c.icegate["be_status"]["label"].startswith("OOC 29-Sep 20:50")
        assert c.ooc and c.duty_paid and c.ooc_date == date(2026, 9, 29) and c.status.value == "ooc_done"
        # the 2025 BE with the same number is looked up with ITS date -> not given 2026's answer
        assert o.icegate["be_status"]["label"].startswith("Not found") and not o.ooc
    finally:
        db.close()
    # the query: matched on BE no + DATE + port (the 2025 shipment with the same number is not it)
    q = [x for x in client.get("/icegate-mails?attention=true", headers=h).json() if x["be_no"] == "9952741"]
    assert len(q) == 1 and q[0]["shipment_id"] == clr_id and "EIR AND TYRE" in q[0]["summary"]
    # ICEGATE later shows the reply -> closed
    fake._q[0]["reply"] = "UPLOADED EIR PLS OOC"
    db = SessionLocal()
    try:
        sync.run(db, "status", portal=fake, force=True)
    finally:
        db.close()
    assert not [x for x in client.get("/icegate-mails?attention=true", headers=h).json() if x["be_no"] == "9952741"]


def test_ins_queue_means_under_examination(client, admin_headers):
    """Client, 2026-09-30: a BE with the INS queue is under examination (before any exam date shows)."""
    sid = client.post("/shipments", json={"mbl": "PORTAL-INS", "port": "INMUN1", "be_no": "9042299", "be_dt": "2026-09-26"},
                      headers=admin_headers).json()["id"]
    ins = {**RUNNING, "currentStatusModel": [{**RUNNING["currentStatusModel"][0], "currentQueue": "INS"}]}
    db = SessionLocal()
    try:
        s = db.get(Shipment, sid)
        sync.apply_be_status(db, s, ins, datetime.now(timezone.utc))
        assert s.under_examination and "Under examination (INS)" in s.icegate["be_status"]["label"]
        # later the queue moves on: still remembered as examined
        sync.apply_be_status(db, s, RUNNING, datetime.now(timezone.utc))
        assert s.under_examination and s.icegate["be_status"]["was_ins"]
        assert s.icegate["be_status"]["label"].endswith("was under examination")
    finally:
        db.rollback()
        db.close()


def test_challans_added_only_when_changed(client, admin_headers, monkeypatch):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode())
    rows = [{"iecCode": "AAVFD7221R", "locationCode": "INMUN1", "boeNumber": 9142224, "boeDate": "26.09.2026",
             "challanNumber": 2063391411, "dutyAmount": 68658.0, "documentType": "BE"}]
    db = SessionLocal()
    try:
        assert sync.run(db, "challans", portal=FakePortal({}, challans=rows))["last_challans"]["added"] == 1
        assert sync.run(db, "challans", portal=FakePortal({}, challans=rows))["last_challans"]["added"] == 0
        rows[0]["dutyAmount"] = 68700.0  # interest went up a day later
        assert sync.run(db, "challans", portal=FakePortal({}, challans=rows))["last_challans"]["added"] == 1
    finally:
        db.close()


def test_outside_hours_does_nothing(monkeypatch):
    class Late(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)  # 23:30 IST
    monkeypatch.setattr(sync, "datetime", Late)
    db = SessionLocal()
    try:
        before = dict(sync._state(db)[1])
        assert sync.run(db, "status", portal=FakePortal({})) == before
    finally:
        db.close()


def test_password_mechanism(client, admin_headers, monkeypatch):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", __import__("cryptography.fernet", fromlist=["Fernet"]).Fernet.generate_key().decode())
    h = admin_headers
    assert client.put("/icegate-login", json={"icegate_id": "acgfa8615dpcb000"}, headers=h).status_code == 200  # one field alone
    r = client.put("/icegate-login", json={"cha_code": "ACGFA8615DCH001"}, headers=h).json()
    assert (r["icegate_id"], r["cha_code"]) == ("ACGFA8615DPCB000", "ACGFA8615DCH001")
    assert client.put("/icegate-login", json={"icegate_id": "ab"}, headers=h).status_code == 422
    r = client.put("/icegate-login/password", json={"password": "old-secret"}, headers=h).json()
    assert r["password_set"] and r["ready"] and "old-secret" not in str(r)

    class Refuses(FakePortal):
        def keep_alive(self):
            raise pc.SessionLapsed("x")

        def login(self, wait):
            raise pc.BadPassword("ICEGATE didn't accept the password")
    db = SessionLocal()
    try:
        st = sync.run(db, "status", portal=Refuses({}), force=True)
        assert "password has been reset" in st["last_error"]
        assert not sync.ready(db)  # stops: no second try until a new password is entered
    finally:
        db.close()
    r = client.get("/icegate-login", headers=h).json()
    assert r["password_bad"] and not r["ready"]
    assert client.post("/icegate-login/run", json={"what": "status"}, headers=h).status_code == 400
    r = client.put("/icegate-login/password", json={"password": "new-secret"}, headers=h).json()
    assert r["ready"] and not r["password_bad"] and r["password_set_by"]
