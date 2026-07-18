"""Extract a player's clutch shooting line from the league clutch (Base) table.

"Clutch" is the NBA's definition: the last five minutes with the score within
five points. The Base clutch table carries shooting, which the Advanced one
(clutch net rating) does not — so this is where clutch FG% / 3P% / FT% / eFG%
come from.

Pure: the league clutch-base DataFrame + a player id in, one record out.
"""

from __future__ import annotations

import pandas as pd


def clutch_shooting_line(clutch_base: pd.DataFrame, player_id: int) -> dict | None:
    """One player's clutch shooting, or None if they have no clutch attempts.

    Returns GP, MIN and PTS (clutch totals / per-game as the endpoint reports),
    plus FG_PCT, FG3_PCT, FT_PCT and EFG_PCT recomputed from makes/attempts so a
    zero-attempt bucket is None rather than a divide-by-zero. Percentages are
    fractions (0.5 = 50%), rounded to three places. Raises KeyError when the
    shooting columns are absent.
    """
    need = ["PLAYER_ID", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA"]
    missing = [c for c in need if c not in clutch_base.columns]
    if missing:
        raise KeyError(f"clutch table missing columns: {missing}")

    rows = clutch_base[clutch_base["PLAYER_ID"] == player_id]
    if rows.empty:
        return None
    r = rows.iloc[0]

    fga, fg3a, fta = float(r["FGA"]), float(r["FG3A"]), float(r["FTA"])
    if fga == 0 and fta == 0:
        return None  # took the floor in the clutch but never shot

    def _pct(makes: float, att: float) -> float | None:
        return round(makes / att, 3) if att else None

    line: dict[str, object] = {}
    for col in ("GP", "MIN", "PTS"):
        if col in rows.columns and pd.notna(r[col]):
            line[col] = round(float(r[col]), 1)
    line["FG_PCT"] = _pct(float(r["FGM"]), fga)
    line["FG3_PCT"] = _pct(float(r["FG3M"]), fg3a)
    line["FT_PCT"] = _pct(float(r["FTM"]), fta)
    line["EFG_PCT"] = _pct(float(r["FGM"]) + 0.5 * float(r["FG3M"]), fga)
    return line
