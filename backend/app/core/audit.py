from typing import Any, Optional
from sqlalchemy.orm import Session

from app.models.audit import AuditLogEntry


def record_change(
    db: Session,
    table_name: str,
    record_id: int,
    field_name: str,
    old_value: Any,
    new_value: Any,
    changed_by_id: Optional[int],
) -> None:
    """
    Spec §2.4: "all changes will need to have version history... retained
    for 7 days." Call this before applying a field change on any tracked
    model. Does not commit — caller's existing db.commit() covers it.

    NOTE: a scheduled job to purge entries older than 7 days is not yet
    implemented — see PROGRESS.md.
    """
    entry = AuditLogEntry(
        table_name=table_name,
        record_id=record_id,
        field_name=field_name,
        old_value=str(old_value) if old_value is not None else None,
        new_value=str(new_value) if new_value is not None else None,
        changed_by_id=changed_by_id,
    )
    db.add(entry)
