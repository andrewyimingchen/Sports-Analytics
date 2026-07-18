"""Offline tests for the team four-factors table."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.analysis import FACTOR_LABELS, four_factors_table


def _two_games() -> pd.DataFrame:
    """Two teams, one game each way (GAME 1 and GAME 2), fully symmetric box.

    AAA is the better shooting / rebounding team; BBB turns it over more.
    """
    rows = [
        # GAME_ID, TEAM_ID, TRI, PTS,FGM,FGA,FG3M,FTM,FTA,TOV,OREB,DREB
        ("0001", 1, "AAA", 110, 42, 85, 12, 14, 18, 10, 11, 34),
        ("0001", 2, "BBB", 100, 38, 88, 9, 15, 20, 16, 9, 30),
        ("0002", 1, "AAA", 108, 41, 84, 11, 15, 19, 11, 12, 33),
        ("0002", 2, "BBB", 99, 37, 87, 8, 17, 22, 15, 8, 31),
    ]
    cols = [
        "GAME_ID", "TEAM_ID", "TEAM_ABBREVIATION",
        "PTS", "FGM", "FGA", "FG3M", "FTM", "FTA", "TOV", "OREB", "DREB",
    ]
    return pd.DataFrame(rows, columns=cols)


def test_shape_and_columns():
    ff = four_factors_table(_two_games())
    assert list(ff.index) == ["AAA", "BBB"]  # sorted tricodes
    for factor in FACTOR_LABELS:
        assert factor in ff.columns
        assert f"{factor}_rank" in ff.columns


def test_offensive_efg_math():
    ff = four_factors_table(_two_games())
    # AAA totals: FGM 83, FG3M 23, FGA 169 -> (83 + 11.5)/169
    assert ff.loc["AAA", "off_efg"] == pytest.approx((83 + 0.5 * 23) / 169)


def test_ranks_reflect_goodness():
    ff = four_factors_table(_two_games())
    # AAA shoots better -> rank 1 on offensive eFG%
    assert ff.loc["AAA", "off_efg_rank"] == 1
    assert ff.loc["BBB", "off_efg_rank"] == 2
    # AAA turns it over less -> lower TOV% is better -> rank 1
    assert ff.loc["AAA", "off_tov_pct"] < ff.loc["BBB", "off_tov_pct"]
    assert ff.loc["AAA", "off_tov_pct_rank"] == 1
    # defense: AAA holds BBB to a lower eFG% -> rank 1
    assert ff.loc["AAA", "def_efg_rank"] == 1


def test_defense_mirrors_opponent():
    ff = four_factors_table(_two_games())
    # AAA's defensive eFG% is BBB's offensive eFG% and vice-versa
    assert ff.loc["AAA", "def_efg"] == pytest.approx(ff.loc["BBB", "off_efg"])
    assert ff.loc["BBB", "def_efg"] == pytest.approx(ff.loc["AAA", "off_efg"])


def test_missing_column_raises():
    bad = _two_games().drop(columns=["OREB"])
    with pytest.raises(KeyError):
        four_factors_table(bad)
