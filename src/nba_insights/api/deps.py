"""FastAPI dependency providers shared by every router.

Tests substitute these through ``app.dependency_overrides``, so routers must
depend on the annotated aliases below rather than constructing clients or
loading model artifacts themselves.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends, HTTPException

from nba_insights.analysis import ROSTER_INPUT_VERSION
from nba_insights.config import MANIFEST_PATH, set_season_started_check
from nba_insights.ingest import NBAClient
from nba_insights.ml import GameOutcomeModel, PlayerPointsModel, WinCurve
from nba_insights.ml.backtest import SEASON_FORECAST_METRICS_PATH
from nba_insights.ml.manifest import MODEL_VERSIONS, load_manifest, verify_artifacts
from nba_insights.ml.player_backtest import PLAYER_SEASON_METRICS_PATH
from nba_insights.ml.train import METRICS_PATH, OUTCOME_PATH, POINTS_PATH, WIN_CURVE_PATH

_UNTRAINED = "models not trained: run `uv run python -m nba_insights.ml.train`"


@lru_cache(maxsize=1)
def get_client() -> NBAClient:
    client = NBAClient()
    # Keep the prior season current until the new one has regular-season games.
    set_season_started_check(client.season_has_started)
    return client


Client = Annotated[NBAClient, Depends(get_client)]


@lru_cache(maxsize=1)
def get_outcome_model() -> GameOutcomeModel:
    if not OUTCOME_PATH.exists():
        raise HTTPException(503, _UNTRAINED)
    return GameOutcomeModel.load(OUTCOME_PATH)


@lru_cache(maxsize=1)
def get_points_model() -> PlayerPointsModel:
    if not POINTS_PATH.exists():
        raise HTTPException(503, _UNTRAINED)
    return PlayerPointsModel.load(POINTS_PATH)


@lru_cache(maxsize=1)
def get_win_curve() -> WinCurve:
    if not WIN_CURVE_PATH.exists():
        raise HTTPException(503, _UNTRAINED)
    return WinCurve.load(WIN_CURVE_PATH)


OutcomeModel = Annotated[GameOutcomeModel, Depends(get_outcome_model)]
PointsModel = Annotated[PlayerPointsModel, Depends(get_points_model)]
LineupCurve = Annotated[WinCurve, Depends(get_win_curve)]


def model_availability() -> dict[str, bool]:
    return {
        "outcome": OUTCOME_PATH.exists(),
        "points": POINTS_PATH.exists(),
        "lineup": WIN_CURVE_PATH.exists(),
    }


@lru_cache(maxsize=1)
def get_model_metrics() -> dict[str, Any]:
    try:
        return json.loads(METRICS_PATH.read_text())
    except Exception:
        return {}


@lru_cache(maxsize=1)
def get_season_forecast_metrics() -> dict[str, Any]:
    try:
        return json.loads(SEASON_FORECAST_METRICS_PATH.read_text())
    except Exception:
        return {}


@lru_cache(maxsize=1)
def get_player_season_metrics() -> dict[str, Any]:
    try:
        return json.loads(PLAYER_SEASON_METRICS_PATH.read_text())
    except Exception:
        return {}


def get_model_registry() -> dict[str, dict[str, Any]]:
    trained = get_model_metrics()
    forecast = get_season_forecast_metrics()
    forecast_metrics = forecast.get("metrics", {})
    record = forecast_metrics.get("record", {})
    player_season = get_player_season_metrics()
    return {
        "outcome": {
            "kind": "trained supervised model",
            "status": (
                "temporal holdout evaluated" if trained.get("outcome") else "artifact missing"
            ),
            "version": MODEL_VERSIONS["outcome"],
            "data_cutoff": trained.get("holdout_season"),
            "metrics": trained.get("outcome", {}),
        },
        "player_points": {
            "kind": "trained supervised model",
            "status": "temporal holdout evaluated" if trained.get("points") else "artifact missing",
            "version": MODEL_VERSIONS["player_points"],
            "data_cutoff": trained.get("holdout_season"),
            "metrics": trained.get("points", {}),
        },
        "player_season": {
            "kind": "age/role carry-forward projection",
            "status": (
                "stable-returner historical holdout evaluated"
                if player_season.get("metrics")
                else "holdout artifact missing"
            ),
            "version": MODEL_VERSIONS["player_season"],
            "data_cutoff": player_season.get("holdout_season"),
            "metrics": player_season.get("metrics", {}),
            "awards_status": player_season.get("awards_validation"),
        },
        "lineup": {
            "kind": "observed/proxy blend",
            "status": "heuristic blend; win curve fitted, no lineup holdout",
            "version": MODEL_VERSIONS["lineup"],
            "data_cutoff": trained.get("holdout_season"),
            "metrics": {"win_curve_slope": trained.get("win_curve_slope")},
        },
        "score_simulator": {
            "kind": "mechanistic Monte Carlo",
            "status": "distribution diagnostic; not the calibrated headline probability",
            "version": MODEL_VERSIONS["score_simulator"],
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
            "version": MODEL_VERSIONS["season_forecast"],
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


def get_manifest_report() -> dict[str, Any]:
    """The tracked manifest plus a live check of the artifacts serving loads.

    Read per request: it is small, and a retrain or redeploy must show up
    without restarting the server.
    """
    manifest = load_manifest()
    verification = verify_artifacts(manifest)
    return {
        "status": "available" if manifest is not None else "missing",
        "path": str(MANIFEST_PATH),
        "verification": verification,
        "manifest": manifest,
    }
