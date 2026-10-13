"""Player stat-line model: predict next-game box stats from recent form.

Two-stage: minutes are predicted from rotation trend, rest and roster
availability; a per-minute rate for each stat in the line (PTS, REB, AST,
STL, FG3M; BLK was measured and rejected, see features.STAT_LINE) from the
stat's own EWMA form plus shared opponent context; each projection is
minutes x rate. Most of the variance in a player's counting stats is
variance in minutes, and modeling it separately beat the single-stage ridge
on holdout for points (MAE 4.58 vs 4.70; naive 10-game-average baseline
4.72). The class keeps its original name because points stay the headline
(with an empirical 80% interval), and it loads legacy points-only artifacts.
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

from nba_insights.ml.features import STAT_LINE, stat_baseline_col, stat_rate_col

MIN_FEATURES = ["min_r5", "min_ewm", "rest_days", "home", "own_missing_min"]


def rate_features(stat: str) -> list[str]:
    """Rate-stage inputs: the stat's own per-minute EWMA plus shared context."""
    return [
        stat_rate_col(stat),
        "fga_r5",
        "home",
        "opp_form_drtg",
        "opp_form_pace",
        "opp_form_net",
        "own_missing_min",
    ]


RATE_FEATURES = rate_features("PTS")


def _pipe() -> Pipeline:
    return make_pipeline(StandardScaler(), Ridge(alpha=1.0))


N_INTERVAL_BINS = 4  # residual spread grows with projection level


class PlayerPointsModel:
    def __init__(
        self,
        minutes: Pipeline | None = None,
        rates: dict[str, Pipeline] | None = None,
        resid_quantiles: dict | tuple[float, float] | None = None,
    ):
        self.minutes = minutes or _pipe()
        # one per-minute rate stage per stat; PTS is always present once fit
        self.rates: dict[str, Pipeline] = rates or {}
        # Empirical 80% interval around the projection. Residual scatter is
        # heteroscedastic — a 30ppg projection has far more spread than an
        # 8ppg one — so training residuals are binned by predicted level:
        # {"edges": [...], "quantiles": [(q10, q90), ...]}. Old artifacts
        # carry a pooled (q10, q90) tuple; None predates intervals entirely.
        # Intervals cover points only.
        self.resid_quantiles = resid_quantiles

    @property
    def rate(self) -> Pipeline:
        """The points rate stage (the original single-stat interface)."""
        return self.rates["PTS"]

    def fit(self, player_games: pd.DataFrame) -> PlayerPointsModel:
        """*player_games* is the output of features.player_game_features.

        Fits a rate stage for every stat whose columns are present, so a
        points-only frame still trains a points-only model.
        """
        self.minutes.fit(player_games[MIN_FEATURES], player_games["MIN"])
        minutes_floor = player_games["MIN"].clip(lower=1)
        self.rates = {}
        for stat in STAT_LINE:
            columns = rate_features(stat)
            if stat not in player_games or not set(columns) <= set(player_games.columns):
                continue
            stage = _pipe()
            stage.fit(player_games[columns], player_games[stat] / minutes_floor)
            self.rates[stat] = stage
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

    def predict_line(self, features: pd.DataFrame) -> pd.DataFrame:
        """Projected stat line: one column per fitted stat, PTS first.

        Stats whose inputs are missing from *features* are skipped, so
        frames built for the points-only model keep working.
        """
        minutes = pd.Series(
            self.minutes.predict(features[MIN_FEATURES]), index=features.index
        ).clip(0, 48)
        line = {}
        for stat in STAT_LINE:
            stage = self.rates.get(stat)
            if stage is None or not set(rate_features(stat)) <= set(features.columns):
                continue
            rate = pd.Series(
                stage.predict(features[rate_features(stat)]), index=features.index
            ).clip(lower=0)
            line[stat] = minutes * rate
        return pd.DataFrame(line, index=features.index)

    def predict(self, features: pd.DataFrame) -> pd.Series:
        """Projected points (the original single-stat interface)."""
        return self.predict_line(features)["PTS"].rename("pred_pts")

    def evaluate(self, player_games: pd.DataFrame) -> dict:
        """Holdout MAE per stat against the player's own 10-game average.

        Top-level mae/baseline_mae/interval_coverage stay points-only for
        continuity with the recorded history; the full line is under "line".
        """
        y = player_games["PTS"]
        line_pred = self.predict_line(player_games)
        pred = line_pred["PTS"]
        line = {
            stat: {
                "mae": float(mean_absolute_error(player_games[stat], line_pred[stat])),
                "baseline_mae": float(
                    mean_absolute_error(player_games[stat], player_games[stat_baseline_col(stat)])
                ),
            }
            for stat in line_pred.columns
            if stat in player_games and stat_baseline_col(stat) in player_games
        }
        out = {
            "n_games": len(player_games),
            "mae": mean_absolute_error(y, pred),
            "baseline_mae": mean_absolute_error(y, player_games["pts_r10"]),
            "line": line,
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
                "rates": self.rates,
                "resid_quantiles": self.resid_quantiles,
            },
            path,
        )

    @classmethod
    def load(cls, path: str | Path) -> PlayerPointsModel:
        blobs = joblib.load(path)
        rates = blobs.get("rates") or {"PTS": blobs["rate"]}  # legacy points-only
        return cls(
            minutes=blobs["minutes"],
            rates=rates,
            resid_quantiles=blobs.get("resid_quantiles"),
        )
