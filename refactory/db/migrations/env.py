"""Alembic env.py — runtime migration environment for Refactory."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from refactory.db.base import Base
import refactory.db.models  # noqa: F401 — ensure all models are registered

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    """Resolve the database URL from environment or alembic.ini."""
    return os.environ.get("REFACTORY_DATABASE_URL", config.get_main_option("sqlalchemy.url", "sqlite:///refactory.db"))


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — emit SQL without a live connection."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live database connection."""
    url = _get_url()
    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
