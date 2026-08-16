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
from app.dependencies.auth import get_current_user
from app.dependencies.db import get_db


@pytest.fixture
def client():
    """Provide an unauthenticated test client and always run FastAPI shutdown."""
    with TestClient(app) as test_client:
        yield test_client


def _rbac_stub_client(role: str) -> TestClient:
    """Return a role stub for unit tests that are not validating JWT authentication.

    This intentionally overrides ``get_current_user`` and deliberately does not attach
    an Authorization header. Tests that need to validate token parsing/user lookup must
    use ``real_auth_client`` instead.
    """
    user = User(id=1, email=f"{role}@example.com", normalized_email=f"{role}@example.com", role=role, is_active=True)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture(name="admin_client")
def admin_rbac_stub_client() -> TestClient:
    """Admin RBAC stub; JWT authentication is intentionally bypassed."""
    test_client = _rbac_stub_client("admin")
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(name="editor_client")
def editor_rbac_stub_client() -> TestClient:
    """Editor RBAC stub; JWT authentication is intentionally bypassed."""
    test_client = _rbac_stub_client("editor")
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(name="viewer_client")
def viewer_rbac_stub_client() -> TestClient:
    """Viewer RBAC stub; JWT authentication is intentionally bypassed."""
    test_client = _rbac_stub_client("viewer")
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
def real_auth_client(async_session_factory) -> TestClient:
    """Client that exercises the real JWT -> user lookup -> active/RBAC dependency chain.

    Only the database dependency is redirected to the isolated test database.
    ``get_current_user`` is never overridden here.
    """

    async def override_get_db():
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


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
    """Mock Redis connection."""
    return AsyncMock(return_value=True)
