"""final invoices: an issued invoice may be altered, deliberately (client, 2026-09-30)

The lock trigger (0026) stays. The app can now alter an issued invoice's content inside
one transaction that sets `clarus.invoice_alter = 'on'` (only after its own checks: before
the 10th of next month, e-invoice not filed). Even then the number, series and status
can't change. Anything else touching an issued invoice is still refused.

Revision ID: 0039
Revises: 0038
"""
from alembic import op

revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None

UNLOCKED = ("irn", "ack_no", "ack_date", "status", "cancelled_at", "cancelled_by_id", "cancel_reason")
_ARR = ", ".join(f"'{c}'" for c in UNLOCKED)


def _function(alter_allowed: bool) -> str:
    alter = """
  IF OLD.status = 'issued' AND current_setting('clarus.invoice_alter', true) = 'on' THEN
    IF NEW.number IS DISTINCT FROM OLD.number OR NEW.seq IS DISTINCT FROM OLD.seq
       OR NEW.fy IS DISTINCT FROM OLD.fy OR NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.status IS DISTINCT FROM OLD.status THEN
      RAISE EXCEPTION 'Final invoice %: number, series and status never change when altering', OLD.number;
    END IF;
    RETURN NEW;
  END IF;""" if alter_allowed else ""
    return f"""
CREATE OR REPLACE FUNCTION final_invoice_guard() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Final invoices are never deleted (id %)', OLD.id;
  END IF;
  IF OLD.status = 'draft' THEN
    RETURN NEW;
  END IF;
  IF OLD.status = 'cancelled' AND to_jsonb(NEW) IS DISTINCT FROM to_jsonb(OLD) THEN
    RAISE EXCEPTION 'Final invoice % is cancelled and cannot change', OLD.number;
  END IF;{alter}
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


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_function(True))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_function(False))
