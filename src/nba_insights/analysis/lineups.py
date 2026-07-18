"""Browse a team's five-man lineups from the league lineup dashboard.

Pure: the raw ``LeagueDashLineups`` frame in, a display-ready board out.
(The stint-level table in ``pbp.lineups`` is the exact-minutes source when
it has been built; this works off the always-available dashboard endpoint.)
"""

from __future__ import annotations

import pandas as pd

# dashboard columns shown, in order; the rest (ranks, redundant E_ variants)
# are dropped
_DISPLAY = [
    "GROUP_NAME", "GP", "MIN", "NET_RATING", "OFF_RATING", "DEF_RATING",
    "EFG_PCT", "POSS",
]


def most_used_lineups(
    lineups: pd.DataFrame,
    team: str,
    must_include_ids: list[int] | None = None,
    min_minutes: float = 0.0,
) -> pd.DataFrame:
    """A team's five-man units, most minutes first.

    *must_include_ids* keeps only lineups containing every listed player
    (matched against GROUP_ID, so it is name-spelling independent);
    *min_minutes* floors total minutes together. Raises KeyError on missing
    required columns.
    """
    need = ["TEAM_ABBREVIATION", "GROUP_ID", "GROUP_NAME", "MIN"]
    missing = [c for c in need if c not in lineups.columns]
    if missing:
        raise KeyError(f"lineups table missing columns: {missing}")

    df = lineups[lineups["TEAM_ABBREVIATION"] == team]
    for pid in must_include_ids or []:
        df = df[df["GROUP_ID"].str.contains(f"-{int(pid)}-", regex=False)]
    df = df[df["MIN"] >= min_minutes]
    cols = [c for c in _DISPLAY if c in df.columns]
    return df[cols].sort_values("MIN", ascending=False).reset_index(drop=True)
