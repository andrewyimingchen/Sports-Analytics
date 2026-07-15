"""Player stat-line model: predict next-game box stats from recent form.

Two-stage: minutes are predicted from rotation trend, rest and roster
availability; a per-minute rate for each stat in the line (PTS, REB, AST,
STL, FG3M — BLK measured and rejected, see features.STAT_LINE) from EWMA
form and opponent context; each projection is the product. Most of the
variance in a player's counting stats is variance in minutes, and modeling
it separately beat the single-stage ridge on holdout
for points (MAE 4.58 vs 4.70; naive 10-game-average baseline 4.72). The
class keeps its original name — points is still the headline — and loads
legacy points-only artifacts.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import StandardScaler

from nba_insights.ml.features import STAT_LINE

MIN_FEATURES = ["min_r5", "min_ewm", "rest_days", "home", "own_missing_min"]


def rate_col(stat: str) -> str:
    return "rate_ewm" if stat == "PTS" else f"{stat.lower()}_rate_ewm"


def baseline_col(stat: str) -> str:
    return f"{stat.lower()}_r10"


def rate_features(stat: str) -> list[str]:
    """Rate-stage features: the stat's own per-minute EWMA plus shared context."""
    return [
        rate_col(stat),
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


class PlayerPointsModel:
    def __init__(self, minutes: Pipeline | None = None, rates: dict[str, Pipeline] | None = None):
        self.minutes = minutes or _pipe()
        self.rates = rates or {}

    @property
    def rate(self) -> Pipeline:
        """The PTS rate stage (back-compat: methodology coefficient chart)."""
        return self.rates["PTS"]

    def fit(self, player_games: pd.DataFrame) -> PlayerPointsModel:
        """*player_games* is the output of features.player_game_features.

        Fits one rate stage per stat whose columns are present, so a
        points-only frame still trains a points-only model.
        """
        self.minutes.fit(player_games[MIN_FEATURES], player_games["MIN"])
        minutes_floor = player_games["MIN"].clip(lower=1)
        for stat in STAT_LINE:
            cols = rate_features(stat)
            if stat not in player_games.columns or not set(cols) <= set(player_games.columns):
                continue
            pipe = _pipe()
            pipe.fit(player_games[cols], player_games[stat] / minutes_floor)
            self.rates[stat] = pipe
        return self

    def predict_line(self, features: pd.DataFrame) -> pd.DataFrame:
        """Projected stat line: one column per fitted stat, PTS always first.

        Stats whose feature columns are missing from *features* are skipped,
        so inputs built for the points-only model keep working.
        """
        minutes = pd.Series(
            self.minutes.predict(features[MIN_FEATURES]), index=features.index
        ).clip(0, 48)
        line = {}
        for stat in STAT_LINE:
            pipe = self.rates.get(stat)
            if pipe is None or not set(rate_features(stat)) <= set(features.columns):
                continue
            rate = pd.Series(
                pipe.predict(features[rate_features(stat)]), index=features.index
            ).clip(lower=0)
            line[stat] = minutes * rate
        return pd.DataFrame(line)

    def predict(self, features: pd.DataFrame) -> pd.Series:
        """Projected points (the original single-stat interface)."""
        return self.predict_line(features)["PTS"].rename("pred_pts")

    def evaluate(self, player_games: pd.DataFrame) -> dict:
        """Per-stat holdout MAE vs the player's own 10-game average.

        Top-level mae/baseline_mae stay points-only for continuity with the
        recorded experiment log; the full line lives under "line".
        """
        pred = self.predict_line(player_games)
        line = {}
        for stat in pred.columns:
            if stat not in player_games or baseline_col(stat) not in player_games:
                continue
            line[stat] = {
                "mae": mean_absolute_error(player_games[stat], pred[stat]),
                "baseline_mae": mean_absolute_error(
                    player_games[stat], player_games[baseline_col(stat)]
                ),
            }
        return {
            "n_games": len(player_games),
            "mae": line["PTS"]["mae"],
            "baseline_mae": line["PTS"]["baseline_mae"],
            "line": line,
        }

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"minutes": self.minutes, "rates": self.rates}, path)

    @classmethod
    def load(cls, path: str | Path) -> PlayerPointsModel:
        blobs = joblib.load(path)
        rates = blobs.get("rates") or {"PTS": blobs["rate"]}  # legacy points-only
        return cls(minutes=blobs["minutes"], rates=rates)
