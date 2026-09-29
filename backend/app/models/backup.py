from datetime import datetime

from sqlalchemy import BigInteger, Column, DateTime, Integer, String

from app.core.database import Base


class BackupRun(Base):
    """One database backup (launch Phase 8): encrypted pg_dump, kept on this server and in
    Drive "Backups". Never deleted by the app (client rule: no deletion in Drive)."""
    __tablename__ = "backup_runs"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)  # erp-YYYY-MM-DD-HHMM.dump.enc
    status = Column(String, nullable=False, default="running")  # running | ok | failed
    started_at = Column(DateTime, nullable=False, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    size_bytes = Column(BigInteger, nullable=True)  # encrypted file
    sha256 = Column(String, nullable=True)
    local_path = Column(String, nullable=True)
    drive_file_id = Column(String, nullable=True)  # None = not in Drive (Drive off, or it failed: see error)
    error = Column(String, nullable=True)
