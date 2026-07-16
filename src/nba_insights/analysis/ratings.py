"""Attach advanced and clutch ratings to the per-game league table."""

from __future__ import annotations

import pandas as pd


def attach_ratings(
    league: pd.DataFrame,
    advanced: pd.DataFrame | None = None,
    clutch: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """League per-game table plus NET_RATING and CLUTCH_NET_RATING columns.

    Joins on PLAYER_ID. Clutch GP is kept as CLUTCH_GP so callers can floor
    out small samples (clutch minutes are scarce — a few per game at most).
    Players missing from either table get NaN, never dropped.
    """
    if "PLAYER_ID" not in league.columns:
        raise KeyError("league table has no PLAYER_ID column")
    out = league
    if advanced is not None and {"PLAYER_ID", "NET_RATING"} <= set(advanced.columns):
        out = out.merge(advanced[["PLAYER_ID", "NET_RATING"]], on="PLAYER_ID", how="left")
    if clutch is not None and {"PLAYER_ID", "NET_RATING"} <= set(clutch.columns):
        cl = clutch[["PLAYER_ID", "GP", "NET_RATING"]].rename(
            columns={"GP": "CLUTCH_GP", "NET_RATING": "CLUTCH_NET_RATING"}
        )
        out = out.merge(cl, on="PLAYER_ID", how="left")
    return out
