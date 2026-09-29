"""Launch Phase 9: unsafe production settings are refused; login throttling; health; headers;
the built screens are served by the backend without hiding the API."""
from app.core import production, web


def test_unsafe_settings_are_listed(monkeypatch, client):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret")
    monkeypatch.setenv("PUBLIC_URL", "http://insecure.example")
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    monkeypatch.setenv("AUTO_MIGRATE", "1")
    found = " | ".join(production.problems())
    for bit in ("JWT_SECRET_KEY", "PUBLIC_URL", "STORAGE_BACKEND", "BACKUP_ENCRYPTION_KEY", "AUTO_MIGRATE",
                "admin@example.com"):  # the seeded default admin is refused too
        assert bit in found, bit


def test_check_or_exit_stops_the_app(monkeypatch, client):
    import pytest
    monkeypatch.setenv("APP_ENV", "production")
    with pytest.raises(SystemExit):
        production.check_or_exit()
    monkeypatch.setenv("APP_ENV", "development")
    production.check_or_exit()  # development: never stops


def test_login_throttle_and_lockout(client):
    bad = {"username": "admin@example.com", "password": "wrong-password"}
    codes = [client.post("/auth/login", data=bad).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429  # 6th attempt in a minute
    from app.core import ratelimit
    ratelimit._attempts.clear()  # a minute later ...
    for _ in range(5):
        client.post("/auth/login", data=bad)
    ratelimit._attempts.clear()
    r = client.post("/auth/login", data={"username": "admin@example.com", "password": "changeme"})
    assert r.status_code == 429 and "locked" in r.json()["detail"]  # 10 wrong -> locked, even with the right password


def test_health_checks_the_database_and_headers(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok", "sandbox": False}
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"


def test_screens_served_but_api_untouched(client, admin_headers, tmp_path, monkeypatch):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>app</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    monkeypatch.setattr(web, "DIST", tmp_path)
    page = client.get("/shipments/58", headers={"Accept": "text/html,application/xhtml+xml"})
    assert page.status_code == 200 and "app" in page.text  # a page load gets the React app
    assert client.get("/assets/app.js").text == "console.log(1)"
    api = client.get("/shipments", headers={**admin_headers, "Accept": "application/json, text/plain, */*"})
    assert api.status_code == 200 and isinstance(api.json(), list)  # the API still answers


def test_cors_is_limited_to_the_site(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://erp.claruslogistics.in/")
    assert web.cors_origins() == ["https://erp.claruslogistics.in"]


def test_scheduler_job_endpoint_needs_the_token(client, monkeypatch):
    from app.core import jobs
    ran = []
    monkeypatch.setitem(jobs.JOBS, "drive-retry", "tests.test_production:_fake_job")
    monkeypatch.setattr("tests.test_production._RAN", ran)
    monkeypatch.setenv("JOB_TOKEN", "t" * 32)
    assert client.post("/internal/jobs/drive-retry").status_code == 403
    assert client.post("/internal/jobs/drive-retry", headers={"X-Job-Token": "wrong"}).status_code == 403
    assert client.post("/internal/jobs/nope", headers={"X-Job-Token": "t" * 32}).status_code == 404
    r = client.post("/internal/jobs/drive-retry", headers={"X-Job-Token": "t" * 32})
    assert r.status_code == 200 and r.json()["ran"] and ran == [1]


_RAN: list = []


def _fake_job():
    import tests.test_production as me
    me._RAN.append(1)


def test_sandbox_never_wipes_a_real_database(monkeypatch):
    """P4: the sandbox reset refuses unless SANDBOX=1 AND the database is named *sandbox*."""
    import pytest

    from app import sandbox

    monkeypatch.setenv("SANDBOX", "0")
    with pytest.raises(RuntimeError):
        sandbox.reset()
    monkeypatch.setenv("SANDBOX", "1")  # the test database isn't named *sandbox*
    with pytest.raises(RuntimeError):
        sandbox.reset()


def test_health_says_sandbox_with_the_demo_login(client, monkeypatch):
    monkeypatch.setenv("SANDBOX", "1")
    body = client.get("/health").json()
    assert body["sandbox"] is True and body["demo_email"] and body["demo_password"]
