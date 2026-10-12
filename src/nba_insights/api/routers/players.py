"""Player identity, profile views, comparison, and share card."""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Annotated
from urllib.parse import urlencode

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response

from nba_insights.analysis import (
    DIMENSIONS,
    career_averages,
    career_per_game,
    comparison_table,
    game_log_table,
    hex_bins,
    percentile_ranks,
    player_contract,
    player_draft_line,
    player_scouting_take,
    player_splits,
    positional_percentile_ranks,
    salary_seasons,
    shot_breakdown,
    shot_quality,
    similar_players,
    team_on_off,
    zone_efficiency,
)
from nba_insights.api import schemas
from nba_insights.api.cards import render_player_card
from nba_insights.api.deps import Client
from nba_insights.api.schemas import errors
from nba_insights.api.security import is_local_request, require_private_access
from nba_insights.api.shared import find_player, finite_records
from nba_insights.config import current_season
from nba_insights.serve import fetch_headshot, league_with_ratings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["players"])


_fetch_headshot = lru_cache(maxsize=256)(fetch_headshot)


@router.get(
    "/players/{player_id}/headshot",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}, **errors(404)},
)
def player_headshot(player_id: int) -> Response:
    """Proxy the NBA CDN headshot (it rejects browser hotlinking)."""
    content = _fetch_headshot(player_id)
    if content is None:
        raise HTTPException(404, "no headshot available")
    return Response(content=content, media_type="image/png")


@router.get("/players/search", response_model=list[schemas.PlayerSummary])
def search_players(q: Annotated[str, Query(min_length=3)], client: Client) -> list[dict]:
    return [
        {"id": p["id"], "full_name": p["full_name"], "is_active": p["is_active"]}
        for p in client.search_players(q)
    ]


# Declared after /players/search so "search" is never parsed as an ID.
@router.get("/players/{player_id}", response_model=schemas.PlayerSummary, responses=errors(404))
def player_lookup(player_id: int, client: Client) -> dict:
    """One player's identity, for deep links that carry only an ID."""
    player = client.find_player(player_id)
    if player is None:
        raise HTTPException(404, f"unknown player {player_id}")
    return {"id": player["id"], "full_name": player["full_name"], "is_active": player["is_active"]}


@router.get("/players/{player_id}/career", response_model=schemas.Records, responses=errors(404))
def player_career(player_id: int, client: Client) -> list[dict]:
    """Per-game career averages, one record per season."""
    totals = client.career_stats(player_id)
    if totals.empty:
        raise HTTPException(404, f"no career data for player {player_id}")
    return career_per_game(totals).to_dict(orient="records")


@router.get(
    "/players/{player_id}/percentiles", response_model=schemas.Percentiles, responses=errors(404)
)
def player_percentiles(player_id: int, client: Client) -> dict:
    """League percentile ranks (0-100) for the current season.

    Uses the ratings-attached league table so the API reports the same
    stat set (incl. net and clutch rating) as the Streamlit app.
    """
    player = find_player(client, player_id)
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


@router.get(
    "/players/{player_id}/insights", response_model=schemas.PlayerInsights, responses=errors(404)
)
def player_insights(player_id: int, client: Client, season: str | None = None) -> dict:
    """League/position context, scouting take, ratings, and draft pedigree."""
    player = find_player(client, player_id)
    selected = season or current_season()
    league = league_with_ratings(client, None if selected == current_season() else selected)
    try:
        ranks = percentile_ranks(league, player["full_name"])
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    position_ranks: dict = {}
    position_group = None
    try:
        positioned, position_group = positional_percentile_ranks(league, player["full_name"])
        position_ranks = positioned.dropna().to_dict()
    except (KeyError, ValueError):
        pass

    row = league[league["PLAYER_NAME"] == player["full_name"]]
    rating_columns = [
        column
        for column in ("TEAM_ABBREVIATION", "NET_RATING", "CLUTCH_NET_RATING", "DPM")
        if column in row
    ]
    ratings = finite_records(row[rating_columns].head(1))
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


