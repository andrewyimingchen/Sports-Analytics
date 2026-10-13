"""Operational commands: verified backups and an external health check.

    uv run python -m nba_insights.ops backup --dest /backups/possession-lab --keep 14
    uv run python -m nba_insights.ops check https://lab.example.com --max-stale-hours 36

``backup`` takes a consistent online copy of the SQLite cache with SQLite's
backup API (safe while the API and pipeline are running, unlike a file copy
in WAL mode), copies the model artifacts, tracked manifest, and pipeline run
log, verifies the copy with ``PRAGMA quick_check``, writes ``backup.json``
with SHA-256 hashes, and keeps the newest ``--keep`` backups.

``check`` is for an uptime monitor on another machine: it fails (exit 1, and
posts to ``POSSESSION_LAB_ALERT_WEBHOOK`` when set) if ``/healthz`` or
``/readyz`` do not answer, readiness is not ``ready``, or the nightly
pipeline has not run within ``--max-stale-hours``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nba_insights.config import CACHE_DB, DATA_DIR, MANIFEST_PATH, MODELS_DIR

logger = logging.getLogger(__name__)

BACKUP_PREFIX = "possession-lab-"
KEEP = 14
MAX_STALE_HOURS = 36.0
WEBHOOK_ENV = "POSSESSION_LAB_ALERT_WEBHOOK"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup(
    dest: Path,
    *,
    cache_db: Path = CACHE_DB,
    models_dir: Path = MODELS_DIR,
    manifest: Path = MANIFEST_PATH,
    run_log: Path | None = None,
    keep: int = KEEP,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Write one verified backup under *dest* and prune older ones; returns its record."""
    now = now or datetime.now(UTC)
    target = dest / f"{BACKUP_PREFIX}{now.strftime('%Y%m%dT%H%M%SZ')}"
    partial = target.with_name(target.name + ".partial")
    shutil.rmtree(partial, ignore_errors=True)
    partial.mkdir(parents=True)
    files: dict[str, Any] = {}

    if cache_db.exists():
        source = sqlite3.connect(f"file:{cache_db}?mode=ro", uri=True)
        copy = sqlite3.connect(partial / cache_db.name)
        try:
            source.backup(copy)
            check = copy.execute("PRAGMA quick_check").fetchone()[0]
        finally:
            copy.close()
            source.close()
        if check != "ok":
            raise sqlite3.DatabaseError(f"backup of {cache_db} failed quick_check: {check}")
        files[cache_db.name] = {
            "bytes": (partial / cache_db.name).stat().st_size,
            "quick_check": check,
        }
    else:
        files[cache_db.name] = {"status": "missing"}

    if models_dir.is_dir():
        shutil.copytree(models_dir, partial / "models")
        for path in sorted((partial / "models").iterdir()):
            files[f"models/{path.name}"] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
    for extra in (manifest, run_log or DATA_DIR / "pipeline.jsonl"):
        if extra.exists():
            shutil.copy2(extra, partial / extra.name)
            files[extra.name] = {"bytes": extra.stat().st_size, "sha256": _sha256(extra)}

    record = {"created_at": now.isoformat(timespec="seconds"), "files": files}
    (partial / "backup.json").write_text(json.dumps(record, indent=2) + "\n")
    partial.rename(target)  # a backup only exists once it is complete
    record["path"] = str(target)
    record["pruned"] = [str(path) for path in prune(dest, keep)]
    return record


def prune(dest: Path, keep: int) -> list[Path]:
    """Delete all but the newest *keep* complete backups (and stale partials)."""
    removed = []
    for partial in dest.glob(f"{BACKUP_PREFIX}*.partial"):
        shutil.rmtree(partial, ignore_errors=True)
        removed.append(partial)
    backups = sorted(p for p in dest.glob(f"{BACKUP_PREFIX}*") if p.is_dir())
    for old in backups[:-keep] if keep > 0 else []:
        shutil.rmtree(old)
        removed.append(old)
    return removed


def check(
    base_url: str, *, max_stale_hours: float = MAX_STALE_HOURS, timeout: float = 10.0
) -> list[str]:
    """Problems found at *base_url* (empty when healthy and fresh)."""
    import requests

    base = base_url.rstrip("/")
    problems: list[str] = []
    try:
        health = requests.get(f"{base}/healthz", timeout=timeout)
        if health.status_code != 200:
            problems.append(f"/healthz answered {health.status_code}")
        ready = requests.get(f"{base}/readyz", timeout=timeout)
    except requests.RequestException as error:
        return [f"unreachable: {type(error).__name__}"]
    if ready.status_code != 200:
        return [*problems, f"/readyz answered {ready.status_code}"]
    body = ready.json()
    if body.get("status") != "ready":
        problems.append(f"readiness is {body.get('status')!r}")
    freshness = body.get("data_freshness") or {}
    hours = freshness.get("hours_since_pipeline")
    if hours is None:
        problems.append("the nightly pipeline has never run")
    elif hours > max_stale_hours:
        problems.append(f"data is stale: last pipeline run {hours:.0f}h ago")
    return problems


def _post_alert(text: str) -> None:
    webhook = os.environ.get(WEBHOOK_ENV)
    if not webhook:
        return
    import requests

    try:
        requests.post(webhook, json={"text": text}, timeout=10).raise_for_status()
    except requests.RequestException:
        logger.error("alert webhook failed", exc_info=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="POSSESSION LAB operations")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("backup", help="verified backup of cache, models, and records")
    b.add_argument("--dest", type=Path, required=True)
    b.add_argument("--keep", type=int, default=KEEP)
    c = sub.add_parser("check", help="health and freshness check for an uptime monitor")
    c.add_argument("url")
    c.add_argument("--max-stale-hours", type=float, default=MAX_STALE_HOURS)
    args = parser.parse_args()

    if args.command == "backup":
        record = backup(args.dest, keep=args.keep)
        logger.info("backup written to %s (%d files)", record["path"], len(record["files"]))
        return
    problems = check(args.url, max_stale_hours=args.max_stale_hours)
    if problems:
        text = f"POSSESSION LAB {args.url}: " + "; ".join(problems)
        logger.error("ALERT %s", text)
        _post_alert(text)
        sys.exit(1)
    logger.info("%s is healthy and fresh", args.url)


if __name__ == "__main__":
    main()
