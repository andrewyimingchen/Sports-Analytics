"""Reshape the league schedule and a player's game log into tidy tables
for the Game center and the profile game log.

Pure: DataFrames in, DataFrames out. The raw inputs follow their endpoints'
column names (ScheduleLeagueV2's flattened camelCase; PlayerGameLogs' UPPER).
"""

from __future__ import annotations

import re

import pandas as pd

_STATUS = {1: "Scheduled", 2: "Live", 3: "Final"}


def scoreboard(schedule: pd.DataFrame) -> pd.DataFrame:
    """One tidy row per game: ID, date, status, teams, score, winner, top scorer.

    *schedule* is the flattened ScheduleLeagueV2 frame. Rows are sorted by
    date; WINNER is the tricode of the winning side (blank until Final);
    TOP_SCORER is "First Last · pts" for finished games when available.
    Raises KeyError when a required column is missing.
    """
    need = [
        "gameId", "gameDate", "gameStatus", "homeTeam_teamTricode", "homeTeam_score",
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
            "GAME_ID": df["gameId"].astype(str),
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


def _minutes(value: object) -> float | None:
    """NBA v3 duration (ISO or ``MM:SS``) to decimal minutes."""
    if not isinstance(value, str):
        return None
    clock = re.fullmatch(r"(\d+):(\d{2}(?:\.\d+)?)", value)
    if clock:
        minutes, seconds = clock.groups()
        return round(int(minutes) + float(seconds) / 60, 1)
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?([\d.]+)S", value)
    if not match:
        return None
    hours, minutes, seconds = match.groups(default="0")
    return round(int(hours) * 60 + int(minutes) + float(seconds) / 60, 1)


def box_score_table(players: pd.DataFrame) -> pd.DataFrame:
    """Tidy player rows from BoxScoreTraditionalV3, grouped by team in the UI.

    DNP rows are retained with their NBA comment and blank statistics. Shooting
    is rendered as makes/attempts so the compact table remains readable.
    """
    need = [
        "teamTricode", "firstName", "familyName", "minutes", "fieldGoalsMade",
        "fieldGoalsAttempted", "threePointersMade", "threePointersAttempted",
        "freeThrowsMade", "freeThrowsAttempted", "reboundsTotal", "assists",
        "steals", "blocks", "turnovers", "points", "plusMinusPoints",
    ]
    missing = [c for c in need if c not in players.columns]
    if missing:
        raise KeyError(f"box score missing columns: {missing}")

    df = players.copy()
    first = df["firstName"].fillna("").astype(str).str.strip()
    last = df["familyName"].fillna("").astype(str).str.strip()
    names = (first + " " + last).str.strip()
    minutes = df["minutes"].map(_minutes)
    comments = df.get("comment", pd.Series("", index=df.index)).fillna("").astype(str)
    played = minutes.notna() & comments.str.strip().eq("")

    def whole(column: str) -> pd.Series:
        return pd.to_numeric(df[column], errors="coerce").round().astype("Int64")

    def shooting(made: str, attempted: str) -> pd.Series:
        return whole(made).astype(str) + "/" + whole(attempted).astype(str)

    out = pd.DataFrame(
        {
            "TEAM": df["teamTricode"],
            "PLAYER": names,
            "MIN": minutes,
            "PTS": whole("points"),
            "REB": whole("reboundsTotal"),
            "AST": whole("assists"),
            "STL": whole("steals"),
            "BLK": whole("blocks"),
            "TO": whole("turnovers"),
            "FG": shooting("fieldGoalsMade", "fieldGoalsAttempted"),
            "3P": shooting("threePointersMade", "threePointersAttempted"),
            "FT": shooting("freeThrowsMade", "freeThrowsAttempted"),
            "+/-": whole("plusMinusPoints"),
            "STATUS": comments,
        }
    )
    stat_cols = ["PTS", "REB", "AST", "STL", "BLK", "TO", "+/-"]
    out.loc[~played, stat_cols] = pd.NA
    out.loc[~played, ["FG", "3P", "FT"]] = ""
    out.loc[played, "STATUS"] = ""

    # A traditional box score ends each team table with its totals. Summing
    # the player rows keeps this pure and avoids a second endpoint/cache key.
    blocks = []
    for team in df["teamTricode"].drop_duplicates():
        mask = df["teamTricode"] == team
        blocks.append(out[mask])
        total_cols = [
            "points", "reboundsTotal", "assists", "steals", "blocks", "turnovers",
            "fieldGoalsMade", "fieldGoalsAttempted", "threePointersMade",
            "threePointersAttempted", "freeThrowsMade", "freeThrowsAttempted",
        ]
        totals = {
            column: int(pd.to_numeric(df.loc[mask, column], errors="coerce").sum())
            for column in total_cols
        }

        blocks.append(
            pd.DataFrame(
                [
                    {
                        "TEAM": team,
                        "PLAYER": "TEAM TOTAL",
                        "MIN": round(float(minutes[mask].sum()), 1),
                        "PTS": totals["points"],
                        "REB": totals["reboundsTotal"],
                        "AST": totals["assists"],
                        "STL": totals["steals"],
                        "BLK": totals["blocks"],
                        "TO": totals["turnovers"],
                        "FG": f"{totals['fieldGoalsMade']}/{totals['fieldGoalsAttempted']}",
                        "3P": (
                            f"{totals['threePointersMade']}/{totals['threePointersAttempted']}"
                        ),
                        "FT": f"{totals['freeThrowsMade']}/{totals['freeThrowsAttempted']}",
                        "+/-": pd.NA,
                        "STATUS": "",
                    }
                ]
            )
        )
    return pd.concat(blocks, ignore_index=True)


def game_finder_box_score_table(players: pd.DataFrame) -> pd.DataFrame:
    """Tidy a completed game's cached LeagueGameFinder player rows.

    This is the reliable Game Center fallback when the dedicated traditional
    box-score endpoint is unavailable. It omits DNPs but retains every player
    who logged a statistic and produces the same compact columns as
    :func:`box_score_table`.
    """
    need = [
        "TEAM_ABBREVIATION", "PLAYER_NAME", "MIN", "PTS", "REB", "AST",
        "STL", "BLK", "TOV", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA",
        "PLUS_MINUS",
    ]
    missing = [column for column in need if column not in players.columns]
    if missing:
        raise KeyError(f"player game rows missing columns: {missing}")

    df = players.copy()

    def whole(column: str) -> pd.Series:
        return pd.to_numeric(df[column], errors="coerce").round().astype("Int64")

    def shooting(made: str, attempted: str) -> pd.Series:
        return whole(made).astype(str) + "/" + whole(attempted).astype(str)

    out = pd.DataFrame(
        {
            "TEAM": df["TEAM_ABBREVIATION"],
            "PLAYER": df["PLAYER_NAME"],
            "MIN": pd.to_numeric(df["MIN"], errors="coerce").round(1),
            "PTS": whole("PTS"),
            "REB": whole("REB"),
            "AST": whole("AST"),
            "STL": whole("STL"),
            "BLK": whole("BLK"),
            "TO": whole("TOV"),
            "FG": shooting("FGM", "FGA"),
            "3P": shooting("FG3M", "FG3A"),
            "FT": shooting("FTM", "FTA"),
            "+/-": whole("PLUS_MINUS"),
            "STATUS": "",
        }
    )
    blocks = []
    for team in df["TEAM_ABBREVIATION"].drop_duplicates():
        mask = df["TEAM_ABBREVIATION"] == team
        blocks.append(out[mask])
        team_rows = df.loc[mask]
        total_columns = [
            "PTS", "REB", "AST", "STL", "BLK", "TOV", "FGM", "FGA",
            "FG3M", "FG3A", "FTM", "FTA",
        ]
        totals = {
            column: int(pd.to_numeric(team_rows[column], errors="coerce").sum())
            for column in total_columns
        }

        blocks.append(
            pd.DataFrame(
                [
                    {
                        "TEAM": team,
                        "PLAYER": "TEAM TOTAL",
                        "MIN": round(float(pd.to_numeric(team_rows["MIN"]).sum()), 1),
                        "PTS": totals["PTS"],
                        "REB": totals["REB"],
                        "AST": totals["AST"],
                        "STL": totals["STL"],
                        "BLK": totals["BLK"],
                        "TO": totals["TOV"],
                        "FG": f'{totals["FGM"]}/{totals["FGA"]}',
                        "3P": f'{totals["FG3M"]}/{totals["FG3A"]}',
                        "FT": f'{totals["FTM"]}/{totals["FTA"]}',
                        "+/-": pd.NA,
                        "STATUS": "",
                    }
                ]
            )
        )
    return pd.concat(blocks, ignore_index=True)


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
