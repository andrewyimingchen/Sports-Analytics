"""Explainable next-season player projections and field-normalized award odds."""

from __future__ import annotations

import numpy as np
import pandas as pd

from nba_insights.analysis.salaries import normalize_name

PLAYER_FORECAST_VERSION = "player-season-v1"
COUNTING_STATS = ("PTS", "REB", "AST", "STL", "BLK", "FG3M")


def _age_multiplier(age: pd.Series) -> pd.Series:
    age = pd.to_numeric(age, errors="coerce")
    return pd.Series(
        np.select(
            [age <= 22, age <= 25, age <= 29, age <= 32, age > 32],
            [1.05, 1.025, 1.0, 0.98, 0.94],
            default=1.0,
        ),
        index=age.index,
    )


def _capped_field_probabilities(scores: pd.Series, expected: float) -> pd.Series:
    """Non-negative field probabilities summing to an expected winner count."""
    weights = np.exp((scores.fillna(scores.median()) - scores.max()).clip(-30, 0))
    probabilities = pd.Series(0.0, index=scores.index)
    remaining = pd.Series(True, index=scores.index)
    target = float(expected)
    while remaining.any() and target > 1e-9:
        scoped = weights[remaining]
        allocation = scoped / scoped.sum() * target
        capped = allocation >= 1
        if not capped.any():
            probabilities.loc[remaining] = allocation
            break
        indices = allocation[capped].index
        probabilities.loc[indices] = 1.0
        remaining.loc[indices] = False
        target -= len(indices)
    return probabilities


def project_player_seasons(
    league: pd.DataFrame,
    roster_players: pd.DataFrame,
    *,
    team_forecast: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Project player roles, box stats, intervals, trajectories, and award fields."""
    required = {"PLAYER_NAME", "MIN", "GP", *COUNTING_STATS}
    if missing := required - set(league):
        raise KeyError(f"player forecast source missing columns: {sorted(missing)}")
    roster = roster_players.copy()
    roster["_KEY"] = roster["PLAYER_NAME"].map(normalize_name)
    source = league.copy()
    source["_KEY"] = source["PLAYER_NAME"].map(normalize_name)
    source = source.sort_values("GP", ascending=False).drop_duplicates("_KEY")
    columns = ["_KEY", "PLAYER_ID", "PLAYER_NAME", "MIN", "GP", *COUNTING_STATS]
    columns += [column for column in ("FG_PCT", "FG3_PCT", "FT_PCT") if column in source]
    joined = roster.merge(source[columns], on="_KEY", how="left", suffixes=("", "_SOURCE"))
    current_minutes = pd.to_numeric(joined["MIN"], errors="coerce").replace(0, np.nan)
    minutes_ratio = joined["PROJECTED_MIN"] / current_minutes
    age_factor = _age_multiplier(joined["AGE"])
    for stat in COUNTING_STATS:
        current = pd.to_numeric(joined[stat], errors="coerce")
        rookie_rate = {"PTS": 12, "REB": 4.5, "AST": 2.5, "STL": 0.7, "BLK": 0.5, "FG3M": 1.2}[stat]
        joined[f"PROJECTED_{stat}"] = (
            current.mul(minutes_ratio).mul(age_factor).fillna(
                rookie_rate * joined["PROJECTED_MIN"] / 24
            )
        ).clip(lower=0)
    for stat, average in (("FG_PCT", 0.47), ("FG3_PCT", 0.36), ("FT_PCT", 0.78)):
        values = pd.to_numeric(joined.get(stat), errors="coerce").fillna(average)
        joined[f"PROJECTED_{stat}"] = (0.72 * values + 0.28 * average).clip(0, 1)
    games = pd.to_numeric(joined["GP"], errors="coerce")
    joined["PROJECTED_GP"] = (66 + 16 * games.fillna(0) / 82).clip(55, 82)
    joined["PTS_LOW"] = (joined["PROJECTED_PTS"] - 4.8).clip(lower=0)
    joined["PTS_HIGH"] = joined["PROJECTED_PTS"] + 4.8
    joined["MIN_LOW"] = (joined["PROJECTED_MIN"] - 5).clip(lower=0)
    joined["MIN_HIGH"] = (joined["PROJECTED_MIN"] + 5).clip(upper=48)
    current_pts = pd.to_numeric(joined["PTS"], errors="coerce")
    change = joined["PROJECTED_PTS"] - current_pts
    joined["TRAJECTORY"] = np.select(
        [~joined["HAS_HISTORY"], change >= 2.0, change <= -2.0],
        ["new entrant", "breakout", "decline"],
        default="steady",
    )
    if team_forecast is not None:
        wins = team_forecast.set_index("TEAM")["PROJECTED_WINS"]
        joined["TEAM_WINS"] = joined["TEAM"].map(wins).fillna(41)
    else:
        joined["TEAM_WINS"] = 41.0
    role = joined["PROJECTED_MIN"] / 36
    mvp_score = (
        0.08 * joined["PROJECTED_PTS"] + 0.035 * joined["PROJECTED_AST"]
        + 0.025 * joined["PROJECTED_REB"] + 0.025 * joined["TEAM_WINS"]
        + 0.12 * joined["PROJECTED_IMPACT"]
    ) * role
    dpoy_score = (
        0.65 * joined["PROJECTED_STL"] + 0.75 * joined["PROJECTED_BLK"]
        + 0.08 * joined["PROJECTED_REB"] + 0.10 * joined["PROJECTED_IMPACT"]
    ) * role
    star_score = mvp_score + 0.018 * joined["PROJECTED_PTS"]
    joined["MVP_PROB"] = _capped_field_probabilities(mvp_score, 1)
    joined["DPOY_PROB"] = _capped_field_probabilities(dpoy_score, 1)
    joined["ALL_STAR_PROB"] = _capped_field_probabilities(star_score, 24)

    feature_columns = ["PROJECTED_PTS", "PROJECTED_REB", "PROJECTED_AST", "AGE"]
    matrix = joined[feature_columns].fillna(joined[feature_columns].median()).to_numpy(float)
    scale = np.nanstd(matrix, axis=0)
    standardized = (matrix[:, None] - matrix[None, :]) / np.where(scale, scale, 1)
    distances = np.sqrt((standardized**2).sum(axis=2))
    np.fill_diagonal(distances, np.inf)
    names = joined["PLAYER_NAME"].astype(str).to_numpy()
    joined["COMPARABLES"] = [names[np.argsort(row)[:3]].tolist() for row in distances]
    return joined.sort_values("PROJECTED_PTS", ascending=False).reset_index(drop=True)


def evaluate_player_season_holdout(projected: pd.DataFrame, actual: pd.DataFrame) -> dict:
    """Evaluate per-game projections against a later-season player table."""
    left = projected.copy()
    right = actual.copy()
    left["_KEY"] = left["PLAYER_NAME"].map(normalize_name)
    right["_KEY"] = right["PLAYER_NAME"].map(normalize_name)
    joined = left.merge(right, on="_KEY", suffixes=("", "_ACTUAL"))
    metrics = {"players": int(len(joined))}
    for stat in COUNTING_STATS:
        error = joined[f"PROJECTED_{stat}"] - pd.to_numeric(joined[f"{stat}_ACTUAL"])
        metrics[f"{stat.lower()}_mae"] = round(float(error.abs().mean()), 3)
    if {"PTS_LOW", "PTS_HIGH", "PTS_ACTUAL"} <= set(joined):
        covered = joined["PTS_ACTUAL"].between(joined["PTS_LOW"], joined["PTS_HIGH"])
        metrics["pts_interval_coverage"] = round(float(covered.mean()), 4)
    return metrics
