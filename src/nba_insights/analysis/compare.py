"""Side-by-side player comparisons."""

from __future__ import annotations

import pandas as pd

DEFAULT_STATS = [
    "GP",
    "MIN",
    "PTS",
    "AST",
    "REB",
    "STL",
    "BLK",
    "TOV",
    "FG_PCT",
    "FG3_PCT",
    "NET_RATING",
    "CLUTCH_NET_RATING",
]


def comparison_table(
    league_stats: pd.DataFrame,
    player_names: list[str],
    stats: list[str] | None = None,
) -> pd.DataFrame:
    """One column per player, one row per stat, from league per-game data.

    Raises KeyError listing any players not present in *league_stats*.
    """
    stats = stats or [s for s in DEFAULT_STATS if s in league_stats.columns]
    rows = league_stats[league_stats["PLAYER_NAME"].isin(player_names)]
    missing = set(player_names) - set(rows["PLAYER_NAME"])
    if missing:
        raise KeyError(f"players not found in league stats: {sorted(missing)}")
    table = rows.set_index("PLAYER_NAME")[stats].T
    return table[player_names]  # preserve caller's column order
