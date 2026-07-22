import pandas as pd
import pytest

from nba_insights.analysis import project_player_seasons


def test_player_projection_has_assumptions_ranges_comps_and_award_totals():
    league = pd.DataFrame(
        {
            "PLAYER_ID": range(1, 31),
            "PLAYER_NAME": [f"Player {index}" for index in range(30)],
            "MIN": [20 + index % 16 for index in range(30)],
            "GP": [50 + index % 30 for index in range(30)],
            "PTS": [10 + index * 0.6 for index in range(30)],
            "REB": [3 + index % 9 for index in range(30)],
            "AST": [2 + index % 8 for index in range(30)],
            "STL": [0.5 + index % 5 / 5 for index in range(30)],
            "BLK": [0.2 + index % 6 / 4 for index in range(30)],
            "FG3M": [0.5 + index % 5 / 2 for index in range(30)],
            "FG_PCT": [0.46] * 30,
            "FG3_PCT": [0.36] * 30,
            "FT_PCT": [0.79] * 30,
        }
    )
    roster = pd.DataFrame(
        {
            "TEAM": [f"T{index % 3}" for index in range(30)],
            "PLAYER_NAME": league["PLAYER_NAME"],
            "SOURCE_TEAM": [f"T{index % 3}" for index in range(30)],
            "STATUS": ["returning"] * 30,
            "AGE": [20 + index % 16 for index in range(30)],
            "GP": league["GP"],
            "SALARY": [10_000_000] * 30,
            "PROJECTED_MIN": league["MIN"],
            "CURRENT_IMPACT": [0.0] * 30,
            "AGE_ADJUSTMENT": [0.0] * 30,
            "PROJECTED_IMPACT": [0.0] * 30,
            "HAS_HISTORY": [True] * 30,
        }
    )
    result = project_player_seasons(league, roster)

    assert result["MVP_PROB"].sum() == pytest.approx(1)
    assert result["DPOY_PROB"].sum() == pytest.approx(1)
    assert result["ALL_STAR_PROB"].sum() == pytest.approx(24)
    assert (result["PTS_LOW"] <= result["PROJECTED_PTS"]).all()
    assert (result["PROJECTED_PTS"] <= result["PTS_HIGH"]).all()
    assert result["COMPARABLES"].map(len).eq(3).all()
    assert set(result["TRAJECTORY"]) <= {"breakout", "steady", "decline", "new entrant"}
