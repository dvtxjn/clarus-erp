from logging.config import fileConfig

from alembic import context

from app.core.database import Base, engine
from app import models  # noqa: F401 — populates Base.metadata

if context.config.config_file_name is not None and context.config.attributes.get("configure_logger", True):
    fileConfig(context.config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online():
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite can't ALTER most things in place
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
