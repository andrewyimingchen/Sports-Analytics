"""Game, season, roster-scenario, player, and lineup predictions."""

from __future__ import annotations

import json
import logging
import zlib
from functools import lru_cache
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from nba_insights.analysis import (
    CUP_2026_GROUPS,
    CUP_2026_RULES_URL,
    CUP_2026_SCHEDULE_COMPLETE,
    CUP_2026_SOURCE_DATE,
    CUP_2026_SOURCE_URL,
    PLAYER_FORECAST_VERSION,
    SCENARIO_VERSION,
    RosterForecastInputs,
    apply_roster_scenario,
    build_roster_forecast_inputs,
    project_player_seasons,
    season_forecast,
)
from nba_insights.api import schemas
from nba_insights.api.deps import (
    Client,
    LineupCurve,
    OutcomeModel,
    PointsModel,
    get_player_season_metrics,
)
from nba_insights.api.schemas import errors
from nba_insights.api.security import protect_simulation, require_simulation_access
from nba_insights.api.shared import (
    find_player,
    finite_records,
    prediction_context,
    snapshot_for_day,
    today,
    validate_matchup,
)
from nba_insights.config import prediction_seasons
from nba_insights.ingest import NBAClient
from nba_insights.ml import blended_lineup_estimate, sim_summary, simulate_matchup
from nba_insights.ml.features import (
    STAT_LINE,
    matchup_features,
    player_next_game_features,
    stat_baseline_col,
)
from nba_insights.serve import league_with_ratings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["predictions"])


@router.get("/predict/game", response_model=schemas.GamePrediction, responses=errors(404, 422, 503))
def predict_game(
    home: str,
    away: str,
    client: Client,
    model: OutcomeModel,
    season: str | None = None,
    home_missing_min: Annotated[float, Query(ge=0, le=240)] = 0,
    away_missing_min: Annotated[float, Query(ge=0, le=240)] = 0,
) -> dict:
    """Home-team win probability for a matchup, both sides at full strength."""
    selected, basis, mode = prediction_context(season)
    day = today()
    snapshot = snapshot_for_day(day, client)
    validate_matchup(snapshot, home, away)
    features = matchup_features(
        snapshot, home, away, home_missing_min=home_missing_min, away_missing_min=away_missing_min
    )
    prob = float(model.predict_proba(features).iloc[0])
    return {
        "home": home,
        "away": away,
        "season": selected,
        "basis_season": basis,
        "projection_mode": mode,
        "home_win_prob": round(prob, 3),
    }


@router.get(
    "/predict/simulate",
    dependencies=[Depends(require_simulation_access)],
    response_model=schemas.Simulation,
    responses=errors(401, 403, 404, 422, 429, 503),
)
def predict_simulation(
    home: str,
    away: str,
    request: Request,
    client: Client,
    model: OutcomeModel,
    season: str | None = None,
    home_missing_min: Annotated[float, Query(ge=0, le=240)] = 0,
    away_missing_min: Annotated[float, Query(ge=0, le=240)] = 0,
    n_sims: Annotated[int, Query(ge=1000, le=20_000)] = 10_000,
) -> dict:
    """Monte Carlo margin/total distribution plus calibrated model comparison."""
    protect_simulation(request, cost=n_sims)
    selected, basis, mode = prediction_context(season)
    day = today()
    snapshot = snapshot_for_day(day, client)
    validate_matchup(snapshot, home, away)
    seed = zlib.crc32(
        f"{selected}|{home}|{away}|{home_missing_min}|{away_missing_min}|{n_sims}".encode()
    )
    sims = simulate_matchup(
        snapshot,
        home,
        away,
        home_missing_min=home_missing_min,
        away_missing_min=away_missing_min,
        n_sims=n_sims,
        seed=seed,
    )
    margin = sims["home_pts"] - sims["away_pts"]
    total = sims["home_pts"] + sims["away_pts"]
    model_features = matchup_features(
        snapshot, home, away, home_missing_min=home_missing_min, away_missing_min=away_missing_min
    )
    model_prob = float(model.predict_proba(model_features).iloc[0])
    return {
        "home": home,
        "away": away,
        "season": selected,
        "basis_season": basis,
        "projection_mode": mode,
        "n_sims": n_sims,
        "median_score": {
            "home": int(sims["home_pts"].median()),
            "away": int(sims["away_pts"].median()),
        },
        "summary": sim_summary(sims),
        "outcome_model_home_win_prob": model_prob,
        "margin_histogram": _histogram(margin, bins=24),
        "total_histogram": _histogram(total, bins=24),
    }


