"""Launch Phase 7 with a fake Shared Drive: documents and generated PDFs are saved in the
right folders, folders are created once, nothing outside the roots is touched, a Drive
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

ROOTS = {"DRIVE_ROOT_FOLDER_ID": "root-docs", "DRIVE_INVOICES_FOLDER_ID": "root-inv", "DRIVE_BACKUPS_FOLDER_ID": "root-bak"}


class FakeDrive(DriveClient):
    """In-memory Shared Drive. Only the network layer is fake: the guard (check_inside)
    and the no-delete refusal in _req are the real ones."""

    def __init__(self):
        super().__init__(ROOTS.values(), service_account={"client_email": "x", "private_key": "x"})
        self.files = {"root-docs": {"name": "Documents", "parents": ["shared"], "mime": FOLDER_MIME},
                      "root-inv": {"name": "Invoices", "parents": ["shared"], "mime": FOLDER_MIME},
                      "root-bak": {"name": "Backups", "parents": ["shared"], "mime": FOLDER_MIME},
                      "shared": {"name": "Clarus ERP", "parents": [], "mime": FOLDER_MIME},
                      "elsewhere": {"name": "Someone's folder", "parents": ["my-drive"], "mime": FOLDER_MIME},
                      "my-drive": {"name": "My Drive", "parents": [], "mime": FOLDER_MIME}}
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

    def upload(self, parent_id, name, data, mime="application/pdf"):
        if self.fail:
            raise DriveError("Drive is down")
        self.check_inside(parent_id)
        with self.lock:
            fid = self._new_id()
            self.files[fid] = {"name": name, "parents": [parent_id], "mime": mime, "data": data}
        return {"id": fid, "webViewLink": f"https://drive.google.com/file/d/{fid}/view"}

    def rename(self, file_id, new_name):
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


def _ship(tc, h, mbl, **kw):
    return tc.post("/shipments", json={"mbl": mbl, **kw}, headers=h).json()["id"]


def _upload(client, h, sid, doc_type, pdf):
    r = client.post(f"/shipments/{sid}/documents", data={"document_type": doc_type},
                    files={"file": ("x.pdf", pdf, "application/pdf")}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_upload_lands_in_client_and_mbl_folder(client, admin_headers, fake_drive):
    sid = _ship(client, admin_headers, "DRV0000001", client="Sunrise Tyres")
    doc = _upload(client, admin_headers, sid, "cfs_tax_invoice", cfs_pdf(bl_no="DRV0000001"))
    assert doc["drive_file_id"] and not doc["drive_sync_pending"] and doc["drive_link"]
    f = fake_drive.files[doc["drive_file_id"]]
    assert fake_drive.path_of(doc["drive_file_id"]) == f"Documents/Sunrise Tyres/DRV0000001/{doc['generated_filename']}"
    assert f["data"][:4] == b"%PDF"


def test_folders_are_created_once(client, admin_headers, fake_drive):
    sids = [_ship(client, admin_headers, "DRV0000002", client="New Client Ltd") for _ in range(2)]
    # the same client + MBL twice, uploaded at the same moment
    results = [None, None]
    gate = threading.Barrier(2)

    def up(i):
        from fastapi.testclient import TestClient
        from app.main import app
        c = TestClient(app)
        gate.wait()
        results[i] = c.post(f"/shipments/{sids[i]}/documents", data={"document_type": "cfs_tax_invoice"},
                            files={"file": ("x.pdf", cfs_pdf(), "application/pdf")}, headers=admin_headers)

    threads = [threading.Thread(target=up, args=(i,)) for i in range(2)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert all(r.status_code == 201 for r in results), [r.text for r in results]
    folders = [i for i, f in fake_drive.files.items() if f["mime"] == FOLDER_MIME and f["name"] == "New Client Ltd"]
    assert len(folders) == 1
    mbl_folders = [i for i, f in fake_drive.files.items() if f["name"] == "DRV0000002" and f["mime"] == FOLDER_MIME]
    assert len(mbl_folders) == 1


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


def test_sent_proforma_and_issued_invoice_pdfs_are_kept(client, admin_headers, fake_drive):
    h = admin_headers
    client.post("/organizations", json={"name": "Drive Pdf Traders", "gstin": "27AAAAA0000A1Z5"}, headers=h)
    sid = _ship(client, h, "DRV0000006", consignee="Drive Pdf Traders", container="1")
    client.patch(f"/shipments/{sid}", json={"duty_amount": "1000", "igst_amount": "0"}, headers=h)
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    invs = {i["kind"]: i for i in client.post(f"/proformas/{pid}/final-invoices", headers=h).json()}
    assert client.patch(f"/proformas/{pid}", json={"status": "sent"}, headers=h).status_code == 200
    tax = client.post(f"/final-invoices/{invs['tax']['id']}/issue", headers=h).json()
    with SessionLocal() as db:
        p = db.query(StoredFile).filter_by(kind="proforma_pdf", ref_id=pid).one()
        i = db.query(StoredFile).filter_by(kind="final_invoice_pdf", ref_id=tax["id"]).one()
    assert fake_drive.path_of(p.drive_file_id).startswith("Invoices/Proformas/") and p.name.endswith(".pdf")
    assert fake_drive.path_of(i.drive_file_id) == f"Invoices/{tax['number'].split('/')[-1]}/{i.name}" and tax["number"].replace("/", "-") in i.name
    assert Path(p.local_path).read_bytes()[:4] == b"%PDF" and Path(i.local_path).exists()


def test_local_backend_still_keeps_generated_pdfs(client, admin_headers):
    assert storage.drive() is None
    sid = _ship(client, admin_headers, "DRV0000007")
    pid = client.post(f"/shipments/{sid}/proformas", headers=admin_headers).json()["id"]
    client.patch(f"/proformas/{pid}", json={"status": "sent"}, headers=admin_headers)
    with SessionLocal() as db:
        sf = db.query(StoredFile).filter_by(kind="proforma_pdf", ref_id=pid).one()
    assert Path(sf.local_path).exists() and sf.drive_file_id is None and not sf.drive_sync_pending
