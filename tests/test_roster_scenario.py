import pandas as pd
import pytest

from nba_insights.analysis.roster_forecast import RosterForecastInputs
from nba_insights.analysis.roster_scenario import apply_roster_scenario


@pytest.fixture
def baseline():
    players = pd.DataFrame(
        {
            "PLAYER_NAME": [f"A{i}" for i in range(6)] + [f"B{i}" for i in range(6)],
            "TEAM": ["AAA"] * 6 + ["BBB"] * 6,
            "PROJECTED_MIN": [40] * 12,
            "PROJECTED_IMPACT": [5, 3, 2, 1, 0, -1] + [4, 2, 1, 0, -1, -2],
            "SALARY": [30_000_000, 20_000_000, 15_000_000, 10_000_000, 5_000_000, 2_000_000] * 2,
        }
    )
    teams = pd.DataFrame(
        {
            "CURRENT_IMPACT": [1.0, 0.5],
            "ROSTER_IMPACT": [1.7, 0.7],
            "NET_ADJUSTMENT": [0.7, 0.2],
            "STRENGTH_ADJUSTMENT": [0.05, 0.014],
            "UNCERTAINTY": [0.2, 0.2],
            "PLAYER_COUNT": [6, 6],
            "KEY_DRIVERS": [["A0"], ["B0"]],
        },
        index=pd.Index(["AAA", "BBB"], name="TEAM"),
    )
    return RosterForecastInputs(players=players, teams=teams, metadata={})


def test_scenario_trade_minutes_injury_and_baseline_immutability(baseline):
    original_players = baseline.players.copy(deep=True)
    original_teams = baseline.teams.copy(deep=True)

    result = apply_roster_scenario(
        baseline,
        [
            {"player": "A0", "new_team": "BBB", "projected_minutes": 32},
            {"player": "B0", "new_team": "AAA", "games_missed": 20},
        ],
    )

    assert result.players.groupby("TEAM")["PROJECTED_MIN"].sum().to_dict() == pytest.approx(
        {"AAA": 240, "BBB": 240}
    )
    assert result.players.set_index("PLAYER_NAME").at["A0", "TEAM"] == "BBB"
    assert result.players.set_index("PLAYER_NAME").at["B0", "GAMES_MISSED"] == 20
    assert result.teams.at["AAA", "ROSTER_IMPACT"] != baseline.teams.at["AAA", "ROSTER_IMPACT"]
    assert {row["status"] for row in result.salary_validation} <= {
        "pass",
        "warning",
        "unavailable",
    }
    pd.testing.assert_frame_equal(baseline.players, original_players)
    pd.testing.assert_frame_equal(baseline.teams, original_teams)


def test_scenario_rejects_duplicate_player_changes(baseline):
    with pytest.raises(ValueError, match="appears more than once"):
        apply_roster_scenario(
            baseline,
            [{"player": "A0", "games_missed": 10}, {"player": "A0", "games_missed": 20}],
        )


def test_scenario_rejects_impossible_minutes_and_roster(baseline):
    with pytest.raises(ValueError, match="240-minute"):
        apply_roster_scenario(
            baseline,
            [
                {"player": "A0", "projected_minutes": 48},
                {"player": "A1", "projected_minutes": 48},
                {"player": "A2", "projected_minutes": 48},
                {"player": "A3", "projected_minutes": 48},
                {"player": "A4", "projected_minutes": 48},
                {"player": "A5", "projected_minutes": 1},
            ],
        )

    with pytest.raises(ValueError, match="at least five"):
        apply_roster_scenario(
            baseline,
            [{"player": "A0", "remove": True}, {"player": "A1", "remove": True}],
        )
