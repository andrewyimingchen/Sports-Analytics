"""Nightly data and model pipeline: warm, backfill, retrain on a cadence, track drift.

    uv run python -m nba_insights.pipeline                 # warm + retrain-if-due + drift
    uv run python -m nba_insights.pipeline --pbp           # also extend the play-by-play corpus
    uv run python -m nba_insights.pipeline --retrain-days 0  # retrain every run

Run it where stats.nba.com is reachable (it blocks most datacenter IPs), from
cron or a systemd timer (see docs/DEPLOYMENT.md). Each run appends one JSON
line to ``data/pipeline.jsonl``. A failed step or a drift verdict exits 1,
logs an error, and posts to ``POSSESSION_LAB_ALERT_WEBHOOK`` when set (a
Slack-compatible ``{"text": ...}`` payload).

Models are fit on completed seasons only, so a retrain does not change them
within a season; it re-scores the holdout (the current season once it has
enough games) and records the run in the manifest. Live calibration is
what watches the shipped model week to week.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nba_insights.config import DATA_DIR, MODELS_DIR, current_season
from nba_insights.errors import EXPECTED_ERRORS, reason_for
from nba_insights.ingest import NBAClient, serving_client
from nba_insights.ml import GameOutcomeModel
from nba_insights.ml.drift import live_calibration
from nba_insights.ml.manifest import load_manifest
from nba_insights.ml.train import (
    METRICS_PATH,
    OUTCOME_PATH,
    build_elo,
    build_matchups,
    run_training,
)
from nba_insights.ops import backup
from nba_insights.pbp.backfill import backfill_season
from nba_insights.warm import warm

logger = logging.getLogger(__name__)

RUN_LOG_PATH = DATA_DIR / "pipeline.jsonl"
DRIFT_PATH = MODELS_DIR / "drift.json"
RETRAIN_DAYS = 7
WEBHOOK_ENV = "POSSESSION_LAB_ALERT_WEBHOOK"


# Expected failures a step records (and alerts on) instead of crashing the run:
# the categorized data/upstream errors plus filesystem and SQLite errors from
# writing reports and backups.
_STEP_ERRORS: tuple[type[BaseException], ...] = (*EXPECTED_ERRORS, OSError, sqlite3.Error)


@dataclass
class Step:
    name: str
    status: str = "ok"  # ok | degraded | skipped | failed
    detail: str = ""
    seconds: float = 0.0


@dataclass
class Run:
    started_at: str
    steps: list[Step] = field(default_factory=list)
    finished_at: str | None = None
    alerts: list[str] = field(default_factory=list)

    def record(self, name: str, action: Callable[[], tuple[str, str]]) -> Step:
        """Run one step; expected failures are recorded, defects propagate."""
        step = Step(name)
        started = time.monotonic()
        try:
            step.status, step.detail = action()
        except _STEP_ERRORS as error:
            step.status, step.detail = "failed", f"{reason_for(error)}: {error}"
            logger.error("pipeline step %s failed", name, exc_info=True)
        step.seconds = round(time.monotonic() - started, 1)
        self.steps.append(step)
        if step.status == "failed":
            self.alerts.append(f"{name} failed ({step.detail})")
        return step


def retrain_due(manifest: dict[str, Any] | None, now: datetime, days: int) -> bool:
    """Whether the last recorded training run is at least *days* old (or missing)."""
    recorded = ((manifest or {}).get("runs", {}).get("train") or {}).get("recorded_at")
    if not recorded:
        return True
    return now - datetime.fromisoformat(recorded) >= timedelta(days=days)


def drift_report(client: NBAClient, model: GameOutcomeModel, reference: dict | None) -> dict:
    """Live calibration of the shipped outcome model on the current season."""
    season = current_season()
    if client.team_games(season).empty:
        return {"season": season, "drift": {"status": "no_games"}}
    matchups = build_matchups(client, [season], build_elo(client, [season]))
    report = live_calibration(matchups, model.predict_proba(matchups), reference)
    return {"season": season, **report}


def run_pipeline(
    client: NBAClient,
    *,
    top: int = 20,
    pbp: bool = False,
    pbp_client: NBAClient | None = None,
    retrain_days: int = RETRAIN_DAYS,
    now: datetime | None = None,
    drift_path: Path = DRIFT_PATH,
    backup_dest: Path | None = None,
) -> Run:
    now = now or datetime.now(UTC)
    run = Run(started_at=now.isoformat(timespec="seconds"))

    def do_warm() -> tuple[str, str]:
        failures = warm(client, top=top)
        return ("degraded" if failures else "ok", f"{failures} failed fetches")

    run.record("warm", do_warm)

    if pbp:

        def do_pbp() -> tuple[str, str]:
            failures = backfill_season(pbp_client or client, current_season())
            return ("degraded" if failures else "ok", f"{failures} failed games")

        run.record("pbp", do_pbp)

    def do_retrain() -> tuple[str, str]:
        if not retrain_due(load_manifest(), now, retrain_days):
            return "skipped", f"last training run is under {retrain_days} days old"
        metrics = run_training(client)
        outcome = metrics["outcome"]
        return (
            "ok",
            f"holdout log loss {outcome['log_loss']:.3f}, accuracy {outcome['accuracy']:.3f}",
        )

    run.record("retrain", do_retrain)

    def do_drift() -> tuple[str, str]:
        if not OUTCOME_PATH.exists():
            return "skipped", "outcome model not trained"
        reference = (
            json.loads(METRICS_PATH.read_text()).get("outcome") if METRICS_PATH.exists() else None
        )
        report = drift_report(client, GameOutcomeModel.load(OUTCOME_PATH), reference)
        report["generated_at"] = now.isoformat(timespec="seconds")
        drift_path.parent.mkdir(parents=True, exist_ok=True)
        drift_path.write_text(json.dumps(report, indent=2) + "\n")
        verdict = report["drift"]
        if verdict["status"] == "drift":
            run.alerts.append(
                f"outcome model drift: recent log loss {verdict['recent_log_loss']:.3f} "
                f"> threshold {verdict['threshold']:.3f}"
            )
            return "degraded", verdict["status"]
        return "ok", verdict["status"]

    run.record("drift", do_drift)

    if backup_dest is not None:

        def do_backup() -> tuple[str, str]:
            record = backup(backup_dest)
            return "ok", f"{record['path']} ({len(record['files'])} files)"

        run.record("backup", do_backup)
    run.finished_at = datetime.now(UTC).isoformat(timespec="seconds")
    return run


PERSISTENT_NIGHTS = 3


def recent_runs(path: Path = RUN_LOG_PATH, n: int = PERSISTENT_NIGHTS) -> list[dict[str, Any]]:
    """The last *n* recorded runs, oldest first (unreadable lines are skipped)."""
    try:
        lines = path.read_text().splitlines()[-n:]
    except OSError:
        return []
    runs = []
    for line in lines:
        try:
            runs.append(json.loads(line))
        except ValueError:
            continue
    return runs


def add_persistence_alerts(
    run: Run, history: list[dict[str, Any]], nights: int = PERSISTENT_NIGHTS
) -> None:
    """Alert when a step has been degraded or failed for *nights* runs in a row.

    One degraded night is usually a transient upstream outage; a streak means
    the data or the model has stopped updating.
    """
    previous = history[-(nights - 1) :] if nights > 1 else []
    if len(previous) < nights - 1:
        return
    for step in run.steps:
        if step.status not in ("degraded", "failed"):
            continue
        streak = all(
            any(
                old["name"] == step.name and old["status"] in ("degraded", "failed")
                for old in past.get("steps", [])
            )
            for past in previous
        )
        if streak:
            run.alerts.append(
                f"{step.name} degraded or failed {nights} runs in a row ({step.detail})"
            )


def append_run_log(run: Run, path: Path = RUN_LOG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as log:
        log.write(json.dumps(asdict(run)) + "\n")


def send_alert(run: Run, webhook: str | None = None) -> bool:
    """Post the run's alerts to the webhook (if configured); True when sent."""
    webhook = webhook or os.environ.get(WEBHOOK_ENV)
    if not webhook or not run.alerts:
        return False
    import requests

    text = "POSSESSION LAB pipeline: " + "; ".join(run.alerts)
    try:
        requests.post(webhook, json={"text": text}, timeout=10).raise_for_status()
    except requests.RequestException:
        logger.error("alert webhook failed", exc_info=True)
        return False
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Nightly data and model pipeline")
    parser.add_argument("--top", type=int, default=20, help="players to warm, by minutes")
    parser.add_argument("--pbp", action="store_true", help="extend the play-by-play corpus")
    parser.add_argument(
        "--retrain-days",
        type=int,
        default=RETRAIN_DAYS,
        help="retrain when the last training run is this many days old (0: every run)",
    )
    parser.add_argument(
        "--backup", type=Path, metavar="DIR", help="also write a verified backup to DIR"
    )
    args = parser.parse_args()

    client = serving_client()
    # the rotation endpoint serves empty responses when hit faster than ~3s
    pbp_client = serving_client(delay=3.0) if args.pbp else None
    run = run_pipeline(
        client,
        top=args.top,
        pbp=args.pbp,
        pbp_client=pbp_client,
        retrain_days=args.retrain_days,
        backup_dest=args.backup,
    )
    add_persistence_alerts(run, recent_runs())
    append_run_log(run)
    for step in run.steps:
        logger.info("%-8s %-8s %5.1fs  %s", step.name, step.status, step.seconds, step.detail)
    if run.alerts:
        for alert in run.alerts:
            logger.error("ALERT %s", alert)
        send_alert(run)
        sys.exit(1)


if __name__ == "__main__":
    main()