@router.get("/players/{player_id}/shots", response_model=schemas.PlayerShots, responses=errors(404))
def player_shots(
    player_id: int,
    client: Client,
    season: str | None = None,
    season_type: Annotated[str, Query(pattern="^(Regular Season|Playoffs)$")] = "Regular Season",
) -> dict:
    """Raw locations plus league-relative zone, hex, diet, and quality views."""
    player = find_player(client, player_id)
    selected = season or current_season()
    shots = client.shot_chart(player_id, season=selected, season_type=season_type)
    if shots.empty:
        return {
            "player": player["full_name"],
            "season": selected,
            "season_type": season_type,
            "attempts": [],
            "zones": [],
            "hexes": [],
            "breakdown": [],
            "quality": {},
        }
    averages = client.shot_league_averages(season=selected, season_type=season_type)
    raw_columns = [
        column
        for column in (
            "LOC_X",
            "LOC_Y",
            "SHOT_MADE_FLAG",
            "SHOT_ZONE_BASIC",
            "SHOT_ZONE_AREA",
            "SHOT_ZONE_RANGE",
            "SHOT_TYPE",
        )
        if column in shots
    ]
    quality = shot_quality(shots, averages).dropna().to_dict()
    return {
        "player": player["full_name"],
        "season": selected,
        "season_type": season_type,
        "attempts": finite_records(shots[raw_columns]),
        "zones": finite_records(zone_efficiency(shots, averages)),
        "hexes": finite_records(hex_bins(shots, averages)),
        "breakdown": finite_records(shot_breakdown(shots, averages)),
        "quality": quality,
    }


@router.get(
    "/players/{player_id}/splits", response_model=schemas.PlayerSplits, responses=errors(404)
)
def player_split_tables(player_id: int, client: Client, season: str | None = None) -> dict:
    """Home/away, month, rest, and opponent splits from the game log."""
    player = find_player(client, player_id)
    selected = season or current_season()
    log = client.game_log(player_id, season=selected)
    tables = {dimension: finite_records(player_splits(log, dimension)) for dimension in DIMENSIONS}
    return {"player": player["full_name"], "season": selected, "splits": tables}


@router.get(
    "/players/{player_id}/on-off", response_model=schemas.PlayerOnOff, responses=errors(404)
)
def player_on_off(player_id: int, client: Client) -> dict:
    """Current team performance with the player on and off the court."""
    player = find_player(client, player_id)
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
        "on_off": finite_records(row)[0],
    }


@router.get(
    "/players/{player_id}/contract",
    dependencies=[Depends(require_private_access)],
    response_model=schemas.PlayerContract,
    responses=errors(401, 403, 404),
)
def player_contract_detail(player_id: int, request: Request, client: Client) -> dict:
    """Private career and future contract detail from scraped salary tables."""
    player = find_player(client, player_id)
    contracts = client.player_contracts()
    try:
        row = player_contract(contracts, player["full_name"])
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    seasons = salary_seasons(contracts)
    salaries = {
        selected: float(row[selected]) for selected in seasons if pd.notna(row.get(selected))
    }
    guaranteed = row.get("GUARANTEED")
    history: list[dict] = []
    slug = row.get("BREF_SLUG")
    if pd.notna(slug):
        try:
            history = finite_records(client.player_salary_history(str(slug)))
        except Exception:
            logger.warning("career salary history unavailable", exc_info=True)
    return {
        "player": player["full_name"],
        "local_only": is_local_request(request),
        "access": "local" if is_local_request(request) else "api_key",
        "salaries": salaries,
        "history": history,
        "guaranteed": float(guaranteed) if pd.notna(guaranteed) else None,
    }


@router.get("/players/{player_id}/games", response_model=schemas.PlayerGames, responses=errors(404))
def player_games(
    player_id: int,
    client: Client,
    season: str | None = None,
    limit: Annotated[int, Query(ge=1, le=82)] = 12,
) -> dict:
    """Recent regular-season game log, using the same tidy view as Streamlit."""
    player = find_player(client, player_id)
    log = client.game_log(player_id, season=season)
    if log.empty:
        return {"player": player["full_name"], "season": season or current_season(), "games": []}
    games = game_log_table(log).head(limit)
    return {
        "player": player["full_name"],
        "season": season or current_season(),
        "games": finite_records(games),
    }


@router.get(
    "/players/{player_id}/similar", response_model=schemas.SimilarPlayers, responses=errors(404)
)
def player_similar(
    player_id: int, client: Client, limit: Annotated[int, Query(ge=1, le=12)] = 6
) -> dict:
    """Current-season statistical comparables from Streamlit's profile page."""
    player = find_player(client, player_id)
    try:
        comps = similar_players(league_with_ratings(client), player["full_name"], n=limit)
    except KeyError as error:
        raise HTTPException(404, str(error)) from error
    return {
        "player": player["full_name"],
        "season": current_season(),
        "similar": finite_records(comps),
    }


@router.get("/compare", response_model=schemas.PlayerComparison, responses=errors(404))
def compare(names: Annotated[list[str], Query(min_length=2, max_length=4)], client: Client) -> dict:
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
            career_seasons[name] = finite_records(career_per_game(totals))
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


@router.get("/players/{player_id}/card", response_class=HTMLResponse, responses=errors(404))
def player_card(player_id: int, client: Client) -> str:
    """Self-contained HTML share card: headline per-game stats + percentiles."""
    player = find_player(client, player_id)
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
