"""Shareable comparison and prediction posters."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response

from nba_insights.analysis import comparison_table
from nba_insights.api.deps import Client, OutcomeModel
from nba_insights.api.schemas import errors
from nba_insights.api.shared import matchup_probability, prediction_context
from nba_insights.config import current_season
from nba_insights.posters import (
    compare_poster_html,
    compare_poster_png,
    prediction_poster_html,
    prediction_poster_png,
)
from nba_insights.serve import league_with_ratings

router = APIRouter(tags=["posters"])


PosterFormat = Annotated[str, Query(pattern="^(html|png)$")]


def _poster_response(html: str, png: bytes | None, format: str) -> Response:
    if format == "png":
        return Response(content=png, media_type="image/png")
    return HTMLResponse(content=html)


@router.get(
    "/posters/compare",
    response_class=HTMLResponse,
    responses={200: {"content": {"image/png": {}}}, **errors(404)},
)
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


@router.get(
    "/posters/game",
    response_class=HTMLResponse,
    responses={200: {"content": {"image/png": {}}}, **errors(404, 422, 503)},
)
def game_poster(
    home: str,
    away: str,
    client: Client,
    model: OutcomeModel,
    season: str | None = None,
    format: PosterFormat = "html",
) -> Response:
    """16:9 share poster of a game prediction (HTML, or PNG with format=png)."""
    selected, _, _ = prediction_context(season)
    prob = matchup_probability(client, model, home, away, selected)
    png = prediction_poster_png(home, away, prob, selected) if format == "png" else None
    return _poster_response(prediction_poster_html(home, away, prob, selected), png, format)
