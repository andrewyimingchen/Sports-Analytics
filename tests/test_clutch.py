"""Offline tests for the clutch shooting line extractor."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.analysis import clutch_shooting_line


def _clutch() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "PLAYER_ID": [1, 2, 3],
            "GP": [40, 35, 5],
            "MIN": [3.2, 2.8, 1.0],
            "PTS": [4.1, 3.0, 0.0],
            "FGM": [60, 40, 0],
            "FGA": [120, 100, 0],
            "FG3M": [20, 5, 0],
            "FG3A": [50, 20, 0],
            "FTM": [30, 18, 0],
            "FTA": [34, 20, 0],
        }
    )


def test_basic_line_and_percentages():
    line = clutch_shooting_line(_clutch(), 1)
    assert line["GP"] == 40
    assert line["FG_PCT"] == pytest.approx(0.5)  # 60/120
    assert line["FG3_PCT"] == pytest.approx(0.4)  # 20/50
    assert line["FT_PCT"] == pytest.approx(30 / 34, abs=1e-3)
    # eFG% = (60 + 0.5*20) / 120, rounded to 3 places
    assert line["EFG_PCT"] == pytest.approx((60 + 10) / 120, abs=1e-3)


def test_player_absent_returns_none():
    assert clutch_shooting_line(_clutch(), 999) is None


def test_no_attempts_returns_none():
    # player 3 logged clutch minutes but never shot
    assert clutch_shooting_line(_clutch(), 3) is None


def test_zero_threes_gives_none_not_divzero():
    df = _clutch()
    df.loc[df["PLAYER_ID"] == 2, ["FG3M", "FG3A"]] = 0
    line = clutch_shooting_line(df, 2)
    assert line["FG3_PCT"] is None
    assert line["FG_PCT"] == pytest.approx(0.4)  # 40/100 still fine


def test_missing_columns_raise():
    with pytest.raises(KeyError):
        clutch_shooting_line(_clutch().drop(columns=["FG3A"]), 1)
