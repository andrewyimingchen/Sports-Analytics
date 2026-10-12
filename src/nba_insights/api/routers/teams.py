"""Team list, Team Room profiles, and head-to-head team comparison."""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlencode

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request

from nba_insights.analysis import (
    FACTOR_LABELS,
    attach_salary,
    compare_teams,
    four_factors_table,
    most_used_lineups,
    salary_seasons,
    team_contracts,
    team_on_off,
    team_payroll,
    team_scouting_take,
)
from nba_insights.api import schemas
from nba_insights.api.deps import Client, OutcomeModel
from nba_insights.api.schemas import errors
from nba_insights.api.security import can_access_private_data, is_local_request
from nba_insights.api.shared import (
    Degradations,
    finite_records,
    prediction_context,
    snapshot_for_day,
    today,
    validate_matchup,
)
from nba_insights.config import current_season
from nba_insights.errors import DATA_ERRORS, DataUnavailableError
from nba_insights.ml.features import matchup_features
from nba_insights.serve import league_with_ratings

router = APIRouter(tags=["teams"])


@router.get("/teams")
def teams(client: Client) -> list[str]:
    """Tricodes of all teams with games this season."""
    day = today()
    return sorted(snapshot_for_day(day, client).index)


@router.get("/teams/{team}/profile", response_model=schemas.TeamProfile, responses=errors(404, 503))
def team_profile(team: str, request: Request, client: Client) -> dict:
    """Full Team Room: identity, factors, roster, lineups, impact, and money."""
    team = team.upper()
    day = today()
    snapshot = snapshot_for_day(day, client)
    if team not in snapshot.index:
        raise HTTPException(404, f"unknown team {team!r}")

    league = league_with_ratings(client)
    if "TEAM_ABBREVIATION" not in league:
        raise HTTPException(503, "team roster data unavailable")
    roster = league[league["TEAM_ABBREVIATION"] == team].sort_values(
        "MIN" if "MIN" in league else "GP", ascending=False
    )
    degraded = Degradations("team_profile", team=team)
    contracts = None
    if can_access_private_data(request):
        with degraded.section("salaries"):
            contracts = client.player_contracts()
            roster = attach_salary(roster, contracts)
    roster_columns = [
        column
        for column in (
            "PLAYER_ID",
            "PLAYER_NAME",
            "GP",
            "MIN",
            "PTS",
            "REB",
            "AST",
            "NET_RATING",
            "DPM",
            "SALARY",
            "GUARANTEED",
        )
        if column in roster
    ]
    form = snapshot.loc[team].to_dict()
    form = {
        key: (value.isoformat() if isinstance(value, pd.Timestamp) else value)
        for key, value in form.items()
        if pd.notna(value)
    }
    games = client.team_games()
    log = games[games["TEAM_ABBREVIATION"] == team].sort_values("GAME_DATE")
    wins = int((log["WL"] == "W").sum()) if "WL" in log else 0
    losses = int((log["WL"] == "L").sum()) if "WL" in log else 0
    recent = log.tail(10)
    take = ""
    with degraded.section("scouting_take"):
        take = team_scouting_take(
            snapshot.loc[team],
            wins,
            losses,
            snapshot,
            recent=(int((recent["WL"] == "W").sum()), int((recent["WL"] == "L").sum())),
        )

    factors: dict = {}
    with degraded.section("four_factors"):
        factor_table = four_factors_table(games)
        if team in factor_table.index:
            factor_frame = factor_table.loc[[team]].reset_index()
            factors = finite_records(factor_frame)[0]

    lineups: list[dict] = []
    with degraded.section("lineups"):
        lineups = finite_records(most_used_lineups(client.lineups(), team).head(20))

    on_off: list[dict] = []
    if not log.empty and "TEAM_ID" in log:
        with degraded.section("on_off"):
            impact = team_on_off(client.team_player_on_off(int(log["TEAM_ID"].iloc[0])))
            on_off = finite_records(impact[impact["MIN_ON"] >= 100].head(20))

    standings: list[dict] = []
    with degraded.section("standings"):
        raw_standings = client.standings()
        standing_columns = [
            column
            for column in (
                "Conference",
                "PlayoffRank",
                "TeamCity",
                "TeamName",
                "TeamID",
                "WINS",
                "LOSSES",
                "WinPCT",
                "L10",
                "strCurrentStreak",
            )
            if column in raw_standings
        ]
        standings = finite_records(raw_standings[standing_columns])

    finances = None
    if contracts is not None:
        with degraded.section("finances"):
            book = team_contracts(contracts, team)
            payroll = team_payroll(contracts)
            finances = {
                "local_only": is_local_request(request),
                "access": "local" if is_local_request(request) else "api_key",
                "seasons": salary_seasons(contracts),
                "payroll": float(payroll.get(team, 0)),
                "contracts": finite_records(book),
            }

    recent_columns = [
        column for column in ("GAME_DATE", "MATCHUP", "WL", "PTS", "PLUS_MINUS") if column in recent
    ]
    # League-wide efficiency lets the Team Room place this team on the
    # offense/defense quadrant without a second request.
    league_form_columns = [
        column for column in ("form_ortg", "form_drtg", "form_net") if column in snapshot
    ]
    league_form = (
        finite_records(snapshot[league_form_columns].rename_axis("team").reset_index())
        if {"form_ortg", "form_drtg"} <= set(league_form_columns)
        else []
    )
    return {
        "team": team,
        "season": current_season(),
        "record": {"wins": wins, "losses": losses},
        "scouting_take": take,
        "form": form,
        "roster": finite_records(roster[roster_columns].head(18)),
        "four_factors": factors,
        "factor_labels": FACTOR_LABELS,
        "league_form": league_form,
        "recent_games": finite_records(recent[recent_columns].iloc[::-1]),
        "standings": standings,
        "lineups": lineups,
        "on_off": on_off,
        "finances": finances,
        "degraded": degraded.items,
    }


