"""Regression tests for the public-read/protected-write security boundary."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from growth.admin_auth import issue_token, require_admin
from utils.security import get_client_id, require_api_key


def _request(method="GET", headers=None):
    raw_headers = [
        (key.lower().encode(), value.encode())
        for key, value in (headers or {}).items()
    ]
    return Request({
        "type": "http",
        "method": method,
        "scheme": "https",
        "path": "/",
        "headers": raw_headers,
        "client": ("203.0.113.10", 1234),
        "server": ("api.example.com", 443),
    })


def test_protected_routes_fail_closed_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("API_KEY", raising=False)

    with pytest.raises(HTTPException) as exc:
        require_api_key(_request())

    assert exc.value.status_code == 503


def test_api_key_accepts_valid_server_side_secret(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_KEY", "server-only-secret")

    require_api_key(_request(headers={"X-API-Key": "server-only-secret"}))


def test_rate_limit_identity_does_not_change_with_user_agent():
    first = _request(headers={"User-Agent": "agent-one"})
    second = _request(headers={"User-Agent": "agent-two"})

    assert get_client_id(first) == get_client_id(second)


def test_admin_rejects_cross_origin_write(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "configured")
    token = issue_token()
    request = _request(
        method="POST",
        headers={"Host": "api.example.com", "Origin": "https://attacker.example"},
    )

    with pytest.raises(HTTPException) as exc:
        require_admin(request, token)

    assert exc.value.status_code == 403
