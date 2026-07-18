"""Offline tests for the Game-center reshaping functions."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.analysis import game_log_table, scoreboard


def test_scoreboard_picks_winner_and_top_scorer():
    schedule = pd.DataFrame(
        {
            "gameDate": ["2026-01-02", "2026-01-01"],
            "gameStatus": [1, 3],  # scheduled, final
            "gameStatusText": ["7:00 pm ET", "Final"],
            "homeTeam_teamTricode": ["LAL", "BOS"],
            "homeTeam_score": [0, 110],
            "awayTeam_teamTricode": ["GSW", "NYK"],
            "awayTeam_score": [0, 121],
            "pointsLeaders_0_firstName": ["", "Jalen"],
            "pointsLeaders_0_lastName": ["", "Brunson"],
            "pointsLeaders_0_points": [None, 40],
        }
    )
    sb = scoreboard(schedule)
    assert list(sb["GAME_DATE"].astype(str)) == ["2026-01-01", "2026-01-02"]  # sorted
    final = sb[sb["STATUS"] == "Final"].iloc[0]
    assert final["WINNER"] == "NYK"  # 121 > 110, the away team
    assert final["TOP_SCORER"] == "Jalen Brunson · 40"
    sched = sb[sb["STATUS"] == "Scheduled"].iloc[0]
    assert sched["WINNER"] == ""  # not decided
    assert sched["TOP_SCORER"] == ""
    with pytest.raises(KeyError, match="homeTeam_teamTricode"):
        scoreboard(schedule.drop(columns=["homeTeam_teamTricode"]))


def test_game_log_table_shapes_and_sorts():
    log = pd.DataFrame(
        {
            "GAME_DATE": ["2026-01-01T00:00:00", "2026-01-03T00:00:00"],
            "MATCHUP": ["GSW vs. LAL", "GSW @ BOS"],
            "WL": ["W", "L"],
            "MIN": [34.4, 30.0],
            "PTS": [30, 22],
            "REB": [5, 7],
            "AST": [6, 9],
            "FGM": [11, 8],
            "FGA": [20, 19],
            "FG3M": [5, 3],
            "PLUS_MINUS": [12, -6],
        }
    )
    out = game_log_table(log)
    assert list(out.columns) == [
        "DATE", "MATCHUP", "WL", "MIN", "PTS", "REB", "AST", "FG", "3PM", "+/-"
    ]
    assert str(out["DATE"].iloc[0]) == "2026-01-03"  # newest first
    assert out["FG"].iloc[0] == "8/19"
    assert out["MIN"].iloc[1] == 34  # 34.4 rounded
    with pytest.raises(KeyError, match="PLUS_MINUS"):
        game_log_table(log.drop(columns=["PLUS_MINUS"]))
