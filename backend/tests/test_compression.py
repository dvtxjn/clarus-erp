"""Responses are gzipped for slow connections (client, 2026-10-09) — except the live-updates stream."""
from app.core.web import DIST


def test_api_json_is_gzipped(client, admin_headers):
    r = client.get("/shipments", headers={**admin_headers, "Accept-Encoding": "gzip"})
    assert r.status_code == 200
    if len(r.content) >= 1024:
        assert r.headers.get("content-encoding") == "gzip"


def test_app_files_are_gzipped_and_cached(client):
    js = next(DIST.glob("assets/index-*.js"), None) if DIST.is_dir() else None
    if js is None:
        return  # frontend not built here
    r = client.get(f"/assets/{js.name}", headers={"Accept-Encoding": "gzip"})
    assert r.headers.get("content-encoding") == "gzip"
    assert "immutable" in r.headers["cache-control"]


def test_live_stream_is_not_compressed(client, admin_headers, monkeypatch):
    from app.routers import realtime as rt
    monkeypatch.setattr(rt, "STREAM_MAX_SECONDS", 0)
    with client.stream("GET", "/realtime/stream", headers={**admin_headers, "Accept-Encoding": "gzip"}) as r:
        assert "content-encoding" not in r.headers
        assert '"t": "hello"' in "".join(r.iter_text())
