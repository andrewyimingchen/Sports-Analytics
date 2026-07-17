"""Backfill play-by-play logs (and rotations) for whole seasons.

    uv run python -m nba_insights.pbp.backfill --seasons 2022-23 2023-24

Fetches each game's play-by-play and rotation intervals. ~1,230 games per
season at the client's rate limit (~0.6s/request) is roughly 30 minutes
per season cold (two requests per game); already-cached games are
skipped, so re-runs are cheap and interrupted runs resume where they
left off — a corpus backfilled before rotations existed only fetches the
rotation half.
"""

from __future__ import annotations

import argparse
import logging

from nba_insights.config import current_season
from nba_insights.ingest import NBAClient

logger = logging.getLogger(__name__)


# A fetch kind is abandoned for the season once most of a meaningful
# sample has failed: a whole season without rotation data upstream trips
# this in ~30 games instead of retrying 1,200 times with backoff, while
# scattered per-game gaps (a handful of games simply have no rotation
# rows) never do.
_BREAKER_MIN_ATTEMPTS = 30
_BREAKER_FAILURE_RATE = 0.5


class _Breaker:
    def __init__(self) -> None:
        self.attempts = 0
        self.failures = 0

    def record(self, ok: bool) -> None:
        self.attempts += 1
        self.failures += not ok

    @property
    def tripped(self) -> bool:
        return (
            self.attempts >= _BREAKER_MIN_ATTEMPTS
            and self.failures / self.attempts > _BREAKER_FAILURE_RATE
        )


def backfill_season(client: NBAClient, season: str, limit: int | None = None) -> int:
    """Fetch (or confirm cached) PBP and rotations for every game of a season."""
    game_ids = sorted(client.team_games(season)["GAME_ID"].unique())
    if limit:
        game_ids = game_ids[:limit]
    failures = 0
    breakers = {"PBP": _Breaker(), "rotation": _Breaker()}
    for i, game_id in enumerate(game_ids, 1):
        for label, fetch in (("PBP", client.play_by_play), ("rotation", client.game_rotation)):
            if breakers[label].tripped:
                continue
            try:
                fetch(game_id)
                breakers[label].record(ok=True)
            except Exception as e:
                failures += 1
                breakers[label].record(ok=False)
                logger.warning("%s failed for %s: %s", label, game_id, e)
                if breakers[label].tripped:
                    logger.warning(
                        "%s: %s mostly failing (%d of %d) — skipping it for the rest "
                        "of the season (likely unavailable upstream)",
                        season, label, breakers[label].failures, breakers[label].attempts,
                    )
        if i % 100 == 0:
            logger.info("%s: %d/%d games", season, i, len(game_ids))
    logger.info("%s done: %d games, %d failures", season, len(game_ids), failures)
    return failures


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Backfill play-by-play logs")
    parser.add_argument("--seasons", nargs="+", default=[current_season()])
    parser.add_argument("--limit", type=int, default=None, help="games per season (for testing)")
    parser.add_argument(
        "--delay", type=float, default=3.0,
        help="seconds between requests (default 3.0 — the rotation endpoint "
        "serves empty responses when hit faster, and tar-pits to ~20s per "
        "request regardless, so a historical season is an overnight run)",
    )
    args = parser.parse_args()

    client = NBAClient(delay=args.delay)
    total_failures = sum(backfill_season(client, s, args.limit) for s in args.seasons)
    if total_failures:
        raise SystemExit(f"{total_failures} games failed")


if __name__ == "__main__":
    main()
