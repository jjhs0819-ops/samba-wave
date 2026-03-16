import asyncio
import logging
import warnings
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from weakref import WeakKeyDictionary

from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.core.config import settings

# Suppress SQLAlchemy warnings about non-checked-in connections
warnings.filterwarnings(
    "ignore",
    message=".*non-checked-in connection.*",
    category=Warning,
)

logger = logging.getLogger(__name__)

_sessionmaker_cache: "WeakKeyDictionary[Any, Any]" = (
    WeakKeyDictionary()
)  # engine ↔ sessionmaker
_write_engine_cache: "WeakKeyDictionary[asyncio.AbstractEventLoop, Any]" = (
    WeakKeyDictionary()
)
_read_engine_cache: "WeakKeyDictionary[asyncio.AbstractEventLoop, Any]" = (
    WeakKeyDictionary()
)

write_db_url = URL.create(
    "postgresql",
    username=settings.write_db_user,
    password=settings.write_db_password,
    host=settings.write_db_host,
    port=settings.write_db_port,
    database=settings.write_db_name,
)

read_db_url = URL.create(
    "postgresql",
    username=settings.read_db_user,
    password=settings.read_db_password,
    host=settings.read_db_host,
    port=settings.read_db_port,
    database=settings.read_db_name,
)


def _build_db_url(user: str, password: str, host: str, port: int, name: str) -> str:
    """Build database URL with optional SSL parameter."""
    base_url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{name}"
    if settings.db_ssl_required:
        return f"{base_url}?ssl=require"
    return base_url


def _create_write_async_engine() -> AsyncEngine:
    return create_async_engine(
        _build_db_url(
            settings.write_db_user,
            settings.write_db_password,
            settings.write_db_host,
            settings.write_db_port,
            settings.write_db_name,
        ),
        future=True,
        echo=False,  # Disable SQL echo to reduce noise
        pool_pre_ping=True,  # Check connection validity before using
        pool_size=15,  # Connection pool size (increased from 5)
        max_overflow=25,  # Additional connections allowed (increased from 10)
        pool_recycle=3600,  # Recycle connections after 1 hour
        pool_timeout=30,  # Connection timeout in seconds
    )


def _create_read_async_engine() -> AsyncEngine:
    return create_async_engine(
        _build_db_url(
            settings.read_db_user,
            settings.read_db_password,
            settings.read_db_host,
            settings.read_db_port,
            settings.read_db_name,
        ),
        future=True,
        echo=False,  # Disable SQL echo to reduce noise
        pool_pre_ping=True,  # Check connection validity before using
        pool_size=15,  # Connection pool size (increased from 5)
        max_overflow=25,  # Additional connections allowed (increased from 10)
        pool_recycle=3600,  # Recycle connections after 1 hour
        pool_timeout=30,  # Connection timeout in seconds
    )


def get_write_engine() -> Any:
    loop = asyncio.get_running_loop()
    if loop not in _write_engine_cache:
        _write_engine_cache[loop] = _create_write_async_engine()
    return _write_engine_cache[loop]


def get_read_engine() -> Any:
    loop = asyncio.get_running_loop()
    if loop not in _read_engine_cache:
        _read_engine_cache[loop] = _create_read_async_engine()
    return _read_engine_cache[loop]


def get_write_sessionmaker() -> Any:
    engine = get_write_engine()
    if engine not in _sessionmaker_cache:
        _sessionmaker_cache[engine] = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _sessionmaker_cache[engine]


def get_read_sessionmaker() -> Any:
    engine = get_read_engine()
    if engine not in _sessionmaker_cache:
        _sessionmaker_cache[engine] = async_sessionmaker(
            engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _sessionmaker_cache[engine]


@asynccontextmanager
async def get_write_session() -> AsyncGenerator[AsyncSession, None]:
    Session = get_write_sessionmaker()
    async with Session() as sess:
        yield sess


@asynccontextmanager
async def get_read_session() -> AsyncGenerator[AsyncSession, None]:
    Session = get_read_sessionmaker()
    async with Session() as sess:
        yield sess


# Non-decorator versions for dependency injection
async def get_write_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for write sessions with guaranteed cleanup.

    Uses try/finally instead of async with to ensure session.close() is called
    even when client disconnects or exceptions occur during request processing.
    """
    Session = get_write_sessionmaker()
    session = Session()
    try:
        yield session
    finally:
        await session.close()


async def get_read_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency for read sessions with guaranteed cleanup.

    Uses try/finally instead of async with to ensure session.close() is called
    even when client disconnects or exceptions occur during request processing.
    """
    Session = get_read_sessionmaker()
    session = Session()
    try:
        yield session
    finally:
        await session.close()
