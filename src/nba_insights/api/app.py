"""JSON API over the same ingest/analysis layers the Streamlit app uses.

Run with: uv run uvicorn nba_insights.api:app --reload

Routes live in :mod:`nba_insights.api.routers`, one module per domain, with
response contracts in :mod:`nba_insights.api.schemas`. The NBAClient and model
artifacts are FastAPI dependencies (:mod:`nba_insights.api.deps`) so tests can
substitute fakes; all endpoints read through the shared cache, so the API and
the app warm each other.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
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
from nba_insights.errors import (
    FAILURES,
    ArtifactUnavailableError,
    DataUnavailableError,
    NBAInsightsError,
    ProviderError,
    UpstreamError,
)
from nba_insights.observability import capture_exception, init_error_tracking

__all__ = [
    "app",
    "get_client",
    "get_outcome_model",
    "get_points_model",
    "get_win_curve",
    "healthcheck",
    "readiness",
]

init_error_tracking()  # optional Sentry; no-op unless SENTRY_DSN is set

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

logger = logging.getLogger(__name__)

# Expected categories map to stable status codes and reason codes; the message
# is ours (never upstream text), so it is safe to return.
_STATUS = {
    UpstreamError.reason: 503,
    DataUnavailableError.reason: 503,
    ArtifactUnavailableError.reason: 503,
    ProviderError.reason: 502,
}


@app.exception_handler(NBAInsightsError)
async def categorized_failure(request: Request, error: NBAInsightsError) -> JSONResponse:
    FAILURES.record(error.reason)
    logger.warning(
        "%s %s failed: %s", request.method, request.url.path, error.reason, exc_info=error
    )
    return JSONResponse(
        {"detail": str(error), "reason": error.reason},
        status_code=_STATUS.get(error.reason, 500),
    )


@app.exception_handler(Exception)
async def unexpected_failure(request: Request, error: Exception) -> JSONResponse:
    # Path only: query strings can carry names, and headers carry API keys.
    FAILURES.record(NBAInsightsError.reason)
    logger.error("%s %s raised unexpectedly", request.method, request.url.path, exc_info=error)
    capture_exception(error)
    return JSONResponse(
        {"detail": "internal server error", "reason": NBAInsightsError.reason},
        status_code=500,
    )


for module in (system, league, teams, players, games, predictions, methodology, ai, posters):
    app.include_router(module.router)
