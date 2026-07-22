"""JSON API over the same ingest/analysis layers the Streamlit app uses.

Run with: uv run uvicorn nba_insights.api:app --reload

The NBAClient is provided by a FastAPI dependency so tests can substitute a
fake; all endpoints read through the shared cache, so the API and the app
warm each other.
"""

from __future__ import annotations

import json
import logging
import os
import zlib
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from nba_insights.analysis import (
    COLUMN_GLOSSARY,
    CUP_2026_GROUPS,
    CUP_2026_RULES_URL,
    CUP_2026_SCHEDULE_COMPLETE,
    CUP_2026_SOURCE_DATE,
    CUP_2026_SOURCE_URL,
    DIMENSIONS,
    FACTOR_LABELS,
    PLAYER_FORECAST_VERSION,
    ROSTER_INPUT_VERSION,
    RosterForecastInputs,
    attach_salary,
    box_score_table,
    build_roster_forecast_inputs,
    career_averages,
    career_per_game,
    comparison_table,
    filter_players,
    four_factors_table,
    game_finder_box_score_table,
    game_log_table,
    game_story,
    hex_bins,
    league_leaders,
    most_used_lineups,
    per_minutes_table,
    percentile_ranks,
    player_contract,
    player_draft_line,
    player_scouting_take,
    player_splits,
    positional_percentile_ranks,
    project_player_seasons,
    query_players,
    salary_seasons,
    scoreboard,
    season_forecast,
    shot_breakdown,
    shot_quality,
    similar_players,
    team_contracts,
    team_on_off,
    team_payroll,
    team_scouting_take,
    zone_efficiency,
)
from nba_insights.api.cards import render_player_card
from nba_insights.config import (
    current_season,
    past_seasons,
    prediction_seasons,
    seasons_since,
)
from nba_insights.ingest import NBAClient
from nba_insights.ml import (
    GameOutcomeModel,
    PlayerPointsModel,
    WinCurve,
    blended_lineup_estimate,
    sim_summary,
    simulate_matchup,
)
from nba_insights.ml.backtest import SEASON_FORECAST_METRICS_PATH
from nba_insights.ml.elo import current_elo
from nba_insights.ml.features import (
    matchup_features,
    player_next_game_features,
    prior_team_form,
    team_form_snapshot,
    team_rest_features,
    upcoming_games,
)
from nba_insights.ml.player_backtest import PLAYER_SEASON_METRICS_PATH
from nba_insights.ml.train import METRICS_PATH, OUTCOME_PATH, POINTS_PATH, WIN_CURVE_PATH
from nba_insights.posters import (
    compare_poster_html,
    compare_poster_png,
    prediction_poster_html,
    prediction_poster_png,
)
from nba_insights.serve import fetch_headshot, league_with_ratings

logger = logging.getLogger(__name__)

app = FastAPI(title="NBA Insights API", version="0.1.0")

_STATIC = Path(__file__).parent / "static"
app.mount("/app", StaticFiles(directory=_STATIC, html=True), name="mobile")


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/app/")


@lru_cache(maxsize=1)
def get_client() -> NBAClient:
    return NBAClient()


Client = Annotated[NBAClient, Depends(get_client)]


@lru_cache(maxsize=1)
def get_outcome_model() -> GameOutcomeModel:
    if not OUTCOME_PATH.exists():
        raise HTTPException(
            503, "models not trained: run `uv run python -m nba_insights.ml.train`"
        )
    return GameOutcomeModel.load(OUTCOME_PATH)


OutcomeModel = Annotated[GameOutcomeModel, Depends(get_outcome_model)]


@lru_cache(maxsize=1)
def get_points_model() -> PlayerPointsModel:
    if not POINTS_PATH.exists():
        raise HTTPException(
            503, "models not trained: run `uv run python -m nba_insights.ml.train`"
        )
    return PlayerPointsModel.load(POINTS_PATH)


@lru_cache(maxsize=1)
def get_win_curve() -> WinCurve:
    if not WIN_CURVE_PATH.exists():
        raise HTTPException(
            503, "models not trained: run `uv run python -m nba_insights.ml.train`"
        )
    return WinCurve.load(WIN_CURVE_PATH)


PointsModel = Annotated[PlayerPointsModel, Depends(get_points_model)]
LineupCurve = Annotated[WinCurve, Depends(get_win_curve)]


@lru_cache(maxsize=1)
def get_model_metrics() -> dict:
    try:
        return json.loads(METRICS_PATH.read_text())
    except Exception:
        return {}


@lru_cache(maxsize=1)
def get_season_forecast_metrics() -> dict:
    try:
        return json.loads(SEASON_FORECAST_METRICS_PATH.read_text())
    except Exception:
        return {}


@lru_cache(maxsize=1)
def get_player_season_metrics() -> dict:
    try:
        return json.loads(PLAYER_SEASON_METRICS_PATH.read_text())
    except Exception:
        return {}


