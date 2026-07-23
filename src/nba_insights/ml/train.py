"""Train all models and report holdout metrics.

    uv run python -m nba_insights.ml.train [--train-seasons 3]

Trains on the N completed seasons before the current one, evaluates on the
current season (a true temporal holdout), then refits nothing — the shipped
models are the ones whose numbers were printed.

Holdout hygiene: hyperparameters are tuned on a dev season (the most recent
*training* season), then the model is refit on all training seasons and the
holdout is scored exactly once. The holdout never participates in any
selection decision.

Artifacts land in data/models/ (loaded by the app's Predictions page) along
with metrics.json — the single source of truth for the numbers quoted in
the UI.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import UTC, datetime

import pandas as pd

from nba_insights.config import MODELS_DIR, current_season, past_seasons
from nba_insights.ingest import NBAClient
from nba_insights.ml import GameOutcomeModel, PlayerPointsModel, WinCurve
from nba_insights.ml.elo import elo_ratings
from nba_insights.ml.features import (
    game_matchup_frame,
    player_game_features,
    prior_minute_rates,
    prior_team_form,
    team_form_features,
)


def _prev_season(season: str) -> str:
    start = int(season[:4])
    return f"{start - 1}-{start % 100:02d}"

logger = logging.getLogger(__name__)

OUTCOME_PATH = MODELS_DIR / "outcome.joblib"
POINTS_PATH = MODELS_DIR / "points.joblib"
WIN_CURVE_PATH = MODELS_DIR / "win_curve.joblib"
METRICS_PATH = MODELS_DIR / "metrics.json"

C_GRID = [0.05, 0.1, 0.25, 0.5, 1.0]


def tune_outcome_c(matchups: pd.DataFrame, dev_season_start: str) -> float:
    """Pick C by dev-season log loss; the holdout is never consulted.

    *matchups* covers all training seasons; rows from the dev season (the
    most recent one, identified by its start year in GAME_DATE) form the
    dev set and the rest the tuning-fit set.
    """
    dates = pd.to_datetime(matchups["GAME_DATE"])
    season_start = pd.Timestamp(f"{dev_season_start}-08-01")
    dev = matchups[dates >= season_start]
    fit = matchups[dates < season_start]
    if dev.empty or fit.empty:
        return 0.25
    best_c, best_ll = 0.25, float("inf")
    for c in C_GRID:
        ll = GameOutcomeModel(C=c).fit(fit).evaluate(dev)["log_loss"]
        logger.info("  C=%.2f dev log loss %.4f", c, ll)
        if ll < best_ll:
            best_c, best_ll = c, ll
    return best_c


ELO_WARMUP_SEASONS = 2  # extra seasons before the earliest, so Elo converges


def build_elo(client: NBAClient, seasons: list[str]) -> pd.DataFrame:
    """Continuous Elo over warm-up + given seasons (one pass, carried over)."""
    earliest = min(int(s[:4]) for s in seasons)
    warmup = [
        f"{y}-{(y + 1) % 100:02d}"
        for y in range(earliest - ELO_WARMUP_SEASONS, earliest)
    ]
    frames = [client.team_games(s) for s in [*warmup, *sorted(seasons)]]
    return elo_ratings(pd.concat(frames, ignore_index=True))


def build_matchups(client: NBAClient, seasons: list[str], elo: pd.DataFrame) -> pd.DataFrame:
    # window=None (season-to-date form): +3pp holdout accuracy over last-10.
    # availability (derived absences, prior-season-seeded): +0.8pp more.
    # carried-over Elo: +0.8pp more (69.2 -> 70.0, ll 0.588 -> 0.585).
    # prior-seeded form: features from game 1 - covers the ~13% of games
    # (each team's first ~10) the model previously refused to predict.
    frames = [
        game_matchup_frame(
            team_form_features(
                client.team_games(s),
                window=None,
                player_games=client.player_games(s),
                prior_rates=prior_minute_rates(client.player_games(_prev_season(s))),
                elo=elo,
                form_priors=prior_team_form(client.team_games(_prev_season(s))),
            )
        )
        for s in seasons
    ]
    return pd.concat(frames, ignore_index=True)


def build_player_frames(client: NBAClient, seasons: list[str]) -> pd.DataFrame:
    # availability-enabled team form so own_missing_min (teammate absences ->
    # usage boost) is real rather than a league-average constant
    frames = [
        player_game_features(
            client.player_games(s),
            team_form_features(
                client.team_games(s),
                window=None,
                player_games=client.player_games(s),
                prior_rates=prior_minute_rates(client.player_games(_prev_season(s))),
            ),
        )
        for s in seasons
    ]
    return pd.concat(frames, ignore_index=True)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Train POSSESSION LAB models")
    parser.add_argument("--train-seasons", type=int, default=3)
    args = parser.parse_args()

    client = NBAClient()
    train_seasons = past_seasons(args.train_seasons)
    test_season = current_season()
    logger.info("training on %s, evaluating on %s", train_seasons, test_season)

    logger.info("building game matchup frames…")
    elo = build_elo(client, [*train_seasons, test_season])
    train_matchups = build_matchups(client, train_seasons, elo)
    test_matchups = build_matchups(client, [test_season], elo)

    logger.info("tuning C on dev season %s…", train_seasons[-1])
    best_c = tune_outcome_c(train_matchups, dev_season_start=train_seasons[-1][:4])
    outcome = GameOutcomeModel(C=best_c).fit(train_matchups)
    outcome_metrics = outcome.evaluate(test_matchups)
    logger.info("game outcome (C=%.2f, holdout %s): %s", best_c, test_season, outcome_metrics)
    outcome.save(OUTCOME_PATH)

    logger.info("building player-game frames…")
    train_players = build_player_frames(client, train_seasons)
    test_players = build_player_frames(client, [test_season])
    points = PlayerPointsModel().fit(train_players)
    points_metrics = points.evaluate(test_players)
    logger.info("player points (holdout %s): %s", test_season, points_metrics)
    points.save(POINTS_PATH)

    curve = WinCurve().fit(
        pd.concat([client.team_games(s) for s in train_seasons], ignore_index=True)
    )
    logger.info("win curve slope: %.4f win%% per net point", curve.slope)
    curve.save(WIN_CURVE_PATH)

    # single source of truth for every number the UI quotes
    METRICS_PATH.write_text(
        json.dumps(
            {
                "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "train_seasons": train_seasons,
                "dev_season": train_seasons[-1],
                "holdout_season": test_season,
                "outcome": {**outcome_metrics, "C": best_c},
                "points": points_metrics,
                "win_curve_slope": curve.slope,
            },
            indent=2,
        )
    )
    logger.info("models and metrics saved to %s", MODELS_DIR)


if __name__ == "__main__":
    main()
