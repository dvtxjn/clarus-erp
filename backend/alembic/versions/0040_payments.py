"""payments received and how they're split over invoices (P1: payments & outstanding)

Revision ID: 0040
Revises: 0039
"""
from alembic import op
import sqlalchemy as sa

revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("party", sa.String(), nullable=False),
        sa.Column("party_gstin", sa.String(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("mode", sa.String(), nullable=True),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_payments_deleted_at", "payments", ["deleted_at"])
    op.create_index("ix_payments_party", "payments", ["party"])
    op.create_table(
        "payment_allocations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id"), nullable=False),
        sa.Column("final_invoice_id", sa.Integer(), sa.ForeignKey("final_invoices.id"), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("tds", sa.Numeric(14, 2), nullable=False, server_default="0"),
    )
    op.create_index("ix_payment_allocations_payment_id", "payment_allocations", ["payment_id"])
    op.create_index("ix_payment_allocations_final_invoice_id", "payment_allocations", ["final_invoice_id"])


def downgrade() -> None:
    op.drop_table("payment_allocations")
    op.drop_table("payments")