@lru_cache(maxsize=4)
def _season_forecast_table(
    selected: str, basis: str, n_sims: int, day: str, client: NBAClient
) -> pd.DataFrame:
    snapshot = snapshot_for_day(day, client)

    conferences = _forecast_conferences(client, basis)
    roster_inputs = None
    if selected != basis:
        roster_inputs = _roster_forecast_inputs(selected, basis, day, client)
    try:
        table = season_forecast(
            snapshot,
            conferences,
            n_sims=n_sims,
            seed=zlib.crc32(f"{selected}|{basis}|{n_sims}".encode()),
            cup_groups=CUP_2026_GROUPS if selected == "2026-27" else None,
            roster_adjustments=(roster_inputs.teams if roster_inputs else None),
        )
        if roster_inputs:
            table = table.merge(roster_inputs.teams.reset_index(), on="TEAM", how="left")
            table.attrs["roster_metadata"] = roster_inputs.metadata
        return table
    except (KeyError, ValueError) as error:
        raise HTTPException(503, str(error)) from error


def _forecast_conferences(client: NBAClient, basis: str) -> dict[str, str]:
    """Map team tricodes to conferences from the same forecast basis season."""
    standings = client.standings(basis)
    games = client.team_games(basis)
    required_standings = {"TeamID", "Conference"}
    required_games = {"TEAM_ID", "TEAM_ABBREVIATION"}
    if not required_standings <= set(standings) or not required_games <= set(games):
        raise HTTPException(503, "conference mapping is unavailable for the forecast")
    team_ids = (
        games[["TEAM_ID", "TEAM_ABBREVIATION"]]
        .dropna()
        .drop_duplicates("TEAM_ID", keep="last")
        .set_index("TEAM_ID")["TEAM_ABBREVIATION"]
        .to_dict()
    )
    return {
        str(team_ids.get(row.TeamID)): str(row.Conference)
        for row in standings[["TeamID", "Conference"]].itertuples(index=False)
        if row.TeamID in team_ids
    }


@lru_cache(maxsize=4)
def _roster_forecast_inputs(
    selected: str, basis: str, day: str, client: NBAClient
) -> RosterForecastInputs:
    """Versioned target roster/minutes inputs shared by forecast and audit API."""
    try:
        return build_roster_forecast_inputs(
            league_with_ratings(client, basis),
            client.player_contracts(),
            target_season=selected,
            generated_on=day,
        )
    except (KeyError, ValueError) as error:
        raise HTTPException(503, f"roster forecast inputs unavailable: {error}") from error


@router.get(
    "/predict/season/roster-inputs",
    response_model=schemas.RosterInputs,
    responses=errors(404, 422, 503),
)
def predict_season_roster_inputs(
    client: Client, season: str | None = None, team: str | None = None
) -> dict:
    """Audit the versioned player-minutes inputs and explainable team adjustments."""
    selected, basis, _ = prediction_context(season or prediction_seasons()[1])
    if selected == basis:
        raise HTTPException(422, "roster inputs are available for the next-season forecast")
    day = today()
    inputs = _roster_forecast_inputs(selected, basis, day, client)
    teams = inputs.teams.reset_index()
    players = inputs.players
    if team:
        team = team.upper()
        teams = teams[teams["TEAM"] == team]
        players = players[players["TEAM"] == team]
        if teams.empty:
            raise HTTPException(404, f"no roster forecast input for {team}")
    return {
        "metadata": inputs.metadata,
        "teams": finite_records(teams),
        "players": finite_records(players),
    }


class RosterScenarioChange(BaseModel):
    player: str = Field(min_length=1)
    new_team: str | None = None
    remove: bool = False
    projected_minutes: float | None = Field(default=None, ge=0, le=48)
    games_missed: int | None = Field(default=None, ge=0, le=82)


class RosterScenarioBody(BaseModel):
    season: str | None = None
    n_sims: int = Field(default=2_000, ge=1_000, le=10_000)
    changes: list[RosterScenarioChange] = Field(min_length=1, max_length=30)


