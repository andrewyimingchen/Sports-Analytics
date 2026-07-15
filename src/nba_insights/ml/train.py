"""Train all models and report holdout metrics.

    uv run python -m nba_insights.ml.train [--train-seasons 3]

Trains on the N completed seasons before the current one, evaluates on the
current season (a true temporal holdout), then refits nothing — the shipped
models are the ones whose numbers were printed. Artifacts land in
data/models/ and are loaded by the app's Predictions page.
"""

from __future__ import annotations

import argparse
import logging

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
    parser = argparse.ArgumentParser(description="Train NBA Insights models")
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
    outcome = GameOutcomeModel().fit(train_matchups)
    metrics = outcome.evaluate(test_matchups)
    logger.info("game outcome (holdout %s): %s", test_season, metrics)
    outcome.save(OUTCOME_PATH)

    logger.info("building player-game frames…")
    train_players = build_player_frames(client, train_seasons)
    test_players = build_player_frames(client, [test_season])
    points = PlayerPointsModel().fit(train_players)
    metrics = points.evaluate(test_players)
    logger.info("player points (holdout %s): %s", test_season, metrics)
    points.save(POINTS_PATH)

    curve = WinCurve().fit(
        pd.concat([client.team_games(s) for s in train_seasons], ignore_index=True)
    )
    logger.info("win curve slope: %.4f win%% per net point", curve.slope)
    curve.save(WIN_CURVE_PATH)

    logger.info("models saved to %s", MODELS_DIR)


if __name__ == "__main__":
    main()
