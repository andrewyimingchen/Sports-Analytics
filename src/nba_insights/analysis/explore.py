"""Filtering for the Explore page's master league table.

Pure: DataFrame in, filtered DataFrame out. Column selection and display
formatting stay in the app layer; this is just the row filter so it can be
unit-tested offline.
"""

from __future__ import annotations

import pandas as pd

# box-score counting columns that scale with minutes; rates (percentages,
# ratings, plus/minus per-game context) are left untouched
_COUNTING = [
    "PTS", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA",
    "OREB", "DREB", "REB", "AST", "TOV", "STL", "BLK", "BLKA", "PF", "PFD",
]


def per_minutes_table(league: pd.DataFrame, minutes: int = 36) -> pd.DataFrame:
    """Rescale per-game counting stats to a per-*minutes* basis.

    Each counting column is multiplied by ``minutes / MIN`` (MIN being
    per-game minutes), so a 24-min/game player's per-36 line extrapolates
    their production. Percentages, ratings, and MIN/GP are kept as-is;
    players with 0 minutes get 0. Requires a MIN column (raises KeyError).
    """
    if "MIN" not in league.columns:
        raise KeyError("league table missing MIN column")
    out = league.copy()
    factor = (minutes / out["MIN"]).where(out["MIN"] > 0, 0.0)
    for col in _COUNTING:
        if col in out.columns:
            out[col] = (out[col] * factor).round(1)
    return out


def filter_players(
    league: pd.DataFrame,
    *,
    min_gp: int = 0,
    min_min: float = 0.0,
    teams: list[str] | None = None,
    name_query: str = "",
) -> pd.DataFrame:
    """Rows of *league* passing every active filter, order preserved.

    *min_gp* / *min_min* are floors on GP / MIN (skipped when the column is
    absent). *teams* keeps only those TEAM_ABBREVIATIONs (empty/None = all).
    *name_query* is a case-insensitive substring match on PLAYER_NAME.
    """
    mask = pd.Series(True, index=league.index)
    if min_gp and "GP" in league.columns:
        mask &= league["GP"] >= min_gp
    if min_min and "MIN" in league.columns:
        mask &= league["MIN"] >= min_min
    if teams and "TEAM_ABBREVIATION" in league.columns:
        mask &= league["TEAM_ABBREVIATION"].isin(teams)
    if name_query and "PLAYER_NAME" in league.columns:
        mask &= league["PLAYER_NAME"].str.contains(name_query.strip(), case=False, na=False)
    return league[mask]
