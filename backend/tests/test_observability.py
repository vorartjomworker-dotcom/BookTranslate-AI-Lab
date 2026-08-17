import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings as app_settings
from app.main import app
from app.metrics import route_template
from app.observability import build_http_request_event, log_http_request


def test_log_level_is_normalized_and_validated() -> None:
    settings = Settings(jwt_secret="x" * 32, log_level=" warning ")
    assert settings.log_level == "WARNING"


def test_metrics_config_is_fail_closed() -> None:
    disabled = Settings(jwt_secret="x" * 32)
    assert disabled.metrics_enabled is False
    assert disabled.metrics_bearer_token == ""

    with pytest.raises(ValueError, match="metrics_bearer_token"):
        Settings(jwt_secret="x" * 32, metrics_enabled=True, metrics_bearer_token="too-short")

    enabled = Settings(
        jwt_secret="x" * 32,
        metrics_enabled=True,
        metrics_bearer_token="m" * 32,
    )
    assert enabled.metrics_enabled is True
    assert enabled.metrics_bearer_token == "m" * 32


def test_http_event_contains_only_safe_request_metadata() -> None:
    event = build_http_request_event(
        request_id="req-123",
        method="POST",
        path="/api/v1/auth/login",
        status_code=401,
        duration_ms=12.34567,
    )

    assert set(event) == {
        "timestamp",
        "event",
        "request_id",
        "method",
        "path",
        "status_code",
        "duration_ms",
    }
    assert event["event"] == "http_request"
    assert event["duration_ms"] == 12.346

    serialized = json.dumps(event)
    for forbidden in ("password", "authorization", "bearer", "client_ip", "query"):
        assert forbidden not in serialized.lower()


def test_request_middleware_logs_path_without_query_string_or_secret() -> None:
    with patch("app.main.log_http_request") as mock_log:
        with TestClient(app) as client:
            response = client.get(
                "/health/live?access_token=super-secret-query-value",
                headers={"Authorization": "Bearer super-secret-header-value"},
            )

    assert response.status_code == 200
    mock_log.assert_called_once()
    kwargs = mock_log.call_args.kwargs
    assert kwargs["request_id"] == response.headers["X-Request-ID"]
    assert kwargs["method"] == "GET"
    assert kwargs["path"] == "/health/live"
    assert kwargs["status_code"] == 200
    assert kwargs["duration_ms"] >= 0

    rendered = repr(kwargs).lower()
    assert "super-secret-query-value" not in rendered
    assert "super-secret-header-value" not in rendered
    assert "access_token" not in rendered
    assert "authorization" not in rendered


def test_request_metrics_use_route_templates_not_arbitrary_paths() -> None:
    assert route_template({"route": SimpleNamespace(path="/api/v1/books/{book_id}")}) == "/api/v1/books/{book_id}"
    assert route_template({}) == "__unmatched__"

    with patch("app.main.observe_http_request") as observe:
        with TestClient(app) as client:
            response = client.get("/health/live?unique=123")

    assert response.status_code == 200
    observe.assert_called_once()
    kwargs = observe.call_args.kwargs
    assert kwargs["method"] == "GET"
    assert kwargs["route"] == "/health/live"
    assert kwargs["status_code"] == 200
    assert kwargs["duration_seconds"] >= 0


def test_metrics_endpoint_is_disabled_by_default() -> None:
    with patch.object(app_settings, "metrics_enabled", False):
        with TestClient(app) as client:
            response = client.get("/metrics")

    assert response.status_code == 404
    assert response.headers["X-Request-ID"]


def test_metrics_endpoint_requires_dedicated_bearer_token() -> None:
    token = "metrics-test-token-0123456789abcdef"
    with patch.object(app_settings, "metrics_enabled", True), \
         patch.object(app_settings, "metrics_bearer_token", token):
        with TestClient(app) as client:
            missing = client.get("/metrics")
            wrong = client.get("/metrics", headers={"Authorization": "Bearer wrong-token"})
            client.get("/health/live")
            success = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})

    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"
    assert wrong.status_code == 401
    assert success.status_code == 200
    assert "text/plain" in success.headers["content-type"]
    assert "booktranslate_http_requests_total" in success.text
    assert "booktranslate_http_request_duration_seconds" in success.text
    assert token not in success.text


def test_http_logger_uses_status_severity() -> None:
    with patch("app.observability._http_logger.info") as info, \
         patch("app.observability._http_logger.warning") as warning, \
         patch("app.observability._http_logger.error") as error:
        log_http_request(request_id="1", method="GET", path="/ok", status_code=200, duration_ms=1)
        log_http_request(request_id="2", method="GET", path="/missing", status_code=404, duration_ms=2)
        log_http_request(request_id="3", method="GET", path="/error", status_code=500, duration_ms=3)

    info.assert_called_once()
    warning.assert_called_once()
    error.assert_called_once()


def test_http_logger_failure_never_escapes() -> None:
    with patch("app.observability._http_logger.info", side_effect=RuntimeError("logging backend down")):
        log_http_request(
            request_id="req-fail-safe",
            method="GET",
            path="/health/live",
            status_code=200,
            duration_ms=1,
        )
