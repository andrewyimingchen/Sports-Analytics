import numpy as np
import pandas as pd

from nba_insights.analysis import build_roster_forecast_inputs, season_forecast


def _league() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "PLAYER_NAME": ["East Star", "East Vet", "West Star", "West Prospect"],
            "TEAM_ABBREVIATION": ["E00", "E00", "W00", "W00"],
            "AGE": [24, 34, 28, 21],
            "GP": [80, 35, 78, 60],
            "MIN": [36.0, 25.0, 35.0, 20.0],
            "PLUS_MINUS": [8.0, 1.0, 5.0, -1.0],
        }
    )


def _contracts() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "PLAYER_NAME": [
                "East Star", "East Vet", "West Star", "West Prospect", "New Rookie"
            ],
            "TEAM_ABBREVIATION": ["W00", "E00", "W00", "W00", "E00"],
            "2026-27": [40_000_000, 8_000_000, 35_000_000, 10_000_000, 12_000_000],
        }
    )


def test_roster_inputs_are_versioned_explainable_and_minutes_normalized():
    result = build_roster_forecast_inputs(
        _league(), _contracts(), target_season="2026-27", generated_on="2026-07-21"
    )

    assert result.metadata["version"] == "roster-minutes-v1"
    assert result.metadata["generated_on"] == "2026-07-21"
    assert result.players.groupby("TEAM")["PROJECTED_MIN"].sum().round(6).eq(240).all()
    assert result.players.set_index("PLAYER_NAME").loc["East Star", "STATUS"] == "changed team"
    statuses = result.players.set_index("PLAYER_NAME")["STATUS"]
    assert statuses.loc["New Rookie"] == "new/no NBA history"
    assert "East Star" in result.teams.loc["W00", "ADDITIONS"]
    assert "East Star" in result.teams.loc["E00", "DEPARTURES"]
    assert result.teams["UNCERTAINTY"].between(0.16, 0.42).all()


def test_roster_adjustments_change_forecast_and_add_record_bands():
    teams = [f"E{i:02d}" for i in range(15)] + [f"W{i:02d}" for i in range(15)]
    snapshot = pd.DataFrame(
        {"form_win_pct": 0.5, "form_net": 0.0, "elo": 1500.0}, index=teams
    )
    conferences = {team: ("East" if team.startswith("E") else "West") for team in teams}
    adjustments = pd.DataFrame(
        {"STRENGTH_ADJUSTMENT": 0.0, "UNCERTAINTY": 0.12}, index=teams
    )
    adjustments.loc["E00", "STRENGTH_ADJUSTMENT"] = 0.7

    result = season_forecast(
        snapshot,
        conferences,
        n_sims=1_000,
        seed=13,
        roster_adjustments=adjustments,
    ).set_index("TEAM")

    assert result.loc["E00", "PROJECTED_WINS"] > 50
    assert result.loc["E00", "PESSIMISTIC_WINS"] <= result.loc["E00", "MEDIAN_WINS"]
    assert result.loc["E00", "MEDIAN_WINS"] <= result.loc["E00", "OPTIMISTIC_WINS"]
    assert np.isfinite(result[["PLAYOFF_PROB", "CHAMP_PROB"]].to_numpy()).all()
