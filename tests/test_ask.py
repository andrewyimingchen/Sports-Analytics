"""Offline tests for the AI Q&A data-access layer (no LLM involved)."""

from __future__ import annotations

import pandas as pd

from nba_insights.analysis import COLUMN_GLOSSARY, query_players


def _league() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "PLAYER_NAME": ["Alice Adams", "Bob Brown", "Cara Cole", "Bench Guy"],
            "TEAM_ABBREVIATION": ["LAL", "LAL", "BOS", "BOS"],
            "GP": [70, 65, 60, 10],
            "MIN": [34.0, 31.0, 28.0, 8.0],
            "PTS": [28.0, 22.0, 19.0, 3.0],
            "AST": [9.4, 3.1, 6.2, 0.5],
            "FG3_PCT": [0.383333, 0.44, 0.41, 0.20],
        }
    )


def test_filter_sort_and_topn():
    # assist leaders among 30+ minute players
    out = query_players(
        _league(), filters={"MIN": 30}, sort_by="AST", top_n=2,
        columns=["PLAYER_NAME", "AST"],
    )
    assert [r["PLAYER_NAME"] for r in out] == ["Alice Adams", "Bob Brown"]  # Cara <30 min
    assert out[0]["AST"] == 9.4


def test_multiple_filters_and_team_and_name():
    lg = _league()
    # BOS players only
    assert {r["PLAYER_NAME"] for r in query_players(lg, teams=["BOS"], top_n=10)} == {
        "Cara Cole", "Bench Guy"
    }
    # name substring
    assert [r["PLAYER_NAME"] for r in query_players(lg, name_contains="brown")] == ["Bob Brown"]
    # two floors together
    out = query_players(lg, filters={"MIN": 25, "AST": 5}, columns=["PLAYER_NAME"])
    assert {r["PLAYER_NAME"] for r in out} == {"Alice Adams", "Cara Cole"}


def test_sort_column_always_included_and_floats_rounded():
    out = query_players(_league(), sort_by="FG3_PCT", top_n=1, columns=["PLAYER_NAME"])
    assert "FG3_PCT" in out[0]  # sort column added even if not requested
    assert out[0]["FG3_PCT"] == 0.44  # Bob, and rounded


def test_unknown_column_degrades_gracefully():
    # a bad LLM argument should be ignored, not raise
    out = query_players(_league(), filters={"NONEXISTENT": 5}, sort_by="ALSO_MISSING")
    assert len(out) == 4  # no filtering happened


def test_glossary_covers_core_stats():
    for col in ("PTS", "AST", "REB", "NET_RATING", "DPM"):
        assert col in COLUMN_GLOSSARY
