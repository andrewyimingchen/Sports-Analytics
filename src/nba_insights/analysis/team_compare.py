"""Pure two-team comparison summaries on a shared season-to-date sample."""

from __future__ import annotations

from typing import Any

import pandas as pd

from nba_insights.analysis.four_factors import FACTOR_LABELS, four_factors_table
from nba_insights.analysis.lineups import most_used_lineups
from nba_insights.ml.features import team_form_snapshot


def _number(value: Any) -> float | int | None:
    if pd.isna(value):
        return None
    if isinstance(value, int):
        return int(value)
    return float(value)


def _shared_sample(
    team_games: pd.DataFrame, first: str, second: str
) -> tuple[pd.DataFrame, str]:
    required = {"TEAM_ABBREVIATION", "GAME_DATE", "WL", "PLUS_MINUS"}
    missing = required - set(team_games.columns)
    if missing:
        raise KeyError(f"team_games missing columns: {sorted(missing)}")
    games = team_games.copy()
    games["GAME_DATE"] = pd.to_datetime(games["GAME_DATE"])
    latest = games[games["TEAM_ABBREVIATION"].isin([first, second])].groupby(
        "TEAM_ABBREVIATION"
    )["GAME_DATE"].max()
    absent = [team for team in (first, second) if team not in latest.index]
    if absent:
        raise ValueError(f"unknown team(s): {', '.join(absent)}")
    cutoff = latest.min()
    return games[games["GAME_DATE"] <= cutoff].copy(), cutoff.date().isoformat()


def _rotation_summary(
    league: pd.DataFrame, lineups: pd.DataFrame, team: str
) -> dict[str, Any]:
    roster = league[league.get("TEAM_ABBREVIATION", pd.Series(dtype=str)) == team].copy()
    if not roster.empty:
        roster = roster.sort_values("MIN", ascending=False) if "MIN" in roster else roster
    rotation = []
    for row in roster.head(8).to_dict(orient="records"):
        rotation.append(
            {
                key: _number(row.get(key)) if key != "PLAYER_NAME" else row.get(key)
                for key in ("PLAYER_NAME", "MIN", "PTS", "NET_RATING", "DPM")
                if key in row
            }
        )
    bench = roster.iloc[5:]
    bench_points = None
    if "PTS" in bench and not bench.empty:
        bench_points = float(pd.to_numeric(bench["PTS"], errors="coerce").sum())

    top_lineup = None
    if not lineups.empty:
        try:
            board = most_used_lineups(lineups, team)
            if not board.empty:
                top_lineup = {
                    key: _number(value) if key != "GROUP_NAME" else value
                    for key, value in board.iloc[0].to_dict().items()
                }
        except KeyError:
            pass
    return {
        "rotation": rotation,
        "bench_points_per_game": bench_points,
        "top_lineup": top_lineup,
    }


def _clutch_summary(clutch: pd.DataFrame, team: str) -> dict[str, Any] | None:
    required = {"TEAM_ABBREVIATION", "MIN", "NET_RATING"}
    if clutch.empty or not required <= set(clutch.columns):
        return None
    rows = clutch[clutch["TEAM_ABBREVIATION"] == team].copy()
    rows["MIN"] = pd.to_numeric(rows["MIN"], errors="coerce").fillna(0)
    rows["NET_RATING"] = pd.to_numeric(rows["NET_RATING"], errors="coerce")
    rows = rows[rows["MIN"] > 0].dropna(subset=["NET_RATING"])
    if rows.empty:
        return None
    total_minutes = float(rows["MIN"].sum())
    return {
        "net_rating": float((rows["NET_RATING"] * rows["MIN"]).sum() / total_minutes),
        "player_minutes": total_minutes,
        "players": int(len(rows)),
    }


def _head_to_head(games: pd.DataFrame, first: str, second: str) -> dict[str, Any]:
    first_rows = games[games["TEAM_ABBREVIATION"] == first].copy()
    opponent = first_rows["MATCHUP"].astype(str).str.rsplit(n=1).str[-1]
    rows = first_rows[opponent == second].sort_values("GAME_DATE")
    wins = int((rows["WL"] == "W").sum())
    losses = int((rows["WL"] == "L").sum())
    return {
        "games": int(len(rows)),
        "first_wins": wins,
        "second_wins": losses,
        "first_average_margin": (
            float(pd.to_numeric(rows["PLUS_MINUS"], errors="coerce").mean())
            if not rows.empty
            else None
        ),
        "meetings": [
            {
                "date": row.GAME_DATE.date().isoformat(),
                "matchup": row.MATCHUP,
                "result": row.WL,
                "margin": _number(row.PLUS_MINUS),
            }
            for row in rows.tail(5).itertuples()
        ][::-1],
    }


