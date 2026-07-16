"""Draft classes: pick history joined with combine measurements."""

from __future__ import annotations

import pandas as pd

_HISTORY_COLS = ["PERSON_ID", "PLAYER_NAME", "SEASON", "ROUND_NUMBER", "OVERALL_PICK"]

# measurement columns kept from the combine table (inches / pounds / seconds)
_COMBINE_COLS = [
    "POSITION",
    "HEIGHT_WO_SHOES",
    "WEIGHT",
    "WINGSPAN",
    "STANDING_REACH",
    "MAX_VERTICAL_LEAP",
    "THREE_QUARTER_SPRINT",
]


def draft_class(
    history: pd.DataFrame, combine: pd.DataFrame | None, year: str | int
) -> pd.DataFrame:
    """One row per pick of a draft year, with combine measurements joined.

    *history* is the all-time draft table (one row per pick), *combine*
    the measurements table for the same year (or None when unavailable —
    the class renders without measurement columns). Players who skipped
    the combine keep NaN measurements. WINGSPAN_DIFF is wingspan minus
    barefoot height, the classic "plays bigger than he measures" number.
    Raises KeyError on missing history columns.
    """
    for col in _HISTORY_COLS:
        if col not in history.columns:
            raise KeyError(f"draft history missing column: {col}")
    picks = history[history["SEASON"].astype(str) == str(year)].copy()
    keep = _HISTORY_COLS + [
        c for c in ("TEAM_ABBREVIATION", "ORGANIZATION") if c in picks.columns
    ]
    picks = picks[keep].sort_values("OVERALL_PICK")

    if combine is not None and "PLAYER_ID" in combine.columns:
        cols = ["PLAYER_ID"] + [c for c in _COMBINE_COLS if c in combine.columns]
        picks = picks.merge(
            combine[cols].rename(columns={"PLAYER_ID": "PERSON_ID"}),
            on="PERSON_ID",
            how="left",
        )
        if {"WINGSPAN", "HEIGHT_WO_SHOES"} <= set(picks.columns):
            picks["WINGSPAN_DIFF"] = picks["WINGSPAN"] - picks["HEIGHT_WO_SHOES"]
    return picks.reset_index(drop=True)


def player_draft_line(history: pd.DataFrame, person_id: int) -> str | None:
    """One-line draft pedigree ("#41 overall, 2014 (DEN)"), None if undrafted."""
    for col in _HISTORY_COLS:
        if col not in history.columns:
            raise KeyError(f"draft history missing column: {col}")
    rows = history[history["PERSON_ID"] == person_id]
    if rows.empty:
        return None
    row = rows.iloc[0]
    team = row.get("TEAM_ABBREVIATION", "")
    suffix = f" ({team})" if team else ""
    return f"#{int(row['OVERALL_PICK'])} overall, {row['SEASON']}{suffix}"
