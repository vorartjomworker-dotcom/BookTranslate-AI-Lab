from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


VALID_SECRET = "test-only-secret-for-jwt-config-at-least-32-chars"


def test_jwt_algorithm_defaults_to_hs256() -> None:
    configured = Settings(jwt_secret=VALID_SECRET)
    assert configured.jwt_algorithm == "HS256"


@pytest.mark.parametrize("secret", ["", "x" * 31])
def test_jwt_secret_requires_at_least_32_characters(secret: str) -> None:
    with pytest.raises(ValidationError, match="jwt_secret must contain at least 32 characters"):
        Settings(jwt_secret=secret)


def test_jwt_algorithm_normalizes_hs256_case() -> None:
    configured = Settings(jwt_secret=VALID_SECRET, jwt_algorithm="hs256")
    assert configured.jwt_algorithm == "HS256"


@pytest.mark.parametrize("algorithm", ["RS256", "HS512", "none", "", " ES256 "])
def test_jwt_algorithm_rejects_non_hs256_values(algorithm: str) -> None:
    with pytest.raises(ValidationError, match="jwt_algorithm must be HS256"):
        Settings(jwt_secret=VALID_SECRET, jwt_algorithm=algorithm)
