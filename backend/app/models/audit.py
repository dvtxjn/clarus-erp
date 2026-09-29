from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey
from sqlalchemy.sql import func

from app.core.database import Base


class AuditLogEntry(Base):
    """
    Spec §2.4: "all changes will need to have version history, retained
    for 7 days." Generic across tables so it doesn't need a new model per
    entity — records table + record id + field + old/new value.

    A scheduled cleanup job should purge rows older than 7 days (not
    implemented yet — see PROGRESS.md).
    """
    __tablename__ = "audit_log_entries"

    id = Column(Integer, primary_key=True, index=True)
    table_name = Column(String, nullable=False, index=True)
    record_id = Column(Integer, nullable=False, index=True)
    field_name = Column(String, nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)

    changed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    changed_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
