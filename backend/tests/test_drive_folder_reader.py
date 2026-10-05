"""Folder reader (client, 2026-10-05) with a fake Shared Drive: the PDFs in a shipment's
linked folder are recognised, attached and read; hand marks override the guess and are
kept across re-scans; ignoring an attached file is admin-only; Drive is only read."""
from app.storage.drive_client import FOLDER_MIME
from tests.conftest import be_pdf, cfs_pdf, make_pdf
from tests.test_drive_storage import _ship, fake_drive  # noqa: F401 — fixture

PDF = "application/pdf"


def _folder(fake, files):
    """A staff folder (not one the ERP made) holding `files`: {name: bytes}."""
    fake.files["job-folder"] = {"name": "JOB 77 - FLD0000001", "parents": ["shared"], "mime": FOLDER_MIME}
    ids = {}
    for name, data in files.items():
        fid = f"src-{len(ids) + 1}"
        fake.files[fid] = {"name": name, "parents": ["job-folder"], "mime": PDF, "data": data}
        ids[name] = fid

    def list_children(folder_id):
        return [{"id": i, "name": f["name"], "mimeType": f["mime"]} for i, f in fake.files.items()
                if folder_id in f["parents"]]
    fake.list_children = list_children
    return ids


def _linked(client, h, mbl):
    sid = _ship(client, h, mbl, client="Folder Co")
    r = client.patch(f"/shipments/{sid}", json={"drive_folder_id": "job-folder"}, headers=h)
    assert r.status_code == 200, r.text
    return sid


def test_folder_is_read_and_values_fill_in(client, admin_headers, fake_drive):
    ids = _folder(fake_drive, {
        "OOC copy.pdf": be_pdf(mawb="FLD0000001", extra=[(40, 30, "OOC COPY")]).read(),
        "scan0012.pdf": make_pdf([(40, 40, "PACKING LIST"), (40, 60, "Tyres 120 pcs")]).read(),
        "notes.pdf": make_pdf([(40, 40, "hello")]).read(),
    })
    sid = _linked(client, admin_headers, "FLD0000001")
    before = {k: dict(v) for k, v in fake_drive.files.items()}

    r = client.post(f"/shipments/{sid}/drive-folder/sync", headers=admin_headers)
    assert r.status_code == 200, r.text
    rows = {f["name"]: f for f in r.json()["files"]}
    assert rows["OOC copy.pdf"]["status"] == "added" and rows["OOC copy.pdf"]["document_type"] == "ooc_bill_of_entry"
    assert rows["scan0012.pdf"]["status"] == "added" and rows["scan0012.pdf"]["document_type"] == "packing_list"
    assert rows["notes.pdf"]["status"] == "unrecognised"
    assert r.json()["updated"]  # BE details filled in from the OOC copy
    assert client.get(f"/shipments/{sid}", headers=admin_headers).json()["be_no"]
    assert fake_drive.files == before  # Drive only read: nothing new, renamed or moved

    docs = client.get(f"/shipments/{sid}/documents", headers=admin_headers).json()
    assert {d["drive_file_id"] for d in docs} == {ids["OOC copy.pdf"], ids["scan0012.pdf"]}
    assert all(d["drive_picked"] for d in docs)

    again = client.post(f"/shipments/{sid}/drive-folder/sync", headers=admin_headers).json()["files"]
    assert {f["status"] for f in again} == {"attached", "unrecognised"}  # re-scan adds nothing twice
    assert len(client.get(f"/shipments/{sid}/documents", headers=admin_headers).json()) == 2