_DRIVER_LABELS = {
    "form_win_pct_diff": "Season win rate",
    "form_pts_diff": "Scoring",
    "form_net_diff": "Point differential",
    "form_efg_diff": "Shooting efficiency",
    "form_tov_pct_diff": "Turnover rate",
    "form_oreb_pct_diff": "Offensive rebounding",
    "form_ft_rate_diff": "Free-throw pressure",
    "form_pace_diff": "Pace",
    "form_ortg_diff": "Offensive rating",
    "form_drtg_diff": "Defensive rating",
    "rest_diff": "Rest advantage",
    "b2b_diff": "Back-to-back difference",
    "three_in_four_diff": "Schedule density",
    "missing_min_diff": "Expected minutes missing",
    "elo_diff": "Elo strength",
    "model_intercept": "Model baseline / home court",
}


@router.get(
    "/teams/compare", response_model=schemas.TeamComparison, responses=errors(404, 422, 503)
)
def team_comparison(
    home: str,
    away: str,
    client: Client,
    model: OutcomeModel,
    season: str | None = None,
    home_missing_min: Annotated[float, Query(ge=0, le=240)] = 0,
    away_missing_min: Annotated[float, Query(ge=0, le=240)] = 0,
) -> dict:
    """Shared-sample team profile plus a ranked local matchup explanation."""
    home, away = home.upper(), away.upper()
    selected, basis, mode = prediction_context(season)
    day = today()
    prediction_snapshot = snapshot_for_day(day, client)
    validate_matchup(prediction_snapshot, home, away)

    games = client.team_games(basis)
    league = league_with_ratings(client, basis)
    degraded = Degradations("team_comparison", home=home, away=away, season=basis)
    lineups = clutch = pd.DataFrame()
    with degraded.section("lineups"):
        lineups = client.lineups(basis)
    with degraded.section("clutch"):
        clutch = client.league_player_clutch(basis)

    try:
        comparison = compare_teams(
            games, league, lineups, clutch, away, home, elo=prediction_snapshot.get("elo")
        )
    except DATA_ERRORS as exc:
        raise DataUnavailableError("team comparison inputs are incomplete") from exc

    features = matchup_features(
        prediction_snapshot,
        home,
        away,
        home_missing_min=home_missing_min,
        away_missing_min=away_missing_min,
    )
    probability = float(model.predict_proba(features).iloc[0])
    drivers = []
    for row in model.explain(features):
        contribution = row["log_odds_contribution"]
        drivers.append(
            {
                **row,
                "label": _DRIVER_LABELS.get(row["feature"], row["feature"]),
                "favors": home if contribution > 0 else away if contribution < 0 else "neutral",
            }
        )

    query = urlencode({"home": home, "away": away, "season": selected})
    return {
        "home": home,
        "away": away,
        "season": selected,
        "basis_season": basis,
        "projection_mode": mode,
        "home_win_prob": round(probability, 4),
        **comparison,
        "drivers": drivers,
        "limitations": [
            (
                "The matchup assumes neutral rest; expected minutes out comes from the "
                "availability controls and does not identify specific players."
            ),
            (
                "Feature contributions explain the fitted logistic model; correlated "
                "inputs are not independent or causal effects."
            ),
            (
                "Clutch, lineup, and bench summaries are descriptive and may be absent "
                "when their upstream samples are unavailable."
            ),
            f"{selected} uses {basis} team form as a {mode.replace('_', ' ')} basis.",
        ],
        "share_url": f"/app/?{query}#matchup",
        "export_filename": f"{away}-at-{home}-{selected}-comparison.json",
        "degraded": degraded.items,
    }
