import io
import os
import tempfile

# Isolated DB per test run — must be set before app modules are imported.
# TEST_DATABASE_URL=postgresql://... runs the suite on Postgres (the database is
# wiped first, so never point it at real data); otherwise a throwaway SQLite file.
_pg = os.environ.get("TEST_DATABASE_URL")
if _pg:
    if "test" not in _pg.rsplit("/", 1)[-1]:
        raise RuntimeError("TEST_DATABASE_URL must name a database with 'test' in it")
    import sqlalchemy as _sa

    with _sa.create_engine(_pg).begin() as _c:
        _c.execute(_sa.text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    os.environ["DATABASE_URL"] = _pg
else:
    _db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    os.environ["DATABASE_URL"] = f"sqlite:///{_db.name}"
os.environ["JWT_SECRET_KEY"] = "test-secret"
os.environ["JOBS_ENABLED"] = "0"  # background jobs are called directly in tests
# Never touch the real Google Drive or real backups from tests (backend/.env may switch them on;
# load_dotenv doesn't override values already set here). Tests plug in a fake Drive themselves.
os.environ["STORAGE_BACKEND"] = "local"
for _k in ("GOOGLE_SERVICE_ACCOUNT_JSON", "DRIVE_ROOT_FOLDER_ID", "DRIVE_INVOICES_FOLDER_ID",
           "DRIVE_BACKUPS_FOLDER_ID", "DRIVE_SHIPMENTS_FOLDER_ID", "BACKUP_ENCRYPTION_KEY"):
    os.environ[_k] = ""
os.environ["BACKUP_DIR"] = tempfile.mkdtemp(prefix="erp-test-backups-")
os.environ["DOCUMENT_STORAGE_ROOT"] = tempfile.mkdtemp(prefix="erp-test-docs-")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

PAGE_H = A4[1]


def make_pdf(lines):
    """lines: [(x, top, text)] with top measured from the page top, like pdfplumber."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 8)
    for x, top, text in lines:
        c.drawString(x, PAGE_H - top - 8, text)
    c.save()
    buf.seek(0)
    return buf


def be_pdf(be_no="2345678", mawb="MEDU1234567890", hawb="HBL998877", importer="ACME TYRES PRIVATE LIMITED",
           ad_code="6390001", containers=("MSKU1234567", "TGHU7654321"), gw="24500.5", extra=()):
    """Synthetic BE laid out like an ICEGATE BE: label rows with values beneath."""
    lines = [
        (40, 40, "BILL OF ENTRY FOR HOME CONSUMPTION"),
        (40, 60, f"INNSA1 {be_no} 05/03/2026"),
        (40, 80, "1.IMPORTER NAME & ADDRESS"),
        (40, 92, importer),
        (40, 104, "PLOT 12 MIDC ANDHERI MUMBAI"),
        (40, 175, "AD CODE"),
        (40, 187, ad_code),
        (40, 140, "6.MAWB NO"), (140, 140, "7.DATE"), (200, 140, "8.HAWB NO"),
        (300, 140, "9.DATE"), (380, 140, "10.PKG"), (440, 140, "11.GW"),
        (40, 155, mawb), (140, 155, "01/03/2026"), (200, 155, hawb or ""),
        (300, 155, "01/03/2026"), (380, 155, "120"), (440, 155, gw),
        (40, 200, "CONTAINER DETAILS " + " ".join(containers)),
        (40, 240, "1.BCD 2.ACD 3.SWS 7.IGST 18.TOT.ASS VAL"),
        (40, 252, "15000.00 0 1500.00 45000.00 0 250000.00"),
        (40, 280, "9.SG 10.SAED 19.TOT. AMOUNT"),
        (40, 292, "0 0 61500.00"),
        *extra,
    ]
    return make_pdf(lines)


def cfs_pdf(be_no="2345678", bl_no="MEDU1234567890", before="1,08,560.00", gst="19,540.80", after="1,28,100.80"):
    return make_pdf([
        (40, 40, "NAVKAR CONTAINER FREIGHT STATION - PROFORMA INVOICE"),
        (40, 60, f"BOE No: {be_no}"),
        (40, 72, f"BL No: {bl_no}"),
        (40, 120, f"Total Amount Before Tax: {before}"),
        (40, 132, f"Tax Amount: GST: {gst}"),
        (40, 144, f"Total Amount After Tax: {after}"),
    ])


@pytest.fixture(scope="session")
def client():
    seed()
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin_headers(client):
    r = client.post("/auth/login", data={"username": "admin@example.com", "password": "changeme"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
