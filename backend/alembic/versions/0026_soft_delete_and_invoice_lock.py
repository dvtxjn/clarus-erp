"""soft delete + issued final invoices locked in the database (launch Phase 1)

- deleted_at / deleted_by_id on shipments, shipment_documents, proformas, final_invoices
  (nothing in these tables is removed any more; the admin can restore).
- final_invoices: cancelled_at / cancelled_by_id / cancel_reason.
- Database triggers on final_invoices, so even a bug or a hand-typed SQL can't change
  what went to the client / the authorities:
    * DELETE is always refused.
    * Once issued: only irn / ack_no / ack_date may change, plus issued -> cancelled
      (with the cancel fields). Cancelled invoices are fully frozen. Drafts stay editable.
  NOTE (SQLite dev only): a later batch migration that rebuilds final_invoices drops
  these triggers — test_final_invoice_triggers_exist catches that.

Revision ID: 0026
Revises: 0025
"""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

SOFT_DELETE_TABLES = ("shipments", "shipment_documents", "proformas", "final_invoices")
# may change on an issued invoice
UNLOCKED = ("irn", "ack_no", "ack_date", "status", "cancelled_at", "cancelled_by_id", "cancel_reason")

PG_FUNCTION = f"""
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
  END IF;
  IF NEW.status IS DISTINCT FROM OLD.status AND NOT (OLD.status = 'issued' AND NEW.status = 'cancelled') THEN
    RAISE EXCEPTION 'Final invoice %: status % -> % is not allowed', OLD.number, OLD.status, NEW.status;
  END IF;
  IF (to_jsonb(NEW) - ARRAY[{", ".join(f"'{c}'" for c in UNLOCKED)}])
     IS DISTINCT FROM (to_jsonb(OLD) - ARRAY[{", ".join(f"'{c}'" for c in UNLOCKED)}]) THEN
    RAISE EXCEPTION 'Final invoice % is issued: only IRN / ACK can change', OLD.number;
  END IF;
  RETURN NEW;
END
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    for table in SOFT_DELETE_TABLES:
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
            b.add_column(sa.Column("deleted_by_id", sa.Integer(), nullable=True))
            b.create_foreign_key(f"fk_{table}_deleted_by", "users", ["deleted_by_id"], ["id"])
            b.create_index(f"ix_{table}_deleted_at", ["deleted_at"])
    with op.batch_alter_table("final_invoices") as b:
        b.add_column(sa.Column("cancelled_at", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("cancelled_by_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("cancel_reason", sa.String(), nullable=True))
        b.create_foreign_key("fk_final_invoices_cancelled_by", "users", ["cancelled_by_id"], ["id"])

    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute(PG_FUNCTION)
        op.execute("CREATE TRIGGER final_invoice_guard BEFORE UPDATE OR DELETE ON final_invoices "
                   "FOR EACH ROW EXECUTE FUNCTION final_invoice_guard()")
    else:
        cols = [c["name"] for c in sa.inspect(conn).get_columns("final_invoices")]
        locked = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in cols if c not in UNLOCKED)
        every = " OR ".join(f"NEW.{c} IS NOT OLD.{c}" for c in cols)
        op.execute("CREATE TRIGGER final_invoice_no_delete BEFORE DELETE ON final_invoices "
                   "BEGIN SELECT RAISE(ABORT, 'Final invoices are never deleted'); END")
        op.execute(
            "CREATE TRIGGER final_invoice_locked BEFORE UPDATE ON final_invoices "
            "WHEN OLD.status <> 'draft' AND ("
            f"  (OLD.status = 'cancelled' AND ({every}))"
            "  OR (NEW.status IS NOT OLD.status AND NOT (OLD.status = 'issued' AND NEW.status = 'cancelled'))"
            f"  OR {locked}"
            ") BEGIN SELECT RAISE(ABORT, 'Final invoice is issued or cancelled: locked'); END")


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS final_invoice_guard ON final_invoices")
        op.execute("DROP FUNCTION IF EXISTS final_invoice_guard()")
    else:
        op.execute("DROP TRIGGER IF EXISTS final_invoice_no_delete")
        op.execute("DROP TRIGGER IF EXISTS final_invoice_locked")
    with op.batch_alter_table("final_invoices") as b:
        b.drop_constraint("fk_final_invoices_cancelled_by", type_="foreignkey")
        b.drop_column("cancel_reason")
        b.drop_column("cancelled_by_id")
        b.drop_column("cancelled_at")
    for table in SOFT_DELETE_TABLES:
        with op.batch_alter_table(table) as b:
            b.drop_index(f"ix_{table}_deleted_at")
            b.drop_constraint(f"fk_{table}_deleted_by", type_="foreignkey")
            b.drop_column("deleted_by_id")
            b.drop_column("deleted_at")
