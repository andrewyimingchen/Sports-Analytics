"""Offline tests for the Game-center reshaping functions."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.analysis import (
    box_score_table,
    game_finder_box_score_table,
    game_log_table,
    scoreboard,
)


def test_scoreboard_picks_winner_and_top_scorer():
    schedule = pd.DataFrame(
        {
            "gameId": ["0022600002", "0022600001"],
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
    assert final["GAME_ID"] == "0022600001"
    assert final["WINNER"] == "NYK"  # 121 > 110, the away team
    assert final["TOP_SCORER"] == "Jalen Brunson · 40"
    sched = sb[sb["STATUS"] == "Scheduled"].iloc[0]
    assert sched["WINNER"] == ""  # not decided
    assert sched["TOP_SCORER"] == ""
    with pytest.raises(KeyError, match="homeTeam_teamTricode"):
        scoreboard(schedule.drop(columns=["homeTeam_teamTricode"]))


def test_box_score_table_formats_players_and_keeps_dnp_rows():
    players = pd.DataFrame(
        {
            "teamTricode": ["BOS", "BOS", "NYK"],
            "firstName": ["Jayson", "Bench", "Jalen"],
            "familyName": ["Tatum", "Player", "Brunson"],
            "minutes": ["PT37M30.00S", "", "PT35M00.00S"],
            "fieldGoalsMade": [10, 0, 12],
            "fieldGoalsAttempted": [20, 0, 24],
            "threePointersMade": [3, 0, 4],
            "threePointersAttempted": [8, 0, 9],
            "freeThrowsMade": [5, 0, 6],
            "freeThrowsAttempted": [6, 0, 6],
            "reboundsTotal": [8, 0, 4],
            "assists": [5, 0, 9],
            "steals": [1, 0, 2],
            "blocks": [1, 0, 0],
            "turnovers": [2, 0, 3],
            "points": [28, 0, 34],
            "plusMinusPoints": [7, 0, -3],
            "comment": ["", "DNP - Coach's Decision", ""],
        }
    )
    out = box_score_table(players)
    tatum = out.iloc[0]
    assert tatum["PLAYER"] == "Jayson Tatum"
    assert tatum["MIN"] == pytest.approx(37.5)
    assert tatum["FG"] == "10/20"
    assert tatum["PTS"] == 28
    dnp = out.iloc[1]
    assert pd.isna(dnp["PTS"])
    assert dnp["FG"] == ""
    assert dnp["STATUS"] == "DNP - Coach's Decision"
    bos_total = out[(out["TEAM"] == "BOS") & (out["PLAYER"] == "TEAM TOTAL")].iloc[0]
    assert bos_total["PTS"] == 28
    assert bos_total["FG"] == "10/20"
    assert bos_total["MIN"] == pytest.approx(37.5)
    assert list(out["TEAM"]) == ["BOS", "BOS", "BOS", "NYK", "NYK"]
    with pytest.raises(KeyError, match="teamTricode"):
        box_score_table(players.drop(columns="teamTricode"))


def test_box_score_table_accepts_clock_minutes_from_live_endpoint():
    players = pd.DataFrame(
        {
            "teamTricode": ["DAL"],
            "firstName": ["Kyrie"],
            "familyName": ["Irving"],
            "minutes": ["39:12"],
            "fieldGoalsMade": [10],
            "fieldGoalsAttempted": [20],
            "threePointersMade": [3],
            "threePointersAttempted": [8],
            "freeThrowsMade": [5],
            "freeThrowsAttempted": [6],
            "reboundsTotal": [8],
            "assists": [5],
            "steals": [1],
            "blocks": [1],
            "turnovers": [2],
            "points": [28],
            "plusMinusPoints": [7],
            "comment": [""],
        }
    )
    result = box_score_table(players)
    assert result.iloc[0]["MIN"] == pytest.approx(39.2)
    assert result.iloc[0]["PTS"] == 28


def test_game_finder_rows_are_a_box_score_fallback():
    rows = pd.DataFrame(
        {
            "TEAM_ABBREVIATION": ["BOS", "NYK"],
            "PLAYER_NAME": ["Jayson Tatum", "Jalen Brunson"],
            "MIN": [37.5, 35.0],
            "PTS": [28, 34],
            "REB": [8, 4],
            "AST": [5, 9],
            "STL": [1, 2],
            "BLK": [1, 0],
            "TOV": [2, 3],
            "FGM": [10, 12],
            "FGA": [20, 24],
            "FG3M": [3, 4],
            "FG3A": [8, 9],
            "FTM": [5, 6],
            "FTA": [6, 6],
            "PLUS_MINUS": [7, -3],
        }
    )
    result = game_finder_box_score_table(rows)
    assert result.iloc[0]["FG"] == "10/20"
    assert result.iloc[1]["PLAYER"] == "TEAM TOTAL"
    assert result.iloc[-1]["PTS"] == 34


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
