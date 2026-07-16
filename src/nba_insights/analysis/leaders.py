"""League leaderboards from the season-wide per-game stats table."""

from __future__ import annotations

import pandas as pd

LEADER_COLUMNS = ["PLAYER_ID", "PLAYER_NAME", "TEAM_ABBREVIATION", "GP"]


def league_leaders(
    league: pd.DataFrame, stat: str = "PTS", top: int = 5, min_gp: int = 20
) -> pd.DataFrame:
    """Top players by a per-game stat, filtered to a minimum games played.

    The GP floor keeps small-sample players (three big games in garbage
    time) off the board, mirroring the league's qualification idea without
    its exact 58-game rule.
    """
    if stat not in league.columns:
        raise KeyError(f"stat column not found: {stat}")
    eligible = league[league["GP"] >= min_gp]
    keep = [c for c in LEADER_COLUMNS if c in league.columns] + [stat]
    return eligible.nlargest(top, stat)[keep].reset_index(drop=True)
