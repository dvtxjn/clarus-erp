"""The view-only Google Sheets copy of the tracker — with a fake sheet (never the real Google)."""
import pytest

from app import sheets_mirror
from app.core.database import SessionLocal


class FakeSheets:
    def __init__(self):
        self.tabs, self.writes, self.batches = [], [], []

    def ensure_tab(self, title):
        self.tabs.append(title)
        return 7

    def write(self, rng, rows):
        self.writes.append((rng, rows))

    def batch(self, requests):
        self.batches.append(requests)


def grid_of(fake):
    """The written grid as plain values (tick boxes -> True/False)."""
    cells = fake.batches[0][0]["updateCells"]["rows"]
    out = []
    for r in cells:
        row = []
        for c in r["values"]:
            v = c.get("userEnteredValue", {})
            row.append(v.get("boolValue", v.get("stringValue", "")))
        out.append(row)
    return out


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
        rows = grid_of(fake)
        assert rows[0][:3] == ["Job", "mbl", "be description"] and "duty paid?" in rows[0]  # the office tracker's columns
        assert "Assessable" not in " ".join(map(str, rows[0]))  # no invoice figures
        mbls = [r[1] for r in rows]
        assert "MIRROR-1" in mbls and "MIRROR-2" in mbls
        duty = rows[0].index("duty paid?")
        assert all(isinstance(r[duty], bool) for r in rows[1:] if r[1])  # tick boxes
        req = fake.batches[0]
        assert req[1]["updateSheetProperties"]["properties"]["gridProperties"]["frozenColumnCount"] == 2
        first = st["rows"]

        # one shipment archived: the sheet keeps its size, the leftover row is written blank
        from app.models.shipment import Shipment

        db.get(Shipment, ids[1]).is_archived = True
        db.commit()
        fake2 = FakeSheets()
        sheets_mirror.mirror(db, fake2)
        rows2 = grid_of(fake2)
        assert len(rows2) == first and all(v == "" for v in rows2[-1])
        assert "MIRROR-2" not in [r[1] for r in rows2]
    finally:
        db.close()


def test_settings_api_admin_only(client, admin_headers):
    r = client.get("/sheets-mirror", headers=admin_headers)
    assert r.status_code == 200 and r.json()["every_minutes"] == 15
    r = client.put("/sheets-mirror", json={"link": "not a link"}, headers=admin_headers)
    assert r.status_code == 422
