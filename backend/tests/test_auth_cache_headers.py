from __future__ import annotations

from typing import AsyncGenerator

import pytest
from fastapi.testclient import TestClient

from app.core.security import hash_password
from app.dependencies.db import get_db
from app.main import app
from app.models import User


@pytest.fixture
def auth_cache_client(async_session_factory, monkeypatch):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    async def allow_login_attempt(**_kwargs) -> None:
        return None

    monkeypatch.setattr("app.api.v1.auth.enforce_login_rate_limit", allow_login_attempt)
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_login_token_response_disables_caching(auth_cache_client, async_session_factory) -> None:
    async with async_session_factory() as session:
        session.add(
            User(
                email="cache-control@example.com",
                password_hash=hash_password("cache-control-password-1"),
                role="viewer",
                is_active=True,
            )
        )
        await session.commit()

    response = auth_cache_client.post(
        "/api/v1/auth/login",
        json={"email": "cache-control@example.com", "password": "cache-control-password-1"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["access_token"]
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