def test_marks_override_and_are_kept(client, admin_headers, fake_drive):
    ids = _folder(fake_drive, {
        "notes.pdf": make_pdf([(40, 40, "hello")]).read(),
        "CFS TAX INV 1.pdf": cfs_pdf(bl_no="FLD0000002").read(),
        "Packing list.pdf": make_pdf([(40, 40, "PACKING LIST")]).read(),
    })
    sid = _linked(client, admin_headers, "FLD0000002")
    base = f"/shipments/{sid}/drive-folder"
    # mark the unknown file, ignore the packing list before the first scan
    assert client.put(f"{base}/marks/{ids['notes.pdf']}", json={"document_type": "commercial_invoice"},
                      headers=admin_headers).status_code == 200
    client.put(f"{base}/marks/{ids['Packing list.pdf']}", json={"document_type": "ignore"}, headers=admin_headers)
    rows = {f["name"]: f for f in client.post(f"{base}/sync", headers=admin_headers).json()["files"]}
    assert rows["notes.pdf"]["document_type"] == "commercial_invoice"
    assert rows["Packing list.pdf"]["status"] == "ignored"
    assert rows["CFS TAX INV 1.pdf"]["document_type"] == "cfs_tax_invoice"

    # re-mark an attached file: re-filed as the new type, not added twice
    client.put(f"{base}/marks/{ids['notes.pdf']}", json={"document_type": "insurance"}, headers=admin_headers)
    client.post(f"{base}/sync", headers=admin_headers)
    docs = client.get(f"/shipments/{sid}/documents", headers=admin_headers).json()
    assert sorted(d["document_type"] for d in docs) == ["cfs_tax_invoice", "insurance"]

    # un-ignore: back to the reader's guess, attached on the next scan
    client.put(f"{base}/marks/{ids['Packing list.pdf']}", json={"document_type": None}, headers=admin_headers)
    client.post(f"{base}/sync", headers=admin_headers)
    listed = {f["name"]: f for f in client.get(f"{base}/files", headers=admin_headers).json()}
    assert listed["Packing list.pdf"]["status"] == "attached"
    assert listed["notes.pdf"]["mark"] == "insurance"

    # ignoring an attached file takes the document off (soft delete) and it stays off
    client.put(f"{base}/marks/{ids['Packing list.pdf']}", json={"document_type": "ignore"}, headers=admin_headers)
    client.post(f"{base}/sync", headers=admin_headers)
    assert "packing_list" not in {d["document_type"] for d in
                                  client.get(f"/shipments/{sid}/documents", headers=admin_headers).json()}


def test_removed_document_is_not_brought_back(client, admin_headers, fake_drive):
    ids = _folder(fake_drive, {"Packing list.pdf": make_pdf([(40, 40, "PACKING LIST")]).read()})
    sid = _linked(client, admin_headers, "FLD0000003")
    client.post(f"/shipments/{sid}/drive-folder/sync", headers=admin_headers)
    doc = client.get(f"/shipments/{sid}/documents", headers=admin_headers).json()[0]
    client.delete(f"/shipments/{sid}/documents/{doc['id']}", headers=admin_headers)
    rows = client.post(f"/shipments/{sid}/drive-folder/sync", headers=admin_headers).json()["files"]
    assert rows[0]["status"] == "removed"
    # marking it again brings it back
    client.put(f"/shipments/{sid}/drive-folder/marks/{ids['Packing list.pdf']}",
               json={"document_type": "packing_list"}, headers=admin_headers)
    rows = client.post(f"/shipments/{sid}/drive-folder/sync", headers=admin_headers).json()["files"]
    assert rows[0]["status"] == "added"


def test_one_per_shipment_types_are_not_doubled_by_the_reader(client, admin_headers, fake_drive):
    _folder(fake_drive, {"PL 1.pdf": make_pdf([(40, 40, "x")]).read(), "PL 2.pdf": make_pdf([(40, 40, "y")]).read()})
    sid = _linked(client, admin_headers, "FLD0000004")
    rows = {f["name"]: f["status"] for f in
            client.post(f"/shipments/{sid}/drive-folder/sync", headers=admin_headers).json()["files"]}
    assert rows == {"PL 1.pdf": "added", "PL 2.pdf": "duplicate"}


def test_needs_a_linked_folder_and_server_drive(client, admin_headers):
    sid = _ship(client, admin_headers, "FLD0000005")
    assert client.post(f"/shipments/{sid}/drive-folder/sync", headers=admin_headers).status_code == 400
