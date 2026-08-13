"""Test fixtures and configuration."""

from typing import AsyncGenerator

import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """Provide a test client for the FastAPI app."""
    return TestClient(app)


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
