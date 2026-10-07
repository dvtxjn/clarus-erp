"""organizations: soft delete (test finding #16 — delete was permanent)

Revision ID: 0053
Revises: 0052
"""
from alembic import op
import sqlalchemy as sa

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("organizations") as b:
        b.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        b.add_column(sa.Column("deleted_by_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_organizations_deleted_by", "users", ["deleted_by_id"], ["id"])
        b.create_index("ix_organizations_deleted_at", ["deleted_at"])


def downgrade() -> None:
    with op.batch_alter_table("organizations") as b:
        b.drop_index("ix_organizations_deleted_at")
        b.drop_constraint("fk_organizations_deleted_by", type_="foreignkey")
        b.drop_column("deleted_by_id")
        b.drop_column("deleted_at")
