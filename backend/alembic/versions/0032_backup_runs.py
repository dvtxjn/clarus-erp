"""backup_runs — one row per database backup (launch Phase 8)

Revision ID: 0032
Revises: 0031
"""
from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backup_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(), nullable=True),
        sa.Column("local_path", sa.String(), nullable=True),
        sa.Column("drive_file_id", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
    )
    op.create_index("ix_backup_runs_started_at", "backup_runs", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_backup_runs_started_at", table_name="backup_runs")
    op.drop_table("backup_runs")
