"""Async SQLAlchemy engine, session factory, and FastAPI DB dependency.

A single module-level async engine and session factory are shared across
the application; `get_db` is the dependency-injection entrypoint routers
and services use to obtain a request-scoped `AsyncSession`.
"""

import asyncio
import sys
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

if sys.platform == "win32":
    # psycopg's async driver requires the selector event loop; asyncio's
    # default ProactorEventLoop on Windows cannot drive it.
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=settings.db_pool_pre_ping,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped `AsyncSession` for use with `Depends`.

    Rolls back the transaction if the caller raises, and always closes
    the session, returning its connection to the pool.
    """
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
