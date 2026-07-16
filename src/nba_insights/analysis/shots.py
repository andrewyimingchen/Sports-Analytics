"""Shot-zone efficiency: a player's FG% per zone against the league."""

from __future__ import annotations

import pandas as pd

ZONE_KEY = ["SHOT_ZONE_BASIC", "SHOT_ZONE_AREA", "SHOT_ZONE_RANGE"]


def zone_efficiency(shots: pd.DataFrame, league_averages: pd.DataFrame) -> pd.DataFrame:
    """One row per zone the player shot from: volume, FG%, and league diff.

    *shots* is raw shot-chart rows (one per attempt, SHOT_MADE_FLAG 0/1);
    *league_averages* is the LeagueAverages frame from the same endpoint.
    DIFF is player FG% minus league FG% for that zone (NaN when the league
    table lacks the zone). Raises KeyError on missing required columns.
    """
    for col in [*ZONE_KEY, "SHOT_MADE_FLAG"]:
        if col not in shots.columns:
            raise KeyError(f"shots table missing column: {col}")
    zones = shots.groupby(ZONE_KEY, as_index=False).agg(
        FGA=("SHOT_MADE_FLAG", "size"), FGM=("SHOT_MADE_FLAG", "sum")
    )
    zones["PLAYER_PCT"] = zones["FGM"] / zones["FGA"]
    league = league_averages[[*ZONE_KEY, "FG_PCT"]].rename(columns={"FG_PCT": "LEAGUE_PCT"})
    zones = zones.merge(league, on=ZONE_KEY, how="left")
    zones["DIFF"] = zones["PLAYER_PCT"] - zones["LEAGUE_PCT"]
    return zones
