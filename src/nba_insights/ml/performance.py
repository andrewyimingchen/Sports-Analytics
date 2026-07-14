"""Player points model: predict next-game PTS from recent form.

Ridge regression trained league-wide on player-game rows. The honest
benchmark is the player's own 10-game rolling average — the model has to
beat that to justify existing, and the margin is reported at train time.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from nba_insights.ml.features import POINTS_FEATURES


class PlayerPointsModel:
    def __init__(self, pipeline: Pipeline | None = None):
        self.pipeline = pipeline or make_pipeline(StandardScaler(), Ridge(alpha=1.0))

    def fit(self, player_games: pd.DataFrame) -> PlayerPointsModel:
        """*player_games* is the output of features.player_game_features."""
        self.pipeline.fit(player_games[POINTS_FEATURES], player_games["PTS"])
        return self

    def predict(self, features: pd.DataFrame) -> pd.Series:
        pred = self.pipeline.predict(features[POINTS_FEATURES])
        return pd.Series(pred, index=features.index, name="pred_pts").clip(lower=0)

    def evaluate(self, player_games: pd.DataFrame) -> dict:
        y = player_games["PTS"]
        pred = self.predict(player_games)
        return {
            "n_games": len(player_games),
            "mae": mean_absolute_error(y, pred),
            "baseline_mae": mean_absolute_error(y, player_games["pts_r10"]),
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, path)

    @classmethod
    def load(cls, path: str | Path) -> PlayerPointsModel:
        return cls(pipeline=joblib.load(path))
