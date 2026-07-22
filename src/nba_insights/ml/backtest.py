"""Reproducible, time-safe season forecast backtest.

Run with::

    uv run python -m nba_insights.ml.backtest --seasons 2024-25 2025-26

Each target season is forecast only from the immediately preceding regular
season. The resulting registry artifact is consumed by the Methodology page.
"""

from __future__ import annotations

import argparse
import json
import zlib
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from nba_insights.analysis import evaluate_season_forecasts, scoreboard, season_forecast
from nba_insights.config import MODELS_DIR
from nba_insights.ingest import NBAClient
from nba_insights.ml.elo import current_elo
from nba_insights.ml.features import team_form_snapshot

SEASON_FORECAST_METRICS_PATH = MODELS_DIR / "season_forecast_metrics.json"
DEFAULT_SEASONS = ["2024-25", "2025-26"]


def _previous_season(season: str, count: int = 1) -> str:
    start = int(season[:4]) - count
    return f"{start}-{(start + 1) % 100:02d}"


def _conference_map(client: NBAClient, basis_season: str) -> dict[str, str]:
    standings = client.standings(basis_season)
    games = client.team_games(basis_season)
    team_ids = (
        games[["TEAM_ID", "TEAM_ABBREVIATION"]]
        .dropna()
        .drop_duplicates("TEAM_ID", keep="last")
        .set_index("TEAM_ID")["TEAM_ABBREVIATION"]
        .to_dict()
    )
    return {
        str(team_ids[row.TeamID]): str(row.Conference)
        for row in standings[["TeamID", "Conference"]].itertuples(index=False)
        if row.TeamID in team_ids
    }


def _forecast_snapshot(client: NBAClient, prior_season: str) -> pd.DataFrame:
    snapshot = team_form_snapshot(client.team_games(prior_season))
    elo_seasons = [_previous_season(prior_season, 2), _previous_season(prior_season), prior_season]
    elo_games = pd.concat([client.team_games(season) for season in elo_seasons], ignore_index=True)
    snapshot["elo"] = current_elo(elo_games).reindex(snapshot.index)
    return snapshot


def _actual_outcomes(client: NBAClient, season: str) -> tuple[pd.DataFrame, str, str]:
    games = client.team_games(season)
    records = (
        games.assign(ACTUAL_WIN=games["WL"].eq("W").astype(int))
        .groupby("TEAM_ABBREVIATION", as_index=False)
        .agg(ACTUAL_WINS=("ACTUAL_WIN", "sum"))
        .rename(columns={"TEAM_ABBREVIATION": "TEAM"})
    )
    board = scoreboard(client.schedule(season))
    playoff_games = board[
        board["GAME_ID"].str.startswith("004") & board["STATUS"].eq("Final")
    ]
    playoff_teams = set(playoff_games["HOME"]) | set(playoff_games["AWAY"])
    if playoff_games.empty:
        raise ValueError(f"no completed playoff games for {season}")
    champion = str(playoff_games.sort_values("GAME_DATE").iloc[-1]["WINNER"])
    cup_games = board[
        board["GAME_ID"].str.startswith("006") & board["STATUS"].eq("Final")
    ]
    if cup_games.empty:
        raise ValueError(f"no completed NBA Cup final for {season}")
    cup_champion = str(cup_games.sort_values("GAME_DATE").iloc[-1]["WINNER"])
    records["MADE_PLAYOFFS"] = records["TEAM"].isin(playoff_teams).astype(int)
    records["WON_CHAMPIONSHIP"] = records["TEAM"].eq(champion).astype(int)
    records["WON_CUP"] = records["TEAM"].eq(cup_champion).astype(int)
    return records, champion, cup_champion


def run_backtest(
    client: NBAClient,
    seasons: list[str],
    *,
    n_sims: int = 5_000,
) -> dict:
    rows = []
    cutoffs = {}
    outcomes = {}
    conferences = _conference_map(client, seasons[-1])
    for season in seasons:
        prior = _previous_season(season)
        prior_games = client.team_games(prior)
        snapshot = _forecast_snapshot(client, prior)
        forecast = season_forecast(
            snapshot,
            conferences,
            n_sims=n_sims,
            seed=zlib.crc32(f"backtest|{season}|{n_sims}".encode()),
        )
        actual, champion, cup_champion = _actual_outcomes(client, season)
        joined = forecast.merge(actual, on="TEAM", validate="one_to_one")
        if len(joined) != 30:
            raise ValueError(f"{season} joined only {len(joined)} teams")
        joined["SEASON"] = season
        rows.append(joined)
        cutoffs[season] = pd.to_datetime(prior_games["GAME_DATE"]).max().date().isoformat()
        outcomes[season] = {"champion": champion, "nba_cup_champion": cup_champion}
    frame = pd.concat(rows, ignore_index=True)
    return {
        "version": "season-forecast-v2-roster",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "forecast_timing": "previous regular season complete; no target-season games",
        "n_sims_per_season": n_sims,
        "data_cutoffs": cutoffs,
        "outcomes": outcomes,
        "metrics": evaluate_season_forecasts(frame),
        "component_validation": {
            "base_simulator": (
                "Historical evaluation above uses only the prior completed regular season."
            ),
            "roster_overlay": {
                "version": "roster-minutes-v1",
                "status": "prospective; not separately historically calibrated",
                "reason": (
                    "Versioned historical offseason contract/roster snapshots are not "
                    "available in the local corpus. Using end-of-target-season rosters "
                    "would leak future transactions and roles, so the backtest refuses "
                    "that shortcut. Pure transformation and integration tests are recorded."
                ),
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the league season forecast")
    parser.add_argument("--seasons", nargs="+", default=DEFAULT_SEASONS)
    parser.add_argument("--n-sims", type=int, default=5_000)
    parser.add_argument("--output", type=Path, default=SEASON_FORECAST_METRICS_PATH)
    args = parser.parse_args()
    artifact = run_backtest(NBAClient(), args.seasons, n_sims=args.n_sims)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2) + "\n")
    print(json.dumps(artifact, indent=2))


if __name__ == "__main__":
    main()
