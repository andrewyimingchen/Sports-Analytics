"""JSON API over the same ingest/analysis layers the Streamlit app uses.

Run with: uv run uvicorn nba_insights.api:app --reload

Routes live in :mod:`nba_insights.api.routers`, one module per domain, with
response contracts in :mod:`nba_insights.api.schemas`. The NBAClient and model
artifacts are FastAPI dependencies (:mod:`nba_insights.api.deps`) so tests can
substitute fakes; all endpoints read through the shared cache, so the API and
the app warm each other.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from nba_insights.api.deps import (
    get_client,
    get_outcome_model,
    get_points_model,
    get_win_curve,
)
from nba_insights.api.routers import (
    ai,
    games,
    league,
    methodology,
    players,
    posters,
    predictions,
    system,
    teams,
)
from nba_insights.api.routers.system import STATIC_DIR, healthcheck, readiness

__all__ = [
    "app",
    "get_client",
    "get_outcome_model",
    "get_points_model",
    "get_win_curve",
    "healthcheck",
    "readiness",
]

app = FastAPI(
    title="POSSESSION LAB API",
    version="0.1.0",
    openapi_tags=[
        {"name": "system", "description": "Capability metadata for the PWA."},
        {"name": "league", "description": "Leaders, team form, tracking, and the explorer."},
        {"name": "teams", "description": "Team Room profiles and team comparison."},
        {"name": "players", "description": "Player profile views and comparison."},
        {"name": "games", "description": "Schedule, box scores, and game stories."},
        {"name": "predictions", "description": "Game, season, player, and lineup models."},
        {"name": "methodology", "description": "Evaluation protocol and model registry."},
        {"name": "ai", "description": "Optional natural-language Q&A."},
        {"name": "posters", "description": "Shareable HTML/PNG posters."},
    ],
)
app.mount("/app", StaticFiles(directory=STATIC_DIR, html=True), name="mobile")

for module in (system, league, teams, players, games, predictions, methodology, ai, posters):
    app.include_router(module.router)
