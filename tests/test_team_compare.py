import pandas as pd

from nba_insights.analysis.team_compare import compare_teams
from test_ml import synthetic_team_games


def test_compare_teams_uses_shared_cutoff_and_builds_context():
    games = synthetic_team_games(20)
    league = pd.DataFrame(
        {
            "TEAM_ABBREVIATION": ["T1"] * 6 + ["T4"] * 6,
            "PLAYER_NAME": [f"T1 Player {i}" for i in range(6)]
            + [f"T4 Player {i}" for i in range(6)],
            "MIN": [36, 34, 32, 30, 28, 18] * 2,
            "PTS": [25, 20, 17, 14, 12, 8] + [20, 18, 16, 13, 10, 7],
            "NET_RATING": [8, 7, 6, 5, 4, 1] + [-2, -3, -4, -5, -6, -8],
        }
    )
    lineups = pd.DataFrame(
        {
            "TEAM_ABBREVIATION": ["T1", "T4"],
            "GROUP_ID": ["-1-2-3-4-5-", "-6-7-8-9-10-"],
            "GROUP_NAME": ["T1 starters", "T4 starters"],
            "MIN": [200, 160],
            "NET_RATING": [9.0, -4.0],
        }
    )
    clutch = pd.DataFrame(
        {
            "TEAM_ABBREVIATION": ["T1", "T1", "T4"],
            "MIN": [20, 10, 15],
            "NET_RATING": [12, 6, -5],
        }
    )

    result = compare_teams(games, league, lineups, clutch, "T1", "T4")

    assert result["sample"]["as_of"]
    assert result["sample"]["games"]["T1"] > 0
    assert {row["key"] for row in result["metrics"]} >= {
        "win_pct",
        "off_rating",
        "def_rating",
        "off_efg",
    }
    assert result["teams"]["T1"]["top_lineup"]["GROUP_NAME"] == "T1 starters"
    assert result["teams"]["T1"]["bench_points_per_game"] == 8
    assert result["teams"]["T1"]["clutch"]["net_rating"] == 10
    assert result["head_to_head"]["games"] >= 1


def test_compare_teams_rejects_duplicates():
    games = synthetic_team_games(10)

    try:
        compare_teams(
            games, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "T1", "T1"
        )
    except ValueError as exc:
        assert str(exc) == "teams must differ"
    else:
        raise AssertionError("duplicate teams should fail")
