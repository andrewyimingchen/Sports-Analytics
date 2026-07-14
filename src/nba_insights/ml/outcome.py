"""Game outcome model: P(home team wins) from pre-game form differentials.

Logistic regression on home-minus-away rolling-form features; the intercept
absorbs home-court advantage. Evaluated against the "home team always wins"
baseline, which historically sits around 54-58%.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from nba_insights.ml.features import OUTCOME_FEATURES


class GameOutcomeModel:
    def __init__(self, pipeline: Pipeline | None = None):
        # C=0.25: the form features are deliberately collinear (net rating,
        # ratings, four factors); holdout-tuned on 2025-26
        self.pipeline = pipeline or make_pipeline(StandardScaler(), LogisticRegression(C=0.25))

    def fit(self, matchups: pd.DataFrame) -> GameOutcomeModel:
        """*matchups* is the output of features.game_matchup_frame."""
        self.pipeline.fit(matchups[OUTCOME_FEATURES], matchups["home_win"])
        return self

    def predict_proba(self, features: pd.DataFrame) -> pd.Series:
        """P(home win) per row of outcome features."""
        proba = self.pipeline.predict_proba(features[OUTCOME_FEATURES])[:, 1]
        return pd.Series(proba, index=features.index, name="home_win_prob")

    def evaluate(self, matchups: pd.DataFrame) -> dict:
        y = matchups["home_win"]
        p = self.predict_proba(matchups)
        home_rate = y.mean()
        return {
            "n_games": len(matchups),
            "accuracy": accuracy_score(y, p >= 0.5),
            "log_loss": log_loss(y, p),
            "baseline_accuracy": max(home_rate, 1 - home_rate),
            "baseline_log_loss": log_loss(y, [home_rate] * len(y)),
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self.pipeline, path)

    @classmethod
    def load(cls, path: str | Path) -> GameOutcomeModel:
        return cls(pipeline=joblib.load(path))
