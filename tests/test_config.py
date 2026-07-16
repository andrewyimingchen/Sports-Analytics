from datetime import date

from nba_insights.config import current_season, seasons_since


def test_season_rolls_over_in_october():
    assert current_season(date(2026, 9, 30)) == "2025-26"
    assert current_season(date(2026, 10, 1)) == "2026-27"


def test_midseason_dates_belong_to_running_season():
    assert current_season(date(2026, 1, 15)) == "2025-26"
    assert current_season(date(2026, 7, 14)) == "2025-26"


def test_seasons_since_newest_first_down_to_dashboard_era():
    out = seasons_since(today=date(2026, 7, 16))
    assert out[0] == "2025-26"  # current season leads
    assert out[-1] == "1996-97"  # dashboard data ends here
    assert len(out) == 30
    assert seasons_since(2024, today=date(2026, 7, 16)) == ["2025-26", "2024-25"]
