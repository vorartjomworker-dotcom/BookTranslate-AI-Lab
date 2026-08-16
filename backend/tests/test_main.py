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


def test_cors_preflight_does_not_allow_credentials(client: TestClient) -> None:
    """Bearer-only CORS must not advertise browser credential support."""
    response = client.options(
        "/api/v1/books",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-credentials" not in response.headers


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


def test_health_legacy_alias_contract_is_frozen(client: TestClient) -> None:
    """Pin the exact legacy /health contract so liveness and readiness never get re-mixed into it."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert set(data.keys()) == {"status", "database", "redis"}
    assert data["status"] in {"ok", "degraded"}
    assert isinstance(data["database"], bool)
    assert isinstance(data["redis"], bool)


def test_health_live_returns_200_with_no_dependency_patching(client: TestClient) -> None:
    """Liveness must succeed whenever the process is up, with zero dependency involvement."""
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_live_returns_200_when_both_dependencies_down() -> None:
    """Liveness stays 200 even if database and redis are both unreachable."""
    with patch("app.main.check_database", new_callable=AsyncMock) as mock_db, \
         patch("app.main.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.side_effect = Exception("Connection refused")
        mock_redis.side_effect = Exception("Connection refused")

        client = TestClient(app)
        response = client.get("/health/live")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_ready_returns_200_when_both_ok() -> None:
    """Readiness is 200 only when both database and redis are reachable."""
    with patch("app.main.check_database", new_callable=AsyncMock) as mock_db, \
         patch("app.main.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.return_value = True
        mock_redis.return_value = True

        client = TestClient(app)
        response = client.get("/health/ready")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["database"] is True
        assert data["redis"] is True


@pytest.mark.asyncio
async def test_health_ready_returns_503_when_database_down() -> None:
    """Readiness must be 503 when the database dependency is unreachable."""
    with patch("app.main.check_database", new_callable=AsyncMock) as mock_db, \
         patch("app.main.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.side_effect = Exception("Connection refused")
        mock_redis.return_value = True

        client = TestClient(app)
        response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] is False
        assert data["redis"] is True


@pytest.mark.asyncio
async def test_health_ready_returns_503_when_redis_down() -> None:
    """Readiness must be 503 when the redis dependency is unreachable."""
    with patch("app.main.check_database", new_callable=AsyncMock) as mock_db, \
         patch("app.main.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.return_value = True
        mock_redis.side_effect = Exception("Connection refused")

        client = TestClient(app)
        response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] is True
        assert data["redis"] is False


@pytest.mark.asyncio
async def test_health_ready_returns_503_when_both_down() -> None:
    """Readiness must be 503 when both database and redis are unreachable."""
    with patch("app.main.check_database", new_callable=AsyncMock) as mock_db, \
         patch("app.main.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.side_effect = Exception("Connection refused")
        mock_redis.side_effect = Exception("Connection refused")

        client = TestClient(app)
        response = client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] is False
        assert data["redis"] is False


@pytest.mark.asyncio
async def test_health_endpoints_never_leak_secrets() -> None:
    """No health endpoint payload may expose DSNs, URLs, credentials, or tracebacks."""
    forbidden_substrings = ("postgresql", "redis://", "password", "traceback", "DATABASE_URL", "REDIS_URL")
    with patch("app.main.check_database", new_callable=AsyncMock) as mock_db, \
         patch("app.main.check_redis", new_callable=AsyncMock) as mock_redis:
        mock_db.side_effect = Exception("Connection refused: postgresql://user:pass@host/db")
        mock_redis.side_effect = Exception("Connection refused: redis://user:pass@host:6379/0")

        client = TestClient(app)
        for path in ("/health", "/health/live", "/health/ready"):
            response = client.get(path)
            body_text = response.text.lower()
            for needle in forbidden_substrings:
                assert needle.lower() not in body_text, f"{path} leaked forbidden content: {needle}"
