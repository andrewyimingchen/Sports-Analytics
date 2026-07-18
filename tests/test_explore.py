"""Offline tests for the Explore-page filtering and per-minutes rescale."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.analysis import filter_players, per_minutes_table


def _league() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "PLAYER_NAME": ["Alice Adams", "Bob Brown", "Cara Cole", "Deep Bench"],
            "TEAM_ABBREVIATION": ["LAL", "LAL", "BOS", "BOS"],
            "GP": [70, 65, 50, 4],
            "MIN": [36.0, 24.0, 30.0, 6.0],
            "PTS": [28.0, 12.0, 18.0, 2.0],
            "FG_PCT": [0.50, 0.44, 0.47, 0.30],
        }
    )


def test_filter_players_applies_every_floor_and_match():
    lg = _league()
    out = filter_players(lg, min_gp=20, min_min=25.0)
    # Alice (70gp/36min) and Cara (50gp/30min) clear both; Bob (24min) and
    # Deep Bench (4gp) are filtered out
    assert list(out["PLAYER_NAME"]) == ["Alice Adams", "Cara Cole"]
    # team filter
    assert set(filter_players(lg, teams=["BOS"])["PLAYER_NAME"]) == {"Cara Cole", "Deep Bench"}
    # name substring, case-insensitive
    assert list(filter_players(lg, name_query="brown")["PLAYER_NAME"]) == ["Bob Brown"]
    # no filters -> everyone, order preserved
    assert len(filter_players(lg)) == 4


def test_per_minutes_scales_counting_not_rates():
    lg = _league()
    p36 = per_minutes_table(lg, 36)
    # Bob at 24 min/game -> per-36 points = 12 * 36/24 = 18
    bob = p36[p36["PLAYER_NAME"] == "Bob Brown"].iloc[0]
    assert bob["PTS"] == pytest.approx(18.0)
    assert bob["FG_PCT"] == pytest.approx(0.44)  # percentages untouched
    assert bob["MIN"] == 24.0  # MIN kept as per-game for filtering
    # a 36-min player is unchanged
    alice = p36[p36["PLAYER_NAME"] == "Alice Adams"].iloc[0]
    assert alice["PTS"] == pytest.approx(28.0)


def test_per_minutes_zero_minutes_is_safe():
    lg = pd.DataFrame({"PLAYER_NAME": ["X"], "MIN": [0.0], "PTS": [0.0]})
    assert per_minutes_table(lg)["PTS"].iloc[0] == 0.0
    with pytest.raises(KeyError, match="MIN"):
        per_minutes_table(lg.drop(columns=["MIN"]))
