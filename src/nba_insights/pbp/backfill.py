"""Backfill play-by-play logs for whole seasons into the cache.

    uv run python -m nba_insights.pbp.backfill --seasons 2022-23 2023-24

~1,230 games per season at the client's rate limit (~0.6s/request) is
roughly 15 minutes per season cold; already-cached games are skipped, so
re-runs are cheap and interrupted runs resume where they left off.
"""

from __future__ import annotations

import argparse
import logging

from nba_insights.config import current_season
from nba_insights.ingest import NBAClient

logger = logging.getLogger(__name__)


def backfill_season(client: NBAClient, season: str, limit: int | None = None) -> int:
    """Fetch (or confirm cached) PBP for every game of a season."""
    game_ids = sorted(client.team_games(season)["GAME_ID"].unique())
    if limit:
        game_ids = game_ids[:limit]
    failures = 0
    for i, game_id in enumerate(game_ids, 1):
        try:
            client.play_by_play(game_id)
        except Exception as e:
            failures += 1
            logger.warning("PBP failed for %s: %s", game_id, e)
        if i % 100 == 0:
            logger.info("%s: %d/%d games", season, i, len(game_ids))
    logger.info("%s done: %d games, %d failures", season, len(game_ids), failures)
    return failures


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Backfill play-by-play logs")
    parser.add_argument("--seasons", nargs="+", default=[current_season()])
    parser.add_argument("--limit", type=int, default=None, help="games per season (for testing)")
    args = parser.parse_args()

    client = NBAClient()
    total_failures = sum(backfill_season(client, s, args.limit) for s in args.seasons)
    if total_failures:
        raise SystemExit(f"{total_failures} games failed")


if __name__ == "__main__":
    main()
