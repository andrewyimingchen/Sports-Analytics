"""Build and load season stint-lineup tables.

    uv run python -m nba_insights.pbp.lineups --season 2025-26

The build is cache-only: it reads rotations and play-by-play that
``pbp.backfill`` already fetched, aggregates them with
:mod:`nba_insights.pbp.stints`, and stores the table in the cache under
a versioned key. It never fetches — the rotation endpoint is tar-pitted
upstream (~20s per request under load), so all network patience lives in
the backfill. A table is only stored when enough of the season is
covered; a partial corpus would silently understate every lineup's
minutes. The app's lineup tab only ever *loads* the table.
"""

from __future__ import annotations

import argparse
import logging

import pandas as pd

from nba_insights.config import current_season
from nba_insights.ingest import NBAClient
from nba_insights.pbp.stints import lineup_ratings, stint_table
from nba_insights.store import Cache

logger = logging.getLogger(__name__)

_KEY = "stint_lineups/v1/{season}"


def build_season(
    client: NBAClient,
    season: str,
    limit: int | None = None,
    min_coverage: float = 0.9,
) -> pd.DataFrame:
    """Aggregate cached stints into a lineup table and store it.

    Cache-only (see module docstring). Raises RuntimeError when fewer
    than *min_coverage* of the season's games have a cached rotation —
    run ``pbp.backfill`` further and retry.
    """
    game_ids = sorted(client.team_games(season)["GAME_ID"].unique())
    if limit:
        game_ids = game_ids[:limit]
    per_game, missing, broken = [], 0, 0
    for game_id in game_ids:
        rotation = client.cached_rotation(game_id)
        if rotation is None or rotation.empty:
            missing += 1
            continue
        try:
            per_game.append(stint_table(rotation, client.play_by_play(game_id)))
        except Exception as e:
            broken += 1
            logger.warning("skipping stints for %s: %s", game_id, e)
    coverage = len(per_game) / len(game_ids) if game_ids else 0.0
    if coverage < min_coverage:
        raise RuntimeError(
            f"{season} corpus covers {coverage:.0%} of {len(game_ids)} games "
            f"({missing} rotations not cached, {broken} unparseable) — below the "
            f"{min_coverage:.0%} floor; run pbp.backfill further, then rebuild"
        )
    table = lineup_ratings(pd.concat(per_game, ignore_index=True))
    # tuples don't survive parquet; GROUP_ID carries the identity
    table = table.drop(columns=["LINEUP"])
    client.cache.put(_KEY.format(season=season), table)
    logger.info(
        "%s: %d lineups from %d games (%.0f%% coverage, %d missing, %d broken)",
        season, len(table), len(per_game), coverage * 100, missing, broken,
    )
    return table


def load_season(cache: Cache, season: str | None = None) -> pd.DataFrame | None:
    """The prebuilt lineup table for a season, or None if never built."""
    table = cache.get(_KEY.format(season=season or current_season()))
    return None if table is None or table.empty else table


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Build the stint-level lineup table")
    parser.add_argument("--season", default=current_season(), help="season, e.g. 2025-26")
    parser.add_argument("--limit", type=int, default=None, help="only the first N games (debug)")
    parser.add_argument(
        "--min-coverage", type=float, default=0.9,
        help="fraction of games that must have cached rotations (default 0.9)",
    )
    args = parser.parse_args()
    build_season(NBAClient(), args.season, limit=args.limit, min_coverage=args.min_coverage)


if __name__ == "__main__":
    main()