def _metric(
    category: str,
    key: str,
    label: str,
    first_value: Any,
    second_value: Any,
    higher_is_better: bool | None = True,
    first_rank: Any = None,
    second_rank: Any = None,
) -> dict[str, Any]:
    a, b = _number(first_value), _number(second_value)
    leader = None
    if higher_is_better is not None and a is not None and b is not None and a != b:
        first_leads = a > b if higher_is_better else a < b
        leader = "first" if first_leads else "second"
    return {
        "category": category,
        "key": key,
        "label": label,
        "first": a,
        "second": b,
        "leader": leader,
        "first_rank": _number(first_rank),
        "second_rank": _number(second_rank),
    }


def compare_teams(
    team_games: pd.DataFrame,
    league: pd.DataFrame,
    lineups: pd.DataFrame,
    clutch: pd.DataFrame,
    first: str,
    second: str,
    elo: pd.Series | None = None,
) -> dict[str, Any]:
    """Compare two teams using one season and a shared chronological cutoff."""
    if first == second:
        raise ValueError("teams must differ")
    games, cutoff = _shared_sample(team_games, first, second)
    snapshot = team_form_snapshot(games)
    factors = four_factors_table(games)
    if elo is not None:
        snapshot["elo"] = elo.reindex(snapshot.index)

    for team in (first, second):
        if team not in snapshot.index or team not in factors.index:
            raise ValueError(f"team {team} has no complete comparison sample")

    a, b = snapshot.loc[first], snapshot.loc[second]
    fa, fb = factors.loc[first], factors.loc[second]
    metrics = [
        _metric("Results", "win_pct", "Win percentage", a.form_win_pct, b.form_win_pct),
        _metric("Efficiency", "off_rating", "Offensive rating", a.form_ortg, b.form_ortg),
        _metric("Efficiency", "def_rating", "Defensive rating", a.form_drtg, b.form_drtg, False),
        _metric("Efficiency", "net_rating", "Net rating", a.form_net, b.form_net),
        _metric("Style", "pace", "Pace", a.form_pace, b.form_pace, None),
    ]
    if "elo" in snapshot:
        metrics.append(_metric("Strength", "elo", "Elo rating", a.elo, b.elo))

    factor_directions = {
        "off_efg": True,
        "off_tov_pct": False,
        "off_oreb_pct": True,
        "off_ft_rate": True,
        "def_efg": False,
        "def_tov_pct": True,
        "def_dreb_pct": True,
        "def_ft_rate": False,
    }
    for key, higher in factor_directions.items():
        metrics.append(
            _metric(
                "Four factors",
                key,
                FACTOR_LABELS[key],
                fa[key],
                fb[key],
                higher,
                fa[f"{key}_rank"],
                fb[f"{key}_rank"],
            )
        )

    if "FG3A" in games:
        totals = games.groupby("TEAM_ABBREVIATION")[["FG3A", "FGA"]].sum()
        rates = totals["FG3A"] / totals["FGA"]
        metrics.append(
            _metric(
                "Shooting",
                "three_rate",
                "Three-point attempt rate",
                rates[first],
                rates[second],
                None,
            )
        )

    records = {}
    for team in (first, second):
        rows = games[games["TEAM_ABBREVIATION"] == team]
        records[team] = {
            "wins": int((rows["WL"] == "W").sum()),
            "losses": int((rows["WL"] == "L").sum()),
            **_rotation_summary(league, lineups, team),
            "clutch": _clutch_summary(clutch, team),
        }

    return {
        "sample": {
            "as_of": cutoff,
            "definition": "Same season through the earlier of the teams' latest game dates",
            "games": {
                team: int((games["TEAM_ABBREVIATION"] == team).sum())
                for team in (first, second)
            },
        },
        "metrics": metrics,
        "teams": records,
        "head_to_head": _head_to_head(games, first, second),
    }