@router.post(
    "/predict/season/scenario",
    dependencies=[Depends(require_simulation_access)],
    response_model=schemas.RosterScenario,
    responses=errors(401, 403, 422, 429, 503),
)
def predict_roster_scenario(body: RosterScenarioBody, request: Request, client: Client) -> dict:
    """Run an ephemeral roster/minutes/availability scenario against baseline."""
    # A scenario computes both a baseline and a changed forecast.
    protect_simulation(request, cost=body.n_sims * 2)
    selected, basis, _ = prediction_context(body.season or prediction_seasons()[1])
    if selected == basis:
        raise HTTPException(422, "roster scenarios are available for the next season")
    day = today()
    baseline_inputs = _roster_forecast_inputs(selected, basis, day, client)
    requested = [change.model_dump() for change in body.changes]
    if any(change["remove"] and change["new_team"] for change in requested):
        raise HTTPException(422, "a player cannot be removed and assigned a new team")
    try:
        scenario = apply_roster_scenario(baseline_inputs, requested)
    except (KeyError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc

    snapshot = snapshot_for_day(day, client)
    conferences = _forecast_conferences(client, basis)
    baseline_table = _season_forecast_table(selected, basis, body.n_sims, day, client)
    seed = zlib.crc32(f"{selected}|{basis}|{body.n_sims}".encode())
    try:
        scenario_table = season_forecast(
            snapshot,
            conferences,
            n_sims=body.n_sims,
            seed=seed,
            cup_groups=CUP_2026_GROUPS if selected == "2026-27" else None,
            roster_adjustments=scenario.teams,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc

    affected = sorted(
        {
            team
            for change in scenario.changes
            for team in (change["from_team"], change["to_team"])
            if team is not None
        }
    )
    outcome_columns = {
        "projected_wins": "PROJECTED_WINS",
        "projected_seed": "PROJECTED_SEED",
        "playoff_probability": "PLAYOFF_PROB",
        "championship_probability": "CHAMP_PROB",
        "cup_probability": "CUP_PROB",
    }
    outcomes = []
    for team in affected:
        before_rows = baseline_table[baseline_table["TEAM"] == team]
        after_rows = scenario_table[scenario_table["TEAM"] == team]
        if before_rows.empty or after_rows.empty:
            continue
        before_row, after_row = before_rows.iloc[0], after_rows.iloc[0]
        before = {label: float(before_row[column]) for label, column in outcome_columns.items()}
        after = {label: float(after_row[column]) for label, column in outcome_columns.items()}
        outcomes.append(
            {
                "team": team,
                "before": before,
                "after": after,
                "change": {label: after[label] - before[label] for label in before},
                "strength": {
                    "before_net_adjustment": float(
                        baseline_inputs.teams.at[team, "NET_ADJUSTMENT"]
                    ),
                    "after_net_adjustment": float(scenario.teams.at[team, "NET_ADJUSTMENT"]),
                    "causal_players": [
                        change["player"]
                        for change in scenario.changes
                        if team in {change["from_team"], change["to_team"]}
                    ],
                },
            }
        )

    roster_columns = [
        column
        for column in (
            "TEAM",
            "PLAYER_NAME",
            "PROJECTED_MIN",
            "GAMES_MISSED",
            "PROJECTED_IMPACT",
            "SALARY",
        )
        if column in scenario.players
    ]
    scenario_key = json.dumps(requested, sort_keys=True, separators=(",", ":"))
    return {
        "scenario_id": f"scenario-{zlib.crc32(scenario_key.encode()):08x}",
        "version": SCENARIO_VERSION,
        "season": selected,
        "basis_season": basis,
        "n_sims": body.n_sims,
        "baseline_immutable": True,
        "paired_simulation_seed": seed,
        "changes": scenario.changes,
        "salary_validation": scenario.salary_validation,
        "outcomes": outcomes,
        "rosters": finite_records(
            scenario.players[scenario.players["TEAM"].isin(affected)][roster_columns]
        ),
        "methodology": (
            "Before and after use the same simulation seed. Explicit player minutes are "
            "locked, remaining rotation minutes are redistributed to 240, and games "
            "missed become replacement-level minutes. Results are scenario deltas, not "
            "causal estimates from historical transactions."
        ),
        "salary_method": (
            "Salary validation is an advisory 125% plus $7.5M incoming screen using "
            "cached contract salaries; it does not model apron, aggregation, timing, "
            "trade-kicker, or exception rules."
        ),
    }


@lru_cache(maxsize=4)
def _player_season_table(selected: str, basis: str, day: str, client: NBAClient) -> pd.DataFrame:
    roster = _roster_forecast_inputs(selected, basis, day, client)
    try:
        team_forecast = _season_forecast_table(selected, basis, 1_000, day, client)
    except HTTPException:
        logger.warning("team forecast unavailable for player awards; using neutral wins")
        team_forecast = None
    return project_player_seasons(
        league_with_ratings(client, basis), roster.players, team_forecast=team_forecast
    )


@router.get(
    "/predict/players", response_model=schemas.PlayerSeasonProjections, responses=errors(422, 503)
)
def predict_player_seasons(
    client: Client,
    season: str | None = None,
    team: str | None = None,
    trajectory: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """Next-season player roles, box-stat ranges, comparables, and award outlook."""
    selected, basis, _ = prediction_context(season or prediction_seasons()[1])
    if selected == basis:
        raise HTTPException(422, "player season projections are available for next season")
    day = today()
    full = _player_season_table(selected, basis, day, client)
    award_totals = {
        "mvp": float(full["MVP_PROB"].sum()),
        "dpoy": float(full["DPOY_PROB"].sum()),
        "all_star": float(full["ALL_STAR_PROB"].sum()),
    }
    filtered = full
    if team:
        filtered = filtered[filtered["TEAM"] == team.upper()]
    if trajectory:
        filtered = filtered[filtered["TRAJECTORY"] == trajectory.lower()]
    return {
        "season": selected,
        "basis_season": basis,
        "version": PLAYER_FORECAST_VERSION,
        "assumptions": (
            "Roles come from roster-minutes-v1. Per-minute production is carried forward "
            "with a one-year age curve; shooting is regressed toward league average. "
            "The population is the target contract roster: inactive/retired players are "
            "omitted, while contracted players without history are labeled new entrants."
        ),
        "intervals": (
            "PTS and MIN ranges are model-risk bands (±4.8 points, ±5 minutes), not "
            "player-specific injury forecasts."
        ),
        "awards_method": (
            "MVP and DPOY fields are field-calibrated to one winner; All-Star probabilities "
            "are capped and normalized to 24 selections. They are comparative model "
            "scores, not historically calibrated betting probabilities."
        ),
        "holdout": get_player_season_metrics(),
        "award_probability_totals": award_totals,
        "count": int(len(filtered)),
        "players": finite_records(filtered.head(limit)),
    }


@router.get(
    "/predict/season",
    dependencies=[Depends(require_simulation_access)],
    response_model=schemas.SeasonForecast,
    responses=errors(401, 403, 422, 429, 503),
)
def predict_season(
    client: Client,
    request: Request,
    season: str | None = None,
    n_sims: Annotated[int, Query(ge=1_000, le=20_000)] = 5_000,
) -> dict:
    """Conference tables and playoff, title, and NBA Cup forecast odds."""
    protect_simulation(request, cost=n_sims)
    selected = season or prediction_seasons()[1]
    selected, basis, mode = prediction_context(selected)
    day = today()
    table = _season_forecast_table(selected, basis, n_sims, day, client)
    roster_metadata = table.attrs.get("roster_metadata")
    conferences = {
        conference: finite_records(
            table[table["CONFERENCE"] == conference].sort_values("PROJECTED_SEED")
        )
        for conference in ("East", "West")
    }
    title_favorite = table.sort_values("CHAMP_PROB", ascending=False).iloc[0]
    cup_favorite = table.sort_values("CUP_PROB", ascending=False).iloc[0]
    cup_groups = {
        group: finite_records(
            table[table["CUP_GROUP"] == group].sort_values("CUP_PROJECTED_GROUP_RANK")
        )
        for group in CUP_2026_GROUPS
    }
    return {
        "season": selected,
        "basis_season": basis,
        "projection_mode": mode,
        "roster_inputs": roster_metadata,
        "n_sims": n_sims,
        "conferences": conferences,
        "favorites": {
            "championship": {
                "team": str(title_favorite["TEAM"]),
                "probability": float(title_favorite["CHAMP_PROB"]),
            },
            "nba_cup": {
                "team": str(cup_favorite["TEAM"]),
                "probability": float(cup_favorite["CUP_PROB"]),
            },
        },
        "nba_cup": {
            "source_url": CUP_2026_SOURCE_URL,
            "rules_url": CUP_2026_RULES_URL,
            "source_date": CUP_2026_SOURCE_DATE,
            "schedule_complete": CUP_2026_SCHEDULE_COMPLETE,
            "groups": cup_groups,
            "assumption": (
                "Official groups and tiebreaks; neutral group-game sites until "
                "the NBA publishes the August schedule. Knockout higher seeds host."
            ),
        },
        "methodology": (
            "Latest team win rate, net rating, and Elo are regressed toward average, "
            + (
                "then versioned target rosters, projected minutes, availability, and "
                "one-year age adjustments are applied. "
                if roster_metadata
                else "then current-season uncertainty is applied. "
            )
            + "An 82-game season, play-in, playoff series, Finals, and a higher-variance "
            "NBA Cup are simulated. Odds are model estimates, not betting-market forecasts."
        ),
    }


def _histogram(values: pd.Series, bins: int) -> list[dict]:
    """Small JSON histogram without adding a charting dependency to the PWA."""
    cuts = pd.cut(values, bins=bins)
    counts = cuts.value_counts(sort=False)
    return [
        {"mid": float(interval.mid), "count": int(count)}
        for interval, count in counts.items()
        if count
    ]


@router.get(
    "/predict/player/{player_id}",
    response_model=schemas.PlayerPointsProjection,
    responses=errors(404, 503),
)
def predict_player_points(
    player_id: int,
    opponent: str,
    client: Client,
    model: PointsModel,
    home: bool = True,
    own_missing_min: Annotated[float | None, Query(ge=0, le=240)] = None,
) -> dict:
    """Next-game player points projection with empirical 80% interval."""
    player = find_player(client, player_id)
    day = today()
    snapshot = snapshot_for_day(day, client)
    if opponent not in snapshot.index:
        raise HTTPException(404, f"unknown team {opponent!r}")
    season_games = client.player_games()
    rows = season_games[season_games["PLAYER_ID"] == player_id]
    if rows.empty:
        raise HTTPException(404, "no current-season games for this player")
    kwargs = {} if own_missing_min is None else {"own_missing_min": own_missing_min}
    features = player_next_game_features(
        rows,
        home=home,
        opp_form_net=float(snapshot.loc[opponent, "form_net"]),
        opp_form_drtg=float(snapshot.loc[opponent, "form_drtg"]),
        opp_form_pace=float(snapshot.loc[opponent, "form_pace"]),
        **kwargs,
    )
    line = model.predict_line(features).iloc[0]
    prediction = float(line["PTS"])
    interval = model.interval(prediction)
    # 10-game averages: the baseline each stat's model must beat, and the
    # only figure shown for blocks (no block model beat it on the holdout).
    recent = {
        stat: float(features[stat_baseline_col(stat)].iloc[0])
        for stat in [*STAT_LINE, "BLK"]
        if stat_baseline_col(stat) in features
        and pd.notna(features[stat_baseline_col(stat)].iloc[0])
    }
    return {
        "player": player["full_name"],
        "opponent": opponent,
        "home": home,
        "projected_points": prediction,
        "interval_80": list(interval) if interval else None,
        "projected_line": {stat: float(value) for stat, value in line.items()},
        "recent_averages": recent,
        "last_5": float(features["pts_r5"].iloc[0]),
        "last_10": float(features["pts_r10"].iloc[0]),
        "games_in_sample": len(rows),
    }


@router.get(
    "/predict/lineup", response_model=schemas.LineupPrediction, responses=errors(404, 422, 503)
)
def predict_lineup(
    team: str,
    player_ids: Annotated[list[int], Query(min_length=5, max_length=5)],
    client: Client,
    curve: LineupCurve,
) -> dict:
    """Observed/proxy blend for a selected five and win chance vs average."""
    if len(set(player_ids)) != 5:
        raise HTTPException(422, "select five different players")
    league = league_with_ratings(client)
    roster = league[(league["TEAM_ABBREVIATION"] == team) & league["PLAYER_ID"].isin(player_ids)]
    if len(roster) != 5:
        raise HTTPException(404, "all five players must be on the selected team")
    names = roster.set_index("PLAYER_ID").loc[player_ids, "PLAYER_NAME"].tolist()
    net, minutes = blended_lineup_estimate(client.lineups(), league, names, player_ids)
    return {
        "team": team,
        "players": names,
        "estimated_net_rating": net,
        "minutes_together": minutes,
        "win_probability_vs_average": curve.win_probability(net),
        "source": "observed_blend" if minutes > 0 else "per_36_proxy",
    }
