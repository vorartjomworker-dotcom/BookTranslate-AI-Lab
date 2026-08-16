from __future__ import annotations

from typing import AsyncGenerator

import jwt
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.dependencies.db import get_db
from app.main import app


@pytest.fixture
def auth_client(async_session_factory):
    async def override_get_db() -> AsyncGenerator:
        async with async_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.parametrize("subject", ["not-a-number", None])
def test_me_rejects_signed_token_with_invalid_subject_as_401(auth_client, subject) -> None:
    token = jwt.encode(
        {"sub": subject, "token_type": "access"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    response = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401, response.text
    body = response.json()
    assert body["code"] == "unauthorized"
    assert body["message"] == "Invalid or expired token."
    assert body.get("request_id")
