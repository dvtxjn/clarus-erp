"""proforma_snapshots: a sent invoice is edited in place; the copy that went out is kept here (client, 2026-10-07)

Revision ID: 0052
Revises: 0051
"""
from alembic import op
import sqlalchemy as sa

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proforma_snapshots",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("proforma_id", sa.Integer, sa.ForeignKey("proformas.id"), nullable=False),
        sa.Column("bill_rate", sa.Numeric(12, 2), nullable=True),
        sa.Column("grand_total", sa.Numeric(12, 2), nullable=True),
        sa.Column("invoice", sa.JSON, nullable=False),
        sa.Column("proforma_data", sa.JSON, nullable=False),
        sa.Column("drive_file_id", sa.String, nullable=True),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_proforma_snapshots_id", "proforma_snapshots", ["id"])
    op.create_index("ix_proforma_snapshots_proforma_id", "proforma_snapshots", ["proforma_id"])


def downgrade() -> None:
    op.drop_table("proforma_snapshots")
