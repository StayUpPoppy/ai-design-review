from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_design_review.review_persistence import Base, database_url_from_env  # noqa: E402


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    value = database_url_from_env()
    if not value:
        raise RuntimeError("DATABASE_URL must be set before running Alembic migrations.")
    return value


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = _database_url()
    from sqlalchemy import engine_from_config, pool

    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
