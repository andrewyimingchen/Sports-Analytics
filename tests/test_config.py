from datetime import date

from nba_insights import config
from nba_insights.config import (
    calendar_season,
    current_season,
    next_season,
    prediction_seasons,
    seasons_since,
    set_season_started_check,
)


def test_calendar_season_rolls_over_in_october():
    assert calendar_season(date(2026, 9, 30)) == "2025-26"
    assert calendar_season(date(2026, 10, 1)) == "2026-27"
    # an explicit date is the pure calendar rule
    assert current_season(date(2026, 10, 1)) == "2026-27"


def test_new_season_waits_for_regular_season_games(monkeypatch):
    monkeypatch.setattr(config, "_today", lambda: date(2026, 10, 5))
    started = {"2026-27": False}
    calls = []

    def check(season):
        calls.append(season)
        return started[season]

    set_season_started_check(check)
    assert calendar_season() == "2026-27"
    assert current_season() == "2025-26"  # preseason: keep the finished season
    assert prediction_seasons() == ["2025-26", "2026-27"]
    assert seasons_since(2025) == ["2025-26"]
    assert current_season() == "2025-26"
    assert calls == ["2026-27"]  # memoized, not rechecked on every call

    started["2026-27"] = True
    set_season_started_check(check)  # re-registering clears the memo
    assert current_season() == "2026-27"


def test_season_check_only_runs_between_october_and_opening_night(monkeypatch):
    calls = []
    set_season_started_check(lambda season: calls.append(season) or False)
    monkeypatch.setattr(config, "_today", lambda: date(2027, 1, 15))
    assert current_season() == "2026-27"  # January: the season is under way
    monkeypatch.setattr(config, "_today", lambda: date(2026, 7, 16))
    assert current_season() == "2025-26"
    assert calls == []


def test_failed_season_check_keeps_prior_season(monkeypatch):
    monkeypatch.setattr(config, "_today", lambda: date(2026, 10, 5))

    def broken(season):
        raise RuntimeError("stats.nba.com unreachable")

    set_season_started_check(broken)
    assert current_season() == "2025-26"


def test_midseason_dates_belong_to_running_season():
    assert current_season(date(2026, 1, 15)) == "2025-26"
    assert current_season(date(2026, 7, 14)) == "2025-26"


def test_seasons_since_newest_first_down_to_dashboard_era():
    out = seasons_since(today=date(2026, 7, 16))
    assert out[0] == "2025-26"  # current season leads
    assert out[-1] == "1996-97"  # dashboard data ends here
    assert len(out) == 30
    assert seasons_since(2024, today=date(2026, 7, 16)) == ["2025-26", "2024-25"]


def test_prediction_seasons_include_upcoming_year():
    today = date(2026, 7, 21)
    assert next_season(today=today) == "2026-27"
    assert prediction_seasons(today) == ["2025-26", "2026-27"]
