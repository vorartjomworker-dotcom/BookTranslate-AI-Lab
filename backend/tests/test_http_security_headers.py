from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


EXPECTED_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
}


def _assert_security_headers(response) -> None:
    for name, value in EXPECTED_SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_baseline_security_headers_are_present_on_success_and_error() -> None:
    with TestClient(app) as client:
        success = client.get("/")
        not_found = client.get("/definitely-not-a-real-route")

    assert success.status_code == 200
    assert not_found.status_code == 404
    _assert_security_headers(success)
    _assert_security_headers(not_found)
