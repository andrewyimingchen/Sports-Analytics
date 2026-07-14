"""Trend analysis over game logs and career totals.

All functions are pure: DataFrames in, DataFrames out. Input column names
follow stats.nba.com conventions (PTS, AST, REB, GP, GAME_DATE, SEASON_ID).
"""

from __future__ import annotations

import pandas as pd

PER_GAME_STATS = ["PTS", "AST", "REB", "STL", "BLK", "TOV", "MIN"]


def rolling_form(game_log: pd.DataFrame, stat: str = "PTS", window: int = 10) -> pd.DataFrame:
    """Per-game values of *stat* in chronological order with a rolling mean.

    Returns columns: GAME_DATE, <stat>, ROLLING — one row per game. The
    rolling mean uses ``min_periods=1`` so early games still get a value.
    """
    if stat not in game_log.columns:
        raise KeyError(f"stat {stat!r} not in game log columns")
    df = game_log.copy()
    df["GAME_DATE"] = pd.to_datetime(df["GAME_DATE"], format="mixed")
    df = df.sort_values("GAME_DATE").reset_index(drop=True)
    out = df[["GAME_DATE", stat]].copy()
    out["ROLLING"] = out[stat].rolling(window, min_periods=1).mean()
    return out


def career_per_game(season_totals: pd.DataFrame, stats: list[str] | None = None) -> pd.DataFrame:
    """Convert career season *totals* into per-game averages by season.

    Returns one row per season with SEASON_ID, GP, and each requested stat
    divided by games played. Seasons with 0 GP are dropped. When a player was
    traded mid-season stats.nba.com emits one row per team plus a TOT row;
    duplicate seasons are collapsed by keeping the row with the most games.
    """
    stats = stats or [s for s in PER_GAME_STATS if s in season_totals.columns]
    missing = [s for s in stats if s not in season_totals.columns]
    if missing:
        raise KeyError(f"columns missing from season totals: {missing}")

    df = season_totals[season_totals["GP"] > 0].copy()
    df = (
        df.sort_values("GP", ascending=False)
        .drop_duplicates("SEASON_ID")
        .sort_values("SEASON_ID")
        .reset_index(drop=True)
    )
    out = df[["SEASON_ID", "GP"]].copy()
    for stat in stats:
        out[stat] = (df[stat] / df["GP"]).round(1)
    return out
