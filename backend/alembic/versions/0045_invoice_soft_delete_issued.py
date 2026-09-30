"""final invoices: the admin may soft-delete (and restore) an issued or cancelled invoice (client, 2026-09-30)

Trial invoices are cleared before going live. The lock trigger stays: an update that changes ONLY
deleted_at / deleted_by_id is let through; anything else on an issued / cancelled invoice is still
refused, and a real DELETE is still never allowed. The number stays taken (the app never gives it again).

Revision ID: 0045
Revises: 0044
"""
from alembic import op
import sqlalchemy as sa

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None

UNLOCKED = ("irn", "ack_no", "ack_date", "status", "cancelled_at", "cancelled_by_id", "cancel_reason")
SOFT = ("deleted_at", "deleted_by_id")
_ARR = ", ".join(f"'{c}'" for c in UNLOCKED)
_SOFT = ", ".join(f"'{c}'" for c in SOFT)


def _function(soft_delete_allowed: bool) -> str:
    soft = f"""
  IF (to_jsonb(NEW) - ARRAY[{_SOFT}]) IS NOT DISTINCT FROM (to_jsonb(OLD) - ARRAY[{_SOFT}]) THEN
    RETURN NEW;  -- only deleted / restored
  END IF;""" if soft_delete_allowed else ""
    return f"""
CREATE OR REPLACE FUNCTION final_invoice_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Final invoices are never deleted (id %)', OLD.id;
  END IF;
  IF OLD.status = 'draft' THEN
    RETURN NEW;
  END IF;{soft}
  IF OLD.status = 'cancelled' AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
    RAISE EXCEPTION 'Final invoice % is cancelled and cannot change', OLD.number;
  END IF;
  IF OLD.status = 'issued' AND current_setting('clarus.invoice_alter', true) = 'on' THEN
    IF NEW.number IS DISTINCT FROM OLD.number OR NEW.seq IS DISTINCT FROM OLD.seq
       OR NEW.fy IS DISTINCT FROM OLD.fy OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.status IS DISTINCT FROM OLD.status THEN
      RAISE EXCEPTION 'Final invoice %: number, series and status never change when altering', OLD.number;
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (OLD.status = 'issued' AND NEW.status = 'cancelled') THEN
    RAISE EXCEPTION 'Final invoice %: status % -> % is not allowed', OLD.number, OLD.status, NEW.status;
  END IF;
  IF (to_jsonb(NEW) - ARRAY[{_ARR}]) IS DISTINCT FROM (to_jsonb(OLD) - ARRAY[{_ARR}]) THEN
    RAISE EXCEPTION 'Final invoice % is issued: only IRN / ACK can change', OLD.number;
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;
"""


def _sqlite_trigger(skip: tuple) -> None:
    conn = op.get_bind()
    cols = [c["name"] for c in sa.inspect(conn).get_columns("final_invoices") if c["name"] not in skip]
    locked = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in cols if c not in UNLOCKED)
    every = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in cols)
    op.execute("DROP TRIGGER IF EXISTS final_invoice_locked")
    op.execute(
        "CREATE TRIGGER final_invoice_locked BEFORE UPDATE ON final_invoices "
        "WHEN OLD.status <> 'draft' AND ("
        f"  (OLD.status = 'cancelled' AND ({every}))"
        "  OR (NEW.status IS NOT OLD.status AND NOT (OLD.status = 'issued' AND NEW.status = 'cancelled'))"
        f"  OR {locked}"
        ") BEGIN SELECT RAISE(ABORT, 'Final invoice is issued or cancelled: locked'); END")


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_function(True))
    else:
        _sqlite_trigger(SOFT)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_function(False))
    else:
        _sqlite_trigger(())
