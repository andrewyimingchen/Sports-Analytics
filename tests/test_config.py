from datetime import date

from nba_insights.config import current_season


def test_season_rolls_over_in_october():
    assert current_season(date(2026, 9, 30)) == "2025-26"
    assert current_season(date(2026, 10, 1)) == "2026-27"


def test_midseason_dates_belong_to_running_season():
    assert current_season(date(2026, 1, 15)) == "2025-26"
    assert current_season(date(2026, 7, 14)) == "2025-26"
