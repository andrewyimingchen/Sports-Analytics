"""Cache warmer: prefetch the current season so first page views are instant.

Run nightly (cron, Task Scheduler) or ad hoc:

    uv run python -m nba_insights.warm --top 20

Warms the league dashboard and standings, then career stats, game logs, and
shot charts for the top N players by minutes per game. The cache lives
wherever the app reads it (``NBA_INSIGHTS_DATA_DIR``, default ``data/``), so
run this from the same directory you run Streamlit from.
"""

from __future__ import annotations

import argparse
import logging
import sys

from nba_insights.ingest import NBAClient

logger = logging.getLogger(__name__)


def warm(client: NBAClient, top: int = 20) -> int:
    """Prefetch league-wide data plus the *top* players by minutes.

    Returns the number of failed fetches (0 means fully warm). Failures are
    logged and skipped so one bad player ID can't abort the run.
    """
    failures = 0

    league = client.league_player_stats()
    client.standings()

    leaders = league.sort_values("MIN", ascending=False).head(top)
    for _, row in leaders.iterrows():
        player_id, name = int(row["PLAYER_ID"]), row["PLAYER_NAME"]
        for label, fetch in [
            ("career", client.career_stats),
            ("game log", client.game_log),
            ("shot chart", client.shot_chart),
        ]:
            try:
                fetch(player_id)
            except Exception as e:
                failures += 1
                logger.warning("skipping %s for %s: %s", label, name, e)
        logger.info("warmed %s", name)
    return failures


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Prefetch NBA data into the local cache")
    parser.add_argument("--top", type=int, default=20, help="players to warm, by minutes per game")
    args = parser.parse_args()

    failures = warm(NBAClient(), top=args.top)
    if failures:
        logger.warning("done with %d failed fetches", failures)
        sys.exit(1)
    logger.info("cache fully warmed")


if __name__ == "__main__":
    main()
