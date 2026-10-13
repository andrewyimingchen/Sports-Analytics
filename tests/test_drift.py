"""Live calibration and the drift verdict."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from nba_insights.ml.drift import live_calibration


def _season(n: int, p_true: np.ndarray | float, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    p = np.broadcast_to(p_true, n)
    return pd.DataFrame(
        {
            "GAME_DATE": pd.date_range("2026-10-20", periods=n, freq="6h"),
            "home_win": (rng.random(n) < p).astype(int),
        }
    )


def test_calibrated_predictions_are_ok_and_summarized():
    rng = np.random.default_rng(1)
    p = rng.uniform(0.2, 0.8, 400)
    games = _season(400, p, seed=2)
    reference = {"log_loss": 0.65}
    report = live_calibration(games, pd.Series(p), reference, recent_days=60)
    assert report["season_to_date"]["n_games"] == 400
    assert report["drift"]["status"] == "ok"
    assert report["weekly"] and sum(w["n_games"] for w in report["weekly"]) == 400
    assert sum(b["count"] for b in report["calibration"]) == 400
    for row in report["calibration"]:  # calibrated: observed tracks forecast
        if row["count"] >= 60:
            assert row["observed_rate"] == pytest.approx(row["mean_probability"], abs=0.12)


def test_confidently_wrong_predictions_are_drift():
    games = _season(300, 0.5, seed=3)
    # always 85% on the home team when outcomes are coin flips
    report = live_calibration(games, pd.Series(np.full(300, 0.85)), {"log_loss": 0.59})
    verdict = report["drift"]
    assert verdict["status"] == "drift"
    assert verdict["recent_log_loss"] > verdict["threshold"] > 0.59


def test_small_samples_and_missing_reference_are_not_judged():
    few = _season(40, 0.6)
    report = live_calibration(few, pd.Series(np.full(40, 0.6)), {"log_loss": 0.6})
    assert report["drift"] == {
        "status": "insufficient_games",
        "rule": report["drift"]["rule"],
        "games": 40,
        "needed": 100,
    }
    assert live_calibration(few, pd.Series(np.full(40, 0.6)), None)["drift"]["status"] == (
        "no_reference"
    )


def test_recent_window_only_counts_the_last_days():
    games = _season(400, 0.6)  # 100 days of games at 4 per day
    report = live_calibration(
        games, pd.Series(np.full(400, 0.6)), {"log_loss": 0.67}, recent_days=10
    )
    assert report["recent"]["n_games"] == 40
    assert report["as_of"] == games["GAME_DATE"].max().date().isoformat()
