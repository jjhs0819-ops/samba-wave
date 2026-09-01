"""Pytest configuration and fixtures for backend tests."""

import pytest
from sqlmodel.ext.asyncio.session import AsyncSession

from backend.db.orm import get_write_sessionmaker


@pytest.fixture
async def db_session() -> AsyncSession:
    """Provide an AsyncSession for database tests.

    Creates a new session for each test and ensures it's cleaned up after.
    """
    Session = get_write_sessionmaker()
    async with Session() as session:
        yield session
