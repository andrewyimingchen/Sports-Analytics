"""Infer a rough position group from role stats, for positional percentiles.

The league dashboard carries no position, and per-player lookups would be
hundreds of network calls — so a player's group (Guard / Wing / Big) is
inferred from how they play: a frontcourt score from per-36 rebounding,
blocks, assists, and three-point volume, split into terciles. It is a
heuristic (a stretch big can look like a wing) — always labelled as such.

Pure: DataFrame in, Series / DataFrame out.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nba_insights.analysis.percentiles import percentile_ranks

GROUPS = ["Guard", "Wing", "Big"]


def _frontcourt_score(pool: pd.DataFrame) -> pd.Series:
    """Higher = more frontcourt. Rebounds and blocks push up; assists and
    three-point volume push down; a rim-level FG% nudges up (weights tuned so
    playmaking bigs like Jokić land as Bigs, not guards)."""
    minutes = pool["MIN"].where(pool["MIN"] > 0, np.nan)
    per36 = {c: pool[c] * 36.0 / minutes for c in ("REB", "BLK", "AST", "FG3A")}

    def z(s: pd.Series) -> pd.Series:
        s = s.fillna(s.mean())
        return (s - s.mean()) / (s.std(ddof=0) or 1.0)

    return (
        z(per36["REB"])
        + z(per36["BLK"])
        - 0.4 * z(per36["AST"])
        - 0.3 * z(per36["FG3A"])
        + 0.4 * z(pool["FG_PCT"])
    )


def infer_positions(league: pd.DataFrame, min_minutes: float = 15.0) -> pd.Series:
    """A Guard/Wing/Big label per player, indexed like *league*.

    Positions are terciles of a frontcourt score computed over the
    rotation pool (>= *min_minutes*); everyone is then labelled against that
    pool's cutoffs (bench players included, just not shaping the cutoffs).
    Raises KeyError on missing required columns.
    """
    need = ["MIN", "REB", "BLK", "AST", "FG3A", "FG_PCT"]
    missing = [c for c in need if c not in league.columns]
    if missing:
        raise KeyError(f"league table missing columns: {missing}")

    rotation = league[league["MIN"] >= min_minutes]
    ref = _frontcourt_score(rotation if len(rotation) >= 3 else league)
    lo, hi = ref.quantile(1 / 3), ref.quantile(2 / 3)

    score = _frontcourt_score(league)
    labels = pd.Series("Wing", index=league.index)
    labels[score <= lo] = "Guard"
    labels[score >= hi] = "Big"
    return labels


def positional_percentile_ranks(
    league: pd.DataFrame,
    player_name: str,
    stats: list[str] | None = None,
    min_games: int = 10,
    min_minutes: float = 15.0,
) -> tuple[pd.Series, str]:
    """Percentile ranks of a player against their *position group* only.

    Returns (ranks, group_label). Everything else mirrors
    :func:`percentile_ranks`, but the comparison pool is narrowed to the
    player's inferred Guard/Wing/Big group. Raises KeyError if the player
    isn't found.
    """
    if "PLAYER_NAME" not in league.columns:
        raise KeyError("league table has no PLAYER_NAME column")
    positions = infer_positions(league, min_minutes=min_minutes)
    match = league.index[league["PLAYER_NAME"] == player_name]
    if len(match) == 0:
        raise KeyError(f"player {player_name!r} not found")
    group = positions.loc[match[0]]
    peers = league[positions == group]
    return percentile_ranks(peers, player_name, stats=stats, min_games=min_games), group
