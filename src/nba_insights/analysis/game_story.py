"""Pure Game Center timeline, shot, lineup, and advanced-game analysis."""

from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from nba_insights.pbp.stints import lineup_ratings, stint_table


def _records(frame: pd.DataFrame) -> list[dict]:
    """Return JSON-native records with missing values encoded as null."""
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient="records"))


def _remaining_seconds(clock: object) -> float:
    if not isinstance(clock, str):
        return 0.0
    iso = re.fullmatch(r"PT(?:(\d+)M)?([\d.]+)S", clock)
    if iso:
        minutes, seconds = iso.groups(default="0")
        return int(minutes) * 60 + float(seconds)
    plain = re.fullmatch(r"(\d+):(\d+(?:\.\d+)?)", clock)
    if plain:
        minutes, seconds = plain.groups()
        return int(minutes) * 60 + float(seconds)
    return 0.0


def _elapsed(period: int, clock: object) -> float:
    duration = 720 if period <= 4 else 300
    before = min(period - 1, 4) * 720 + max(period - 5, 0) * 300
    return before + duration - _remaining_seconds(clock)


def game_timeline(pbp: pd.DataFrame) -> pd.DataFrame:
    """Score changes with a score/time-only, forward-looking home win estimate."""
    required = {"period", "clock", "scoreHome", "scoreAway"}
    missing = required - set(pbp.columns)
    if missing:
        raise KeyError(f"play-by-play missing columns: {sorted(missing)}")
    frame = pbp.copy()
    frame["HOME_SCORE"] = pd.to_numeric(frame["scoreHome"], errors="coerce")
    frame["AWAY_SCORE"] = pd.to_numeric(frame["scoreAway"], errors="coerce")
    frame = frame.dropna(subset=["HOME_SCORE", "AWAY_SCORE"])
    changed = frame[["HOME_SCORE", "AWAY_SCORE"]].ne(
        frame[["HOME_SCORE", "AWAY_SCORE"]].shift()
    ).any(axis=1)
    frame = frame[changed].copy()
    frame["PERIOD"] = pd.to_numeric(frame["period"], errors="coerce").astype(int)
    frame["ELAPSED"] = [
        _elapsed(period, clock)
        for period, clock in zip(frame["PERIOD"], frame["clock"], strict=True)
    ]
    max_period = max(4, int(frame["PERIOD"].max())) if not frame.empty else 4
    total_seconds = 2880 + max(0, max_period - 4) * 300
    remaining = (total_seconds - frame["ELAPSED"]).clip(lower=0)
    margin = frame["HOME_SCORE"] - frame["AWAY_SCORE"]
    scale = np.maximum(2.2, np.sqrt(remaining / 60 + 1) * 1.8)
    logit = margin / scale + 0.12 * (remaining / total_seconds)
    frame["HOME_WIN_PROB"] = 1 / (1 + np.exp(-logit))
    if not frame.empty:
        final_margin = margin.iloc[-1]
        frame.loc[frame.index[-1], "HOME_WIN_PROB"] = 1.0 if final_margin > 0 else 0.0
    frame["MARGIN"] = margin
    frame["CLOCK"] = frame["clock"]
    columns = [
        "ELAPSED", "PERIOD", "CLOCK", "HOME_SCORE", "AWAY_SCORE", "MARGIN",
        "HOME_WIN_PROB",
    ]
    return frame[columns].reset_index(drop=True)


def _team_advanced(player_rows: pd.DataFrame) -> list[dict]:
    rows = []
    for team, frame in player_rows.groupby("TEAM_ABBREVIATION", sort=False):
        totals = {
            column: float(pd.to_numeric(frame.get(column), errors="coerce").sum())
            for column in (
                "PTS", "FGM", "FGA", "FG3M", "FTA", "OREB", "DREB", "REB",
                "AST", "TOV", "STL", "BLK",
            )
        }
        fga = totals["FGA"]
        denominator = 2 * (fga + 0.44 * totals["FTA"])
        rows.append(
            {
                "TEAM": str(team),
                **{key: round(value) for key, value in totals.items()},
                "EFG_PCT": (totals["FGM"] + 0.5 * totals["FG3M"]) / fga if fga else None,
                "TS_PCT": totals["PTS"] / denominator if denominator else None,
                "TOV_RATE": totals["TOV"] / (
                    fga + 0.44 * totals["FTA"] + totals["TOV"]
                ) if fga else None,
                "FT_RATE": totals["FTA"] / fga if fga else None,
                "AST_TOV": totals["AST"] / totals["TOV"] if totals["TOV"] else None,
            }
        )
    return rows


def _lineup_summary(
    rotation: pd.DataFrame | None,
    pbp: pd.DataFrame,
    player_rows: pd.DataFrame,
) -> list[dict]:
    if rotation is None or rotation.empty:
        return []
    stints = stint_table(rotation, pbp)
    if stints.empty:
        return []
    ratings = lineup_ratings(stints).head(10)
    names = player_rows.drop_duplicates("PLAYER_ID").set_index("PLAYER_ID")["PLAYER_NAME"]
    teams = player_rows.drop_duplicates("PLAYER_ID").set_index("PLAYER_ID")[
        "TEAM_ABBREVIATION"
    ]
    result = []
    for row in ratings.itertuples():
        ids = list(row.LINEUP)
        labels = [str(names.get(player_id, player_id)) for player_id in ids]
        team_labels = [teams.get(player_id) for player_id in ids if player_id in teams.index]
        result.append(
            {
                "TEAM": str(pd.Series(team_labels).mode().iloc[0]) if team_labels else "",
                "PLAYERS": labels,
                "MIN": round(float(row.MIN), 1),
                "PLUS_MINUS": round(float(row.PLUS_MINUS), 1),
                "NET_RATING": round(float(row.NET_RATING), 1),
                "STINTS": int(row.STINTS),
            }
        )
    return result


