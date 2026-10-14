from nba_insights.api.app import healthcheck, readiness


def test_healthcheck_has_no_runtime_dependencies():
    assert healthcheck() == {"status": "ok"}


def test_readiness_reports_shell_and_optional_models():
    result = readiness()
    assert result["status"] == "ready"
    assert result["pwa_shell"] is True
    assert set(result["optional_models"]) == {"outcome", "points", "lineup"}


def test_season_check_is_installed_at_startup(monkeypatch):
    """/meta must not report an empty new season after a restart (Oct 1 to opening night)."""
    from datetime import date

    from fastapi.testclient import TestClient

    from nba_insights import config
    from nba_insights.api import app, deps

    class NotStartedClient:
        def season_has_started(self, season):
            return False

    monkeypatch.setattr(config, "_today", lambda: date(2026, 10, 13))
    monkeypatch.setattr(deps, "NBAClient", NotStartedClient)
    deps.get_client.cache_clear()
    try:
        with TestClient(app) as client:  # runs the lifespan, as uvicorn does
            # the first request touches no client-backed route
            assert client.get("/meta").json()["current_season"] == "2025-26"
    finally:
        deps.get_client.cache_clear()
