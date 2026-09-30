"""containers per shipment + arrival at the FPOD (inland free days)

Revision ID: 0041
Revises: 0040
"""
from alembic import op
import sqlalchemy as sa

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shipment_containers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shipment_id", sa.Integer(), sa.ForeignKey("shipments.id"), nullable=False),
        sa.Column("container_no", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("arrival_date", sa.Date(), nullable=True),
        sa.Column("arrival_status", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("is_manual", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_shipment_containers_shipment_id", "shipment_containers", ["shipment_id"])
    op.create_index("ix_shipment_containers_deleted_at", "shipment_containers", ["deleted_at"])


def downgrade() -> None:
    op.drop_table("shipment_containers")