def get_model_registry() -> dict:
    trained = get_model_metrics()
    forecast = get_season_forecast_metrics()
    forecast_metrics = forecast.get("metrics", {})
    record = forecast_metrics.get("record", {})
    return {
        "outcome": {
            "kind": "trained supervised model",
            "status": (
                "temporal holdout evaluated"
                if trained.get("outcome")
                else "artifact missing"
            ),
            "version": "logistic-outcome-v1",
            "data_cutoff": trained.get("holdout_season"),
            "metrics": trained.get("outcome", {}),
        },
        "player_points": {
            "kind": "trained supervised model",
            "status": "temporal holdout evaluated" if trained.get("points") else "artifact missing",
            "version": "player-points-v1",
            "data_cutoff": trained.get("holdout_season"),
            "metrics": trained.get("points", {}),
        },
        "player_season": {
            "kind": "age/role carry-forward projection",
            "status": (
                "stable-returner historical holdout evaluated"
                if get_player_season_metrics().get("metrics")
                else "holdout artifact missing"
            ),
            "version": PLAYER_FORECAST_VERSION,
            "data_cutoff": get_player_season_metrics().get("holdout_season"),
            "metrics": get_player_season_metrics().get("metrics", {}),
            "awards_status": get_player_season_metrics().get("awards_validation"),
        },
        "lineup": {
            "kind": "observed/proxy blend",
            "status": "heuristic blend; win curve fitted, no lineup holdout",
            "version": "lineup-blend-v1",
            "data_cutoff": trained.get("holdout_season"),
            "metrics": {"win_curve_slope": trained.get("win_curve_slope")},
        },
        "score_simulator": {
            "kind": "mechanistic Monte Carlo",
            "status": "distribution diagnostic; not the calibrated headline probability",
            "version": "matchup-simulator-v1",
            "data_cutoff": trained.get("holdout_season"),
            "metrics": {},
        },
        "season_forecast": {
            "kind": "Monte Carlo simulation",
            "status": (
                "historically backtested"
                if forecast_metrics
                else "heuristic; backtest artifact missing"
            ),
            "version": "season-forecast-v2-roster",
            "data_cutoff": forecast.get("data_cutoffs"),
            "metrics": forecast_metrics,
            "roster_overlay": {
                "version": ROSTER_INPUT_VERSION,
                "status": (
                    "prospective explainable overlay; base simulator is historically "
                    "backtested, roster overlay is not separately calibrated"
                ),
            },
            "beats_baseline": bool(
                record and record.get("mae", float("inf")) < record.get("baseline_mae", 0)
            ),
        },
    }


@lru_cache(maxsize=2)
def _snapshot_for_day(day: str, client: NBAClient) -> pd.DataFrame:
    """Team form snapshot with Elo, cached per calendar day.

    Prior-seeded like the outcome model's training features, so
    early-season serving inputs match the training distribution.
    """
    try:
        priors = prior_team_form(client.team_games(past_seasons(1)[0]))
    except Exception:
        logger.warning("prior-season form unavailable; serving unseeded snapshot",
                       exc_info=True)
        priors = None
    snapshot = team_form_snapshot(client.team_games(), form_priors=priors)
    try:
        games = pd.concat(
            [client.team_games(s) for s in [*past_seasons(2), current_season()]],
            ignore_index=True,
        )
        snapshot["elo"] = current_elo(games).reindex(snapshot.index)
    except Exception:
        # matchup_features degrades to a neutral elo_diff
        logger.warning("Elo unavailable; predictions use a neutral elo_diff",
                       exc_info=True)
    return snapshot


def _find_player(client: NBAClient, player_id: int) -> dict:
    match = client.find_player(player_id)
    if not match:
        raise HTTPException(404, f"no player with id {player_id}")
    return match


def _require_local(request: Request) -> None:
    """Keep scraped salary data on the user's own machine.

    The public API deliberately excludes contracts. TestClient is admitted so
    the guard and payload can remain covered without weakening production.
    """
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(403, "salary data is available only from the local machine")


def _is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}


@app.get("/teams")
def teams(client: Client) -> list[str]:
    """Tricodes of all teams with games this season."""
    day = pd.Timestamp.now("UTC").date().isoformat()
    return sorted(_snapshot_for_day(day, client).index)


@app.get("/meta")
def metadata() -> dict:
    return {
        "current_season": current_season(),
        "seasons": seasons_since(),
        "prediction_seasons": prediction_seasons(),
    }


def _prediction_context(season: str | None) -> tuple[str, str, str]:
    """Return requested season, source-data season, and projection mode."""
    available = prediction_seasons()
    selected = season or available[0]
    if selected not in available:
        raise HTTPException(
            422,
            f"prediction season must be one of {', '.join(available)}",
        )
    basis = available[0]
    mode = "season_to_date" if selected == basis else "preseason_carry_forward"
    return selected, basis, mode


def _finite_records(frame: pd.DataFrame) -> list[dict]:
    """JSON-safe records: pandas NaN/NaT become null, timestamps become ISO strings."""
    clean = frame.astype(object).where(frame.notna(), None)
    for column in clean.columns:
        clean[column] = clean[column].map(
            lambda value: (
                value.isoformat()
                if isinstance(value, (pd.Timestamp, pd.Timedelta))
                else value
            )
        )
    return clean.to_dict(orient="records")


