"""ICEGATE e-mails read into the ERP (customs timeline, needs attention)

Revision ID: 0044
Revises: 0043
"""
from alembic import op
import sqlalchemy as sa

revision = "0044"
down_revision = "0043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "icegate_mails",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("message_id", sa.String(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("be_no", sa.String(), nullable=True),
        sa.Column("be_date", sa.Date(), nullable=True),
        sa.Column("job_no", sa.String(), nullable=True),
        sa.Column("port", sa.String(), nullable=True),
        sa.Column("mbl", sa.String(), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("shipment_id", sa.Integer(), sa.ForeignKey("shipments.id"), nullable=True),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("notes", sa.JSON(), nullable=True),
        sa.Column("pdf_name", sa.String(), nullable=True),
        sa.Column("pdf", sa.LargeBinary(), nullable=True),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("shipment_documents.id"), nullable=True),
        sa.Column("attention", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_note", sa.String(), nullable=True),
        sa.Column("imported_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for col in ("received_at", "kind", "be_no", "job_no", "shipment_id"):
        op.create_index(f"ix_icegate_mails_{col}", "icegate_mails", [col])


def downgrade() -> None:
    op.drop_table("icegate_mails")
