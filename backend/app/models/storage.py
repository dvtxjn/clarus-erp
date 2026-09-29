from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, UniqueConstraint

from app.core.database import Base


class DriveFolder(Base):
    """Drive folders the ERP created (or found) — one row per path, so two uploads at
    once never create the same folder twice. path e.g. "Documents/SUNRISE TYRES/MEDU1234567"."""
    __tablename__ = "drive_folders"

    id = Column(Integer, primary_key=True)
    path = Column(String, nullable=False, unique=True)
    drive_id = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class StoredFile(Base):
    """A PDF the ERP generated and saved: a proforma when it's marked Sent, a final
    invoice when it's issued. Kept locally and (STORAGE_BACKEND=drive) in Drive; if the
    Drive save fails it stays pending and a background job retries."""
    __tablename__ = "stored_files"
    __table_args__ = (UniqueConstraint("kind", "ref_id", name="uq_stored_files_kind_ref"),)

    id = Column(Integer, primary_key=True)
    kind = Column(String, nullable=False)  # "proforma_pdf" | "final_invoice_pdf"
    ref_id = Column(Integer, nullable=False)  # proforma / final invoice id
    folder_path = Column(String, nullable=False)  # Drive path under a root, e.g. "Invoices/Proformas/26-27"
    name = Column(String, nullable=False)
    local_path = Column(String, nullable=False)
    drive_file_id = Column(String, nullable=True)
    drive_link = Column(String, nullable=True)
    drive_sync_pending = Column(Boolean, nullable=False, default=False)
    drive_error = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
