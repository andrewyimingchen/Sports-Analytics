"""Team on/off splits: how a team performs with each player on vs off court."""

from __future__ import annotations

import pandas as pd

REQUIRED = [
    "VS_PLAYER_ID",
    "VS_PLAYER_NAME",
    "COURT_STATUS",
    "MIN",
    "OFF_RATING",
    "DEF_RATING",
    "NET_RATING",
]

# source column -> short metric name in the pivoted output
_METRICS = {"MIN": "MIN", "OFF_RATING": "ORTG", "DEF_RATING": "DRTG", "NET_RATING": "NET"}


def team_on_off(onoff: pd.DataFrame) -> pd.DataFrame:
    """One row per player: team ratings with them on vs off the floor.

    *onoff* is the concatenated per-player on/off frames from the team
    on/off endpoint (COURT_STATUS "On"/"Off", MIN in total minutes; names
    arrive "Last, First"). Output columns are PLAYER_ID, PLAYER_NAME plus
    {MIN,ORTG,DRTG,NET}_{ON,OFF} and NET_DIFF (on-court net minus
    off-court net), sorted by NET_DIFF descending. A player missing one
    side (e.g. never off the floor) keeps NaN there. Raises KeyError on
    missing required columns.
    """
    for col in REQUIRED:
        if col not in onoff.columns:
            raise KeyError(f"on/off table missing column: {col}")
    df = onoff.assign(SIDE=onoff["COURT_STATUS"].str.strip().str.upper())
    wide = df.pivot_table(
        index=["VS_PLAYER_ID", "VS_PLAYER_NAME"],
        columns="SIDE",
        values=list(_METRICS),
    )
    wide.columns = [f"{_METRICS[metric]}_{side}" for metric, side in wide.columns]
    wide = wide.reset_index().rename(
        columns={"VS_PLAYER_ID": "PLAYER_ID", "VS_PLAYER_NAME": "PLAYER_NAME"}
    )
    for col in ("NET_ON", "NET_OFF"):
        if col not in wide.columns:  # a side can be absent early in a season
            wide[col] = float("nan")
    wide["NET_DIFF"] = wide["NET_ON"] - wide["NET_OFF"]
    return wide.sort_values("NET_DIFF", ascending=False, ignore_index=True)
