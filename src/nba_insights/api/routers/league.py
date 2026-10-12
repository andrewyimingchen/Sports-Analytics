"""League-wide leaders, form, tracking tables, and the player explorer."""

from __future__ import annotations

import logging
from typing import Annotated
from urllib.parse import urlencode

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from nba_insights.analysis import (
    TRACKING_CATEGORIES,
    filter_players,
    league_leaders,
    per_minutes_table,
    tracking_table,
)
from nba_insights.api import schemas
from nba_insights.api.deps import Client, get_outcome_model
from nba_insights.api.schemas import errors
from nba_insights.api.shared import finite_records, snapshot_for_day, today
from nba_insights.config import current_season, seasons_since
from nba_insights.ml.features import (
    matchup_features,
    team_form_snapshot,
    team_rest_features,
    upcoming_games,
)
from nba_insights.serve import league_with_ratings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["league"])


@router.get("/league/pulse", response_model=schemas.LeaguePulse)
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
        leaders[label] = finite_records(board)

    next_slate: list[dict] = []
    if selected == current_season():
        day = today()
        indexed_snapshot = snapshot_for_day(day, client)
        snapshot = indexed_snapshot.reset_index()
        try:
            slate = upcoming_games(client.schedule())
            rest = (
                team_rest_features(client.team_games(), tipoff=slate["tipoff"].iloc[0])
                if not slate.empty
                else None
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
                        matchup_features(indexed_snapshot, game.home, game.away, **fatigue)
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
        "team_form": finite_records(snapshot[form_columns]),
        "next_slate": next_slate,
    }


@router.get(
    "/tracking",
    response_model=schemas.Tracking,
    response_model_exclude_unset=True,
    responses=errors(422),
)
def tracking_surface(
    client: Client,
    category: str = "drives",
    scope: str = "player",
    season: str | None = None,
    min_games: Annotated[int, Query(ge=0, le=82)] = 10,
    team: str | None = None,
    query: str | None = None,
    sort: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """Official tracking/hustle table with definitions and cache freshness."""
    selected = season or current_season()
    if selected not in seasons_since():
        raise HTTPException(422, f"season must be one of {', '.join(seasons_since())}")
    if category not in TRACKING_CATEGORIES:
        raise HTTPException(422, f"category must be one of {', '.join(TRACKING_CATEGORIES)}")
    normalized_scope = scope.capitalize()
    if normalized_scope not in {"Player", "Team"}:
        raise HTTPException(422, "scope must be player or team")
    config = TRACKING_CATEGORIES[category]
    key = (
        f"hustle/{scope.lower()}/{selected}"
        if category == "hustle"
        else f"tracking/{scope.lower()}/{config['measure']}/{selected}"
    )
    endpoint = "LeagueHustleStatsPlayer/Team" if category == "hustle" else "LeagueDashPtStats"
    try:
        frame = (
            client.hustle_stats(selected, normalized_scope)
            if category == "hustle"
            else client.tracking_stats(config["measure"], selected, normalized_scope)
        )
        if normalized_scope == "Team" and "TEAM_ABBREVIATION" not in frame and "TEAM_ID" in frame:
            games = client.team_games(selected)
            if {"TEAM_ID", "TEAM_ABBREVIATION"} <= set(games.columns):
                team_codes = games[["TEAM_ID", "TEAM_ABBREVIATION"]].drop_duplicates(
                    "TEAM_ID", keep="last"
                )
                frame = frame.merge(team_codes, on="TEAM_ID", how="left")
        table, metadata = tracking_table(
            frame,
            category,
            scope=normalized_scope,
            min_games=min_games,
            team=team,
            query=query,
            sort=sort,
            limit=limit,
        )
        cache_info = (
            client.cache.entry_info(key, ttl=client._season_ttl(selected))
            if hasattr(client, "cache") and hasattr(client.cache, "entry_info")
            else None
        )
        source = {
            "status": "available" if not frame.empty else "empty",
            "endpoint": endpoint,
            "provider": "stats.nba.com via nba_api",
            "fetched_at": cache_info.get("fetched_at") if cache_info else None,
            "age_seconds": cache_info.get("age_seconds") if cache_info else None,
            "stale": cache_info.get("stale") if cache_info else None,
            "upstream_rows": int(len(frame)),
            "schema_audit": {
                "available": metadata["available_metrics"],
                "missing": metadata["missing_metrics"],
            },
        }
        return {
            "season": selected,
            **metadata,
            "source": source,
            "count": int(len(table)),
            "records": finite_records(table),
            "share_url": (
                "/app/?"
                + urlencode(
                    {
                        "tracking_category": category,
                        "tracking_scope": scope.lower(),
                        "tracking_season": selected,
                        "tracking_team": team or "",
                        "tracking_min_games": min_games,
                        "tracking_query": query or "",
                    }
                )
                + "#tracking"
            ),
        }
    except Exception as exc:
        logger.warning("tracking category %s unavailable", category, exc_info=True)
        return {
            "season": selected,
            "category": category,
            "label": config["label"],
            "scope": scope.lower(),
            "definitions": config["metrics"],
            "percentage_metrics": [],
            "minimum_games": min_games,
            "source": {
                "status": "unavailable",
                "endpoint": endpoint,
                "provider": "stats.nba.com via nba_api",
                "detail": str(exc),
            },
            "count": 0,
            "records": [],
        }


@router.get("/league/explore", response_model=schemas.LeagueExplore)
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
        "players": finite_records(filtered[columns]),
    }
