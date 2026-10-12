"""Schedule, box scores, and play-by-play game stories."""

from __future__ import annotations

import logging

import pandas as pd
from fastapi import APIRouter, HTTPException

from nba_insights.analysis import (
    box_score_table,
    game_finder_box_score_table,
    game_story,
    scoreboard,
)
from nba_insights.api import schemas
from nba_insights.api.deps import Client
from nba_insights.api.schemas import errors
from nba_insights.api.shared import finite_records
from nba_insights.config import current_season

logger = logging.getLogger(__name__)

router = APIRouter(tags=["games"])


@router.get("/games", response_model=schemas.Schedule)
def games(client: Client, season: str | None = None) -> dict:
    """Full-season schedule and results from Streamlit's Game Center."""
    board = scoreboard(client.schedule(season))
    return {"season": season or current_season(), "games": finite_records(board)}


@router.get("/games/{game_id}/box-score", response_model=schemas.BoxScore, responses=errors(404))
def game_box_score(game_id: str, client: Client, season: str | None = None) -> dict:
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
        str(team): finite_records(rows.drop(columns="TEAM"))
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


@router.get(
    "/games/{game_id}/story",
    response_model=schemas.GameStory,
    response_model_exclude_unset=True,
    responses=errors(404),
)
def game_story_detail(game_id: str, client: Client, season: str | None = None) -> dict:
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
        logs[logs["GAME_ID"].astype(str) == str(game_id)] if "GAME_ID" in logs else pd.DataFrame()
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
    story = game_story(pbp, rows, home=str(game["HOME"]), away=str(game["AWAY"]), rotation=rotation)
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
