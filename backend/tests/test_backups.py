"""Launch Phase 8: encrypted backups with a manifest, the 12-hour schedule, and the admin
warnings (stale / shrunk / failed). Needs Postgres (pg_dump)."""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app import backups
from app.core.database import SessionLocal
from app.models.backup import BackupRun

pytestmark = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="backups need Postgres (pg_dump)")


@pytest.fixture
def key(monkeypatch, tmp_path, client):
    k = Fernet.generate_key().decode()
    monkeypatch.setenv("BACKUP_ENCRYPTION_KEY", k)
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
    with SessionLocal() as db:
        db.query(BackupRun).delete()
        db.commit()
    return k


def _fake(started_hours_ago, size, status="ok", error=None):
    with SessionLocal() as db:
        db.add(BackupRun(name=f"erp-fake-{started_hours_ago}.dump.enc", status=status, size_bytes=size, error=error,
                         started_at=datetime.now(backups.IST).replace(tzinfo=None) - timedelta(hours=started_hours_ago)))
        db.commit()


def test_backup_is_encrypted_readable_and_has_a_manifest(key, client, admin_headers):
    run = backups.run_backup()
    assert run.status == "ok", run.error
    enc = Path(run.local_path).read_bytes()
    assert not enc.startswith(b"PGDMP")  # encrypted on disk
    assert Fernet(key.encode()).decrypt(enc).startswith(b"PGDMP")  # a real pg_dump inside
    manifest = json.loads(Path(run.local_path + ".manifest.json").read_text())
    assert manifest["rows"]["shipments"] >= 0 and manifest["migration"] and manifest["encrypted_bytes"] == len(enc)
    assert run.name.startswith("erp-") and run.name.endswith(".dump.enc")
    st = client.get("/health/backups", headers=admin_headers).json()
    assert st["enabled"] and st["last_ok_name"] == run.name and st["warnings"] == []


def test_only_every_twelve_hours(key, monkeypatch):
    calls = []
    monkeypatch.setattr(backups, "run_backup", lambda: calls.append(1))
    _fake(3, 1000)
    backups.backup_if_due()
    assert calls == []  # a good one 3 hours ago
    _fake(13, 1000)
    with SessionLocal() as db:
        db.query(BackupRun).filter(BackupRun.name == "erp-fake-3.dump.enc").delete()
        db.commit()
    backups.backup_if_due()
    assert calls == [1]  # last good one 13 hours ago


def test_warnings_for_stale_shrunk_and_failed(key):
    _fake(30, 100_000)
    assert any("26 hours" in w for w in backups.status()["warnings"])
    _fake(1, 40_000)  # 60 % smaller than the one before
    w = backups.status()["warnings"]
    assert not any("26 hours" in x for x in w) and any("smaller" in x for x in w)
    _fake(0, None, status="failed", error="pg_dump failed: disk full")
    assert any("disk full" in x for x in backups.status()["warnings"])


def test_backup_health_is_admin_only(client):
    assert client.get("/health/backups").status_code == 401
