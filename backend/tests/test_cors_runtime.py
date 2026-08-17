from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def _preflight(client: TestClient, origin: str):
    return client.options(
        "/",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )


def test_allowed_loopback_origin_receives_exact_preflight_allow_origin() -> None:
    origin = "http://localhost:3000"
    with TestClient(app) as client:
        response = _preflight(client, origin)

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == origin
    assert "Access-Control-Allow-Credentials" not in response.headers
    assert response.headers.get("Vary") == "Origin"


def test_unlisted_remote_origin_preflight_is_rejected_without_acao() -> None:
    with TestClient(app) as client:
        response = _preflight(client, "https://untrusted.example")

    assert response.status_code == 400
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Access-Control-Allow-Credentials" not in response.headers


def test_unlisted_origin_simple_request_never_receives_acao() -> None:
    with TestClient(app) as client:
        response = client.get("/", headers={"Origin": "https://untrusted.example"})

    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers
    assert "Access-Control-Allow-Credentials" not in response.headers
