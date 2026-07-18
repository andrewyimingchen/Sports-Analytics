"""Reshape the league schedule and a player's game log into tidy tables
for the Game center and the profile game log.

Pure: DataFrames in, DataFrames out. The raw inputs follow their endpoints'
column names (ScheduleLeagueV2's flattened camelCase; PlayerGameLogs' UPPER).
"""

from __future__ import annotations

import pandas as pd

_STATUS = {1: "Scheduled", 2: "Live", 3: "Final"}


def scoreboard(schedule: pd.DataFrame) -> pd.DataFrame:
    """One tidy row per game: date, status, teams, score, winner, top scorer.

    *schedule* is the flattened ScheduleLeagueV2 frame. Rows are sorted by
    date; WINNER is the tricode of the winning side (blank until Final);
    TOP_SCORER is "First Last · pts" for finished games when available.
    Raises KeyError when a required column is missing.
    """
    need = [
        "gameDate", "gameStatus", "homeTeam_teamTricode", "homeTeam_score",
        "awayTeam_teamTricode", "awayTeam_score",
    ]
    missing = [c for c in need if c not in schedule.columns]
    if missing:
        raise KeyError(f"schedule missing columns: {missing}")

    df = schedule.copy()
    dates = pd.to_datetime(df["gameDate"]).dt.date
    status_text = df.get("gameStatusText", pd.Series("", index=df.index))
    out = pd.DataFrame(
        {
            "GAME_DATE": dates,
            "STATUS": df["gameStatus"].map(_STATUS).fillna(status_text),
            "STATUS_TEXT": status_text,
            "AWAY": df["awayTeam_teamTricode"],
            "HOME": df["homeTeam_teamTricode"],
            "AWAY_PTS": pd.to_numeric(df["awayTeam_score"], errors="coerce"),
            "HOME_PTS": pd.to_numeric(df["homeTeam_score"], errors="coerce"),
        }
    )
    final = df["gameStatus"] == 3
    out["WINNER"] = ""
    out.loc[final & (out["HOME_PTS"] > out["AWAY_PTS"]), "WINNER"] = out["HOME"]
    out.loc[final & (out["AWAY_PTS"] > out["HOME_PTS"]), "WINNER"] = out["AWAY"]

    out["TOP_SCORER"] = ""
    if {"pointsLeaders_0_lastName", "pointsLeaders_0_points"} <= set(df.columns):
        first = df.get("pointsLeaders_0_firstName", pd.Series("", index=df.index)).fillna("")
        last = df["pointsLeaders_0_lastName"]
        pts = pd.to_numeric(df["pointsLeaders_0_points"], errors="coerce")
        top = [
            f"{f} {ln} · {int(p)}".strip()
            if isinstance(ln, str) and ln and pd.notna(p)
            else ""
            for f, ln, p in zip(first, last, pts, strict=True)
        ]
        out.loc[final, "TOP_SCORER"] = pd.Series(top, index=df.index)[final]

    return out.sort_values("GAME_DATE").reset_index(drop=True)


def game_log_table(game_log: pd.DataFrame) -> pd.DataFrame:
    """A player's game log as a compact display table, newest game first.

    Columns: DATE, MATCHUP, WL, MIN, PTS, REB, AST, FG ("7/14"), 3PM, +/-.
    Raises KeyError when a required column is missing.
    """
    need = ["GAME_DATE", "MATCHUP", "WL", "MIN", "PTS", "REB", "AST",
            "FGM", "FGA", "FG3M", "PLUS_MINUS"]
    missing = [c for c in need if c not in game_log.columns]
    if missing:
        raise KeyError(f"game log missing columns: {missing}")

    df = game_log.copy()
    df["_date"] = pd.to_datetime(df["GAME_DATE"]).dt.date
    df = df.sort_values("_date", ascending=False)
    fgm = df["FGM"].round().astype("Int64")
    fga = df["FGA"].round().astype("Int64")
    return pd.DataFrame(
        {
            "DATE": df["_date"],
            "MATCHUP": df["MATCHUP"],
            "WL": df["WL"],
            "MIN": df["MIN"].round().astype("Int64"),
            "PTS": df["PTS"].astype("Int64"),
            "REB": df["REB"].astype("Int64"),
            "AST": df["AST"].astype("Int64"),
            "FG": fgm.astype(str) + "/" + fga.astype(str),
            "3PM": df["FG3M"].astype("Int64"),
            "+/-": df["PLUS_MINUS"].round().astype("Int64"),
        }
    ).reset_index(drop=True)
