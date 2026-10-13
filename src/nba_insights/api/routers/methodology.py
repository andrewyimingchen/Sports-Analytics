"""Model evaluation protocol, metrics, and the model registry."""

from __future__ import annotations

from fastapi import APIRouter

from nba_insights.api import schemas
from nba_insights.api.deps import (
    get_drift_report,
    get_manifest_report,
    get_model_metrics,
    get_model_registry,
    get_season_forecast_metrics,
)

router = APIRouter(tags=["methodology"])


@router.get("/methodology", response_model=schemas.Methodology, response_model_exclude_unset=True)
def methodology() -> dict:
    """Static protocol plus artifact-recorded holdout metrics for the PWA."""
    return {
        "evaluation": {
            "protocol": "Temporal holdout; hyperparameters tune on the last training season.",
            "leakage": "Every rolling feature is shifted; Elo and availability are pre-game.",
            "decision_metrics": ["log loss", "Brier score", "accuracy", "mean absolute error"],
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
            "Venue-split form",
            "SOS-adjusted net",
            "Garbage-time form filtering",
            "Gradient boosting",
            "Five neural-network configurations",
        ],
    }


@router.get(
    "/methodology/registry", response_model=schemas.Registry, response_model_exclude_unset=True
)
def methodology_registry() -> dict:
    """Machine-readable model lineage, validation status, and data cutoffs."""
    report = get_manifest_report()
    return {
        "models": get_model_registry(),
        "season_backtest": get_season_forecast_metrics(),
        "manifest": {
            "status": report["status"],
            "updated_at": (report["manifest"] or {}).get("updated_at"),
            "verification": report["verification"]["status"],
        },
    }


@router.get("/methodology/manifest", response_model=schemas.ManifestReport)
def methodology_manifest() -> dict:
    """Reproducibility record for the served artifacts, verified against their hashes."""
    return get_manifest_report()


@router.get(
    "/methodology/drift", response_model=schemas.DriftReport, response_model_exclude_unset=True
)
def methodology_drift() -> dict:
    """Live calibration of the outcome model on the current season (nightly pipeline)."""
    report = get_drift_report()
    if report is None:
        return {"status": "missing"}
    return {"status": "available", **report}
