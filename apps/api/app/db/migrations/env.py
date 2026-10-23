import asyncio

from alembic import context
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.models import Base

config = context.config
target_metadata = Base.metadata

# Tests pass the URL and app role in explicitly; otherwise they come from Settings.
if "url" not in config.attributes:
    from app.config import get_settings

    settings = get_settings()
    config.attributes["url"] = settings.migrations_database_url or settings.database_url
    config.attributes["app_db_user"] = settings.app_db_user


def run_offline() -> None:
    context.configure(
        url=config.attributes["url"], target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        # Every API pod runs the migrations before it starts (Helm init container); the lock
        # makes them take turns, and the later ones find nothing left to do.
        connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('daleel-migrations'))"))
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(config.attributes["url"], poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
