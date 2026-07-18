"""Reshape a player's game log into the situational splits that
Basketball-Reference and NBA.com show — home/away, by month, by rest, and by
opponent — from data we already fetch.

Pure: a game-log DataFrame in, a per-split table out. No I/O. Shooting
percentages are aggregated from makes/attempts (sum FGM / sum FGA), not
averaged per game, so they weight by volume the way a real split does.
"""

from __future__ import annotations

import calendar

import pandas as pd

# the split dimensions this module knows how to build
DIMENSIONS = ("home_away", "month", "rest", "opponent")

# per-game-average stats reported for every split
_MEAN_STATS = ["MIN", "PTS", "REB", "AST", "FG3M", "PLUS_MINUS"]
# shooting rates reported as aggregate makes/attempts, when the columns exist
_SHOOTING = {"FG_PCT": ("FGM", "FGA"), "FG3_PCT": ("FG3M", "FG3A"), "FT_PCT": ("FTM", "FTA")}

_MONTH_ORDER = list(calendar.month_name)  # ["", "January", ..., "December"]


def _rest_label(days: float) -> str:
    if pd.isna(days):
        return "Season opener"
    days = int(days)
    if days <= 1:
        return "0-1 days (B2B)"
    if days == 2:
        return "2 days"
    return "3+ days"


def _group_key(df: pd.DataFrame, dimension: str) -> tuple[pd.Series, list[str]]:
    """Return (group label per row, ordered category list) for a dimension."""
    if dimension == "home_away":
        key = df["MATCHUP"].str.contains("vs.", regex=False).map({True: "Home", False: "Away"})
        return key, ["Home", "Away"]
    if dimension == "month":
        key = pd.to_datetime(df["GAME_DATE"]).dt.month.map(lambda m: _MONTH_ORDER[m])
        order = [m for m in _MONTH_ORDER if m in set(key)]
        return key, order
    if dimension == "rest":
        gap = pd.to_datetime(df["GAME_DATE"]).sort_values().diff().dt.days
        gap = gap.reindex(df.index)
        key = gap.map(_rest_label)
        rest_order = ("0-1 days (B2B)", "2 days", "3+ days", "Season opener")
        return key, [c for c in rest_order if c in set(key)]
    if dimension == "opponent":
        key = df["MATCHUP"].str.split().str[-1]  # trailing tricode
        order = sorted(set(key.dropna()))
        return key, order
    raise ValueError(f"unknown split dimension: {dimension!r}")


def player_splits(game_log: pd.DataFrame, dimension: str) -> pd.DataFrame:
    """Aggregate a player's game log into situational splits.

    *dimension* is one of DIMENSIONS. Returns one row per split value (ordered
    naturally — Home before Away, months chronological, rest ascending) with GP,
    per-game averages (MIN, PTS, REB, AST, 3PM, +/-), and aggregate shooting
    percentages (FG%, 3P%, FT%) computed from summed makes/attempts. Raises
    KeyError when a required column is missing.
    """
    need = ["GAME_DATE", "MATCHUP", "MIN", "PTS", "REB", "AST"]
    missing = [c for c in need if c not in game_log.columns]
    if missing:
        raise KeyError(f"game log missing columns: {missing}")

    df = game_log.copy()
    key, order = _group_key(df, dimension)
    df = df.assign(_split=key)

    rows = []
    for label in order:
        grp = df[df["_split"] == label]
        row: dict[str, object] = {"Split": label, "GP": int(len(grp))}
        for stat in _MEAN_STATS:
            if stat in grp.columns:
                row[stat] = round(float(grp[stat].mean()), 1)
        for pct, (makes, att) in _SHOOTING.items():
            if makes in grp.columns and att in grp.columns:
                total_att = float(grp[att].sum())
                row[pct] = round(grp[makes].sum() / total_att, 3) if total_att else None
        rows.append(row)
    return pd.DataFrame(rows)