def game_story(
    pbp: pd.DataFrame,
    player_rows: pd.DataFrame,
    *,
    home: str,
    away: str,
    rotation: pd.DataFrame | None = None,
) -> dict:
    """Complete cached game story for the PWA."""
    timeline = game_timeline(pbp)
    team_map = (
        player_rows.dropna(subset=["TEAM_ID", "TEAM_ABBREVIATION"])
        .drop_duplicates("TEAM_ID")
        .set_index("TEAM_ID")["TEAM_ABBREVIATION"]
        .to_dict()
    )
    player_map = (
        player_rows.dropna(subset=["PLAYER_ID", "PLAYER_NAME"])
        .drop_duplicates("PLAYER_ID")
        .set_index("PLAYER_ID")["PLAYER_NAME"]
        .to_dict()
    )
    events = pbp.copy()
    events["TEAM"] = events.get("teamId", pd.Series(index=events.index)).map(team_map)
    events["PLAYER"] = events.get("personId", pd.Series(index=events.index)).map(player_map)
    events["MADE"] = events.get("actionType", "").eq("Made Shot")
    shot_mask = pd.to_numeric(events.get("isFieldGoal"), errors="coerce").eq(1)
    shot_columns = [
        column
        for column in (
            "period", "clock", "TEAM", "PLAYER", "actionType", "subType",
            "MADE", "xLegacy", "yLegacy", "shotDistance",
        )
        if column in events
    ]
    shots = events.loc[shot_mask, shot_columns].copy()
    shots.columns = [column.upper() for column in shots.columns]
    if not shots.empty:
        shots = shots.astype(object).where(shots.notna(), None)
    shot_summary = (
        events.loc[shot_mask]
        .groupby(["TEAM", "subType"], dropna=False)
        .agg(FGA=("MADE", "size"), FGM=("MADE", "sum"))
        .reset_index()
        .rename(columns={"subType": "SHOT_TYPE"})
    )
    if not shot_summary.empty:
        shot_summary["FG_PCT"] = shot_summary["FGM"] / shot_summary["FGA"]

    changes = timeline["HOME_WIN_PROB"].diff().abs()
    turning = timeline.loc[changes.nlargest(min(5, len(changes))).index].copy()
    turning["SWING"] = changes.reindex(turning.index)
    turning_points = _records(turning.sort_values("ELAPSED"))

    home_run = away_run = best_home = best_away = 0
    previous_home = previous_away = 0
    for row in timeline.itertuples():
        home_points = int(row.HOME_SCORE - previous_home)
        away_points = int(row.AWAY_SCORE - previous_away)
        if home_points:
            home_run += home_points
            away_run = 0
        if away_points:
            away_run += away_points
            home_run = 0
        best_home, best_away = max(best_home, home_run), max(best_away, away_run)
        previous_home, previous_away = row.HOME_SCORE, row.AWAY_SCORE

    clutch_home = clutch_away = 0
    previous_home = previous_away = previous_margin = 0
    for row in timeline.itertuples():
        late_game = row.PERIOD > 4 or (
            row.PERIOD == 4 and _remaining_seconds(row.CLOCK) <= 300
        )
        in_clutch = late_game and abs(previous_margin) <= 5
        if in_clutch:
            clutch_home += int(row.HOME_SCORE - previous_home)
            clutch_away += int(row.AWAY_SCORE - previous_away)
        previous_home, previous_away = row.HOME_SCORE, row.AWAY_SCORE
        previous_margin = row.MARGIN

    feed_mask = events.get("actionType", "").isin(
        ["Made Shot", "Free Throw", "Turnover", "Foul", "Timeout"]
    )
    feed = []
    for row in events.loc[feed_mask].tail(30).itertuples():
        feed.append(
            {
                "PERIOD": int(row.period),
                "CLOCK": row.clock,
                "TEAM": getattr(row, "TEAM", None),
                "PLAYER": getattr(row, "PLAYER", None),
                "EVENT": " ".join(
                    part for part in (str(row.actionType), str(row.subType or "")) if part
                ),
                "SCORE": (
                    f"{row.scoreAway}-{row.scoreHome}"
                    if str(row.scoreHome) and str(row.scoreAway)
                    else ""
                ),
            }
        )
    return {
        "home": home,
        "away": away,
        "timeline": _records(timeline),
        "turning_points": turning_points,
        "biggest_runs": {home: best_home, away: best_away},
        "lead_changes": int(
            ((timeline["MARGIN"] * timeline["MARGIN"].shift(1)) < 0).sum()
        ),
        "clutch_points": {home: clutch_home, away: clutch_away},
        "shots": _records(shots),
        "shot_summary": _records(shot_summary),
        "shot_locations_available": {"XLEGACY", "YLEGACY"} <= set(shots.columns),
        "advanced": _team_advanced(player_rows),
        "lineups": _lineup_summary(rotation, pbp, player_rows),
        "feed": feed,
        "win_probability_method": (
            "Score-and-time-only heuristic; each point uses only the score and clock "
            "known at that event. It is leakage-safe but not a trained/calibrated model."
        ),
    }
