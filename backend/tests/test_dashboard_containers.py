"""Dashboard (client, 2026-09-29): containers and gross weight per month, by ETA and by
Cleared Date, split by port. Shipment counts don't matter; containers and weight do."""
from datetime import date
from types import SimpleNamespace

from app.routers.shipments import _containers, _tonnes, container_metrics


def ship(**kw):
    base = dict(container=None, gross_wt=None, eta=None, cleared_date=None, port=None, is_fully_cleared=False)
    return SimpleNamespace(**{**base, **kw})


def test_parsing_container_and_weight_text():
    assert _containers(ship(container="5")) == 5
    assert _containers(ship(container=" 10 ")) == 10
    assert _containers(ship(container="")) == 0 and _containers(ship(container="n/a")) == 0
    assert _tonnes(ship(gross_wt="124.270 MTS")) == 124.27
    assert _tonnes(ship(gross_wt="1,500 KGS")) == 1.5
    assert _tonnes(ship(gross_wt=None)) == 0


def test_monthly_containers_by_eta_and_cleared_split_by_port():
    today = date(2026, 9, 29)
    rows = [
        ship(container="5", gross_wt="100.000 MTS", eta=date(2026, 8, 3), port="INNSA1",
             cleared_date=date(2026, 8, 20), is_fully_cleared=True),
        ship(container="2", gross_wt="30.500 MTS", eta=date(2026, 8, 30), port="INMUN1"),
        ship(container="3", gross_wt="10 MTS", eta=date(2026, 9, 1), port="INNSA1",
             cleared_date=date(2026, 9, 2), is_fully_cleared=False),  # exception: not counted as cleared
        ship(container="9", eta=date(2024, 1, 1), port="INNSA1"),  # older than 12 months: left out
    ]
    r = container_metrics(rows, today)
    assert r["this_month"] == "2026-09" and r["last_month"] == "2026-08"
    aug = r["containers_by_eta_month"][0]
    assert aug["month"] == "2026-08" and aug["containers"] == 7 and aug["tonnes"] == 130.5
    assert aug["by_port"] == {"INNSA1": {"containers": 5, "tonnes": 100.0}, "INMUN1": {"containers": 2, "tonnes": 30.5}}
    assert [m["month"] for m in r["containers_by_eta_month"]] == ["2026-08", "2026-09"]
    assert r["containers_cleared_by_month"] == [
        {"month": "2026-08", "containers": 5, "tonnes": 100.0, "by_port": {"INNSA1": {"containers": 5, "tonnes": 100.0}}}
    ]


def test_dashboard_endpoint_has_the_container_figures(client, admin_headers):
    d = client.get("/shipments/summary/dashboard", headers=admin_headers).json()
    for k in ("containers_by_eta_month", "containers_cleared_by_month", "live_containers", "live_tonnes", "last_month"):
        assert k in d
