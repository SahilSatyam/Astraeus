"""Alembic environment, async-aware.

DSN comes from :class:`astraeus_config.DatabaseSettings` — never from
``alembic.ini`` — so the same settings stack governs runtime and migrations.

Autogenerate imports ``astraeus_db.base.Base`` so every model registered with
that base is discoverable. Phase 1+ models add themselves to ``Base.metadata``
by being imported in ``astraeus_db/__init__.py`` (see ADR-0007 once added).
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig
from typing import TYPE_CHECKING

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from astraeus_config import DatabaseSettings
from astraeus_db.base import Base

if TYPE_CHECKING:
    from sqlalchemy import MetaData
    from sqlalchemy.engine import Connection


config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_settings = DatabaseSettings()
config.set_main_option("sqlalchemy.url", _settings.dsn)

target_metadata: MetaData = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — no DB connection, emits SQL only."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode against an async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
