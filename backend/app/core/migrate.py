"""Run Alembic migrations to head (used on startup and by the seed script)."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from app.core.database import engine

BACKEND_DIR = Path(__file__).resolve().parents[2]


def run_migrations() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["configure_logger"] = False
    tables = set(inspect(engine).get_table_names())
    # DBs created before Alembic was set up (via create_all) match the baseline.
    if "shipments" in tables and "alembic_version" not in tables:
        command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")
