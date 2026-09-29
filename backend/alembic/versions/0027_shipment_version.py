"""shipments.version — optimistic concurrency (launch Phase 2)

Every write bumps it (SQLAlchemy version_id_col); PATCH compares the values the
user saw ("base") and answers 409 when someone else changed the same field.

Revision ID: 0027
Revises: 0026
"""
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shipments") as b:
        b.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_shipments_updated_at", "shipments", ["updated_at"])


def downgrade() -> None:
    op.drop_index("ix_shipments_updated_at", table_name="shipments")
    with op.batch_alter_table("shipments") as b:
        b.drop_column("version")
