from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from nba_insights.api import app
from nba_insights.api.security import (
    _BUDGET,
    client_identity,
    is_local_request,
    protect_ai,
    protect_simulation,
    require_private_access,
    require_simulation_access,
)


def _request(host: str, headers: dict[str, str] | None = None) -> Request:
    encoded = [
        (name.lower().encode(), value.encode())
        for name, value in (headers or {}).items()
    ]
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": encoded,
            "client": (host, 12345),
            "server": ("testserver", 80),
        }
    )


@pytest.fixture(autouse=True)
def reset_security(monkeypatch):
    for name in (
        "POSSESSION_LAB_API_KEY",
        "POSSESSION_LAB_REQUIRE_API_KEY",
        "POSSESSION_LAB_TRUSTED_PROXY_IPS",
        "POSSESSION_LAB_SIMULATION_BUDGET",
        "POSSESSION_LAB_AI_REQUEST_BUDGET",
        "POSSESSION_LAB_RATE_WINDOW_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    _BUDGET.clear()
    yield
    _BUDGET.clear()


def test_local_access_rejects_untrusted_forwarding_headers():
    assert is_local_request(_request("127.0.0.1"))
    forwarded = _request("127.0.0.1", {"X-Forwarded-For": "198.51.100.7"})
    assert not is_local_request(forwarded)


def test_trusted_proxy_resolves_original_client(monkeypatch):
    monkeypatch.setenv("POSSESSION_LAB_TRUSTED_PROXY_IPS", "127.0.0.1")
    request = _request("127.0.0.1", {"X-Forwarded-For": "198.51.100.7"})
    assert client_identity(request) == "198.51.100.7"
    assert not is_local_request(request)


def test_private_remote_access_is_disabled_without_a_key():
    with pytest.raises(HTTPException) as error:
        require_private_access(_request("198.51.100.7"))
    assert error.value.status_code == 403


def test_private_remote_access_accepts_configured_bearer_key(monkeypatch):
    monkeypatch.setenv("POSSESSION_LAB_API_KEY", "correct-horse")
    with pytest.raises(HTTPException) as error:
        require_private_access(_request("198.51.100.7"))
    assert error.value.status_code == 401
    require_private_access(
        _request("198.51.100.7", {"Authorization": "Bearer correct-horse"})
    )


def test_simulation_budget_is_weighted_by_requested_work(monkeypatch):
    monkeypatch.setenv("POSSESSION_LAB_SIMULATION_BUDGET", "1000")
    request = _request("198.51.100.7")
    protect_simulation(request, cost=600)
    with pytest.raises(HTTPException) as error:
        protect_simulation(request, cost=500)
    assert error.value.status_code == 429
    assert int(error.value.headers["Retry-After"]) >= 1


def test_simulation_auth_can_be_required_for_remote_callers(monkeypatch):
    monkeypatch.setenv("POSSESSION_LAB_REQUIRE_API_KEY", "true")
    monkeypatch.setenv("POSSESSION_LAB_API_KEY", "secret")
    with pytest.raises(HTTPException) as error:
        protect_simulation(_request("198.51.100.7"), cost=1000)
    assert error.value.status_code == 401
    protect_simulation(
        _request("198.51.100.7", {"X-API-Key": "secret"}),
        cost=1000,
    )


def test_ai_requires_remote_auth_and_has_its_own_budget(monkeypatch):
    monkeypatch.setenv("POSSESSION_LAB_API_KEY", "secret")
    monkeypatch.setenv("POSSESSION_LAB_AI_REQUEST_BUDGET", "1")
    request = _request("198.51.100.7", {"X-API-Key": "secret"})
    protect_ai(request)
    with pytest.raises(HTTPException) as error:
        protect_ai(request)
    assert error.value.status_code == 429


def _route_dependencies(path: str, method: str) -> set:
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == path and method in getattr(route, "methods", set())
    )
    return {dependency.call for dependency in route.dependant.dependencies}


def test_sensitive_guards_run_as_route_dependencies():
    assert protect_ai in _route_dependencies("/ask", "POST")
    assert require_private_access in _route_dependencies(
        "/players/{player_id}/contract", "GET"
    )
    for path, method in (
        ("/predict/simulate", "GET"),
        ("/predict/season", "GET"),
        ("/predict/season/scenario", "POST"),
    ):
        assert require_simulation_access in _route_dependencies(path, method)
