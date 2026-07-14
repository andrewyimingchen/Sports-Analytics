"""League-relative percentile ranks for a player."""

from __future__ import annotations

import pandas as pd

DEFAULT_STATS = ["PTS", "AST", "REB", "STL", "BLK", "FG_PCT", "FG3_PCT", "FT_PCT"]


def percentile_ranks(
    league_stats: pd.DataFrame,
    player_name: str,
    stats: list[str] | None = None,
    min_games: int = 10,
) -> pd.Series:
    """Percentile (0-100) of a player against the league for each stat.

    *league_stats* is one row per player (PLAYER_NAME plus stat columns), as
    returned by the league dashboard. Players with fewer than *min_games*
    are excluded from the distribution so deep-bench small samples don't
    distort ranks. Raises KeyError if the player isn't found.
    """
    stats = stats or [s for s in DEFAULT_STATS if s in league_stats.columns]
    pool = league_stats
    if "GP" in pool.columns:
        pool = pool[pool["GP"] >= min_games]

    row = pool[pool["PLAYER_NAME"] == player_name]
    if row.empty:
        raise KeyError(f"player {player_name!r} not found (or under {min_games} games)")

    ranks = {stat: round(pool[stat].rank(pct=True)[row.index[0]] * 100, 1) for stat in stats}
    return pd.Series(ranks, name=player_name)
