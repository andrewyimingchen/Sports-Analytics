"""Suite-wide fixtures."""

from __future__ import annotations

from datetime import date

import pytest

from nba_insights import config

# Offseason date whose current season (2025-26) matches the fixture data, so
# results never depend on the day the suite runs.
PINNED_TODAY = date(2026, 7, 16)


@pytest.fixture(autouse=True)
def pinned_calendar(monkeypatch):
    monkeypatch.setattr(config, "_today", lambda: PINNED_TODAY)
    config.set_season_started_check(None)
    yield
    config.set_season_started_check(None)
