"""Launch Phase 7 with a fake Shared Drive: documents are saved only into the shipment's linked folder
(or one picked at save time) and the ERP never makes folders for them; generated PDFs keep their folders; nothing outside the roots is touched, a Drive
outage never loses a file, and nothing is ever deleted (client rule)."""
import os
import threading
from pathlib import Path

import pytest

from app import storage
from app.core.database import SessionLocal
from app.models.document import ShipmentDocument
from app.models.storage import DriveFolder, StoredFile
from app.storage.drive_client import API, DriveClient, DriveError, FOLDER_MIME, OutsideRoot
from tests.conftest import be_pdf, cfs_pdf

ROOTS = {"DRIVE_ROOT_FOLDER_ID": "root-docs", "DRIVE_INVOICES_FOLDER_ID": "root-inv", "DRIVE_BACKUPS_FOLDER_ID": "root-bak",
         "DRIVE_ERP_ROOT_ID": "root-erp"}


class FakeDrive(DriveClient):
    """In-memory Shared Drive. Only the network layer is fake: the guard (check_inside)
    and the no-delete refusal in _req are the real ones."""

    def __init__(self):
        super().__init__(ROOTS.values(), service_account={"client_email": "x", "private_key": "x"})
        self.files = {"root-docs": {"name": "Documents", "parents": ["shared"], "mime": FOLDER_MIME},
                      "root-inv": {"name": "Invoices", "parents": ["shared"], "mime": FOLDER_MIME},
                      "root-bak": {"name": "Backups", "parents": ["shared"], "mime": FOLDER_MIME},
                      "shared": {"name": "CLARUS ERP - System", "parents": [], "mime": FOLDER_MIME},
                      "root-erp": {"name": "CLARUS ERP", "parents": [], "mime": FOLDER_MIME},
                      "elsewhere": {"name": "Someone's folder", "parents": ["my-drive"], "mime": FOLDER_MIME},
                      "my-drive": {"name": "My Drive", "parents": [], "mime": FOLDER_MIME},
                      "shipFolder01": {"name": "SUNRISE / DRV0000001", "parents": ["my-drive"], "mime": FOLDER_MIME},
                      "otherFolder1": {"name": "Other", "parents": ["my-drive"], "mime": FOLDER_MIME}}
        self.fail = False
        self.lock = threading.Lock()
        self.n = 0

    def _new_id(self):
        self.n += 1
        return f"f{self.n}"

    def _req(self, method, url, **kw):  # only reached for the guard's parent lookups
        if method.upper() == "DELETE" or "trashed" in str(kw.get("json") or {}):
            raise DriveError("Refused: the ERP never deletes or trashes anything in Google Drive")
        fid = url.rsplit("/", 1)[-1]
        meta = {"id": fid, "parents": self.files[fid]["parents"]}

        class R:
            def json(self_inner):
                return meta
        return R()

    def get(self, file_id, fields="id,name,parents"):
        f = self.files[file_id]
        return {"id": file_id, "name": f["name"], "parents": f["parents"]}

    def find_folder(self, parent_id, name):
        with self.lock:
            return next((i for i, f in self.files.items()
                         if f["mime"] == FOLDER_MIME and f["name"] == name and parent_id in f["parents"]), None)

    def create_folder(self, parent_id, name):
        self.check_inside(parent_id)
        with self.lock:
            fid = self._new_id()
            self.files[fid] = {"name": name, "parents": [parent_id], "mime": FOLDER_MIME}
        self._inside.add(fid)
        return fid

    def upload(self, parent_id, name, data, mime="application/pdf", linked=False):
        if self.fail:
            raise DriveError("Drive is down")
        if not linked:
            self.check_inside(parent_id)
        with self.lock:
            fid = self._new_id()
            self.files[fid] = {"name": name, "parents": [parent_id], "mime": mime, "data": data}
        return {"id": fid, "webViewLink": f"https://drive.google.com/file/d/{fid}/view"}

    def rename(self, file_id, new_name, linked=False):
        if not linked:
            self.check_inside(self.files[file_id]["parents"][0])
        self.files[file_id]["name"] = new_name

    def download(self, file_id):
        return self.files[file_id]["data"]

    def path_of(self, fid):
        parts = []
        while fid in self.files and fid != "shared":
            parts.append(self.files[fid]["name"])
            fid = (self.files[fid]["parents"] or [None])[0]
        return "/".join(reversed(parts))


