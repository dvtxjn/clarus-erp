"""Google Drive storage (launch Phase 7): folder registry, saved PDFs, pending uploads

Revision ID: 0028
Revises: 0027
"""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drive_folders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("path", sa.String(), nullable=False, unique=True),
        sa.Column("drive_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "stored_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("ref_id", sa.Integer(), nullable=False),
        sa.Column("folder_path", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("local_path", sa.String(), nullable=False),
        sa.Column("drive_file_id", sa.String(), nullable=True),
        sa.Column("drive_link", sa.String(), nullable=True),
        sa.Column("drive_sync_pending", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("drive_error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("kind", "ref_id", name="uq_stored_files_kind_ref"),
    )
    with op.batch_alter_table("shipment_documents") as b:
        b.add_column(sa.Column("drive_sync_pending", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("drive_error", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("shipment_documents") as b:
        b.drop_column("drive_error")
        b.drop_column("drive_sync_pending")
    op.drop_table("stored_files")
    op.drop_table("drive_folders")
