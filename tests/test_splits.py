"""Offline tests for the player situational-splits reshaper."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.analysis import player_splits


def _log() -> pd.DataFrame:
    # four games: 2 home / 2 away, spanning Oct-Nov, a back-to-back and rest
    return pd.DataFrame(
        {
            "GAME_DATE": ["2025-10-22", "2025-10-23", "2025-11-01", "2025-11-05"],
            "MATCHUP": ["OKC vs. LAL", "OKC @ DEN", "OKC vs. DEN", "OKC @ LAL"],
            "MIN": [35, 30, 33, 31],
            "PTS": [30, 20, 26, 24],
            "REB": [5, 7, 6, 8],
            "AST": [10, 4, 8, 6],
            "FG3M": [4, 2, 3, 1],
            "FGM": [10, 8, 9, 8],
            "FGA": [20, 20, 18, 16],
            "FG3A": [8, 6, 6, 4],
            "FTM": [6, 2, 5, 7],
            "FTA": [6, 4, 5, 8],
            "PLUS_MINUS": [12, -6, 8, -3],
        }
    )


def test_home_away_split():
    out = player_splits(_log(), "home_away")
    assert list(out["Split"]) == ["Home", "Away"]  # Home first
    home = out[out["Split"] == "Home"].iloc[0]
    assert home["GP"] == 2
    assert home["PTS"] == 28.0  # (30 + 26) / 2
    # aggregate FG%: (10+9)/(20+18)
    assert home["FG_PCT"] == pytest.approx((10 + 9) / (20 + 18), abs=1e-3)


def test_month_split_is_chronological():
    out = player_splits(_log(), "month")
    assert list(out["Split"]) == ["October", "November"]
    assert out[out["Split"] == "October"].iloc[0]["GP"] == 2


def test_rest_split_flags_b2b():
    out = player_splits(_log(), "rest")
    # Oct 22 opener, Oct 23 is a B2B, then rested games
    labels = set(out["Split"])
    assert "0-1 days (B2B)" in labels
    assert "Season opener" in labels
    b2b = out[out["Split"] == "0-1 days (B2B)"].iloc[0]
    assert b2b["GP"] == 1  # only Oct 23


def test_opponent_split():
    out = player_splits(_log(), "opponent")
    assert set(out["Split"]) == {"LAL", "DEN"}
    assert out[out["Split"] == "LAL"].iloc[0]["GP"] == 2


def test_missing_column_raises():
    with pytest.raises(KeyError):
        player_splits(_log().drop(columns=["MATCHUP"]), "home_away")


def test_shooting_omitted_when_columns_absent():
    log = _log().drop(columns=["FGM", "FGA"])
    out = player_splits(log, "home_away")
    assert "FG_PCT" not in out.columns  # degrades, doesn't raise
    assert "FT_PCT" in out.columns  # FT columns still present
