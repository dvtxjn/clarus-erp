"""Nhava Sheva: we usually pay the CFS (client, 2026-10-09) — "CFS paid by us" by default there, and the
CFS invoice is flagged until it's attached. Mundra / Delhi: not by default."""
from datetime import date, timedelta

from app import alerts
from app.core.enums import DocumentType as D
from tests.test_alerts import TODAY, ship


def _cfs(**kw):
    return ship(**{"port": "INNSA1", "cfs_paid_by_us": True, "ooc": True, "ooc_date": TODAY - timedelta(days=3),
                   "cfs_inv_received": False, **kw})


def test_cfs_invoice_flagged_after_ooc_until_attached():
    a = alerts.cfs_invoice_alert(_cfs(), set(), TODAY)
    assert a["kind"] == "cfs_invoice" and a["severity"] == "urgent" and "not attached" in a["text"]
    assert alerts.cfs_invoice_alert(_cfs(), {D.CFS_TAX_INVOICE}, TODAY) is None


def test_cfs_invoice_not_flagged_before_ooc_or_when_client_pays():
    assert alerts.cfs_invoice_alert(_cfs(ooc=False, ooc_date=None), set(), TODAY) is None
    assert alerts.cfs_invoice_alert(_cfs(cfs_paid_by_us=False), set(), TODAY) is None


def test_received_but_not_attached_says_so():
    a = alerts.cfs_invoice_alert(_cfs(cfs_inv_received=True), set(), TODAY)
    assert "received but not attached" in a["text"]


def _add(client, h, mbl, **kw):
    r = client.post("/shipments", json={"mbl": mbl, "client": "CFS Marker Co", **kw}, headers=h)
    assert r.status_code == 201, r.text
    return r.json()


def test_nhava_sheva_defaults_to_cfs_paid_by_us(client, admin_headers):
    h = admin_headers
    nsa, mun = _add(client, h, "CFSDEF1", port="INNSA1"), _add(client, h, "CFSDEF2", port="INMUN1")
    assert nsa["cfs_paid_by_us"] and nsa["tds_on_cfs"] and not mun["cfs_paid_by_us"]
    # told otherwise on the form: stays off
    assert not _add(client, h, "CFSDEF3", port="INNSA1", cfs_paid_by_us=False)["cfs_paid_by_us"]


def test_port_set_later_switches_it_on_once(client, admin_headers):
    h = admin_headers
    s = _add(client, h, "CFSDEF4")
    assert not s["cfs_paid_by_us"]
    s = client.patch(f"/shipments/{s['id']}", json={"port": "INNSA1"}, headers=h).json()
    assert s["cfs_paid_by_us"]
    # switched off by hand (the usual rule doesn't fit this job): another edit doesn't turn it back on
    client.patch(f"/shipments/{s['id']}", json={"cfs_paid_by_us": False}, headers=h)
    s = client.patch(f"/shipments/{s['id']}", json={"remarks": "client pays CFS", "port": "INNSA1"}, headers=h).json()
    assert not s["cfs_paid_by_us"]


def test_cleared_job_is_left_alone(client, admin_headers):
    s = _add(client, admin_headers, "CFSDEF5", cleared_date=str(date(2026, 9, 1)))
    s = client.patch(f"/shipments/{s['id']}", json={"port": "INNSA1"}, headers=admin_headers).json()
    assert not s["cfs_paid_by_us"]
