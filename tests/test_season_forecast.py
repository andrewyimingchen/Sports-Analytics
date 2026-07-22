import numpy as np
import pandas as pd
import pytest

from nba_insights.analysis import season_forecast


def test_season_forecast_returns_conference_and_title_probabilities():
    teams = [f"E{i:02d}" for i in range(15)] + [f"W{i:02d}" for i in range(15)]
    strength = np.linspace(0.75, 0.25, 30)
    snapshot = pd.DataFrame(
        {
            "form_win_pct": strength,
            "form_net": (strength - 0.5) * 30,
            "elo": 1500 + (strength - 0.5) * 500,
        },
        index=teams,
    )
    conferences = {team: ("East" if team.startswith("E") else "West") for team in teams}

    result = season_forecast(snapshot, conferences, n_sims=1_000, seed=7)

    assert len(result) == 30
    assert set(result["CONFERENCE"]) == {"East", "West"}
    assert result["CHAMP_PROB"].sum() == pytest.approx(1)
    assert result["CUP_PROB"].sum() == pytest.approx(1)
    assert result["PLAYOFF_PROB"].sum() == pytest.approx(16)
    assert result.loc[result["TEAM"] == "E00", "PROJECTED_WINS"].iloc[0] > 50
    assert result.loc[result["TEAM"] == "E00", "CHAMP_PROB"].iloc[0] > result.loc[
        result["TEAM"] == "W14", "CHAMP_PROB"
    ].iloc[0]
