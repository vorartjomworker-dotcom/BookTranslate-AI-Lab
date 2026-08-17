from __future__ import annotations

import hashlib
import hmac

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.core.exceptions import APIError
from app.core.security import normalize_email

_LOGIN_RATE_LIMIT_WINDOW_SECONDS = 60
_LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS = 5
_LOGIN_RATE_LIMIT_IP_ATTEMPTS = 30

_RATE_LIMIT_SCRIPT = """
local account_count = redis.call('INCR', KEYS[1])
if account_count == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end

local ip_count = redis.call('INCR', KEYS[2])
if ip_count == 1 then
  redis.call('EXPIRE', KEYS[2], ARGV[1])
end

local account_ttl = redis.call('TTL', KEYS[1])
local ip_ttl = redis.call('TTL', KEYS[2])
return {account_count, account_ttl, ip_count, ip_ttl}
"""


def _rate_limit_key(namespace: str, value: str) -> str:
    digest = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        value.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"auth:login:{namespace}:{digest}"


async def enforce_login_rate_limit(*, email: str, client_ip: str) -> None:
    """Apply fail-closed Redis-backed login throttling without storing raw email/IP values."""
    normalized_email = normalize_email(email)
    account_key = _rate_limit_key("account", normalized_email)
    ip_key = _rate_limit_key("ip", client_ip or "unknown")

    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        values = await client.eval(
            _RATE_LIMIT_SCRIPT,
            2,
            account_key,
            ip_key,
            _LOGIN_RATE_LIMIT_WINDOW_SECONDS,
        )
    except RedisError as exc:
        raise APIError(
            "Authentication temporarily unavailable.",
            code="service_unavailable",
            http_status=503,
        ) from exc
    finally:
        try:
            await client.aclose()
        except RedisError:
            pass

    account_count, account_ttl, ip_count, ip_ttl = (int(value) for value in values)
    account_limited = account_count > _LOGIN_RATE_LIMIT_ACCOUNT_ATTEMPTS
    ip_limited = ip_count > _LOGIN_RATE_LIMIT_IP_ATTEMPTS

    if not (account_limited or ip_limited):
        return

    retry_after = max(
        account_ttl if account_limited else 0,
        ip_ttl if ip_limited else 0,
        1,
    )
    raise APIError(
        "Too many login attempts. Please try again later.",
        code="rate_limited",
        http_status=429,
        headers={"Retry-After": str(retry_after)},
    )
