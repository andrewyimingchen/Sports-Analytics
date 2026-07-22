"""Game outcome model: P(home team wins) from pre-game form differentials.

Logistic regression on home-minus-away rolling-form features; the intercept
absorbs home-court advantage. Evaluated against the "home team always wins"
baseline, which historically sits around 54-58%.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from nba_insights.ml.features import OUTCOME_FEATURES


class GameOutcomeModel:
    def __init__(self, pipeline: Pipeline | None = None, C: float = 0.25):
        # Regularization matters: the form features are deliberately
        # collinear (net rating, ratings, four factors). C is tuned by
        # ml.train on a dev season carved from the training years — never
        # on the reported holdout.
        self.pipeline = pipeline or make_pipeline(StandardScaler(), LogisticRegression(C=C))

    def fit(self, matchups: pd.DataFrame) -> GameOutcomeModel:
        """*matchups* is the output of features.game_matchup_frame."""
        self.pipeline.fit(matchups[OUTCOME_FEATURES], matchups["home_win"])
        return self

    def predict_proba(self, features: pd.DataFrame) -> pd.Series:
        """P(home win) per row of outcome features."""
        proba = self.pipeline.predict_proba(features[OUTCOME_FEATURES])[:, 1]
        return pd.Series(proba, index=features.index, name="home_win_prob")

    def explain(self, features: pd.DataFrame) -> list[dict]:
        """Per-feature log-odds contributions for one matchup.

        Contributions are local to the fitted logistic pipeline: inputs are
        standardized by the pipeline and multiplied by the fitted coefficient.
        They explain this model's number, not a causal basketball effect.
        """
        if len(features) != 1:
            raise ValueError("explain expects exactly one matchup row")
        transformer = self.pipeline[:-1]
        estimator = self.pipeline.steps[-1][1]
        if not hasattr(estimator, "coef_") or not hasattr(estimator, "intercept_"):
            raise TypeError("outcome estimator does not expose linear coefficients")
        transformed = np.asarray(transformer.transform(features[OUTCOME_FEATURES]))[0]
        coefficients = np.asarray(estimator.coef_)[0]
        rows = []
        for feature, raw, standardized, coefficient in zip(
            OUTCOME_FEATURES,
            features.iloc[0][OUTCOME_FEATURES],
            transformed,
            coefficients,
            strict=True,
        ):
            contribution = float(standardized * coefficient)
            rows.append(
                {
                    "feature": feature,
                    "raw_difference": float(raw),
                    "standardized_value": float(standardized),
                    "log_odds_contribution": contribution,
                    "odds_multiplier": float(np.exp(contribution)),
                }
            )
        rows.append(
            {
                "feature": "model_intercept",
                "raw_difference": None,
                "standardized_value": None,
                "log_odds_contribution": float(estimator.intercept_[0]),
                "odds_multiplier": float(np.exp(estimator.intercept_[0])),
            }
        )
        return sorted(rows, key=lambda row: abs(row["log_odds_contribution"]), reverse=True)

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
