"""Failure categories: client retries, cache fallback, and API error handling."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest
import requests
from fastapi.testclient import TestClient

from nba_insights import errors
from nba_insights.api import app
from nba_insights.api.deps import get_client
from nba_insights.errors import (
    FAILURES,
    ArtifactUnavailableError,
    DataUnavailableError,
    ProviderError,
    UpstreamError,
    reason_for,
)
from nba_insights.ingest import NBAClient
from nba_insights.store import Cache


@pytest.fixture(autouse=True)
def reset_failures():
    FAILURES.clear()
    yield
    FAILURES.clear()


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (UpstreamError("x"), "upstream_unavailable"),
        (DataUnavailableError("x"), "data_unavailable"),
        (ArtifactUnavailableError("x"), "artifact_unavailable"),
        (ProviderError("x"), "provider_failed"),
        (KeyError("PTS"), "data_unavailable"),
        (ValueError("bad"), "data_unavailable"),
        (IndexError("empty"), "data_unavailable"),
        (TypeError("bug"), "internal_error"),
    ],
)
def test_reason_codes_are_stable(error, reason):
    assert reason_for(error) == reason


def test_failure_counter_tallies_by_reason():
    FAILURES.record("upstream_unavailable")
    FAILURES.record("upstream_unavailable")
    FAILURES.record("data_unavailable")
    assert FAILURES.snapshot() == {"data_unavailable": 1, "upstream_unavailable": 2}
    assert errors.FAILURES is FAILURES


def _client(tmp_path) -> NBAClient:
    return NBAClient(cache=Cache(tmp_path / "cache.sqlite3"), delay=0, retries=2)


def test_fetch_failures_retry_then_raise_upstream_error(tmp_path, monkeypatch):
    monkeypatch.setattr("nba_insights.ingest.client.time.sleep", lambda seconds: None)
    calls = []

    def flaky():
        calls.append(1)
        raise requests.ConnectionError("stats.nba.com timed out")

    with pytest.raises(UpstreamError, match="team_games/2025-26") as raised:
        _client(tmp_path)._cached("team_games/2025-26", flaky, ttl=None)
    assert len(calls) == 2
    assert isinstance(raised.value.__cause__, requests.ConnectionError)


def test_defects_in_a_fetch_propagate_without_retry(tmp_path, monkeypatch):
    monkeypatch.setattr("nba_insights.ingest.client.time.sleep", lambda seconds: None)
    calls = []

    def buggy():
        calls.append(1)
        raise TypeError("unsupported operand")

    with pytest.raises(TypeError):
        _client(tmp_path)._cached("k", buggy, ttl=None)
    assert len(calls) == 1


def test_cache_serves_stale_only_for_upstream_failures(tmp_path):
    clock_now = [pd.Timestamp("2026-10-01", tz="UTC").to_pydatetime()]
    cache = Cache(tmp_path / "cache.sqlite3", now=lambda: clock_now[0])
    frame = pd.DataFrame({"PTS": [1]})
    cache.put("k", frame)
    clock_now[0] += timedelta(days=3)

    def down():
        raise UpstreamError("down")

    def buggy():
        raise TypeError("bug")

    pd.testing.assert_frame_equal(cache.get_or_fetch("k", down, ttl=timedelta(days=1)), frame)
    with pytest.raises(TypeError):
        cache.get_or_fetch("k", buggy, ttl=timedelta(days=1))


class _BrokenClient:
    def __init__(self, error: Exception):
        self.error = error

    def schedule(self, season=None):
        raise self.error


@pytest.mark.parametrize(
    ("error", "status", "reason"),
    [
        (
            UpstreamError("fetch schedule/2025-26 failed after 3 attempts"),
            503,
            "upstream_unavailable",
        ),
        (DataUnavailableError("schedule lacks GAME_ID"), 503, "data_unavailable"),
        (TypeError("secret-bearing defect text"), 500, "internal_error"),
    ],
)
def test_central_handler_maps_failures_to_reason_codes(error, status, reason):
    app.dependency_overrides[get_client] = lambda: _BrokenClient(error)
    try:
        response = TestClient(app, raise_server_exceptions=False).get("/games")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == status
    assert response.json()["reason"] == reason
    # unexpected exception text is logged, never returned
    assert "secret-bearing" not in response.text
    assert FAILURES.snapshot() == {reason: 1}


def test_readiness_reports_failure_counts():
    FAILURES.record("upstream_unavailable")
    body = TestClient(app).get("/readyz").json()
    assert body["failures"] == {"upstream_unavailable": 1}
