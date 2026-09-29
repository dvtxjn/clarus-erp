"""
Copy the local SQLite database into a fresh Postgres database (Phase 0).

    .venv/bin/python scripts/sqlite_to_postgres.py erp_dev.db postgresql://erp:...@localhost:5432/erp_db

Safety
  - The SQLite file is opened read-only; it is never modified.
  - Refuses to run unless the Postgres database has no tables at all.
  - Refuses if the SQLite schema is not at the code's latest migration, or has a
    column the code doesn't know (that data would be lost).
  - Creates the schema with the normal migrations, clears the rows those
    migrations seed (charge list, licences, ...) and copies every row as-is, in
    foreign-key order. Sequences are reset so new rows get the next id.
  - Prints the row count per table on both sides; exits 1 on any difference.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def main(sqlite_path: str, target_url: str) -> int:
    src_file = Path(sqlite_path).resolve()
    if not src_file.is_file():
        print(f"No such file: {src_file}")
        return 1
    if not target_url.startswith("postgresql"):
        print("The target must be a postgresql:// URL.")
        return 1

    # the app's engine (used by the migrations) must point at the target
    os.environ["DATABASE_URL"] = target_url
    sys.path.insert(0, str(BACKEND_DIR))
    import sqlalchemy as sa
    from alembic.script import ScriptDirectory
    from alembic.config import Config

    from app import models  # noqa: F401 — populates Base.metadata
    from app.core.database import Base, engine as target
    from app.core.migrate import run_migrations

    source = sa.create_engine(f"sqlite:///file:{src_file}?mode=ro&uri=true")

    # --- checks before anything is written ---
    existing = sa.inspect(target).get_table_names()
    if existing:
        print(f"Refusing: the target database already has {len(existing)} tables. Use an empty database.")
        return 1
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    with source.connect() as c:
        version = c.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    if version != head:
        print(f"Refusing: the SQLite file is at migration {version}, the code is at {head}. "
              "Start the app once on SQLite to upgrade it first.")
        return 1
    src_insp = sa.inspect(source)
    src_tables = set(src_insp.get_table_names()) - {"alembic_version"}
    unknown_tables = src_tables - set(Base.metadata.tables)
    if unknown_tables:
        print(f"Refusing: tables not in the code: {sorted(unknown_tables)}")
        return 1
    for name in src_tables:
        extra = {c["name"] for c in src_insp.get_columns(name)} - set(Base.metadata.tables[name].c.keys())
        if extra:
            print(f"Refusing: {name} has columns not in the code: {sorted(extra)}")
            return 1

    # --- schema, then data ---
    print(f"Creating the schema (migrations to {head}) ...")
    run_migrations()
    tables = [t for t in Base.metadata.sorted_tables if t.name in src_tables]
    with target.begin() as dst:
        names = ", ".join(t.name for t in Base.metadata.sorted_tables)
        dst.execute(sa.text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))  # rows seeded by the migrations
        with source.connect() as src:
            for t in tables:
                rows = [dict(r._mapping) for r in src.execute(sa.select(t))]
                if rows:
                    dst.execute(t.insert(), rows)
        for t in tables:
            pk = list(t.primary_key.columns)
            if len(pk) == 1 and isinstance(pk[0].type, sa.Integer):
                dst.execute(sa.text(
                    f"SELECT setval(pg_get_serial_sequence('{t.name}', '{pk[0].name}'), "
                    f"COALESCE(MAX({pk[0].name}), 1), MAX({pk[0].name}) IS NOT NULL) FROM {t.name}"))

    # --- verify ---
    ok = True
    print(f"\n{'table':<24}{'sqlite':>8}{'postgres':>10}")
    with source.connect() as src, target.connect() as dst:
        for t in tables:
            a = src.execute(sa.select(sa.func.count()).select_from(t)).scalar()
            b = dst.execute(sa.select(sa.func.count()).select_from(t)).scalar()
            ok &= a == b
            print(f"{t.name:<24}{a:>8}{b:>10}{'' if a == b else '   <-- DIFFERENT'}")
    print("\nAll row counts match." if ok else "\nROW COUNTS DIFFER — do not use the Postgres copy.")
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
