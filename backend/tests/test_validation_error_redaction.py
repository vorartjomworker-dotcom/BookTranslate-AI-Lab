from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.security import PASSWORD_MAX_LENGTH
from app.main import app


def _assert_safe_validation_contract(payload: dict) -> None:
    assert payload["code"] == "validation_error"
    assert payload["message"] == "Validation error."
    assert isinstance(payload["request_id"], str)
    assert payload["request_id"]

    errors = payload["details"]["errors"]
    assert errors
    for error in errors:
        assert set(error) == {"type", "loc", "msg"}
        assert "input" not in error
        assert "ctx" not in error


def test_login_validation_error_does_not_reflect_password_input() -> None:
    secret_marker = "PASSWORD-MUST-NOT-BE-REFLECTED-9f4a2c"
    password = secret_marker + ("x" * (PASSWORD_MAX_LENGTH + 1))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "validation@example.com", "password": password},
        )

    assert response.status_code == 422
    payload = response.json()
    _assert_safe_validation_contract(payload)
    serialized = response.text
    assert secret_marker not in serialized
    assert password not in serialized
    assert any(error["loc"] == ["body", "password"] for error in payload["details"]["errors"])


def test_login_validation_error_does_not_reflect_forbidden_extra_input() -> None:
    secret_marker = "EXTRA-SECRET-MUST-NOT-BE-REFLECTED-a71d5e"

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={
                "email": "validation@example.com",
                "password": "valid-shape-password",
                "recovery_token": secret_marker,
            },
        )

    assert response.status_code == 422
    payload = response.json()
    _assert_safe_validation_contract(payload)
    assert secret_marker not in response.text
    assert any(error["loc"] == ["body", "recovery_token"] for error in payload["details"]["errors"])
