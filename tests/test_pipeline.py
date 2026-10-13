"""Nightly pipeline orchestration: steps, cadence, alerts, and the run log."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from nba_insights import pipeline
from nba_insights.errors import UpstreamError

NOW = datetime(2026, 11, 2, 6, 0, tzinfo=UTC)


@pytest.fixture
def stubbed(monkeypatch, tmp_path):
    calls: list[str] = []
    monkeypatch.setattr(pipeline, "warm", lambda client, top: calls.append("warm") or 0)
    monkeypatch.setattr(
        pipeline, "backfill_season", lambda client, season: calls.append("pbp") or 0
    )
    monkeypatch.setattr(
        pipeline,
        "run_training",
        lambda client: calls.append("retrain") or {"outcome": {"log_loss": 0.59, "accuracy": 0.70}},
    )
    monkeypatch.setattr(
        pipeline,
        "load_manifest",
        lambda: {"runs": {"train": {"recorded_at": "2026-10-30T00:00:00+00:00"}}},
    )
    outcome = tmp_path / "outcome.joblib"
    outcome.write_text("model")
    metrics = tmp_path / "metrics.json"
    metrics.write_text(json.dumps({"outcome": {"log_loss": 0.59}}))
    monkeypatch.setattr(pipeline, "OUTCOME_PATH", outcome)
    monkeypatch.setattr(pipeline, "METRICS_PATH", metrics)
    monkeypatch.setattr(pipeline.GameOutcomeModel, "load", classmethod(lambda cls, path: "model"))
    verdict = {"status": "ok"}
    monkeypatch.setattr(
        pipeline,
        "drift_report",
        lambda client, model, reference: (
            calls.append("drift") or {"season": "2026-27", "drift": dict(verdict)}
        ),
    )
    return calls, verdict, tmp_path


def _run(tmp_path, **kwargs):
    return pipeline.run_pipeline(object(), now=NOW, drift_path=tmp_path / "drift.json", **kwargs)


def test_nightly_run_warms_skips_recent_retrain_and_writes_drift(stubbed):
    calls, _, tmp_path = stubbed
    run = _run(tmp_path)
    assert calls == ["warm", "drift"]  # trained 3 days ago: retrain skipped, no pbp
    assert [(s.name, s.status) for s in run.steps] == [
        ("warm", "ok"),
        ("retrain", "skipped"),
        ("drift", "ok"),
    ]
    assert run.alerts == []
    report = json.loads((tmp_path / "drift.json").read_text())
    assert report["generated_at"] == NOW.isoformat(timespec="seconds")


def test_retrain_runs_when_due_and_pbp_when_asked(stubbed):
    calls, _, tmp_path = stubbed
    run = _run(tmp_path, pbp=True, retrain_days=2)
    assert calls == ["warm", "pbp", "retrain", "drift"]
    retrain = next(s for s in run.steps if s.name == "retrain")
    assert retrain.status == "ok" and "0.590" in retrain.detail


def test_failed_steps_and_drift_raise_alerts_without_stopping_the_run(stubbed, monkeypatch):
    calls, verdict, tmp_path = stubbed

    def down(client, top):
        raise UpstreamError("stats.nba.com down")

    monkeypatch.setattr(pipeline, "warm", down)
    verdict.update(status="drift", recent_log_loss=0.71, threshold=0.65)
    run = _run(tmp_path)
    assert [(s.name, s.status) for s in run.steps][0] == ("warm", "failed")
    assert "drift" in calls  # later steps still ran
    assert len(run.alerts) == 2
    assert "warm failed (upstream_unavailable" in run.alerts[0]
    assert "recent log loss 0.710 > threshold 0.650" in run.alerts[1]


def test_defects_propagate_instead_of_being_recorded(stubbed, monkeypatch):
    _, _, tmp_path = stubbed
    monkeypatch.setattr(pipeline, "warm", lambda client, top: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        _run(tmp_path)


def test_retrain_due_rules():
    assert pipeline.retrain_due(None, NOW, 7)
    recent = {"runs": {"train": {"recorded_at": "2026-10-30T00:00:00+00:00"}}}
    assert not pipeline.retrain_due(recent, NOW, 7)
    assert pipeline.retrain_due(recent, NOW, 0)


def test_run_log_appends_and_webhook_posts(stubbed, monkeypatch):
    _, _, tmp_path = stubbed
    run = _run(tmp_path)
    log = tmp_path / "pipeline.jsonl"
    pipeline.append_run_log(run, log)
    pipeline.append_run_log(run, log)
    lines = log.read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["steps"][0]["name"] == "warm"

    posted = []

    class Response:
        def raise_for_status(self):
            pass

    import requests

    monkeypatch.setattr(
        requests, "post", lambda url, json, timeout: posted.append(json) or Response()
    )
    assert not pipeline.send_alert(run, webhook="https://hooks.example/x")  # no alerts
    run.alerts.append("drift")
    assert pipeline.send_alert(run, webhook="https://hooks.example/x")
    assert posted == [{"text": "POSSESSION LAB pipeline: drift"}]
    monkeypatch.delenv(pipeline.WEBHOOK_ENV, raising=False)
    assert not pipeline.send_alert(run)  # no webhook configured


def test_a_degraded_streak_alerts_but_one_bad_night_does_not():
    def run_with(status):
        run = pipeline.Run(started_at="x")
        run.steps.append(pipeline.Step("warm", status, "5 failed fetches"))
        return run

    degraded = {"steps": [{"name": "warm", "status": "degraded"}]}
    healthy = {"steps": [{"name": "warm", "status": "ok"}]}

    one_night = run_with("degraded")
    pipeline.add_persistence_alerts(one_night, [healthy, healthy])
    assert one_night.alerts == []

    streak = run_with("degraded")
    pipeline.add_persistence_alerts(streak, [degraded, degraded])
    assert streak.alerts == ["warm degraded or failed 3 runs in a row (5 failed fetches)"]

    new_install = run_with("degraded")
    pipeline.add_persistence_alerts(new_install, [degraded])  # not enough history yet
    assert new_install.alerts == []


def test_recent_runs_skips_unreadable_lines(tmp_path):
    log = tmp_path / "pipeline.jsonl"
    log.write_text('{"steps": []}\nnot json\n{"steps": [1]}\n')
    assert pipeline.recent_runs(log, n=3) == [{"steps": []}, {"steps": [1]}]
    assert pipeline.recent_runs(tmp_path / "missing.jsonl") == []


def test_backup_step_runs_when_a_destination_is_given(stubbed, monkeypatch):
    calls, _, tmp_path = stubbed
    monkeypatch.setattr(
        pipeline, "backup", lambda dest: calls.append("backup") or {"path": str(dest), "files": {}}
    )
    run = _run(tmp_path, backup_dest=tmp_path / "backups")
    assert calls[-1] == "backup"
    assert run.steps[-1].name == "backup" and run.steps[-1].status == "ok"
