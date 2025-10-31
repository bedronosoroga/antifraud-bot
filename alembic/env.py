from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

config = context.config

# If there is alembic.ini logging config, it will be loaded
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None  # we write migrations manually, autogenerate is not used


def _sync_url(url: str) -> str:
    if url and "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg")
    return url


def get_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        url = "postgresql+asyncpg://antifraud:  @127.0.0.1:5433/antifraud"
    return _sync_url(url)


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = get_url()
    engine = create_engine(url, future=True, pool_pre_ping=True)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