@app.get("/league/pulse")
def league_pulse(client: Client, season: str | None = None) -> dict:
    """League leaders and all-team form, shared with Streamlit's League pulse."""
    selected = season or current_season()
    league = league_with_ratings(client, None if selected == current_season() else selected)
    max_gp = int(league["GP"].max()) if "GP" in league and not league.empty else 0
    min_gp = min(20, max(1, max_gp // 2))
    specs = {
        "points": "PTS",
        "assists": "AST",
        "rebounds": "REB",
        "threes": "FG3M",
        "net_rating": "NET_RATING",
        "clutch_net": "CLUTCH_NET_RATING",
    }
    leaders: dict[str, list[dict]] = {}
    for label, stat in specs.items():
        if stat not in league:
            continue
        pool = league
        if stat == "NET_RATING" and "MIN" in league:
            pool = pool[pool["MIN"] >= 24]
        elif stat == "CLUTCH_NET_RATING" and {"MIN", "CLUTCH_GP"} <= set(league.columns):
            pool = pool[(pool["MIN"] >= 24) & (pool["CLUTCH_GP"] >= min_gp)]
        board = league_leaders(pool, stat, top=5, min_gp=min_gp)
        leaders[label] = _finite_records(board)

    next_slate: list[dict] = []
    if selected == current_season():
        day = pd.Timestamp.now("UTC").date().isoformat()
        indexed_snapshot = _snapshot_for_day(day, client)
        snapshot = indexed_snapshot.reset_index()
        try:
            slate = upcoming_games(client.schedule())
            rest = (
                team_rest_features(client.team_games(), tipoff=slate["tipoff"].iloc[0])
                if not slate.empty else None
            )
            model = get_outcome_model()
            for game in slate.itertuples():
                fatigue = {}
                if rest is not None and game.home in rest.index and game.away in rest.index:
                    home_rest, away_rest = rest.loc[game.home], rest.loc[game.away]
                    fatigue = {
                        "rest_diff": float(home_rest["rest_days"] - away_rest["rest_days"]),
                        "b2b_diff": float(home_rest["b2b"] - away_rest["b2b"]),
                        "three_in_four_diff": float(
                            home_rest["three_in_four"] - away_rest["three_in_four"]
                        ),
                    }
                probability = float(
                    model.predict_proba(
                        matchup_features(
                            indexed_snapshot, game.home, game.away, **fatigue
                        )
                    ).iloc[0]
                )
                next_slate.append(
                    {
                        "home": game.home,
                        "away": game.away,
                        "tipoff": pd.Timestamp(game.tipoff).isoformat(),
                        "home_win_prob": probability,
                    }
                )
        except Exception:
            logger.warning("next slate unavailable for league pulse", exc_info=True)
    else:
        snapshot = team_form_snapshot(client.team_games(selected)).reset_index()
    if snapshot.columns[0] != "team":
        snapshot = snapshot.rename(columns={snapshot.columns[0]: "team"})
    form_columns = [
        column
        for column in (
            "team",
            "form_win_pct",
            "form_pts",
            "form_net",
            "form_ortg",
            "form_drtg",
            "form_pace",
            "elo",
            "last_game_date",
        )
        if column in snapshot
    ]
    if "form_net" in snapshot:
        snapshot = snapshot.sort_values("form_net", ascending=False)
    return {
        "season": selected,
        "minimum_games": min_gp,
        "leaders": leaders,
        "team_form": _finite_records(snapshot[form_columns]),
        "next_slate": next_slate,
    }


@app.get("/teams/{team}/profile")
def team_profile(team: str, request: Request, client: Client) -> dict:
    """Full Team Room: identity, factors, roster, lineups, impact, and money."""
    team = team.upper()
    day = pd.Timestamp.now("UTC").date().isoformat()
    snapshot = _snapshot_for_day(day, client)
    if team not in snapshot.index:
        raise HTTPException(404, f"unknown team {team!r}")

    league = league_with_ratings(client)
    if "TEAM_ABBREVIATION" not in league:
        raise HTTPException(503, "team roster data unavailable")
    roster = league[league["TEAM_ABBREVIATION"] == team].sort_values(
        "MIN" if "MIN" in league else "GP", ascending=False
    )
    contracts = None
    if _is_local(request):
        try:
            contracts = client.player_contracts()
            roster = attach_salary(roster, contracts)
        except Exception:
            logger.warning("local salary context unavailable for %s", team, exc_info=True)
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
    try:
        take = team_scouting_take(
            snapshot.loc[team], wins, losses, snapshot,
            recent=(int((recent["WL"] == "W").sum()), int((recent["WL"] == "L").sum())),
        )
    except Exception:
        take = ""

    factors: dict = {}
    try:
        factor_table = four_factors_table(games)
        if team in factor_table.index:
            factor_frame = factor_table.loc[[team]].reset_index()
            factors = _finite_records(factor_frame)[0]
    except Exception:
        logger.warning("four factors unavailable for %s", team, exc_info=True)

    lineups: list[dict] = []
    try:
        lineups = _finite_records(most_used_lineups(client.lineups(), team).head(20))
    except Exception:
        logger.warning("lineups unavailable for %s", team, exc_info=True)

    on_off: list[dict] = []
    if not log.empty and "TEAM_ID" in log:
        try:
            impact = team_on_off(client.team_player_on_off(int(log["TEAM_ID"].iloc[0])))
            on_off = _finite_records(impact[impact["MIN_ON"] >= 100].head(20))
        except Exception:
            logger.warning("on/off unavailable for %s", team, exc_info=True)

    standings: list[dict] = []
    try:
        raw_standings = client.standings()
        standing_columns = [
            column
            for column in (
                "Conference", "PlayoffRank", "TeamCity", "TeamName", "TeamID",
                "WINS", "LOSSES", "WinPCT", "L10", "strCurrentStreak",
            )
            if column in raw_standings
        ]
        standings = _finite_records(raw_standings[standing_columns])
    except Exception:
        logger.warning("standings unavailable", exc_info=True)

    finances = None
    if contracts is not None:
        try:
            book = team_contracts(contracts, team)
            payroll = team_payroll(contracts)
            finances = {
                "local_only": True,
                "seasons": salary_seasons(contracts),
                "payroll": float(payroll.get(team, 0)),
                "contracts": _finite_records(book),
            }
        except Exception:
            logger.warning("contract book unavailable for %s", team, exc_info=True)

    recent_columns = [
        column for column in ("GAME_DATE", "MATCHUP", "WL", "PTS", "PLUS_MINUS")
        if column in recent
    ]
    return {
        "team": team,
        "season": current_season(),
        "record": {"wins": wins, "losses": losses},
        "scouting_take": take,
        "form": form,
        "roster": _finite_records(roster[roster_columns].head(18)),
        "four_factors": factors,
        "factor_labels": FACTOR_LABELS,
        "recent_games": _finite_records(recent[recent_columns].iloc[::-1]),
        "standings": standings,
        "lineups": lineups,
        "on_off": on_off,
        "finances": finances,
    }


def _matchup_prob(
    client: NBAClient,
    model: GameOutcomeModel,
    home: str,
    away: str,
    season: str | None = None,
) -> float:
    """Home-team win probability, validating the matchup (404/422)."""
    _prediction_context(season)
    day = pd.Timestamp.now("UTC").date().isoformat()
    snapshot = _snapshot_for_day(day, client)
    for team in (home, away):
        if team not in snapshot.index:
            raise HTTPException(404, f"unknown team {team!r}")
    if home == away:
        raise HTTPException(422, "home and away must differ")
    return float(model.predict_proba(matchup_features(snapshot, home, away)).iloc[0])


@app.get("/predict/game")
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
    selected, basis, mode = _prediction_context(season)
    day = pd.Timestamp.now("UTC").date().isoformat()
    snapshot = _snapshot_for_day(day, client)
    for team in (home, away):
        if team not in snapshot.index:
            raise HTTPException(404, f"unknown team {team!r}")
    if home == away:
        raise HTTPException(422, "home and away must differ")
    features = matchup_features(
        snapshot, home, away, home_missing_min=home_missing_min,
        away_missing_min=away_missing_min,
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


@app.get("/predict/simulate")
def predict_simulation(
    home: str,
    away: str,
    client: Client,
    model: OutcomeModel,
    season: str | None = None,
    home_missing_min: Annotated[float, Query(ge=0, le=240)] = 0,
    away_missing_min: Annotated[float, Query(ge=0, le=240)] = 0,
    n_sims: Annotated[int, Query(ge=1000, le=20_000)] = 10_000,
) -> dict:
    """Monte Carlo margin/total distribution plus calibrated model comparison."""
    selected, basis, mode = _prediction_context(season)
    day = pd.Timestamp.now("UTC").date().isoformat()
    snapshot = _snapshot_for_day(day, client)
    for selected in (home, away):
        if selected not in snapshot.index:
            raise HTTPException(404, f"unknown team {selected!r}")
    if home == away:
        raise HTTPException(422, "home and away must differ")
    seed = zlib.crc32(
        f"{selected}|{home}|{away}|{home_missing_min}|{away_missing_min}|{n_sims}".encode()
    )
    sims = simulate_matchup(
        snapshot, home, away, home_missing_min=home_missing_min,
        away_missing_min=away_missing_min, n_sims=n_sims, seed=seed,
    )
    margin = sims["home_pts"] - sims["away_pts"]
    total = sims["home_pts"] + sims["away_pts"]
    model_features = matchup_features(
        snapshot, home, away, home_missing_min=home_missing_min,
        away_missing_min=away_missing_min,
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
    selected: str,
    basis: str,
    n_sims: int,
    day: str,
    client: NBAClient,
) -> pd.DataFrame:
    snapshot = _snapshot_for_day(day, client)
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
    conferences = {
        str(team_ids.get(row.TeamID)): str(row.Conference)
        for row in standings[["TeamID", "Conference"]].itertuples(index=False)
        if row.TeamID in team_ids
    }
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
            table = table.merge(
                roster_inputs.teams.reset_index(), on="TEAM", how="left"
            )
            table.attrs["roster_metadata"] = roster_inputs.metadata
        return table
    except (KeyError, ValueError) as error:
        raise HTTPException(503, str(error)) from error


@lru_cache(maxsize=4)
def _roster_forecast_inputs(
    selected: str,
    basis: str,
    day: str,
    client: NBAClient,
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


@app.get("/predict/season/roster-inputs")
def predict_season_roster_inputs(
    client: Client,
    season: str | None = None,
    team: str | None = None,
) -> dict:
    """Audit the versioned player-minutes inputs and explainable team adjustments."""
    selected, basis, _ = _prediction_context(season or prediction_seasons()[1])
    if selected == basis:
        raise HTTPException(422, "roster inputs are available for the next-season forecast")
    day = pd.Timestamp.now("UTC").date().isoformat()
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
        "teams": _finite_records(teams),
        "players": _finite_records(players),
    }


@lru_cache(maxsize=4)
def _player_season_table(
    selected: str,
    basis: str,
    day: str,
    client: NBAClient,
) -> pd.DataFrame:
    roster = _roster_forecast_inputs(selected, basis, day, client)
    try:
        team_forecast = _season_forecast_table(selected, basis, 1_000, day, client)
    except HTTPException:
        logger.warning("team forecast unavailable for player awards; using neutral wins")
        team_forecast = None
    return project_player_seasons(
        league_with_ratings(client, basis),
        roster.players,
        team_forecast=team_forecast,
    )


@app.get("/predict/players")
def predict_player_seasons(
    client: Client,
    season: str | None = None,
    team: str | None = None,
    trajectory: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """Next-season player roles, box-stat ranges, comparables, and award outlook."""
    selected, basis, _ = _prediction_context(season or prediction_seasons()[1])
    if selected == basis:
        raise HTTPException(422, "player season projections are available for next season")
    day = pd.Timestamp.now("UTC").date().isoformat()
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
        "players": _finite_records(filtered.head(limit)),
    }


@app.get("/predict/season")
def predict_season(
    client: Client,
    season: str | None = None,
    n_sims: Annotated[int, Query(ge=1_000, le=20_000)] = 5_000,
) -> dict:
    """Conference tables and playoff, title, and NBA Cup forecast odds."""
    selected = season or prediction_seasons()[1]
    selected, basis, mode = _prediction_context(selected)
    day = pd.Timestamp.now("UTC").date().isoformat()
    table = _season_forecast_table(selected, basis, n_sims, day, client)
    roster_metadata = table.attrs.get("roster_metadata")
    conferences = {
        conference: _finite_records(
            table[table["CONFERENCE"] == conference].sort_values("PROJECTED_SEED")
        )
        for conference in ("East", "West")
    }
    title_favorite = table.sort_values("CHAMP_PROB", ascending=False).iloc[0]
    cup_favorite = table.sort_values("CUP_PROB", ascending=False).iloc[0]
    cup_groups = {
        group: _finite_records(
            table[table["CUP_GROUP"] == group].sort_values(
                "CUP_PROJECTED_GROUP_RANK"
            )
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


@app.get("/predict/player/{player_id}")
def predict_player_points(
    player_id: int,
    opponent: str,
    client: Client,
    model: PointsModel,
    home: bool = True,
    own_missing_min: Annotated[float | None, Query(ge=0, le=240)] = None,
) -> dict:
    """Next-game player points projection with empirical 80% interval."""
    player = _find_player(client, player_id)
    day = pd.Timestamp.now("UTC").date().isoformat()
    snapshot = _snapshot_for_day(day, client)
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
    prediction = float(model.predict(features).iloc[0])
    interval = model.interval(prediction)
    return {
        "player": player["full_name"],
        "opponent": opponent,
        "home": home,
        "projected_points": prediction,
        "interval_80": list(interval) if interval else None,
        "last_5": float(features["pts_r5"].iloc[0]),
        "last_10": float(features["pts_r10"].iloc[0]),
        "games_in_sample": len(rows),
    }


@app.get("/predict/lineup")
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
    roster = league[
        (league["TEAM_ABBREVIATION"] == team) & league["PLAYER_ID"].isin(player_ids)
    ]
    if len(roster) != 5:
        raise HTTPException(404, "all five players must be on the selected team")
    names = roster.set_index("PLAYER_ID").loc[player_ids, "PLAYER_NAME"].tolist()
    net, minutes = blended_lineup_estimate(
        client.lineups(), league, names, player_ids
    )
    return {
        "team": team,
        "players": names,
        "estimated_net_rating": net,
        "minutes_together": minutes,
        "win_probability_vs_average": curve.win_probability(net),
        "source": "observed_blend" if minutes > 0 else "per_36_proxy",
    }


@app.get("/methodology")
def methodology() -> dict:
    """Static protocol plus artifact-recorded holdout metrics for the PWA."""
    return {
        "evaluation": {
            "protocol": "Temporal holdout; hyperparameters tune on the last training season.",
            "leakage": "Every rolling feature is shifted; Elo and availability are pre-game.",
            "decision_metrics": [
                "log loss", "Brier score", "accuracy", "mean absolute error"
            ],
        },
        "metrics": get_model_metrics(),
        "registry": get_model_registry(),
        "season_backtest": get_season_forecast_metrics(),
        "journey": [
            {"stage": "Always pick home", "accuracy": 54.9},
            {"stage": "Last-10 form", "accuracy": 65.1},
            {"stage": "Season + four factors", "accuracy": 68.3},
            {"stage": "+ Availability", "accuracy": 69.2},
            {"stage": "+ Elo", "accuracy": 70.0},
            {"stage": "+ Seeded form", "accuracy": 70.2},
        ],
        "models": {
            "outcome": (
                "TRAINED · TEMPORAL HOLDOUT EVALUATED. Scaled logistic regression "
                "on prior-seeded team form, rest, "
                "availability, Elo, and home court."
            ),
            "simulator": (
                "MECHANISTIC · NOT A CALIBRATED HEADLINE. 10,000 draws over pace "
                "and opponent-adjusted efficiency; used for score distributions."
            ),
            "points": (
                "TRAINED · TEMPORAL HOLDOUT EVALUATED. Two-stage ridge: predicted "
                "minutes multiplied by predicted points per minute, with an empirical "
                "80% interval."
            ),
            "lineup": (
                "HEURISTIC BLEND · NO LINEUP HOLDOUT. Observed five-man net rating "
                "shrunk toward a per-36 player proxy and mapped through a fitted win curve."
            ),
            "season": (
                "HISTORICALLY BACKTESTED SIMULATION. Prior-season win rate, net "
                "rating, and Elo with offseason uncertainty; registry exposes record "
                "MAE, playoff/title/Cup Brier scores, baselines, calibration, and cutoffs."
            ),
        },
        "rejected": [
            "Venue-split form", "SOS-adjusted net", "Garbage-time form filtering",
            "Gradient boosting", "Five neural-network configurations",
        ],
    }


@app.get("/methodology/registry")
def methodology_registry() -> dict:
    """Machine-readable model lineage, validation status, and data cutoffs."""
    return {
        "models": get_model_registry(),
        "season_backtest": get_season_forecast_metrics(),
    }


_fetch_headshot = lru_cache(maxsize=256)(fetch_headshot)


@app.get("/players/{player_id}/headshot")
def player_headshot(player_id: int) -> Response:
    """Proxy the NBA CDN headshot (it rejects browser hotlinking)."""
    content = _fetch_headshot(player_id)
    if content is None:
        raise HTTPException(404, "no headshot available")
    return Response(content=content, media_type="image/png")


@app.get("/players/search")
def search_players(q: Annotated[str, Query(min_length=3)], client: Client) -> list[dict]:
    return [
        {"id": p["id"], "full_name": p["full_name"], "is_active": p["is_active"]}
        for p in client.search_players(q)
    ]


@app.get("/players/{player_id}/career")
def player_career(player_id: int, client: Client) -> list[dict]:
    """Per-game career averages, one record per season."""
    totals = client.career_stats(player_id)
    if totals.empty:
        raise HTTPException(404, f"no career data for player {player_id}")
    return career_per_game(totals).to_dict(orient="records")


@app.get("/players/{player_id}/percentiles")
def player_percentiles(player_id: int, client: Client) -> dict:
    """League percentile ranks (0-100) for the current season.

    Uses the ratings-attached league table so the API reports the same
    stat set (incl. net and clutch rating) as the Streamlit app.
    """
    player = _find_player(client, player_id)
    league = league_with_ratings(client)
    try:
        ranks = percentile_ranks(league, player["full_name"])
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {
        "player": player["full_name"],
        "season": current_season(),
        # dropna: a player missing from a rating table must not emit NaN
        # (invalid JSON), just omit the stat
        "percentiles": ranks.dropna().to_dict(),
    }


@app.get("/players/{player_id}/insights")
def player_insights(
    player_id: int,
    client: Client,
    season: str | None = None,
) -> dict:
    """League/position context, scouting take, ratings, and draft pedigree."""
    player = _find_player(client, player_id)
    selected = season or current_season()
    league = league_with_ratings(client, None if selected == current_season() else selected)
    try:
        ranks = percentile_ranks(league, player["full_name"])
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    position_ranks: dict = {}
    position_group = None
    try:
        positioned, position_group = positional_percentile_ranks(
            league, player["full_name"]
        )
        position_ranks = positioned.dropna().to_dict()
    except (KeyError, ValueError):
        pass

    row = league[league["PLAYER_NAME"] == player["full_name"]]
    rating_columns = [
        column
        for column in ("TEAM_ABBREVIATION", "NET_RATING", "CLUTCH_NET_RATING", "DPM")
        if column in row
    ]
    ratings = _finite_records(row[rating_columns].head(1))
    draft = None
    try:
        draft = player_draft_line(client.draft_history(), player_id)
    except Exception:
        logger.warning("draft context unavailable for player %s", player_id, exc_info=True)
    return {
        "player": player["full_name"],
        "season": selected,
        "ratings": ratings[0] if ratings else {},
        "league_percentiles": ranks.dropna().to_dict(),
        "position_group": position_group,
        "position_percentiles": position_ranks,
        "scouting_take": player_scouting_take(ranks),
        "draft": draft,
    }


@app.get("/players/{player_id}/shots")
def player_shots(
    player_id: int,
    client: Client,
    season: str | None = None,
    season_type: Annotated[
        str, Query(pattern="^(Regular Season|Playoffs)$")
    ] = "Regular Season",
) -> dict:
    """Raw locations plus league-relative zone, hex, diet, and quality views."""
    player = _find_player(client, player_id)
    selected = season or current_season()
    shots = client.shot_chart(player_id, season=selected, season_type=season_type)
    if shots.empty:
        return {
            "player": player["full_name"], "season": selected,
            "season_type": season_type, "attempts": [], "zones": [], "hexes": [],
            "breakdown": [], "quality": {},
        }
    averages = client.shot_league_averages(season=selected, season_type=season_type)
    raw_columns = [
        column
        for column in (
            "LOC_X", "LOC_Y", "SHOT_MADE_FLAG", "SHOT_ZONE_BASIC",
            "SHOT_ZONE_AREA", "SHOT_ZONE_RANGE", "SHOT_TYPE",
        )
        if column in shots
    ]
    quality = shot_quality(shots, averages).dropna().to_dict()
    return {
        "player": player["full_name"],
        "season": selected,
        "season_type": season_type,
        "attempts": _finite_records(shots[raw_columns]),
        "zones": _finite_records(zone_efficiency(shots, averages)),
        "hexes": _finite_records(hex_bins(shots, averages)),
        "breakdown": _finite_records(shot_breakdown(shots, averages)),
        "quality": quality,
    }


@app.get("/players/{player_id}/splits")
def player_split_tables(
    player_id: int,
    client: Client,
    season: str | None = None,
) -> dict:
    """Home/away, month, rest, and opponent splits from the game log."""
    player = _find_player(client, player_id)
    selected = season or current_season()
    log = client.game_log(player_id, season=selected)
    tables = {
        dimension: _finite_records(player_splits(log, dimension))
        for dimension in DIMENSIONS
    }
    return {"player": player["full_name"], "season": selected, "splits": tables}


@app.get("/players/{player_id}/on-off")
def player_on_off(player_id: int, client: Client) -> dict:
    """Current team performance with the player on and off the court."""
    player = _find_player(client, player_id)
    totals = client.career_stats(player_id)
    current = totals[totals["SEASON_ID"] == current_season()] if "SEASON_ID" in totals else totals
    if current.empty or "TEAM_ID" not in current or not current["TEAM_ID"].notna().any():
        raise HTTPException(404, "current team is unavailable for on/off context")
    team_id = int(current[current["TEAM_ID"].notna()].iloc[-1]["TEAM_ID"])
    table = team_on_off(client.team_player_on_off(team_id))
    row = table[table["PLAYER_ID"] == player_id]
    if row.empty:
        raise HTTPException(404, "on/off row is unavailable for this player")
    return {
        "player": player["full_name"],
        "season": current_season(),
        "on_off": _finite_records(row)[0],
    }


@app.get("/players/{player_id}/contract")
def player_contract_detail(player_id: int, request: Request, client: Client) -> dict:
    """Local-only current/future contract detail from the scraped salary table."""
    _require_local(request)
    player = _find_player(client, player_id)
    contracts = client.player_contracts()
    try:
        row = player_contract(contracts, player["full_name"])
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    seasons = salary_seasons(contracts)
    salaries = {
        selected: float(row[selected])
        for selected in seasons
        if pd.notna(row.get(selected))
    }
    guaranteed = row.get("GUARANTEED")
    return {
        "player": player["full_name"],
        "local_only": True,
        "salaries": salaries,
        "guaranteed": float(guaranteed) if pd.notna(guaranteed) else None,
    }


@app.get("/players/{player_id}/games")
def player_games(
    player_id: int,
    client: Client,
    season: str | None = None,
    limit: Annotated[int, Query(ge=1, le=82)] = 12,
) -> dict:
    """Recent regular-season game log, using the same tidy view as Streamlit."""
    player = _find_player(client, player_id)
    log = client.game_log(player_id, season=season)
    if log.empty:
        return {"player": player["full_name"], "season": season or current_season(), "games": []}
    games = game_log_table(log).head(limit)
    return {
        "player": player["full_name"],
        "season": season or current_season(),
        "games": _finite_records(games),
    }


@app.get("/players/{player_id}/similar")
def player_similar(
    player_id: int,
    client: Client,
    limit: Annotated[int, Query(ge=1, le=12)] = 6,
) -> dict:
    """Current-season statistical comparables from Streamlit's profile page."""
    player = _find_player(client, player_id)
    try:
        comps = similar_players(league_with_ratings(client), player["full_name"], n=limit)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    return {
        "player": player["full_name"],
        "season": current_season(),
        "similar": _finite_records(comps),
    }


@app.get("/league/explore")
def explore_league(
    client: Client,
    season: str | None = None,
    rate: Annotated[str, Query(pattern="^(per_game|per_36)$")] = "per_game",
    min_gp: Annotated[int, Query(ge=0, le=82)] = 0,
    min_min: Annotated[float, Query(ge=0, le=48)] = 0,
    teams: Annotated[list[str] | None, Query()] = None,
    q: str = "",
    sort: str = "PTS",
    order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
) -> dict:
    """Filterable, sortable master player table from Streamlit's Explore page."""
    league = league_with_ratings(client, season)
    if rate == "per_36":
        league = per_minutes_table(league, 36)
    filtered = filter_players(
        league,
        min_gp=min_gp,
        min_min=min_min,
        teams=[team.upper() for team in teams] if teams else None,
        name_query=q,
    )
    columns = [
        column
        for column in (
            "PLAYER_ID",
            "PLAYER_NAME",
            "TEAM_ABBREVIATION",
            "GP",
            "MIN",
            "PTS",
            "REB",
            "AST",
            "STL",
            "BLK",
            "TOV",
            "FG_PCT",
            "FG3M",
            "FG3_PCT",
            "NET_RATING",
            "CLUTCH_NET_RATING",
            "DPM",
        )
        if column in filtered
    ]
    sort_column = sort if sort in columns else "PTS" if "PTS" in columns else columns[0]
    filtered = filtered.sort_values(sort_column, ascending=order == "asc", na_position="last")
    return {
        "season": season or current_season(),
        "rate": rate,
        "count": len(filtered),
        "players": _finite_records(filtered[columns]),
    }


@app.get("/games")
def games(client: Client, season: str | None = None) -> dict:
    """Full-season schedule and results from Streamlit's Game Center."""
    board = scoreboard(client.schedule(season))
    return {
        "season": season or current_season(),
        "games": _finite_records(board),
    }


@app.get("/games/{game_id}/box-score")
def game_box_score(
    game_id: str,
    client: Client,
    season: str | None = None,
) -> dict:
    """Team-grouped traditional box score for a completed game."""
    table = pd.DataFrame()
    source = "league_game_finder"
    try:
        logs = client.player_games(season or current_season())
        if "GAME_ID" in logs:
            rows = logs[logs["GAME_ID"].astype(str) == str(game_id)]
            if not rows.empty:
                table = game_finder_box_score_table(rows)
    except Exception:
        logger.warning("cached player-game box score unavailable", exc_info=True)
    if table.empty:
        source = "traditional_box_score"
        try:
            raw = client.box_score(game_id)
            if not raw.empty:
                table = box_score_table(raw)
        except Exception as error:
            logger.warning("traditional box score unavailable", exc_info=True)
            raise HTTPException(404, "box score is unavailable for this game") from error
    if table.empty:
        raise HTTPException(404, "box score is unavailable for this game")
    teams = {
        str(team): _finite_records(rows.drop(columns="TEAM"))
        for team, rows in table.groupby("TEAM", sort=False)
    }
    return {"game_id": game_id, "source": source, "teams": teams}


def _traditional_story_rows(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalize v3 box rows to the LeagueGameFinder columns game_story uses."""
    if raw.empty:
        return pd.DataFrame()
    first = raw["firstName"].fillna("").astype(str).str.strip()
    last = raw["familyName"].fillna("").astype(str).str.strip()
    mapping = {
        "personId": "PLAYER_ID",
        "teamId": "TEAM_ID",
        "teamTricode": "TEAM_ABBREVIATION",
        "points": "PTS",
        "fieldGoalsMade": "FGM",
        "fieldGoalsAttempted": "FGA",
        "threePointersMade": "FG3M",
        "freeThrowsAttempted": "FTA",
        "reboundsOffensive": "OREB",
        "reboundsDefensive": "DREB",
        "reboundsTotal": "REB",
        "assists": "AST",
        "turnovers": "TOV",
        "steals": "STL",
        "blocks": "BLK",
    }
    rows = raw[list(mapping)].rename(columns=mapping).copy()
    rows["PLAYER_NAME"] = (first + " " + last).str.strip()
    return rows


@app.get("/games/{game_id}/story")
def game_story_detail(
    game_id: str,
    client: Client,
    season: str | None = None,
) -> dict:
    """Cached timeline, shots, lineups, advanced stats, and win-probability story."""
    selected = season or current_season()
    board = scoreboard(client.schedule(selected))
    match = board[board["GAME_ID"].astype(str) == str(game_id)]
    if match.empty:
        raise HTTPException(404, "game is not present in the selected season")
    game = match.iloc[0]
    if game["STATUS"] != "Final":
        return {
            "game_id": game_id,
            "available": False,
            "reason": "Game story becomes available after the game is final.",
        }
    pbp = client.cached_play_by_play(game_id)
    if pbp is None or pbp.empty:
        return {
            "game_id": game_id,
            "available": False,
            "reason": (
                "Cached play-by-play is unavailable. Run `uv run python -m "
                "nba_insights.pbp.backfill --seasons " + selected + "` to add it."
            ),
        }
    logs = client.player_games(selected)
    rows = (
        logs[logs["GAME_ID"].astype(str) == str(game_id)]
        if "GAME_ID" in logs
        else pd.DataFrame()
    )
    if rows.empty:
        try:
            rows = _traditional_story_rows(client.box_score(game_id))
        except Exception:
            rows = pd.DataFrame()
    if rows.empty:
        return {
            "game_id": game_id,
            "available": False,
            "reason": "Player/team identity data is unavailable for this game.",
        }
    rotation = client.cached_rotation(game_id)
    story = game_story(
        pbp,
        rows,
        home=str(game["HOME"]),
        away=str(game["AWAY"]),
        rotation=rotation,
    )
    return {
        "game_id": game_id,
        "available": True,
        "availability": {
            "timeline": True,
            "shot_locations": story["shot_locations_available"],
            "lineups": bool(story["lineups"]),
            "play_by_play": True,
        },
        **story,
    }


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/ask")
def ask_league(body: AskBody, client: Client) -> dict:
    """Credential-safe natural-language Q&A over one structured league tool."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(
            503,
            "AI Q&A is optional: set ANTHROPIC_API_KEY or run `ant auth login`",
        )
    try:
        import anthropic
        from anthropic import beta_tool
    except ImportError as error:
        raise HTTPException(
            503, "AI Q&A requires `uv sync --extra ai`"
        ) from error

    league = league_with_ratings(client)

    @beta_tool
    def query_league(
        filters: dict | None = None,
        name_contains: str = "",
        teams: list | None = None,
        sort_by: str = "",
        ascending: bool = False,
        top_n: int = 10,
        columns: list | None = None,
    ) -> str:
        """Query current per-player stats; filters are inclusive minimums."""
        return json.dumps(
            query_players(
                league,
                filters=filters,
                name_contains=name_contains,
                teams=teams or None,
                sort_by=sort_by or None,
                ascending=ascending,
                top_n=top_n,
                columns=columns,
            )
        )

    glossary = "\n".join(f"- {column}: {meaning}" for column, meaning in COLUMN_GLOSSARY.items())
    system = (
        f"Answer NBA questions for {current_season()} using only query_league. "
        "Call the tool before stating any number. Percentages are fractions; present "
        "them as percentages. Keep the answer concise and mention active filters. "
        f"Available columns:\n{glossary}"
    )
    model = os.environ.get("NBA_ASK_MODEL", "claude-opus-4-8")
    try:
        runner = anthropic.Anthropic().beta.messages.tool_runner(
            model=model,
            max_tokens=2048,
            system=system,
            tools=[query_league],
            messages=[{"role": "user", "content": body.question}],
        )
        final = None
        for message in runner:
            final = message
        answer = "".join(block.text for block in final.content if block.type == "text")
    except anthropic.AuthenticationError as error:
        raise HTTPException(503, "Anthropic credential was rejected") from error
    except Exception as error:
        logger.warning("AI Q&A failed", exc_info=True)
        raise HTTPException(502, f"AI answer failed: {error}") from error
    return {
        "answer": answer or "No answer was produced.",
        "model": model,
        "season": current_season(),
    }


@app.get("/compare")
def compare(
    names: Annotated[list[str], Query(min_length=2, max_length=4)], client: Client
) -> dict:
    """Current and career comparison for 2-4 active or retired players."""
    league = league_with_ratings(client)
    players = []
    for name in names:
        exact = [player for player in client.search_players(name) if player["full_name"] == name]
        if not exact:
            raise HTTPException(404, f"player {name!r} not found")
        players.append(exact[0])

    # Career comparisons remain useful when one or more players are retired.
    # Current stats and their poster require all players in the league snapshot.
    try:
        table = comparison_table(league, names)
    except KeyError:
        table = pd.DataFrame()
    table = table.astype(object).where(table.notna(), None)

    career_stats: dict[str, dict] = {}
    career_seasons: dict[str, list[dict]] = {}
    ranks: dict[str, dict] = {}
    qualities: dict[str, dict] = {}
    try:
        league_averages = client.shot_league_averages()
    except Exception:
        league_averages = None
    for player in players:
        name = player["full_name"]
        totals = client.career_stats(player["id"])
        if not totals.empty:
            career_stats[name] = career_averages(totals).dropna().to_dict()
            career_seasons[name] = _finite_records(career_per_game(totals))
        try:
            ranks[name] = percentile_ranks(league, name).dropna().to_dict()
        except KeyError:
            ranks[name] = {}
        if league_averages is not None:
            try:
                qualities[name] = (
                    shot_quality(client.shot_chart(player["id"]), league_averages)
                    .dropna()
                    .to_dict()
                )
            except Exception:
                qualities[name] = {}
    poster_png = None
    if not table.empty:
        query = urlencode({"names": names}, doseq=True)
        poster_png = f"/posters/compare?{query}&format=png"
    return {
        "season": current_season(),
        "stats": table.to_dict(),
        "career": career_stats,
        "career_seasons": career_seasons,
        "percentiles": ranks,
        "shot_quality": qualities,
        "poster_png": poster_png,
    }


@app.get("/players/{player_id}/card", response_class=HTMLResponse)
def player_card(player_id: int, client: Client) -> str:
    """Self-contained HTML share card: headline per-game stats + percentiles."""
    player = _find_player(client, player_id)
    totals = client.career_stats(player_id)
    if totals.empty:
        raise HTTPException(404, f"no career data for player {player_id}")
    latest = career_per_game(totals).iloc[-1]

    ranks = None
    if player["is_active"]:
        try:
            ranks = percentile_ranks(client.league_player_stats(), player["full_name"])
        except Exception:  # card degrades to stats-only rather than 500ing
            ranks = None

    return render_player_card(player["full_name"], latest, ranks)


PosterFormat = Annotated[str, Query(pattern="^(html|png)$")]


def _poster_response(html: str, png: bytes | None, format: str) -> Response:
    if format == "png":
        return Response(content=png, media_type="image/png")
    return HTMLResponse(content=html)


@app.get("/posters/compare")
def compare_poster(
    names: Annotated[list[str], Query(min_length=2, max_length=4)],
    client: Client,
    format: PosterFormat = "html",
) -> Response:
    """1:1 share poster of a player comparison (HTML, or PNG with format=png)."""
    league = league_with_ratings(client)
    try:
        table = comparison_table(league, names)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    season = current_season()
    png = compare_poster_png(table, season) if format == "png" else None
    return _poster_response(compare_poster_html(table, season), png, format)


@app.get("/posters/game")
def game_poster(
    home: str,
    away: str,
    client: Client,
    model: OutcomeModel,
    season: str | None = None,
    format: PosterFormat = "html",
) -> Response:
    """16:9 share poster of a game prediction (HTML, or PNG with format=png)."""
    selected, _, _ = _prediction_context(season)
    prob = _matchup_prob(client, model, home, away, selected)
    png = prediction_poster_png(home, away, prob, selected) if format == "png" else None
    return _poster_response(prediction_poster_html(home, away, prob, selected), png, format)
