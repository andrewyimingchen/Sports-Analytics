"""Shot-zone efficiency: a player's FG% per zone against the league."""

from __future__ import annotations

import pandas as pd

ZONE_KEY = ["SHOT_ZONE_BASIC", "SHOT_ZONE_AREA", "SHOT_ZONE_RANGE"]

# eFG weight: a made three is worth 1.5 made twos
_THREE_WEIGHT = 1.5


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


def shot_quality(shots: pd.DataFrame, league_averages: pd.DataFrame) -> pd.Series:
    """Split a player's eFG% into shot selection and shot making.

    Each attempt's expected value is the league FG% for its zone, weighted
    :data:`_THREE_WEIGHT` for threes — so XEFG is the eFG% a league-average
    shooter would post on this player's shot diet (selection), and MAKING
    (= EFG − XEFG, in eFG points) is finishing above or below what the
    locations alone predict. Shots in zones the league table lacks (e.g.
    backcourt heaves) are dropped from both numbers so they stay
    comparable; FGA counts the shots actually scored. LEAGUE_EFG is the
    league-wide eFG% over the same zone table (NaN if it has no FGA/FGM).
    Raises KeyError on missing required columns.
    """
    for col in [*ZONE_KEY, "SHOT_MADE_FLAG", "SHOT_TYPE"]:
        if col not in shots.columns:
            raise KeyError(f"shots table missing column: {col}")
    league = league_averages[[*ZONE_KEY, "FG_PCT"]].rename(columns={"FG_PCT": "LEAGUE_PCT"})
    matched = shots.merge(league, on=ZONE_KEY, how="inner")

    if matched.empty:
        efg = xefg = float("nan")
    else:
        weight = matched["SHOT_TYPE"].str.contains("3PT").map({True: _THREE_WEIGHT, False: 1.0})
        xefg = float((matched["LEAGUE_PCT"] * weight).mean())
        efg = float((matched["SHOT_MADE_FLAG"] * weight).mean())

    league_efg = float("nan")
    if {"FGA", "FGM"} <= set(league_averages.columns):
        lg_weight = league_averages["SHOT_ZONE_BASIC"].str.contains("3").map(
            {True: _THREE_WEIGHT, False: 1.0}
        )
        lg_fga = league_averages["FGA"].sum()
        if lg_fga:
            league_efg = float((league_averages["FGM"] * lg_weight).sum() / lg_fga)

    return pd.Series(
        {
            "FGA": float(len(matched)),
            "EFG": efg,
            "XEFG": xefg,
            "MAKING": efg - xefg,
            "LEAGUE_EFG": league_efg,
        }
    )
