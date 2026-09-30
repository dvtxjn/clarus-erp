"""Reading the ICEGATE mailbox automatically — with a fake Gmail (never a real mailbox)."""
from cryptography.fernet import Fernet

from app.core.database import SessionLocal
from app.icegate_mail import gmail
from tests.test_icegate_mail import ack, mail


class FakeGmail:
    def __init__(self, mails, history="100"):
        self.mails, self.history, self.watched = dict(mails), history, None

    def profile(self):
        return {"emailAddress": "icegate@example.com", "historyId": self.history}

    def search(self, q, limit=500):
        return list(self.mails)

    def new_ids(self, start):
        return [i for i in self.mails if int(i) > int(start)], self.history

    def raw(self, i):
        return self.mails[i]

    def watch(self, topic):
        self.watched = topic
        return {"expiration": "9999999999999"}


def test_sync_reads_new_mail_once(client, admin_headers, monkeypatch):
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", Fernet.generate_key().decode())
    client.post("/shipments", json={"mbl": "GMAILTEST1", "job": "961", "port": "INNSA1"}, headers=admin_headers)
    m1 = mail("Job number 961_CACHI01_Success", "ok", "devfilingtest@icegate.gov.in", [("1.ack", ack("INNSA1", "961", "9612345", "29092026"))])
    db = SessionLocal()
    try:
        row, _ = gmail.state(db)
        gmail.save(db, row, {"token": "x"})  # connected (the fake needs no token)
        fake = FakeGmail({"1": m1}, history="5")
        st = gmail.sync(db, fake, topic="projects/p/topics/t")
        assert st["last_error"] is None and st["history_id"] == "5" and st["last_new"] == 1 and fake.watched
        # a later push: only mails after history 5 are fetched; an already-read one is skipped by fingerprint
        fake.mails["6"] = mail("Bill of entry number generated", "Your Bill of entry has been successfully generated with BE number 9612345.")
        fake.mails["7"] = m1
        fake.history = "7"
        st = gmail.sync(db, fake)
        assert st["last_new"] == 1 and st["history_id"] == "7"
    finally:
        db.close()
    s = next(x for x in client.get("/shipments", headers=admin_headers).json() if x["mbl"] == "GMAILTEST1")
    assert s["be_no"] == "9612345"


def test_push_needs_token(client, monkeypatch):
    monkeypatch.setenv("JOB_TOKEN", "secret-token")
    assert client.post("/internal/gmail/push?token=wrong").status_code == 403
    assert client.post("/internal/gmail/push?token=secret-token").status_code == 204


def test_callback_refuses_bad_state(client):
    r = client.get("/oauth/gmail/callback?code=abc&state=forged", follow_redirects=False)
    assert r.status_code in (302, 307) and "mailbox=expired" in r.headers["location"]


def test_status_admin_only(client, admin_headers):
    r = client.get("/gmail-reader", headers=admin_headers)
    assert r.status_code == 200 and "connected" in r.json()
