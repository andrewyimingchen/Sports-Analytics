"""Model manifest: run records, artifact verification, sources, and README sync."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from nba_insights.ml import manifest
from nba_insights.store import Cache

ROOT = Path(__file__).resolve().parent.parent


def _record(tmp_path: Path, run: str = "season_backtest", **overrides) -> dict:
    kwargs = {
        "configuration": {"n_sims_per_season": 1000},
        "data": {"seasons": ["2024-25"]},
        "models": {"season_forecast": manifest.MODEL_VERSIONS["season_forecast"]},
        "metrics": {"record": {"mae": 9.0, "baseline_mae": 11.0}},
        "sources": {"status": "not_recorded"},
        "models_dir": tmp_path / "models",
        "path": tmp_path / "manifest.json",
        "command": ["python", "-m", "nba_insights.ml.backtest"],
        "recorded_at": "2026-07-22T00:00:00+00:00",
        "code": {"package_version": "0.1.0", "git_commit": "abc", "git_dirty": False},
    }
    kwargs.update(overrides)
    return manifest.record_run(run, **kwargs)


def test_record_run_hashes_artifacts_and_keeps_other_runs(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "season_forecast_metrics.json").write_text('{"a": 1}')
    _record(tmp_path)
    written = _record(
        tmp_path,
        run="player_backtest",
        models={"player_season": manifest.MODEL_VERSIONS["player_season"]},
        metrics={"pts_mae": 2.7},
    )

    assert set(written["runs"]) == {"season_backtest", "player_backtest"}
    season = written["runs"]["season_backtest"]
    assert season["artifacts"]["season_forecast_metrics.json"]["bytes"] == 8
    assert len(season["artifacts"]["season_forecast_metrics.json"]["sha256"]) == 64
    assert season["command"] == "python -m nba_insights.ml.backtest"
    assert season["feature_schema"] is None
    # an artifact the run should have written but did not is explicit
    player = written["runs"]["player_backtest"]
    assert player["artifacts"]["player_season_metrics.json"] == {"status": "missing"}
    assert json.loads((tmp_path / "manifest.json").read_text()) == written


def test_train_run_records_the_feature_schema(tmp_path):
    written = _record(
        tmp_path,
        run="train",
        models={"outcome": manifest.MODEL_VERSIONS["outcome"]},
    )
    schema = written["runs"]["train"]["feature_schema"]
    assert schema == manifest.feature_schema()
    assert "elo_diff" in schema["outcome"]
    assert len(schema["fingerprint"]) == 16


def test_unknown_run_is_rejected(tmp_path):
    with pytest.raises(KeyError):
        _record(tmp_path, run="nope")


def test_verify_artifacts_reports_match_mismatch_and_missing(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    for name in manifest.RUN_ARTIFACTS["train"]:
        (models / name).write_bytes(name.encode())
    recorded = _record(tmp_path, run="train", models={})

    assert manifest.verify_artifacts(recorded, models) == {
        "status": "verified",
        "artifacts": dict.fromkeys(manifest.RUN_ARTIFACTS["train"], "match"),
    }
    (models / "outcome.joblib").write_bytes(b"retrained")
    (models / "points.joblib").unlink()
    result = manifest.verify_artifacts(recorded, models)
    assert result["status"] == "drift"
    assert result["artifacts"]["outcome.joblib"] == "mismatch"
    assert result["artifacts"]["points.joblib"] == "missing"
    assert manifest.verify_artifacts(None, models)["status"] == "manifest_missing"


def test_verify_marks_artifacts_without_a_recorded_hash(tmp_path):
    recorded = _record(tmp_path)  # nothing written, so the artifact is recorded missing
    result = manifest.verify_artifacts(recorded, tmp_path / "models")
    assert result == {
        "status": "drift",
        "artifacts": {"season_forecast_metrics.json": "not_recorded"},
    }


def test_source_snapshots_fingerprint_what_the_run_read(tmp_path):
    cache = Cache(tmp_path / "cache.sqlite3")
    frame = pd.DataFrame({"TEAM": ["A", "B"], "PTS": [100, 101]})
    cache.get_or_fetch("teams/2025-26", lambda: frame)
    cache.get_or_fetch("teams/2024-25", lambda: frame.iloc[:1])
    cache.put("unread/key", frame)

    sources = manifest.source_snapshots(cache)

    assert sources["status"] == "recorded"
    assert [s["key"] for s in sources["snapshots"]] == ["teams/2024-25", "teams/2025-26"]
    assert sources["snapshots"][1]["rows"] == 2
    assert sources["snapshots"][1]["fingerprint"] == manifest.frame_fingerprint(frame)
    # same content read through a fresh cache yields the same fingerprint
    again = Cache(tmp_path / "cache.sqlite3")
    again.get_or_fetch("teams/2025-26", lambda: pytest.fail("should be cached"))
    again.get_or_fetch("teams/2024-25", lambda: pytest.fail("should be cached"))
    assert manifest.source_snapshots(again)["fingerprint"] == sources["fingerprint"]


def test_frame_fingerprint_changes_with_content():
    frame = pd.DataFrame({"PTS": [1, 2]})
    assert manifest.frame_fingerprint(frame) == manifest.frame_fingerprint(frame.copy())
    assert manifest.frame_fingerprint(frame) != manifest.frame_fingerprint(frame.assign(PTS=[1, 3]))


def test_backfill_marks_unknown_provenance(tmp_path):
    models = tmp_path / "models"
    models.mkdir()
    (models / "player_season_metrics.json").write_text(
        json.dumps(
            {
                "version": "player-season-v1",
                "generated_at": "2026-07-22T15:21:25+00:00",
                "source_season": "2024-25",
                "holdout_season": "2025-26",
                "population": "returners",
                "metrics": {"players": 241, "pts_mae": 2.68},
            }
        )
    )
    written = manifest.backfill(models, tmp_path / "manifest.json")
    run = written["runs"]["player_backtest"]
    assert set(written["runs"]) == {"player_backtest"}
    assert run["sources"]["status"] == "not_recorded"
    assert run["code"]["git_commit"] is None
    assert run["recorded_at"] == "2026-07-22T15:21:25+00:00"
    assert manifest.verify_artifacts(written, models)["status"] == "verified"


def test_readme_table_renders_gaps_explicitly():
    table = manifest.render_readme_table(None)
    assert table.count("not recorded") == 3
    assert "updated never" in table


def test_sync_readme_detects_a_stale_table(tmp_path):
    readme = tmp_path / "README.md"
    readme.write_text(f"intro\n{manifest.README_START}\nold\n{manifest.README_END}\noutro\n")
    assert manifest.sync_readme(readme, None, check=True) is False
    manifest.sync_readme(readme, None)
    assert manifest.sync_readme(readme, None, check=True) is True
    assert readme.read_text().startswith("intro\n") and readme.read_text().endswith("outro\n")


def test_repository_readme_matches_the_tracked_manifest():
    tracked = manifest.load_manifest(ROOT / "models" / "manifest.json")
    assert tracked is not None, "models/manifest.json must be committed"
    assert tracked["schema_version"] == manifest.SCHEMA_VERSION
    assert manifest.sync_readme(ROOT / "README.md", tracked, check=True), (
        f"README metrics table is stale: run `{manifest.README_COMMAND}`"
    )
