"""Backups, the external health check, readiness freshness, and error scrubbing."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from nba_insights import observability, ops
from nba_insights.store import Cache

NOW = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)


@pytest.fixture
def data(tmp_path):
    cache = Cache(tmp_path / "data" / "cache.sqlite3")
    cache.put("league/2026-27", pd.DataFrame({"PTS": [1, 2, 3]}))
    models = tmp_path / "data" / "models"
    models.mkdir()
    (models / "outcome.joblib").write_bytes(b"model")
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")
    log = tmp_path / "data" / "pipeline.jsonl"
    log.write_text('{"steps": []}\n')
    return {
        "cache_db": cache.db_path,
        "models_dir": models,
        "manifest": manifest,
        "run_log": log,
    }


def test_backup_is_consistent_verified_and_hashed(data, tmp_path):
    record = ops.backup(tmp_path / "backups", now=NOW, **data)
    target = tmp_path / "backups" / "possession-lab-20261102T060000Z"
    assert record["path"] == str(target)
    assert record["files"]["cache.sqlite3"]["quick_check"] == "ok"
    assert len(record["files"]["models/outcome.joblib"]["sha256"]) == 64
    assert {"manifest.json", "pipeline.jsonl"} <= set(record["files"])
    restored = Cache(target / "cache.sqlite3")
    assert restored.get("league/2026-27")["PTS"].tolist() == [1, 2, 3]
    assert json.loads((target / "backup.json").read_text())["created_at"] == record["created_at"]


def test_backup_keeps_the_newest_and_clears_partials(data, tmp_path):
    dest = tmp_path / "backups"
    (dest / "possession-lab-20261101T000000Z.partial").mkdir(parents=True)
    for day in range(3):
        ops.backup(dest, now=NOW + timedelta(days=day), keep=2, **data)
    kept = sorted(p.name for p in dest.iterdir())
    assert kept == ["possession-lab-20261103T060000Z", "possession-lab-20261104T060000Z"]


def test_backup_records_a_missing_cache(data, tmp_path):
    data["cache_db"] = tmp_path / "nope.sqlite3"
    record = ops.backup(tmp_path / "backups", now=NOW, **data)
    assert record["files"]["nope.sqlite3"] == {"status": "missing"}


class _Response:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}

    def json(self):
        return self._body


def _serve(monkeypatch, health=200, ready=200, body=None, error=None):
    import requests

    def get(url, timeout):
        if error:
            raise error
        return _Response(health) if url.endswith("/healthz") else _Response(ready, body)

    monkeypatch.setattr(requests, "get", get)


def test_check_passes_when_healthy_and_fresh(monkeypatch):
    fresh = {"status": "ready", "data_freshness": {"hours_since_pipeline": 20.0}}
    _serve(monkeypatch, body=fresh)
    assert ops.check("https://lab.example.com/") == []


@pytest.mark.parametrize(
    ("kwargs", "problem"),
    [
        ({"body": {"status": "ready", "data_freshness": {"hours_since_pipeline": 50.0}}}, "stale"),
        ({"body": {"status": "ready", "data_freshness": {}}}, "never run"),
        ({"health": 503, "ready": 503}, "/readyz answered 503"),
        ({"body": {"status": "starting"}}, "readiness is 'starting'"),
    ],
)
def test_check_reports_problems(monkeypatch, kwargs, problem):
    _serve(monkeypatch, **kwargs)
    assert any(problem in item for item in ops.check("https://lab.example.com"))


def test_check_reports_an_unreachable_host(monkeypatch):
    import requests

    _serve(monkeypatch, error=requests.ConnectionError("refused"))
    assert ops.check("https://lab.example.com") == ["unreachable: ConnectionError"]


def test_readiness_reports_pipeline_freshness(monkeypatch, tmp_path):
    from nba_insights.api import deps

    monkeypatch.setattr(deps, "DATA_DIR", tmp_path)
    assert deps.pipeline_freshness(NOW)["stale"] is True  # never ran
    (tmp_path / "pipeline.jsonl").write_text(
        json.dumps({"finished_at": "2026-11-01T06:00:00+00:00", "alerts": ["x"]}) + "\n"
    )
    freshness = deps.pipeline_freshness(NOW)
    assert freshness == {
        "last_pipeline_run": "2026-11-01T06:00:00+00:00",
        "hours_since_pipeline": 24.0,
        "stale": False,
        "last_run_alerts": 1,
    }
    assert deps.pipeline_freshness(NOW + timedelta(days=1))["stale"] is True


def test_error_events_are_scrubbed_of_secrets_and_queries():
    event = {
        "request": {
            "url": "https://lab.example.com/compare?names=Alice",
            "query_string": "names=Alice",
            "cookies": {"session": "s"},
            "headers": {"X-API-Key": "secret", "Authorization": "Bearer t", "Accept": "json"},
        }
    }
    scrubbed = observability.scrub_event(event)["request"]
    assert scrubbed == {"url": "https://lab.example.com/compare", "headers": {"Accept": "json"}}


def test_error_tracking_is_off_without_a_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert observability.init_error_tracking() is False
    observability.capture_exception(ValueError("ignored"))  # no-op, no error


def test_sqlite_backup_api_reads_a_live_wal_database(data, tmp_path):
    # a writer holding an open transaction must not block or corrupt the backup
    writer = sqlite3.connect(data["cache_db"])
    writer.execute("BEGIN")
    writer.execute(
        "INSERT INTO cache_entries (key, fetched_at, payload) VALUES ('v3:x', '2026', x'00')"
    )
    try:
        record = ops.backup(tmp_path / "backups", now=NOW, **data)
    finally:
        writer.rollback()
        writer.close()
    assert record["files"]["cache.sqlite3"]["quick_check"] == "ok"
