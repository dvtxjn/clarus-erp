from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint

from app.core.database import Base


class DriveFileMark(Base):
    """What a file in a shipment's Drive folder was marked as, by hand (client, 2026-10-05).
    document_type = a DocumentType value, or "ignore" to keep the folder reader off it.
    No row = the reader guesses. Re-scans always respect these."""
    __tablename__ = "drive_file_marks"
    __table_args__ = (UniqueConstraint("shipment_id", "drive_file_id", name="uq_drive_file_marks_file"),)

    IGNORE = "ignore"

    id = Column(Integer, primary_key=True)
    shipment_id = Column(Integer, ForeignKey("shipments.id"), nullable=False, index=True)
    drive_file_id = Column(String, nullable=False)
    file_name = Column(String, nullable=True)
    document_type = Column(String, nullable=False)
    marked_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    marked_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
