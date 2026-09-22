"""认证与来源校验。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from kel.security import new_session_token, redact


def test_token_must_match_exactly(client: TestClient, settings):
    assert client.get("/v1/sessions").status_code == 200
    other = new_session_token()
    assert client.get(
        "/v1/sessions", headers={"Authorization": f"Bearer {other}"}
    ).status_code == 401
    assert client.get(
        "/v1/sessions", headers={"Authorization": settings.session_token}
    ).status_code == 401


def test_desktop_origins_are_allowed(client: TestClient):
    for origin in ("tauri://localhost", "http://tauri.localhost", "http://127.0.0.1:5273"):
        response = client.get("/v1/sessions", headers={"Origin": origin})
        assert response.status_code == 200, origin


def test_foreign_origin_is_rejected(client: TestClient):
    response = client.get("/v1/sessions", headers={"Origin": "https://evil.example.com"})
    assert response.status_code == 403


def test_preflight_from_desktop_origin_is_allowed(client: TestClient):
    """带 Authorization 头的请求会触发预检；没有 CORS 头 webview 会报 Load failed。"""
    for origin in ("tauri://localhost", "http://tauri.localhost", "http://127.0.0.1:5273"):
        response = client.options(
            "/v1/sessions",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert response.status_code == 200, origin
        assert response.headers["access-control-allow-origin"] == origin
        assert "authorization" in response.headers["access-control-allow-headers"].lower()


def test_actual_request_carries_allow_origin_header(client: TestClient):
    response = client.get("/v1/sessions", headers={"Origin": "tauri://localhost"})
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"


def test_preflight_from_foreign_origin_has_no_cors_headers(client: TestClient):
    response = client.options(
        "/v1/sessions",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert "access-control-allow-origin" not in response.headers


def test_redact_removes_secrets():
    assert redact("key=abc123 path=/Users/foo", "abc123", "/Users/foo") == "key=*** path=***"
