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
from app.models import User
from app.core.security import create_access_token
from app.dependencies.auth import get_current_user


@pytest.fixture
def client() -> TestClient:
    """Provide a test client for the FastAPI app."""
    return TestClient(app)


def _authenticated_client(role: str) -> TestClient:
    user = User(id=1, email=f"{role}@example.com", normalized_email=f"{role}@example.com", role=role, is_active=True)
    app.dependency_overrides[get_current_user] = lambda: user
    test_client = TestClient(app)
    test_client.headers.update({"Authorization": f"Bearer {create_access_token(user.id)}"})
    return test_client


@pytest.fixture
def admin_client() -> TestClient:
    test_client = _authenticated_client("admin")
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def editor_client() -> TestClient:
    test_client = _authenticated_client("editor")
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def viewer_client() -> TestClient:
    test_client = _authenticated_client("viewer")
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.pop(get_current_user, None)


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
