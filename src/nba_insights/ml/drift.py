"""Live calibration of the game-outcome model, and when to call it drift.

The holdout in ``models/manifest.json`` says how the model did on a full
completed season. This module scores the shipped model on the *current*
season as it is played: every completed game's prediction from pre-game
features only (the same shifted, prior-seeded form the model trains on),
grouped by week, plus a recent window compared with the holdout.

Drift is judged statistically rather than by a fixed margin: log loss over
100 games has a standard error near 0.05, so a fixed threshold either cries
wolf or misses real degradation. The recent window alerts when its mean log
loss exceeds the holdout's by more than ``z`` standard errors of the
per-game losses, and only once it has ``min_games`` games.

Pure functions: DataFrames and dicts in, dicts out.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

EPSILON = 1e-15
MIN_GAMES = 100  # recent window size before drift is judged
RECENT_DAYS = 28
Z = 2.0
CALIBRATION_EDGES = [0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0]


def _game_losses(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(p, EPSILON, 1 - EPSILON)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def _summary(y: np.ndarray, p: np.ndarray) -> dict[str, Any]:
    if len(y) == 0:
        return {"n_games": 0}
    losses = _game_losses(y, p)
    home_rate = float(y.mean())
    return {
        "n_games": int(len(y)),
        "accuracy": float(((p >= 0.5) == (y == 1)).mean()),
        "log_loss": float(losses.mean()),
        "log_loss_se": float(losses.std(ddof=1) / math.sqrt(len(y))) if len(y) > 1 else None,
        "brier": float(((p - y) ** 2).mean()),
        "home_win_rate": home_rate,
        "mean_prediction": float(p.mean()),
    }


def live_calibration(
    games: pd.DataFrame,
    probabilities: pd.Series,
    reference: dict[str, Any] | None,
    *,
    as_of: pd.Timestamp | None = None,
    recent_days: int = RECENT_DAYS,
    min_games: int = MIN_GAMES,
    z: float = Z,
) -> dict[str, Any]:
    """Season-to-date, weekly, and recent-window calibration plus a drift verdict.

    *games* needs GAME_DATE and home_win (one row per completed game, pre-game
    features); *probabilities* are the model's home-win probabilities for the
    same rows. *reference* is the recorded holdout metrics (needs log_loss).
    """
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(games["GAME_DATE"]).to_numpy(),
            "y": games["home_win"].astype(float).to_numpy(),
            "p": np.asarray(probabilities, dtype=float),
        }
    ).sort_values("date")
    as_of = as_of if as_of is not None else (frame["date"].max() if len(frame) else None)

    weekly = []
    if len(frame):
        for week, rows in frame.groupby(frame["date"].dt.to_period("W-SUN")):
            weekly.append(
                {
                    "week_start": week.start_time.date().isoformat(),
                    **_summary(rows["y"].to_numpy(), rows["p"].to_numpy()),
                }
            )

    bins = []
    if len(frame):
        binned = pd.cut(frame["p"], CALIBRATION_EDGES, include_lowest=True)
        for interval, rows in frame.groupby(binned, observed=True):
            bins.append(
                {
                    "lower": float(interval.left),
                    "upper": float(interval.right),
                    "count": int(len(rows)),
                    "mean_probability": float(rows["p"].mean()),
                    "observed_rate": float(rows["y"].mean()),
                }
            )

    recent = frame
    if as_of is not None:
        recent = frame[frame["date"] > pd.Timestamp(as_of) - pd.Timedelta(days=recent_days)]
    recent_summary = _summary(recent["y"].to_numpy(), recent["p"].to_numpy())

    verdict = _verdict(recent_summary, reference, min_games=min_games, z=z)
    return {
        "as_of": None if as_of is None else pd.Timestamp(as_of).date().isoformat(),
        "season_to_date": _summary(frame["y"].to_numpy(), frame["p"].to_numpy()),
        "recent": {"days": recent_days, **recent_summary},
        "weekly": weekly,
        "calibration": bins,
        "reference": reference,
        "drift": verdict,
    }


def _verdict(
    recent: dict[str, Any], reference: dict[str, Any] | None, *, min_games: int, z: float
) -> dict[str, Any]:
    rule = f"recent log loss > holdout log loss + {z:g} standard errors, once {min_games}+ games"
    if not reference or reference.get("log_loss") is None:
        return {"status": "no_reference", "rule": rule}
    if recent.get("n_games", 0) < min_games or recent.get("log_loss_se") is None:
        return {
            "status": "insufficient_games",
            "rule": rule,
            "games": recent.get("n_games", 0),
            "needed": min_games,
        }
    threshold = float(reference["log_loss"]) + z * float(recent["log_loss_se"])
    drifting = float(recent["log_loss"]) > threshold
    return {
        "status": "drift" if drifting else "ok",
        "rule": rule,
        "recent_log_loss": recent["log_loss"],
        "holdout_log_loss": float(reference["log_loss"]),
        "threshold": threshold,
    }
