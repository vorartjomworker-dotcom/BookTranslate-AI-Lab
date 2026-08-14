"""Test fixtures and configuration."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.main import app
from app.models.base import Base


@pytest.fixture
def client() -> TestClient:
    """Provide a test client for the FastAPI app."""
    return TestClient(app)


@pytest_asyncio.fixture
async def async_session_factory():
    """Provide a lightweight SQLite-backed async session factory for unit tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def mock_database() -> AsyncMock:
    """Mock database connection."""
    return AsyncMock()


@pytest.fixture
async def mock_redis() -> AsyncMock:
    """Mock Redis connection."""
    return AsyncMock()


@pytest.fixture
def mock_check_database() -> AsyncMock:
    """Mock check_database function."""
    return AsyncMock(return_value=True)


@pytest.fixture
def mock_check_redis() -> AsyncMock:
    """Mock check_redis function."""
    return AsyncMock(return_value=True)
