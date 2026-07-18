"""Offline tests for the rule-based scouting takes."""

from __future__ import annotations

import pandas as pd

from nba_insights.analysis import player_scouting_take, team_scouting_take


def test_player_take_names_elite_then_strong_then_weak():
    ranks = pd.Series(
        {
            "PTS": 100.0, "AST": 96.0, "REB": 20.0, "STL": 94.0, "BLK": 60.0,
            "FG_PCT": 85.0, "FG3_PCT": 40.0, "FT_PCT": 88.0,
            # composite stats must be ignored, not surfaced as "skills"
            "NET_RATING": 99.0, "DPM": 99.0,
        }
    )
    take = player_scouting_take(ranks)
    assert take.startswith("Elite scoring, playmaking, and steals")
    assert "also strong at" in take
    assert "finishing" in take or "free-throw shooting" in take
    assert "below-average rebounding" in take
    assert "net rating" not in take.lower()  # composite excluded
    assert take.endswith(".")


def test_player_take_balanced_when_nothing_stands_out():
    ranks = pd.Series(
        {"PTS": 55.0, "AST": 50.0, "REB": 48.0, "STL": 52.0, "BLK": 45.0, "FG_PCT": 58.0}
    )
    take = player_scouting_take(ranks)
    assert take.startswith("A balanced profile, best at")
    assert "58th percentile" in take


def test_player_take_empty_without_skill_columns():
    assert player_scouting_take(pd.Series({"NET_RATING": 90.0, "DPM": 88.0})) == ""


def test_team_take_ranks_offense_and_defense_in_league():
    league = pd.DataFrame(
        {
            "form_ortg": [117.0, 114.0, 110.0, 105.0, 103.0],
            "form_drtg": [106.0, 108.0, 110.0, 113.0, 116.0],
        },
        index=["AAA", "BBB", "CCC", "DDD", "EEE"],
    )
    form = pd.Series({"form_net": 11.1, "form_ortg": 117.0, "form_drtg": 106.0})
    take = team_scouting_take(form, 64, 18, league, recent=(8, 2))
    assert take.startswith("64-18, a clear contender at +11.1 net rating.")
    assert "1st offense and 1st defense" in take
    assert "elite on both ends" in take
    assert "trending up — 8 of its last 10" in take.lower()


def test_team_take_tiers_and_trend_direction():
    weak = pd.Series({"form_net": -8.0, "form_ortg": 103.0, "form_drtg": 116.0})
    take = team_scouting_take(weak, 18, 64, recent=(2, 8))
    assert "among the league's weakest" in take
    assert "cooling off" in take.lower()


def test_team_take_empty_without_net_rating():
    assert team_scouting_take(pd.Series({"form_ortg": 110.0}), 0, 0) == ""
