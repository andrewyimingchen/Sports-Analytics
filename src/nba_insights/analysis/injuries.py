"""Injury-report absences as expected minutes out (pure, no I/O).

The outcome model's availability input is each team's *expected minutes
out*: for every absent player, the minutes he was expected to play,
measured exactly as in training (:func:`nba_insights.ml.features.
availability_features`): current-season minutes per team game, blended
with last season's minutes per game counted as ``prior_weight``
pseudo-games. A player out for months therefore counts for little -- his
team's form already reflects playing without him -- while a regular who
just went down counts in full.

Report statuses become absence weights (:data:`STATUS_WEIGHTS`): Out and
Doubtful count fully, Questionable half, Probable/Available not at all.
That weighting is a heuristic; the market scorecard is where it gets
tested.
"""

from __future__ import annotations

import pandas as pd

from nba_insights.analysis.salaries import normalize_name
from nba_insights.ml.features import prior_minute_rates

STATUS_WEIGHTS = {"Out": 1.0, "Doubtful": 1.0, "Questionable": 0.5}
MAX_MISSING_MIN = 240.0  # the model input's valid range per team


def latest_report(log: pd.DataFrame) -> pd.DataFrame:
    """Rows of the most recent report in an injury log."""
    if log.empty:
        return log
    return log[log["REPORT_AT"] == log["REPORT_AT"].max()].reset_index(drop=True)


def injured_minutes(
    report: pd.DataFrame,
    player_games: pd.DataFrame,
    prior_player_games: pd.DataFrame,
    weights: dict[str, float] | None = None,
    prior_weight: float = 20.0,
) -> pd.DataFrame:
    """Per listed player: expected minutes and the minutes counted as missing.

    *player_games* is the current season's player game log, and
    *prior_player_games* last season's (name lookup and prior rates).
    Players are matched by folded name; unmatched players (two-way
    call-ups, rookies without minutes) get EXP_MIN 0 and PLAYER_ID NaN.
    """
    weights = STATUS_WEIGHTS if weights is None else weights
    listed = report[report["PLAYER"].astype(bool)].copy()
    columns = ["TEAM", "PLAYER_NAME", "STATUS", "REASON", "PLAYER_ID", "EXP_MIN", "WEIGHT"]
    if listed.empty:
        return pd.DataFrame(columns=[*columns, "MISSING_MIN"])

    current = player_games.copy()
    current["MIN"] = pd.to_numeric(current["MIN"], errors="coerce").fillna(0)
    names = pd.concat(
        [
            prior_player_games[["PLAYER_ID", "PLAYER_NAME"]],
            current[["PLAYER_ID", "PLAYER_NAME"]],
        ]
    ).drop_duplicates("PLAYER_ID", keep="last")
    by_name = dict(zip(names["PLAYER_NAME"].map(normalize_name), names["PLAYER_ID"], strict=True))

    team_games = current.groupby("TEAM_ABBREVIATION")["GAME_ID"].nunique()
    minutes = current.groupby(["TEAM_ABBREVIATION", "PLAYER_ID"])["MIN"].sum()
    prior = prior_minute_rates(prior_player_games)

    def expected(row: pd.Series) -> float:
        player_id = row["PLAYER_ID"]
        if pd.isna(player_id):
            return 0.0
        played = float(team_games.get(row["TEAM"], 0))
        season_min = float(minutes.get((row["TEAM"], player_id), 0.0))
        seed = float(prior.get(player_id, 0.0))
        return (season_min + seed * prior_weight) / (played + prior_weight)

    listed["PLAYER_ID"] = listed["PLAYER_NAME"].map(normalize_name).map(by_name)
    exp_min = listed.apply(expected, axis=1).astype(float)
    listed["WEIGHT"] = listed["STATUS"].map(weights).fillna(0.0)
    listed["MISSING_MIN"] = (exp_min * listed["WEIGHT"]).round(2)
    listed["EXP_MIN"] = exp_min.round(1)
    return listed[[*columns, "MISSING_MIN"]].reset_index(drop=True)


def team_missing_minutes(players: pd.DataFrame) -> pd.Series:
    """Expected minutes out per team tricode, capped at the model's range."""
    return players.groupby("TEAM")["MISSING_MIN"].sum().clip(upper=MAX_MISSING_MIN)
