"""shipments: FTA info; FTA numbers typed onto the end of the MBL move into it

The sheet had FTA certificate numbers written after the MBL
('LPL1543012-UKIN-160926-E96101'): the MBL is 'LPL1543012', the FTA no is
'UKIN-160926-E96101' (client, 2026-09-29). Each move is audit-logged.

Revision ID: 0035
Revises: 0034
"""
import re

from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

FTA = re.compile(r"^(?P<mbl>.*?)[\s-]*(?P<fta>[A-Z]{4}-\d{6}-[A-Z0-9]{5,8})\s*$")


def upgrade() -> None:
    with op.batch_alter_table("shipments") as b:
        b.add_column(sa.Column("fta_info", sa.Text(), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, mbl FROM shipments WHERE mbl IS NOT NULL")).fetchall()
    for sid, mbl in rows:
        m = FTA.match(mbl.strip())
        if not m or not m.group("mbl").strip():
            continue
        new_mbl, fta = m.group("mbl").strip(), m.group("fta")
        bind.execute(sa.text("UPDATE shipments SET mbl = :m, fta_info = :f WHERE id = :i"), {"m": new_mbl, "f": fta, "i": sid})
        for field, old, new in (("mbl", mbl, new_mbl), ("fta_info", None, fta)):
            bind.execute(
                sa.text("INSERT INTO audit_log_entries (table_name, record_id, field_name, old_value, new_value) "
                        "VALUES ('shipments', :i, :f, :o, :n)"),
                {"i": sid, "f": field, "o": old, "n": new},
            )


def downgrade() -> None:
    # put the FTA number back on the end of the MBL, as it was typed
    op.execute("UPDATE shipments SET mbl = mbl || '-' || fta_info WHERE fta_info ~ '^[A-Z]{4}-[0-9]{6}-'")
    with op.batch_alter_table("shipments") as b:
        b.drop_column("fta_info")