@pytest.fixture
def fake_drive(monkeypatch, client):
    for k, v in {**ROOTS, "STORAGE_BACKEND": "drive"}.items():
        monkeypatch.setenv(k, v)
    fake = FakeDrive()
    storage.set_drive_client(fake)
    with SessionLocal() as db:  # folder ids belong to this fake drive only
        db.query(DriveFolder).delete()
        db.commit()
    yield fake
    storage.set_drive_client(None)


def _ship(tc, h, mbl, folder="shipFolder01", **kw):
    """A shipment linked to its Drive folder (staff's own folder, outside the ERP's roots)."""
    return tc.post("/shipments", json={"mbl": mbl, "drive_folder_id": folder, **kw}, headers=h).json()["id"]


def _upload(client, h, sid, doc_type, pdf, **data):
    r = client.post(f"/shipments/{sid}/documents", data={"document_type": doc_type, **data},
                    files={"file": ("x.pdf", pdf, "application/pdf")}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _folders(fake):
    return {i for i, f in fake.files.items() if f["mime"] == FOLDER_MIME}


def test_upload_goes_into_the_linked_folder_only(client, admin_headers, fake_drive):
    before = _folders(fake_drive)
    sid = _ship(client, admin_headers, "DRV0000001", client="Sunrise Tyres")
    doc = _upload(client, admin_headers, sid, "cfs_tax_invoice", cfs_pdf(bl_no="DRV0000001"))
    assert doc["drive_file_id"] and not doc["drive_sync_pending"] and doc["drive_link"]
    f = fake_drive.files[doc["drive_file_id"]]
    assert f["parents"] == ["shipFolder01"] and f["name"] == doc["generated_filename"] and f["data"][:4] == b"%PDF"
    # another folder picked at save time
    doc = _upload(client, admin_headers, sid, "cfs_tax_invoice", cfs_pdf(), save_to_folder_id="otherFolder1")
    assert fake_drive.files[doc["drive_file_id"]]["parents"] == ["otherFolder1"] and doc["drive_folder_id"] == "otherFolder1"
    assert _folders(fake_drive) == before  # no folder made, ever


def test_unlinked_shipment_waits_for_its_folder(client, admin_headers, fake_drive):
    before = _folders(fake_drive)
    sid = _ship(client, admin_headers, "DRV0000002", folder=None, client="New Client Ltd")
    doc = _upload(client, admin_headers, sid, "cfs_tax_invoice", cfs_pdf())
    assert doc["drive_sync_pending"] and "No Drive folder linked" in doc["drive_error"]
    buffer = doc["drive_file_id"]  # a buffer copy, flat in System Documents (the disk is wiped on redeploy)
    assert fake_drive.files[buffer]["parents"] == ["root-docs"]
    files_before = len(fake_drive.files)
    assert storage.retry_pending() >= 1 and _folders(fake_drive) == before
    assert len(fake_drive.files) == files_before  # buffered once, not on every retry
    with SessionLocal() as db:
        Path(db.get(ShipmentDocument, doc["id"]).file_path).unlink()  # redeploy wiped the disk
    client.patch(f"/shipments/{sid}", json={"drive_folder_id": "shipFolder01"}, headers=admin_headers)
    storage.retry_pending()
    with SessionLocal() as db:
        d = db.get(ShipmentDocument, doc["id"])
        assert not d.drive_sync_pending and fake_drive.files[d.drive_file_id]["parents"] == ["shipFolder01"]
        assert d.drive_file_id != buffer
    bad = client.post(f"/shipments/{sid}/documents", data={"document_type": "cfs_tax_invoice", "save_to_folder_id": "../x"},
                      files={"file": ("x.pdf", cfs_pdf(), "application/pdf")}, headers=admin_headers)
    assert bad.status_code == 422


def test_writes_outside_the_roots_are_refused(fake_drive):
    with pytest.raises(OutsideRoot):
        fake_drive.upload("elsewhere", "x.pdf", b"%PDF")
    with pytest.raises(OutsideRoot):
        fake_drive.create_folder("my-drive", "sneaky")
    fake_drive.upload("root-docs", "ok.pdf", b"%PDF")  # inside: fine


def test_nothing_is_ever_deleted(client, admin_headers, fake_drive):
    # the client itself refuses deletes and trashing, before any network call
    real = DriveClient(ROOTS.values(), service_account={"client_email": "x", "private_key": "x"})
    with pytest.raises(DriveError, match="never deletes"):
        real._req("DELETE", f"{API}/files/abc")
    with pytest.raises(DriveError, match="never deletes"):
        real._req("PATCH", f"{API}/files/abc", json={"trashed": True})
    assert not any(hasattr(DriveClient, m) for m in ("delete", "trash", "move", "empty_trash"))
    # Remove document: the Drive file stays, only renamed; restore renames it back
    sid = _ship(client, admin_headers, "DRV0000003", client="Keep Co")
    doc = _upload(client, admin_headers, sid, "cfs_tax_invoice", cfs_pdf())
    client.delete(f"/shipments/{sid}/documents/{doc['id']}", headers=admin_headers)
    f = fake_drive.files[doc["drive_file_id"]]
    assert f["name"] == f"[removed] {doc['generated_filename']}" and f["data"][:4] == b"%PDF"
    client.post(f"/deleted/document/{doc['id']}/restore", headers=admin_headers)
    assert fake_drive.files[doc["drive_file_id"]]["name"] == doc["generated_filename"]


def test_drive_outage_keeps_the_file_and_retries(client, admin_headers, fake_drive):
    fake_drive.fail = True
    sid = _ship(client, admin_headers, "DRV0000004", client="Retry Co")
    doc = _upload(client, admin_headers, sid, "cfs_tax_invoice", cfs_pdf())
    assert doc["drive_sync_pending"] and "down" in doc["drive_error"] and os.path.exists(doc["file_path"])
    assert doc["extraction"]["fields"]  # the upload itself worked fully
    fake_drive.fail = False
    assert storage.retry_pending() == 0
    with SessionLocal() as db:
        d = db.get(ShipmentDocument, doc["id"])
        assert d.drive_file_id and not d.drive_sync_pending and d.drive_error is None


def test_missing_local_file_comes_back_from_drive(client, admin_headers, fake_drive):
    sid = _ship(client, admin_headers, "DRV0000005", client="Redeploy Co")
    doc = _upload(client, admin_headers, sid, "assessed_bill_of_entry", be_pdf(mawb="DRV0000005"))
    Path(doc["file_path"]).unlink()  # like a redeploy wiping the server's disk
    r = client.get(f"/shipments/{sid}/documents/{doc['id']}/file", headers=admin_headers)
    assert r.status_code == 200 and r.content[:4] == b"%PDF"
    assert client.post(f"/shipments/{sid}/documents/{doc['id']}/reread", headers=admin_headers).status_code == 200


def _issue(client, h, sid):
    client.patch(f"/shipments/{sid}", json={"duty_amount": "1000", "igst_amount": "0"}, headers=h)
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    invs = {i["kind"]: i for i in client.post(f"/proformas/{pid}/final-invoices", headers=h).json()}
    assert client.patch(f"/proformas/{pid}", json={"status": "sent"}, headers=h).status_code == 200
    tax = client.post(f"/final-invoices/{invs['tax']['id']}/issue", headers=h).json()
    with SessionLocal() as db:
        return (db.query(StoredFile).filter_by(kind="proforma_pdf", ref_id=pid).one(),
                db.query(StoredFile).filter_by(kind="final_invoice_pdf", ref_id=tax["id"]).one(), tax)


def test_invoice_pdfs_go_into_the_shipment_folder(client, admin_headers, fake_drive):
    """Client, 2026-10-05: proforma and final invoice PDFs are saved in the shipment's linked folder."""
    h = admin_headers
    client.post("/organizations", json={"name": "Drive Pdf Traders", "gstin": "27AAAAA0000A1Z5"}, headers=h)
    before = _folders(fake_drive)
    p, i, tax = _issue(client, h, _ship(client, h, "DRV0000006", consignee="Drive Pdf Traders", container="1"))
    assert fake_drive.files[p.drive_file_id]["parents"] == ["shipFolder01"] and p.name.endswith(".pdf")
    assert fake_drive.files[i.drive_file_id]["parents"] == ["shipFolder01"] and tax["number"].replace("/", "-") in i.name
    assert Path(p.local_path).read_bytes()[:4] == b"%PDF" and Path(i.local_path).exists()
    assert _folders(fake_drive) == before  # no folder made


def test_unlinked_invoices_go_to_proforma_invoices_by_client(client, admin_headers, fake_drive):
    """No linked folder: CLARUS ERP/Proforma Invoices/<client>, one folder per client however many invoices."""
    h = admin_headers
    client.post("/organizations", json={"name": "Drive Pdf Traders", "gstin": "27AAAAA0000A1Z5"}, headers=h)
    files = []
    for mbl in ("DRV0000016", "DRV0000017"):
        sid = _ship(client, h, mbl, folder=None, consignee="Drive Pdf Traders", container="1", client="Unlinked Co")
        files += _issue(client, h, sid)[:2]
    parents = {fake_drive.files[f.drive_file_id]["parents"][0] for f in files}
    assert len(parents) == 1
    folder = fake_drive.files[parents.pop()]
    assert folder["name"] == "Unlinked Co"
    assert fake_drive.files[folder["parents"][0]]["name"] == "Proforma Invoices"
    assert fake_drive.files[folder["parents"][0]]["parents"] == ["root-erp"]


def test_local_backend_still_keeps_generated_pdfs(client, admin_headers):
    assert storage.drive() is None
    sid = _ship(client, admin_headers, "DRV0000007")
    pid = client.post(f"/shipments/{sid}/proformas", headers=admin_headers).json()["id"]
    client.patch(f"/proformas/{pid}", json={"status": "sent"}, headers=admin_headers)
    with SessionLocal() as db:
        sf = db.query(StoredFile).filter_by(kind="proforma_pdf", ref_id=pid).one()
    assert Path(sf.local_path).exists() and sf.drive_file_id is None and not sf.drive_sync_pending


def test_file_picked_from_the_shipment_folder_is_linked_not_copied(client, admin_headers, fake_drive, monkeypatch):
    from app.integrations import google_drive

    async def fake_fetch(file_id, token):
        return google_drive.DriveFile(file_id=file_id, name="OOC copy.pdf", content=be_pdf(mawb="DRV0000008").read(),
                                      web_link=f"https://drive.google.com/file/d/{file_id}/view")
    monkeypatch.setattr(google_drive, "fetch_drive_pdf", fake_fetch)
    sid = _ship(client, admin_headers, "DRV0000008", client="Staff Folder Co")
    before = len(fake_drive.files)
    r = client.post(f"/shipments/{sid}/documents/from-drive", headers=admin_headers,
                    json={"document_type": "assessed_bill_of_entry", "file_id": "staff-file-1", "access_token": "t"})
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["drive_picked"] and doc["drive_file_id"] == "staff-file-1" and not doc["drive_sync_pending"]
    assert len(fake_drive.files) == before  # no second copy, no ERP folders made
    assert doc["extraction"]["fields"]  # still read like an upload
    client.delete(f"/shipments/{sid}/documents/{doc['id']}", headers=admin_headers)  # removing never renames theirs
    assert len(fake_drive.files) == before


def test_file_from_the_folder_read_by_the_server_without_a_google_token(client, admin_headers, fake_drive):
    """No Google sign-in in the browser: the server's own Drive reads the picked file."""
    fake_drive.files["staff-file-2"] = {"name": "OOC copy.pdf", "parents": ["shipFolder01"], "mime": "application/pdf",
                                        "data": be_pdf(mawb="DRV0000009").read()}
    fake_drive.files["staff-xls-1"] = {"name": "sheet.xlsx", "parents": ["shipFolder01"], "mime": "application/vnd.ms-excel",
                                       "data": b"x"}
    real_get = fake_drive.get
    fake_drive.get = lambda fid, fields="": {**real_get(fid), "mimeType": fake_drive.files[fid]["mime"],
                                             "size": str(len(fake_drive.files[fid].get("data", b"")))}
    sid = _ship(client, admin_headers, "DRV0000009", client="Server Pick Co")
    before = dict(fake_drive.files)
    r = client.post(f"/shipments/{sid}/documents/from-drive", headers=admin_headers,
                    json={"document_type": "assessed_bill_of_entry", "file_id": "staff-file-2"})
    assert r.status_code == 201, r.text
    assert r.json()["drive_picked"] and r.json()["drive_file_id"] == "staff-file-2"
    assert fake_drive.files == before  # only read
    bad = client.post(f"/shipments/{sid}/documents/from-drive", headers=admin_headers,
                      json={"document_type": "packing_list", "file_id": "staff-xls-1"})
    assert bad.status_code == 400 and "isn't a PDF" in bad.json()["detail"]


def test_folder_search_and_status_use_the_server_drive(client, admin_headers, fake_drive, monkeypatch):
    seen = {}

    def search(terms, limit=25):
        seen["terms"] = terms
        return [{"id": "shipFolder01", "name": "SUNRISE / DRV0000001"}]
    monkeypatch.setattr(fake_drive, "search_folders", search)
    assert client.get("/drive/status", headers=admin_headers).json() == {"server": True}
    r = client.get("/drive/folders", params={"q": ["DRV0000001", "12", "JOB 129"]}, headers=admin_headers)
    assert r.status_code == 200, r.text
    assert r.json() == [{"id": "shipFolder01", "name": "SUNRISE / DRV0000001",
                         "url": "https://drive.google.com/drive/folders/shipFolder01"}]
    assert seen["terms"] == ["DRV0000001", "JOB 129"]  # too-short terms dropped, phrases kept whole
    fake_drive.files["pdf-a"] = {"name": "BL.pdf", "parents": ["shipFolder01"], "mime": "application/pdf", "data": b""}
    fake_drive.list_children = lambda fid: [{"id": i, "name": f["name"], "mimeType": f["mime"]}
                                            for i, f in fake_drive.files.items() if fid in f["parents"]]
    assert client.get("/drive/folders/shipFolder01/pdfs", headers=admin_headers).json() == [{"id": "pdf-a", "name": "BL.pdf"}]


def test_drive_status_without_server_drive(client, admin_headers):
    assert client.get("/drive/status", headers=admin_headers).json() == {"server": False}
    assert client.get("/drive/folders", params={"q": "abc"}).status_code == 401
    assert client.get("/drive/folders", params={"q": "abc"}, headers=admin_headers).status_code == 400


def test_big_upload_goes_in_resumable_pieces_and_survives_a_stalled_piece(monkeypatch):
    """Backups are bigger than one request can carry in time: pieces, and a timed-out piece is resumed."""
    import httpx
    from app.storage import drive_client as dc

    monkeypatch.setattr(dc, "CHUNK", 256 * 1024)
    monkeypatch.setattr(dc.time, "sleep", lambda s: None)
    data = os.urandom(dc.ONE_SHOT_MAX + 300 * 1024)
    got, stalled = bytearray(), []

    def handler(req: httpx.Request):
        if req.method == "DELETE":
            raise AssertionError("no deletes")
        if req.method == "POST":
            assert req.url.params["uploadType"] == "resumable"
            assert req.headers["x-upload-content-length"] == str(len(data))
            return httpx.Response(200, headers={"Location": "https://upload.example/session1"})
        rng = req.headers["content-range"]
        if rng.startswith("bytes */"):  # status query after the stall
            return httpx.Response(308, headers={"Range": f"bytes=0-{len(got) - 1}"} if got else {})
        start = int(rng.split(" ")[1].split("-")[0])
        if start == 512 * 1024 and not stalled:
            stalled.append(1)
            raise httpx.ReadTimeout("The read operation timed out", request=req)
        assert start == len(got)
        got.extend(req.content)
        if len(got) == len(data):
            return httpx.Response(200, json={"id": "big1", "size": str(len(data))})
        return httpx.Response(308, headers={"Range": f"bytes=0-{len(got) - 1}"})

    c = DriveClient(ROOTS.values(), service_account={"client_email": "x", "private_key": "x"})
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(c, "_auth", lambda: {"Authorization": "Bearer t"})
    meta = c.upload("root-bak", "b.enc", data, "application/octet-stream", linked=True)
    assert meta["id"] == "big1" and bytes(got) == data and stalled
