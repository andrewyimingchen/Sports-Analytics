from nba_insights.api.app import healthcheck, readiness


def test_healthcheck_has_no_runtime_dependencies():
    assert healthcheck() == {"status": "ok"}


def test_readiness_reports_shell_and_optional_models():
    result = readiness()
    assert result["status"] == "ready"
    assert result["pwa_shell"] is True
    assert set(result["optional_models"]) == {"outcome", "points", "lineup"}

