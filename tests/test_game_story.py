import pandas as pd

from nba_insights.analysis import game_story, game_timeline


def _pbp():
    return pd.DataFrame(
        {
            "period": [1, 1, 1, 4, 4, 4],
            "clock": [
                "PT11M30.00S",
                "PT11M00.00S",
                "PT10M30.00S",
                "PT04M30.00S",
                "PT01M00.00S",
                "PT00M00.00S",
            ],
            "teamId": [1, 2, 1, 2, 1, 1],
            "personId": [10, 20, 10, 20, 10, 10],
            "actionType": [
                "Made Shot",
                "Missed Shot",
                "Made Shot",
                "Made Shot",
                "Made Shot",
                "period",
            ],
            "subType": ["Layup", "Jump Shot", "3PT", "3PT", "Layup", "end"],
            "scoreHome": ["2", "", "5", "100", "102", "102"],
            "scoreAway": ["0", "", "0", "101", "101", "101"],
            "isFieldGoal": [1, 1, 1, 1, 1, 0],
            "xLegacy": [0, 120, 230, -220, 10, None],
            "yLegacy": [5, 100, 40, 35, 8, None],
            "shotDistance": [1, 15, 24, 24, 2, None],
        }
    )


def _players():
    return pd.DataFrame(
        {
            "PLAYER_ID": [10, 20],
            "PLAYER_NAME": ["Home Player", "Away Player"],
            "TEAM_ID": [1, 2],
            "TEAM_ABBREVIATION": ["HOM", "AWY"],
            "PTS": [102, 101],
            "FGM": [40, 38],
            "FGA": [80, 82],
            "FG3M": [12, 15],
            "FTA": [14, 12],
            "OREB": [10, 8],
            "DREB": [30, 29],
            "REB": [40, 37],
            "AST": [25, 23],
            "TOV": [11, 13],
            "STL": [7, 6],
            "BLK": [4, 3],
        }
    )


def test_timeline_probability_uses_score_and_time_and_finishes_at_one():
    timeline = game_timeline(_pbp())
    assert timeline["ELAPSED"].is_monotonic_increasing
    assert timeline.iloc[-1]["HOME_WIN_PROB"] == 1
    assert timeline.iloc[-1]["MARGIN"] == 1


def test_game_story_builds_shots_advanced_clutch_and_runs():
    result = game_story(_pbp(), _players(), home="HOM", away="AWY")
    assert result["shot_locations_available"] is True
    assert sum(row["FGA"] for row in result["shot_summary"]) == 5
    assert {row["TEAM"] for row in result["advanced"]} == {"HOM", "AWY"}
    assert result["clutch_points"]["HOM"] >= 2
    assert result["lead_changes"] >= 1
    assert result["lineups"] == []
    assert "not a trained/calibrated model" in result["win_probability_method"]
