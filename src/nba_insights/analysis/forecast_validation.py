"""Pure metrics for time-safe league forecast backtests."""

from __future__ import annotations

import numpy as np
import pandas as pd


def _brier(probability: pd.Series, outcome: pd.Series) -> float:
    return float(np.mean((probability.to_numpy(float) - outcome.to_numpy(float)) ** 2))


def calibration_table(
    probability: pd.Series,
    outcome: pd.Series,
    bins: int = 5,
) -> list[dict]:
    """Equal-width reliability bins with empty bins omitted."""
    frame = pd.DataFrame({"probability": probability, "outcome": outcome})
    frame["bin"] = pd.cut(
        frame["probability"],
        bins=np.linspace(0, 1, bins + 1),
        include_lowest=True,
    )
    grouped = frame.groupby("bin", observed=True)
    return [
        {
            "lower": round(float(interval.left), 3),
            "upper": round(float(interval.right), 3),
            "mean_probability": round(float(rows["probability"].mean()), 4),
            "observed_rate": round(float(rows["outcome"].mean()), 4),
            "count": int(len(rows)),
        }
        for interval, rows in grouped
        if len(rows)
    ]


def evaluate_season_forecasts(backtest: pd.DataFrame) -> dict:
    """Score season forecast rows joined to outcomes.

    Required columns are one row per team-season. Champion and Cup outcomes
    are one-hot. The resulting baselines are deliberately simple and fully
    reproducible: 41 wins for every team, 16/30 playoff probability, and 1/30
    championship/Cup probability.
    """
    required = {
        "SEASON",
        "PROJECTED_WINS",
        "PLAYOFF_PROB",
        "CHAMP_PROB",
        "CUP_PROB",
        "ACTUAL_WINS",
        "MADE_PLAYOFFS",
        "WON_CHAMPIONSHIP",
        "WON_CUP",
    }
    missing = required - set(backtest.columns)
    if missing:
        raise KeyError(f"backtest missing columns: {sorted(missing)}")
    frame = backtest.copy()
    record_error = frame["PROJECTED_WINS"] - frame["ACTUAL_WINS"]
    playoff = _brier(frame["PLAYOFF_PROB"], frame["MADE_PLAYOFFS"])
    championship = _brier(frame["CHAMP_PROB"], frame["WON_CHAMPIONSHIP"])
    cup = _brier(frame["CUP_PROB"], frame["WON_CUP"])
    return {
        "seasons": sorted(frame["SEASON"].astype(str).unique().tolist()),
        "season_count": int(frame["SEASON"].nunique()),
        "team_seasons": int(len(frame)),
        "record": {
            "mae": round(float(record_error.abs().mean()), 3),
            "rmse": round(float(np.sqrt(np.mean(record_error**2))), 3),
            "baseline_mae": round(float((41.0 - frame["ACTUAL_WINS"]).abs().mean()), 3),
        },
        "playoffs": {
            "brier": round(playoff, 5),
            "baseline_brier": round(
                _brier(pd.Series(16 / 30, index=frame.index), frame["MADE_PLAYOFFS"]),
                5,
            ),
            "calibration": calibration_table(frame["PLAYOFF_PROB"], frame["MADE_PLAYOFFS"]),
        },
        "championship": {
            "brier": round(championship, 5),
            "baseline_brier": round(
                _brier(pd.Series(1 / 30, index=frame.index), frame["WON_CHAMPIONSHIP"]),
                5,
            ),
        },
        "nba_cup": {
            "brier": round(cup, 5),
            "baseline_brier": round(
                _brier(pd.Series(1 / 30, index=frame.index), frame["WON_CUP"]),
                5,
            ),
        },
    }
