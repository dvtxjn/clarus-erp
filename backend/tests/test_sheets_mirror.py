"""The view-only Google Sheets copy of the tracker — with a fake sheet (never the real Google)."""
import pytest

from app import sheets_mirror
from app.core.database import SessionLocal


class FakeSheets:
    def __init__(self):
        self.tabs, self.writes = [], []

    def ensure_tab(self, title):
        self.tabs.append(title)

    def write(self, rng, rows):
        self.writes.append((rng, rows))


def test_link_parsing():
    sid = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789"
    assert sheets_mirror.sheet_id_from(f"https://docs.google.com/spreadsheets/d/{sid}/edit#gid=0") == sid
    assert sheets_mirror.sheet_id_from(sid) == sid
    assert sheets_mirror.sheet_id_from("https://example.com/x") is None


def test_refuses_deletes():
    c = sheets_mirror.SheetsClient("x" * 30, service_account={})
    for call in [("DELETE", ""), ("POST", "/values/A1:clear"),
                 ("POST", ":batchUpdate", {"requests": [{"deleteSheet": {"sheetId": 1}}]}),
                 ("POST", ":batchUpdate", {"requests": [{"deleteDimension": {}}]})]:
        kw = {"json": call[2]} if len(call) > 2 else {}
        with pytest.raises(sheets_mirror.SheetsError, match="never deletes"):
            c._req(call[0], call[1], **kw)


def test_mirror_writes_live_rows_and_blanks_leftovers(client, admin_headers):
    ids = []
    for mbl in ("MIRROR-1", "MIRROR-2"):
        r = client.post("/shipments", json={"mbl": mbl, "client": "ZZ Mirror"}, headers=admin_headers)
        ids.append(r.json()["id"])
    db = SessionLocal()
    try:
        from app.models.settings import AppSetting

        db.merge(AppSetting(key=sheets_mirror.KEY, value={"sheet_id": "s" * 30}))
        db.commit()
        fake = FakeSheets()
        st = sheets_mirror.mirror(db, fake)
        assert st["last_error"] is None
        rng, rows = fake.writes[0]
        assert rows[0][:2] == ["Client", "Job"]
        assert "Assessable" not in " ".join(rows[0])  # no invoice figures
        mbls = [r[3] for r in rows]
        assert "MIRROR-1" in mbls and "MIRROR-2" in mbls
        first = st["rows"]

        # one shipment archived: the sheet keeps its size, the leftover row is written blank
        from app.models.shipment import Shipment

        db.get(Shipment, ids[1]).is_archived = True
        db.commit()
        fake2 = FakeSheets()
        sheets_mirror.mirror(db, fake2)
        rng2, rows2 = fake2.writes[0]
        assert len(rows2) == first and rows2[-1] == [""] * len(rows2[-1])
        assert "MIRROR-2" not in [r[3] for r in rows2]
    finally:
        db.close()


def test_settings_api_admin_only(client, admin_headers):
    r = client.get("/sheets-mirror", headers=admin_headers)
    assert r.status_code == 200 and r.json()["every_minutes"] == 15
    r = client.put("/sheets-mirror", json={"link": "not a link"}, headers=admin_headers)
    assert r.status_code == 422
