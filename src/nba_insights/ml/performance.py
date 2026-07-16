"""Player points model: predict next-game PTS from recent form.

Two-stage: minutes are predicted from rotation trend, rest and roster
availability; per-minute scoring rate from EWMA form and opponent context;
the point projection is their product. Most of the variance in a player's
points is variance in minutes, and modeling it separately beat the
single-stage ridge on holdout (MAE 4.58 vs 4.70; naive 10-game-average
baseline 4.72).
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

MIN_FEATURES = ["min_r5", "min_ewm", "rest_days", "home", "own_missing_min"]
RATE_FEATURES = [
    "rate_ewm",
    "fga_r5",
    "home",
    "opp_form_drtg",
    "opp_form_pace",
    "opp_form_net",
    "own_missing_min",
]


def _pipe() -> Pipeline:
    return make_pipeline(StandardScaler(), Ridge(alpha=1.0))


N_INTERVAL_BINS = 4  # residual spread grows with projection level


class PlayerPointsModel:
    def __init__(
        self,
        minutes: Pipeline | None = None,
        rate: Pipeline | None = None,
        resid_quantiles: dict | tuple[float, float] | None = None,
    ):
        self.minutes = minutes or _pipe()
        self.rate = rate or _pipe()
        # Empirical 80% interval around the projection. Residual scatter is
        # heteroscedastic — a 30ppg projection has far more spread than an
        # 8ppg one — so training residuals are binned by predicted level:
        # {"edges": [...], "quantiles": [(q10, q90), ...]}. Old artifacts
        # carry a pooled (q10, q90) tuple; None predates intervals entirely.
        self.resid_quantiles = resid_quantiles

    def fit(self, player_games: pd.DataFrame) -> PlayerPointsModel:
        """*player_games* is the output of features.player_game_features."""
        self.minutes.fit(player_games[MIN_FEATURES], player_games["MIN"])
        rate_target = player_games["PTS"] / player_games["MIN"].clip(lower=1)
        self.rate.fit(player_games[RATE_FEATURES], rate_target)
        pred = self.predict(player_games)
        resid = player_games["PTS"] - pred
        edges = pred.quantile([i / N_INTERVAL_BINS for i in range(1, N_INTERVAL_BINS)])
        bins = np.searchsorted(edges.to_numpy(), pred.to_numpy())
        self.resid_quantiles = {
            "edges": [float(e) for e in edges],
            "quantiles": [
                (float(resid[bins == b].quantile(0.10)), float(resid[bins == b].quantile(0.90)))
                for b in range(N_INTERVAL_BINS)
            ],
        }
        return self

    def interval(self, prediction: float) -> tuple[float, float] | None:
        """Empirical 80% interval around a projection, floored at 0 points."""
        if self.resid_quantiles is None:
            return None
        if isinstance(self.resid_quantiles, dict):
            idx = int(np.searchsorted(self.resid_quantiles["edges"], prediction))
            lo, hi = self.resid_quantiles["quantiles"][idx]
        else:  # pooled band from a pre-binning artifact
            lo, hi = self.resid_quantiles
        return (max(0.0, prediction + lo), max(0.0, prediction + hi))

    def predict(self, features: pd.DataFrame) -> pd.Series:
        minutes = pd.Series(
            self.minutes.predict(features[MIN_FEATURES]), index=features.index
        ).clip(0, 48)
        rate = pd.Series(
            self.rate.predict(features[RATE_FEATURES]), index=features.index
        ).clip(lower=0)
        return (minutes * rate).rename("pred_pts")

    def evaluate(self, player_games: pd.DataFrame) -> dict:
        y = player_games["PTS"]
        pred = self.predict(player_games)
        out = {
            "n_games": len(player_games),
            "mae": mean_absolute_error(y, pred),
            "baseline_mae": mean_absolute_error(y, player_games["pts_r10"]),
        }
        if self.resid_quantiles is not None:
            # measured coverage of the nominal 80% interval on this data
            bands = np.array([self.interval(p) for p in pred])
            hit = (y.to_numpy() >= bands[:, 0]) & (y.to_numpy() <= bands[:, 1])
            out["interval_coverage"] = float(hit.mean())
        return out

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "minutes": self.minutes,
                "rate": self.rate,
                "resid_quantiles": self.resid_quantiles,
            },
            path,
        )

    @classmethod
    def load(cls, path: str | Path) -> PlayerPointsModel:
        blobs = joblib.load(path)
        return cls(
            minutes=blobs["minutes"],
            rate=blobs["rate"],
            resid_quantiles=blobs.get("resid_quantiles"),
        )
