from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.core.config import Settings


JWT_SECRET = "cors-test-jwt-secret-at-least-32-characters-long"


def _settings(origins: list[str]) -> Settings:
    return Settings(jwt_secret=JWT_SECRET, cors_allowed_origins=origins)


def test_cors_allows_https_and_loopback_http_origins() -> None:
    settings = _settings(
        [
            "https://translate.example.com",
            "https://admin.example.com:8443",
            "http://localhost:3000",
            "http://127.0.0.1:3001",
            "http://[::1]:3002",
        ]
    )

    assert settings.cors_allowed_origins == [
        "https://translate.example.com",
        "https://admin.example.com:8443",
        "http://localhost:3000",
        "http://127.0.0.1:3001",
        "http://[::1]:3002",
    ]


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "null",
        "https://*",
        "http://example.com",
        "ftp://example.com",
        "https://user:password@example.com",
        "https://example.com/path",
        "https://example.com/?token=secret",
        "https://example.com/#fragment",
        "https://example.com:99999",
        "example.com",
        "",
    ],
)
def test_cors_rejects_wildcards_non_origins_and_insecure_remote_http(origin: str) -> None:
    with pytest.raises(PydanticValidationError):
        _settings([origin])


def test_cors_rejects_duplicate_origins() -> None:
    with pytest.raises(PydanticValidationError):
        _settings(["https://translate.example.com", "https://translate.example.com"])
