import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import db.models
from config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = db.models.Base.metadata


def _include_object(
    object: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    excluded_table = reflected and type_ == "table" and name == "spatial_ref_sys"
    excluded_index = reflected and type_ == "index" and name in {
        "ix_chunks_embedding_hnsw",
        "ix_chunks_metadata_gin",
        "ix_chunks_text_bm25",
    }
    return not (excluded_table or excluded_index)


def _run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run_migrations)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        include_object=_include_object,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_async_migrations())
