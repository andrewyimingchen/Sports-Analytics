"""Offline tests for player similarity comps."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.analysis import similar_players

_COLS = ["PTS", "REB", "AST", "STL", "BLK", "TOV", "FG3A", "FTA",
         "FG_PCT", "FG3_PCT", "FT_PCT"]


def _player(name, team, min_, **stats):
    row = {"PLAYER_NAME": name, "TEAM_ABBREVIATION": team, "MIN": min_}
    row.update({c: stats.get(c, 0.0) for c in _COLS})
    return row


def _league() -> pd.DataFrame:
    # a guard, a near-clone of the guard, a big, and a bench scrub
    return pd.DataFrame(
        [
            _player("Star Guard", "AAA", 34, PTS=28, AST=8, FG3A=9, FTA=7,
                    FG_PCT=0.48, FG3_PCT=0.40, FT_PCT=0.90, REB=4),
            _player("Clone Guard", "BBB", 33, PTS=27, AST=7.5, FG3A=8.5, FTA=6.5,
                    FG_PCT=0.47, FG3_PCT=0.39, FT_PCT=0.88, REB=4.2),
            _player("Big Man", "CCC", 30, PTS=14, REB=12, BLK=2.2, AST=1.5,
                    FG_PCT=0.62, FG3A=0.2, FTA=4),
            _player("Bench Scrub", "DDD", 6, PTS=2, AST=0.5),
        ]
    )


def test_nearest_comp_is_the_clone_and_scrub_excluded_by_minutes():
    comps = similar_players(_league(), "Star Guard", n=3, min_minutes=20)
    assert comps["PLAYER_NAME"].iloc[0] == "Clone Guard"  # most similar
    assert comps["SIMILARITY"].iloc[0] > 80  # near-identical -> high match
    # the 6-minute scrub is below the floor and never a neighbor
    assert "Bench Scrub" not in set(comps["PLAYER_NAME"])
    # the big man is a worse comp than the clone
    if "Big Man" in set(comps["PLAYER_NAME"]):
        big = comps.loc[comps["PLAYER_NAME"] == "Big Man", "SIMILARITY"].iloc[0]
        assert big < comps["SIMILARITY"].iloc[0]


def test_target_excluded_from_own_comps_and_columns():
    comps = similar_players(_league(), "Star Guard", n=5, min_minutes=20)
    assert "Star Guard" not in set(comps["PLAYER_NAME"])
    assert list(comps.columns) == [
        "PLAYER_NAME", "TEAM_ABBREVIATION", "PTS", "REB", "AST", "SIMILARITY"
    ]


def test_unknown_player_and_missing_columns_raise():
    with pytest.raises(KeyError, match="Nobody"):
        similar_players(_league(), "Nobody")
    with pytest.raises(KeyError, match="FG3A"):
        similar_players(_league().drop(columns=["FG3A"]), "Star Guard")
