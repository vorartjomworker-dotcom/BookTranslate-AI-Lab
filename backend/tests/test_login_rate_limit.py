from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

import app.auth.rate_limit as rate_limit
from app.core.exceptions import APIError
from app.dependencies.db import get_db
from app.main import app


class _FakeRedis:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple] = []
        self.closed = False

    async def eval(self, *args):
        self.calls.append(args)
        if self.error is not None:
            raise self.error
        return self.response

    async def aclose(self) -> None:
        self.closed = True


def _install_fake_redis(monkeypatch, fake: _FakeRedis) -> None:
    monkeypatch.setattr(rate_limit.Redis, "from_url", lambda *_args, **_kwargs: fake)


@pytest.mark.asyncio
async def test_login_rate_limit_allows_attempt_below_both_limits(monkeypatch) -> None:
    fake = _FakeRedis(response=[1, 59, 1, 59])
    _install_fake_redis(monkeypatch, fake)

    await rate_limit.enforce_login_rate_limit(email="User@Example.com", client_ip="203.0.113.7")

    assert fake.closed is True
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_login_rate_limit_blocks_account_and_sets_retry_after(monkeypatch) -> None:
    fake = _FakeRedis(response=[6, 41, 1, 58])
    _install_fake_redis(monkeypatch, fake)

    with pytest.raises(APIError) as exc_info:
        await rate_limit.enforce_login_rate_limit(email="user@example.com", client_ip="203.0.113.7")

    error = exc_info.value
    assert error.http_status == 429
    assert error.code == "rate_limited"
    assert error.headers["Retry-After"] == "41"


@pytest.mark.asyncio
async def test_login_rate_limit_blocks_ip_and_uses_longest_applicable_retry_after(monkeypatch) -> None:
    fake = _FakeRedis(response=[6, 12, 31, 37])
    _install_fake_redis(monkeypatch, fake)

    with pytest.raises(APIError) as exc_info:
        await rate_limit.enforce_login_rate_limit(email="user@example.com", client_ip="203.0.113.7")

    assert exc_info.value.http_status == 429
    assert exc_info.value.headers["Retry-After"] == "37"


@pytest.mark.asyncio
async def test_login_rate_limit_fails_closed_when_redis_is_unavailable(monkeypatch) -> None:
    fake = _FakeRedis(error=RedisError("redis unavailable"))
    _install_fake_redis(monkeypatch, fake)

    with pytest.raises(APIError) as exc_info:
        await rate_limit.enforce_login_rate_limit(email="user@example.com", client_ip="203.0.113.7")

    error = exc_info.value
    assert error.http_status == 503
    assert error.code == "service_unavailable"
    assert fake.closed is True


@pytest.mark.asyncio
async def test_login_rate_limit_does_not_send_raw_identity_values_to_redis(monkeypatch) -> None:
    fake = _FakeRedis(response=[1, 59, 1, 59])
    _install_fake_redis(monkeypatch, fake)

    email = "Sensitive.User@Example.com"
    client_ip = "203.0.113.77"
    await rate_limit.enforce_login_rate_limit(email=email, client_ip=client_ip)

    call_text = " ".join(str(value) for value in fake.calls[0])
    assert email.lower() not in call_text.lower()
    assert client_ip not in call_text
    assert "auth:login:account:" in call_text
    assert "auth:login:ip:" in call_text


def test_login_endpoint_preserves_rate_limit_contract_and_retry_after(monkeypatch) -> None:
    async def reject_login_attempt(**_kwargs) -> None:
        raise APIError(
            "Too many login attempts. Please try again later.",
            code="rate_limited",
            http_status=429,
            headers={"Retry-After": "17"},
        )

    async def unused_db():
        yield object()

    monkeypatch.setattr("app.api.v1.auth.enforce_login_rate_limit", reject_login_attempt)
    app.dependency_overrides[get_db] = unused_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "not-used"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "17"
    body = response.json()
    assert body["code"] == "rate_limited"
    assert body["message"] == "Too many login attempts. Please try again later."
    assert body["request_id"] == response.headers["X-Request-ID"]
