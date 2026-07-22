import pandas as pd
import pytest

from nba_insights.analysis.tracking import tracking_table


def test_tracking_table_filters_defines_and_audits_columns():
    frame = pd.DataFrame(
        {
            "PLAYER_ID": [1, 2, 3],
            "PLAYER_NAME": ["Alpha", "Beta", "Gamma"],
            "TEAM_ABBREVIATION": ["AAA", "AAA", "BBB"],
            "GP": [20, 5, 30],
            "MIN": [32, 18, 35],
            "DRIVES": [12.0, 8.0, 15.0],
            "DRIVE_PTS": [8.0, 4.0, 10.0],
            "DRIVE_FG_PCT": [0.52, 0.45, 0.56],
        }
    )

    table, metadata = tracking_table(
        frame, "drives", min_games=10, team="AAA", query="alp"
    )

    assert table["PLAYER_NAME"].tolist() == ["Alpha"]
    assert metadata["definitions"]["DRIVES"] == "Drives per game"
    assert "DRIVE_FG_PCT" in metadata["percentage_metrics"]
    assert "DRIVE_AST" in metadata["missing_metrics"]
    assert metadata["minimum_games"] == 10


def test_tracking_table_sorts_defense_lower_first():
    frame = pd.DataFrame(
        {
            "TEAM_ID": [1, 2],
            "TEAM_NAME": ["One", "Two"],
            "TEAM_ABBREVIATION": ["ONE", "TWO"],
            "GP": [20, 20],
            "DEF_RIM_FGM": [5.0, 6.0],
            "DEF_RIM_FGA": [11.0, 11.5],
            "DEF_RIM_FG_PCT": [0.44, 0.51],
        }
    )

    table, metadata = tracking_table(
        frame, "defense", scope="Team", sort="DEF_RIM_FG_PCT"
    )

    assert table["TEAM_ABBREVIATION"].tolist() == ["ONE", "TWO"]
    assert metadata["scope"] == "team"
    assert metadata["definitions"]["DEF_RIM_FG_PCT"].startswith("Opponent rim")


def test_tracking_table_rejects_unknown_category():
    with pytest.raises(ValueError, match="unknown tracking category"):
        tracking_table(pd.DataFrame(), "telepathy")
