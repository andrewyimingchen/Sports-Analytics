"""Structured query over the league table — the safe data-access layer the
AI Q&A page exposes to Claude as a tool.

Pure: DataFrame + structured args in, plain records out. The LLM chooses the
arguments; this executes them with pandas (no eval, no LLM-generated code),
so answers stay grounded in the cached table and nothing arbitrary runs.
"""

from __future__ import annotations

import pandas as pd

# columns the Q&A layer exposes, with plain-language meaning for the model
COLUMN_GLOSSARY: dict[str, str] = {
    "PLAYER_NAME": "player name",
    "TEAM_ABBREVIATION": "team tricode",
    "GP": "games played",
    "MIN": "minutes per game",
    "PTS": "points per game",
    "AST": "assists per game",
    "REB": "rebounds per game",
    "STL": "steals per game",
    "BLK": "blocks per game",
    "TOV": "turnovers per game",
    "FG_PCT": "field-goal % (fraction, e.g. 0.48)",
    "FG3_PCT": "three-point % (fraction)",
    "FT_PCT": "free-throw % (fraction)",
    "FG3M": "three-pointers made per game",
    "NET_RATING": "on-court net rating (points per 100 possessions)",
    "CLUTCH_NET_RATING": "net rating in the clutch (last 5 min, within 5 pts)",
    "DPM": "DARKO daily plus-minus (all-in-one impact estimate)",
    "PLUS_MINUS": "average plus-minus per game",
}
_DEFAULT_COLS = ["PLAYER_NAME", "TEAM_ABBREVIATION", "GP", "MIN", "PTS", "AST", "REB"]


def query_players(
    league: pd.DataFrame,
    *,
    filters: dict[str, float] | None = None,
    name_contains: str = "",
    teams: list[str] | None = None,
    sort_by: str | None = None,
    ascending: bool = False,
    top_n: int = 10,
    columns: list[str] | None = None,
) -> list[dict]:
    """Filter, sort, and slice the league table; return plain records.

    *filters* is a column → minimum-value map (e.g. {"MIN": 30, "AST": 5});
    only rows meeting every floor are kept. *name_contains* / *teams* narrow
    by player name substring / team tricodes. *sort_by* orders the result
    (descending unless *ascending*), *top_n* caps it, and *columns* selects
    the fields returned (the sort column is always included). Unknown columns
    are ignored, so a bad LLM argument degrades rather than raising.
    """
    df = league
    if name_contains and "PLAYER_NAME" in df.columns:
        df = df[df["PLAYER_NAME"].str.contains(name_contains.strip(), case=False, na=False)]
    if teams and "TEAM_ABBREVIATION" in df.columns:
        df = df[df["TEAM_ABBREVIATION"].isin(teams)]
    for col, floor in (filters or {}).items():
        if col in df.columns:
            df = df[df[col] >= floor]
    if sort_by and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=ascending)
    df = df.head(max(1, int(top_n)))

    keep = [c for c in (columns or _DEFAULT_COLS) if c in df.columns]
    if sort_by and sort_by in df.columns and sort_by not in keep:
        keep.append(sort_by)
    if not keep:
        keep = [c for c in _DEFAULT_COLS if c in df.columns]
    out = df[keep].copy()
    # round floats so the model gets clean numbers, not 20.68399...
    for col in out.select_dtypes("number").columns:
        out[col] = out[col].round(3)
    return out.to_dict("records")
