import pandas as pd
import pytest

from nba_insights.analysis import calibration_table, evaluate_season_forecasts
from nba_insights.ml.backtest import _actual_outcomes


def test_forecast_metrics_include_baselines_and_calibration():
    frame = pd.DataFrame(
        {
            "SEASON": ["2024-25"] * 4,
            "PROJECTED_WINS": [55, 48, 34, 27],
            "ACTUAL_WINS": [52, 45, 37, 30],
            "PLAYOFF_PROB": [0.9, 0.7, 0.3, 0.1],
            "MADE_PLAYOFFS": [1, 1, 0, 0],
            "CHAMP_PROB": [0.5, 0.3, 0.15, 0.05],
            "WON_CHAMPIONSHIP": [1, 0, 0, 0],
            "CUP_PROB": [0.2, 0.4, 0.2, 0.2],
            "WON_CUP": [0, 1, 0, 0],
        }
    )

    result = evaluate_season_forecasts(frame)

    assert result["team_seasons"] == 4
    assert result["record"]["mae"] == 3
    assert result["playoffs"]["brier"] < result["playoffs"]["baseline_brier"]
    assert result["championship"]["brier"] < result["championship"]["baseline_brier"]
    assert result["playoffs"]["calibration"]


def test_calibration_omits_empty_bins_and_validation_rejects_missing_columns():
    rows = calibration_table(pd.Series([0.1, 0.9]), pd.Series([0, 1]))
    assert len(rows) == 2
    assert sum(row["count"] for row in rows) == 2
    with pytest.raises(KeyError, match="backtest missing"):
        evaluate_season_forecasts(pd.DataFrame({"SEASON": ["2025-26"]}))


def test_backtest_outcomes_come_from_target_season_game_ids():
    class Client:
        def team_games(self, season):
            return pd.DataFrame(
                {
                    "TEAM_ABBREVIATION": ["AAA", "BBB", "AAA", "BBB"],
                    "WL": ["W", "L", "L", "W"],
                }
            )

        def schedule(self, season):
            return pd.DataFrame(
                {
                    "gameId": ["0042500001", "0042500002", "0062500001"],
                    "gameDate": ["2026-05-01", "2026-06-20", "2025-12-17"],
                    "gameStatus": [3, 3, 3],
                    "gameStatusText": ["Final"] * 3,
                    "homeTeam_teamTricode": ["AAA", "BBB", "AAA"],
                    "homeTeam_score": [100, 90, 110],
                    "awayTeam_teamTricode": ["BBB", "AAA", "BBB"],
                    "awayTeam_score": [90, 95, 105],
                }
            )

    records, champion, cup_champion = _actual_outcomes(Client(), "2025-26")
    assert champion == "AAA"
    assert cup_champion == "AAA"
    assert records["MADE_PLAYOFFS"].sum() == 2
