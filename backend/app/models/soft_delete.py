"""
Soft delete (DEPLOYMENT_PLAN Phase 1): shipments, documents, proformas and final
invoices are never removed from the database. "Delete" sets deleted_at / deleted_by_id;
every normal ORM query (including relationship loads and db.get) then skips the row.
Only the admin can see deleted rows (Recently deleted) and restore them.

To see deleted rows on purpose:  db.query(X).execution_options(include_deleted=True)
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, event
from sqlalchemy.orm import Session, declared_attr, with_loader_criteria


class SoftDeleteMixin:
    @declared_attr
    def deleted_at(cls):
        return Column(DateTime, nullable=True, index=True)

    @declared_attr
    def deleted_by_id(cls):
        return Column(Integer, ForeignKey("users.id"), nullable=True)

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


def soft_delete(db: Session, obj: SoftDeleteMixin, user_id: Optional[int]) -> None:
    obj.deleted_at = datetime.now()
    obj.deleted_by_id = user_id
    db.flush()
    db.expire_all()  # collections already loaded (shipment.documents, .proformas) still hold the row


def restore(db: Session, obj: SoftDeleteMixin) -> None:
    obj.deleted_at = None
    obj.deleted_by_id = None
    db.flush()
    db.expire_all()


@event.listens_for(Session, "do_orm_execute")
def _hide_deleted(state):
    if state.is_select and not state.execution_options.get("include_deleted", False):
        state.statement = state.statement.options(
            with_loader_criteria(SoftDeleteMixin, lambda cls: cls.deleted_at.is_(None), include_aliases=True)
        )
