"""tracker CSV re-import: HBL in its own field again (split "MBL/HBL" cells), HBL column shown,
flag for shipments missing from the sheet

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('shipments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('missing_from_sheet_at', sa.DateTime(), nullable=True))
    conn = op.get_bind()
    # "274483845/QDDR2607499" in the MBL cell -> mbl + hbl (client: HBL gets its own column)
    for sid, mbl, hbl in conn.execute(sa.text("SELECT id, mbl, hbl FROM shipments WHERE mbl LIKE '%/%'")).fetchall():
        parts = [p.strip() for p in mbl.split("/") if p.strip()]
        if len(parts) >= 2 and not (hbl or "").strip():
            conn.execute(sa.text("UPDATE shipments SET mbl=:m, hbl=:h WHERE id=:i"),
                         {"m": parts[0], "h": "/".join(parts[1:]), "i": sid})
            conn.execute(sa.text("INSERT INTO audit_log_entries (table_name, record_id, field_name, old_value, new_value) "
                                 "VALUES ('shipments', :i, 'mbl/hbl split', :o, :n)"),
                         {"i": sid, "o": mbl, "n": f"{parts[0]} | {'/'.join(parts[1:])}"})
    conn.execute(sa.text("UPDATE tracker_columns SET is_removed=0 WHERE key='hbl'"))


def downgrade() -> None:
    with op.batch_alter_table('shipments', schema=None) as batch_op:
        batch_op.drop_column('missing_from_sheet_at')
