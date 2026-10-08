"""Launch Phase 1: soft delete + admin restore, issued invoices locked in the database,
invoicing admin-only. Runs on SQLite and on Postgres (TEST_DATABASE_URL)."""
import pytest
import sqlalchemy as sa

from app.core.database import engine
from tests.conftest import be_pdf, cfs_pdf


def _ship(client, h, mbl, **kw):
    r = client.post("/shipments", json={"mbl": mbl, **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload(client, h, sid, doc_type, pdf):
    r = client.post(f"/shipments/{sid}/documents", data={"document_type": doc_type},
                    files={"file": ("x.pdf", pdf, "application/pdf")}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def _deleted(client, h):
    return {(d["kind"], d["id"]): d for d in client.get("/deleted", headers=h).json()}


def _restore(client, h, kind, item_id):
    return client.post(f"/deleted/{kind}/{item_id}/restore", headers=h)


def _count(table, item_id):
    with engine.connect() as c:
        return c.execute(sa.text(f"SELECT count(*) FROM {table} WHERE id = :i"), {"i": item_id}).scalar()


def _issued_pair(client, h, mbl):
    """A shipment with one issued tax invoice and one draft reimbursement invoice."""
    client.post("/organizations", json={"name": f"Safety Traders {mbl}", "gstin": "27AAAAA0000A1Z5"}, headers=h)
    sid = _ship(client, h, mbl, consignee=f"Safety Traders {mbl}", container="1")
    client.patch(f"/shipments/{sid}", json={"duty_amount": "1000", "igst_amount": "0"}, headers=h)
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    invs = {i["kind"]: i for i in client.post(f"/proformas/{pid}/final-invoices", headers=h).json()}
    tax = client.post(f"/final-invoices/{invs['tax']['id']}/issue", headers=h).json()
    assert tax["status"] == "issued", tax
    return sid, pid, tax, invs["reimbursement"]


def test_shipment_delete_is_soft_and_restorable(client, admin_headers):
    h = admin_headers
    sid = _ship(client, h, "SAFE0000001")
    assert client.delete(f"/shipments/{sid}", headers=h).status_code == 204
    assert _count("shipments", sid) == 1  # still in the database
    assert client.get(f"/shipments/{sid}", headers=h).status_code == 404
    assert all(s["id"] != sid for s in client.get("/shipments", headers=h).json())
    d = _deleted(client, h)[("shipment", sid)]
    assert d["deleted_by"] and d["deleted_at"]
    assert _restore(client, h, "shipment", sid).status_code == 200
    assert client.get(f"/shipments/{sid}", headers=h).status_code == 200
    assert ("shipment", sid) not in _deleted(client, h)


def test_document_delete_restore_brings_totals_back(client, admin_headers):
    h = admin_headers
    sid = _ship(client, h, "SAFE0000002")
    doc = _upload(client, h, sid, "cfs_tax_invoice", cfs_pdf(before="1,000.00", gst="180.00", after="1,180.00"))
    total = lambda: client.get(f"/shipments/{sid}", headers=h).json()["cfs_amount_total"]  # noqa: E731
    assert float(total()) == 1180.0
    client.delete(f"/shipments/{sid}/documents/{doc['id']}", headers=h)
    assert _count("shipment_documents", doc["id"]) == 1
    assert total() is None
    assert all(x["id"] != doc["id"] for x in client.get(f"/shipments/{sid}/documents", headers=h).json())
    assert _restore(client, h, "document", doc["id"]).status_code == 200
    assert float(total()) == 1180.0
    assert any(x["id"] == doc["id"] for x in client.get(f"/shipments/{sid}/documents", headers=h).json())


def test_child_of_deleted_shipment_needs_the_shipment_first(client, admin_headers):
    h = admin_headers
    sid = _ship(client, h, "SAFE0000003")
    doc = _upload(client, h, sid, "assessed_bill_of_entry", be_pdf(mawb="SAFE0000003"))
    client.delete(f"/shipments/{sid}/documents/{doc['id']}", headers=h)
    client.delete(f"/shipments/{sid}", headers=h)
    r = _restore(client, h, "document", doc["id"])
    assert r.status_code == 400 and "shipment first" in r.json()["detail"]
    _restore(client, h, "shipment", sid)
    assert _restore(client, h, "document", doc["id"]).status_code == 200


def test_proforma_is_never_deleted(client, admin_headers):
    h = admin_headers
    sid = _ship(client, h, "SAFE0000004")
    p1 = client.post(f"/shipments/{sid}/proformas", headers=h).json()
    assert client.delete(f"/proformas/{p1['id']}", headers=h).status_code == 400
    assert [p["id"] for p in client.get(f"/shipments/{sid}/proformas", headers=h).json()] == [p1["id"]]


def test_final_invoice_draft_delete_and_restore(client, admin_headers):
    h = admin_headers
    sid, pid, tax, reim = _issued_pair(client, h, "SAFE0000005")
    assert client.delete(f"/final-invoices/{reim['id']}", headers=h).status_code == 204
    assert _count("final_invoices", reim["id"]) == 1
    assert {i["id"] for i in client.get(f"/shipments/{sid}/final-invoices", headers=h).json()} == {tax["id"]}
    assert _restore(client, h, "final_invoice", reim["id"]).status_code == 200
    # issued: only the admin may delete it (clearing trial invoices, client 2026-09-30) — still only hidden
    assert client.delete(f"/final-invoices/{tax['id']}", headers=h).status_code == 204
    assert _count("final_invoices", tax["id"]) == 1
    assert _restore(client, h, "final_invoice", tax["id"]).status_code == 200


def test_database_refuses_changes_to_issued_invoices(client, admin_headers):
    h = admin_headers
    _sid, _pid, tax, reim = _issued_pair(client, h, "SAFE0000006")
    i = tax["id"]

    def run(sql, **params):
        with engine.begin() as c:
            c.execute(sa.text(sql), {"i": i, **params})

    for sql in ("DELETE FROM final_invoices WHERE id = :i",
                "UPDATE final_invoices SET number = 'CL/999/26-27' WHERE id = :i",
                "UPDATE final_invoices SET remarks = 'changed' WHERE id = :i",
                "UPDATE final_invoices SET advance_received = 5 WHERE id = :i",
                "UPDATE final_invoices SET status = 'draft' WHERE id = :i",
                # hiding it (soft delete) is allowed, but not together with any other change
                "UPDATE final_invoices SET deleted_at = CURRENT_TIMESTAMP, remarks = 'x' WHERE id = :i"):
        with pytest.raises(sa.exc.DatabaseError):
            run(sql)
    with pytest.raises(sa.exc.DatabaseError):  # drafts can't be hard-deleted either
        run("DELETE FROM final_invoices WHERE id = :d", d=reim["id"])
    run("UPDATE final_invoices SET remarks = 'draft is editable' WHERE id = :d", d=reim["id"])
    run("UPDATE final_invoices SET irn = 'IRN1', ack_no = 'ACK1' WHERE id = :i")  # allowed

    r = client.post(f"/final-invoices/{i}/cancel", json={"reason": "wrong party"}, headers=h)
    assert r.status_code == 200
    with engine.connect() as c:
        row = c.execute(sa.text("SELECT status, cancel_reason, cancelled_at, cancelled_by_id FROM final_invoices "
                                "WHERE id = :i"), {"i": i}).one()
    assert row[0] == "cancelled" and row[1] == "wrong party" and row[2] is not None and row[3] is not None
    with pytest.raises(sa.exc.DatabaseError):  # cancelled: fully frozen
        run("UPDATE final_invoices SET irn = 'IRN2' WHERE id = :i")


def test_invoicing_is_admin_only_even_for_billing_users(client, admin_headers):
    h = admin_headers
    sid = _ship(client, h, "SAFE0000007")
    pid = client.post(f"/shipments/{sid}/proformas", headers=h).json()["id"]
    client.post("/auth/users", json={"email": "acct@example.com", "password": "y" * 12, "full_name": "Accounts",
                                     "role": "accountant", "can_access_billing": True}, headers=h)
    tok = client.post("/auth/login", data={"username": "acct@example.com", "password": "y" * 12}).json()["access_token"]
    u = {"Authorization": f"Bearer {tok}"}
    for url in (f"/shipments/{sid}/proformas", f"/proformas/{pid}/invoice", f"/proformas/{pid}/invoice.pdf",
                "/charge-master", "/licences", "/pricing-rules", f"/shipments/{sid}/final-invoices",
                "/invoice-counter", "/duty-challans", "/daily-updates", "/organizations", "/deleted"):
        assert client.get(url, headers=u).status_code == 403, url
    assert client.post(f"/shipments/{sid}/proformas", headers=u).status_code == 403
    assert client.delete(f"/shipments/{sid}", headers=u).status_code == 403
    assert client.get(f"/shipments/{sid}", headers=u).status_code == 200  # the tracker itself is fine


def test_tracker_import_does_not_bring_back_a_deleted_shipment(client, admin_headers):
    h = admin_headers
    sid = _ship(client, h, "SAFE0000008")
    client.delete(f"/shipments/{sid}", headers=h)
    csv = b"Job,MBL,Consignee\n,SAFE0000008,Someone\n"
    p = client.post("/tracker-import/preview", files={"file": ("t.csv", csv, "text/csv")}, headers=h).json()
    assert p["new"] == [] and any("SAFE0000008" in s and "deleted" in s for s in p["skipped"])
    assert all(m["shipment_id"] != sid for m in p["missing"])
