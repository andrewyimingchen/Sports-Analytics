"""Stable-roster historical holdout for next-season player stat projections."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from nba_insights.analysis import (
    evaluate_player_season_holdout,
    project_player_seasons,
)
from nba_insights.analysis.salaries import normalize_name
from nba_insights.config import MODELS_DIR
from nba_insights.ingest import NBAClient

PLAYER_SEASON_METRICS_PATH = MODELS_DIR / "player_season_metrics.json"


def run_player_backtest(client: NBAClient, source_season: str, target_season: str) -> dict:
    source = client.league_player_stats(source_season)
    target = client.league_player_stats(target_season)
    source = source.assign(_KEY=source["PLAYER_NAME"].map(normalize_name))
    target = target.assign(_KEY=target["PLAYER_NAME"].map(normalize_name))
    stable = source.merge(
        target[["_KEY", "TEAM_ABBREVIATION"]],
        on="_KEY",
        suffixes=("", "_TARGET"),
    )
    stable = stable[
        stable["TEAM_ABBREVIATION"].eq(stable["TEAM_ABBREVIATION_TARGET"])
        & stable["GP"].ge(20)
        & stable["MIN"].ge(8)
    ].copy()
    roster = pd.DataFrame(
        {
            "TEAM": stable["TEAM_ABBREVIATION"],
            "PLAYER_NAME": stable["PLAYER_NAME"],
            "SOURCE_TEAM": stable["TEAM_ABBREVIATION"],
            "STATUS": "returning",
            "HAS_HISTORY": True,
            "AGE": stable["AGE"] + 1,
            "GP": stable["GP"],
            "SALARY": pd.NA,
            "PROJECTED_MIN": stable["MIN"],
            "CURRENT_IMPACT": 0.0,
            "AGE_ADJUSTMENT": 0.0,
            "PROJECTED_IMPACT": 0.0,
        }
    )
    projected = project_player_seasons(source, roster)
    return {
        "version": "player-season-v1",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_season": source_season,
        "holdout_season": target_season,
        "population": "same-team returners with 20+ games and 8+ minutes in source",
        "metrics": evaluate_player_season_holdout(projected, target),
        "awards_validation": (
            "Award fields are field-size normalized (1 MVP, 1 DPOY, 24 All-Stars) "
            "but not historically outcome-calibrated; displayed as comparative scores."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="2024-25")
    parser.add_argument("--target", default="2025-26")
    parser.add_argument("--output", type=Path, default=PLAYER_SEASON_METRICS_PATH)
    args = parser.parse_args()
    artifact = run_player_backtest(NBAClient(), args.source, args.target)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(artifact, indent=2))


if __name__ == "__main__":
    main()
