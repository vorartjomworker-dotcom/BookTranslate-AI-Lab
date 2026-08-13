"""Tests for main application endpoints."""

import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """Provide a test client for the FastAPI app."""
    return TestClient(app)


def test_root_endpoint(client: TestClient) -> None:
    """Test GET / endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "status" in data
    assert data["status"] == "running"
    assert "version" in data


def test_root_response_structure(client: TestClient) -> None:
    """Test root endpoint response structure."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, dict)
    assert all(isinstance(v, str) for v in data.values())


@pytest.mark.asyncio
async def test_health_check_both_ok() -> None:
    """Test health endpoint when both database and redis are OK."""
    with patch("app.main.check_database", new_callable=AsyncMock) as mock_db, \
         patch("app.main.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.return_value = True
        mock_redis.return_value = True

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["database"] is True
        assert data["redis"] is True


@pytest.mark.asyncio
async def test_health_check_database_down() -> None:
    """Test health endpoint when database is down."""
    with patch("app.main.check_database", new_callable=AsyncMock) as mock_db, \
         patch("app.main.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.side_effect = Exception("Connection refused")
        mock_redis.return_value = True

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] is False
        assert data["redis"] is True


@pytest.mark.asyncio
async def test_health_check_redis_down() -> None:
    """Test health endpoint when redis is down."""
    with patch("app.main.check_database", new_callable=AsyncMock) as mock_db, \
         patch("app.main.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.return_value = True
        mock_redis.side_effect = Exception("Connection refused")

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] is True
        assert data["redis"] is False


@pytest.mark.asyncio
async def test_health_check_both_down() -> None:
    """Test health endpoint when both database and redis are down."""
    with patch("app.main.check_database", new_callable=AsyncMock) as mock_db, \
         patch("app.main.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.side_effect = Exception("Connection refused")
        mock_redis.side_effect = Exception("Connection refused")

        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] is False
        assert data["redis"] is False
