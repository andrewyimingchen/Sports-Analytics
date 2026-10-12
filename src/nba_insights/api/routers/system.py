"""Probes, the PWA entry redirect, and client capability metadata."""

from __future__ import annotations

import os
from importlib.util import find_spec
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from nba_insights.api.deps import model_availability
from nba_insights.api.schemas import Health, Meta, Readiness
from nba_insights.config import current_season, prediction_seasons, seasons_since
from nba_insights.errors import FAILURES

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

router = APIRouter(tags=["system"])


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/app/")


@router.get("/healthz", include_in_schema=False, response_model=Health)
def healthcheck() -> dict[str, str]:
    """Cheap liveness probe with no cache, model, or upstream dependency."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False, response_model=Readiness)
def readiness() -> dict:
    """Deployment readiness plus optional artifact availability."""
    return {
        "status": "ready",
        "pwa_shell": (STATIC_DIR / "index.html").exists(),
        "optional_models": model_availability(),
        "failures": FAILURES.snapshot(),
    }


@router.get("/meta", response_model=Meta)
def metadata() -> dict:
    """Seasons the PWA can select and which optional capabilities are enabled."""
    return {
        "current_season": current_season(),
        "seasons": seasons_since(),
        "prediction_seasons": prediction_seasons(),
        "capabilities": {
            "ask_ai": bool(os.environ.get("ANTHROPIC_API_KEY"))
            and find_spec("anthropic") is not None,
            "private_salary": "local_requests_only",
            "models": model_availability(),
        },
    }
