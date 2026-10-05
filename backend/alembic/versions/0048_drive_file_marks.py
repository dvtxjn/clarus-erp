"""drive_file_marks: hand marks for files in a shipment's Drive folder (client, 2026-10-05)

The folder reader guesses what each PDF is; a mark overrides the guess (or ignores the file).

Revision ID: 0048
Revises: 0047
"""
from alembic import op
import sqlalchemy as sa

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "drive_file_marks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("shipment_id", sa.Integer, sa.ForeignKey("shipments.id"), nullable=False),
        sa.Column("drive_file_id", sa.String, nullable=False),
        sa.Column("file_name", sa.String, nullable=True),
        sa.Column("document_type", sa.String, nullable=False),
        sa.Column("marked_by_id", sa.Integer, sa.ForeignKey("users.id"), nullable=True),
        sa.Column("marked_at", sa.DateTime, nullable=True),
        sa.UniqueConstraint("shipment_id", "drive_file_id", name="uq_drive_file_marks_file"),
    )
    op.create_index("ix_drive_file_marks_shipment_id", "drive_file_marks", ["shipment_id"])


def downgrade() -> None:
    op.drop_index("ix_drive_file_marks_shipment_id", "drive_file_marks")
    op.drop_table("drive_file_marks")
