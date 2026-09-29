"""shipment_documents.drive_picked — linked to a file already in the shipment's Drive folder

Revision ID: 0029
Revises: 0028
"""
from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("shipment_documents") as b:
        b.add_column(sa.Column("drive_picked", sa.Boolean(), nullable=False, server_default=sa.false()))
    # documents added "from Google Drive" before this column existed
    op.execute("UPDATE shipment_documents SET drive_picked = TRUE WHERE drive_file_id IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table("shipment_documents") as b:
        b.drop_column("drive_picked")
