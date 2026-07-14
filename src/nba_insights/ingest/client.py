"""Rate-limited, cached client for the endpoints the product needs.

Wraps `nba_api` (stats.nba.com). Player/team lookup uses the static tables
bundled with nba_api, so it works offline. Everything else is fetched through
the cache: finished seasons never expire, current-season data refreshes daily.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import timedelta

import pandas as pd
from nba_api.stats.endpoints import (
    leaguedashlineups,
    leaguedashplayerstats,
    leaguegamefinder,
    leaguestandings,
    playercareerstats,
    playergamelog,
    playergamelogs,
    playerprofilev2,
    scheduleleaguev2,
    shotchartdetail,
)
from nba_api.stats.static import players

from nba_insights.config import CACHE_DB, current_season
from nba_insights.store import Cache

logger = logging.getLogger(__name__)

CURRENT_SEASON_TTL = timedelta(hours=24)


class NBAClient:
    def __init__(
        self,
        cache: Cache | None = None,
        delay: float = 0.6,
        retries: int = 3,
    ):
        self.cache = cache or Cache(CACHE_DB)
        self.delay = delay
        self.retries = retries
        self._last_call = 0.0

    # -- static lookups (offline) --------------------------------------------

    def search_players(self, name: str) -> list[dict]:
        """Match players by full-name fragment using nba_api's bundled table."""
        return players.find_players_by_full_name(name)

    # -- remote endpoints (cached) ---------------------------------------------

    def career_stats(self, player_id: int) -> pd.DataFrame:
        """Season-by-season regular-season totals for a player's whole career."""
        return self._cached(
            f"career_stats/{player_id}",
            lambda: self._fetch_career_stats(player_id),
            ttl=CURRENT_SEASON_TTL,  # active players gain rows during the season
        )

    @staticmethod
    def _fetch_career_stats(player_id: int) -> pd.DataFrame:
        df = playercareerstats.PlayerCareerStats(
            player_id=player_id
        ).season_totals_regular_season.get_data_frame()
        if df.empty:
            # stats.nba.com intermittently serves an empty (G-League-tagged)
            # response for some player IDs; PlayerProfileV2 has the same table.
            df = playerprofilev2.PlayerProfileV2(
                player_id=player_id, per_mode36="Totals"
            ).season_totals_regular_season.get_data_frame()
        return df

    def game_log(self, player_id: int, season: str | None = None) -> pd.DataFrame:
        season = season or current_season()
        return self._cached(
            f"game_log/v2/{player_id}/{season}",  # v2: key bumped when fetcher changed
            lambda: self._fetch_game_log(player_id, season),
            ttl=self._season_ttl(season),
        )

    @staticmethod
    def _fetch_game_log(player_id: int, season: str) -> pd.DataFrame:
        # PlayerGameLogs (plural) is primary: the singular endpoint serves
        # truncated logs for some player IDs (same upstream per-ID corruption
        # as career stats — see _fetch_career_stats).
        df = playergamelogs.PlayerGameLogs(
            player_id_nullable=player_id,
            season_nullable=season,
            season_type_nullable="Regular Season",
        ).get_data_frames()[0]
        if df.empty:
            df = playergamelog.PlayerGameLog(
                player_id=player_id, season=season
            ).get_data_frames()[0]
        return df

    def league_player_stats(
        self, season: str | None = None, per_mode: str = "PerGame"
    ) -> pd.DataFrame:
        """One row per player: league-wide per-game stats for a season."""
        season = season or current_season()
        return self._cached(
            f"league_player_stats/{season}/{per_mode}",
            lambda: leaguedashplayerstats.LeagueDashPlayerStats(
                season=season, per_mode_detailed=per_mode
            ).get_data_frames()[0],
            ttl=self._season_ttl(season),
        )

    def shot_chart(self, player_id: int, season: str | None = None) -> pd.DataFrame:
        season = season or current_season()
        return self._cached(
            f"shot_chart/{player_id}/{season}",
            lambda: shotchartdetail.ShotChartDetail(
                team_id=0,
                player_id=player_id,
                season_nullable=season,
                context_measure_simple="FGA",
            ).get_data_frames()[0],
            ttl=self._season_ttl(season),
        )

    def team_games(self, season: str | None = None) -> pd.DataFrame:
        """League-wide team-game rows for a season (two rows per game)."""
        return self._game_finder("T", season or current_season())

    def player_games(self, season: str | None = None) -> pd.DataFrame:
        """League-wide player-game rows for a season (~26k rows)."""
        return self._game_finder("P", season or current_season())

    def _game_finder(self, mode: str, season: str) -> pd.DataFrame:
        return self._cached(
            f"game_finder/{mode}/{season}",
            lambda: leaguegamefinder.LeagueGameFinder(
                season_nullable=season,
                season_type_nullable="Regular Season",
                league_id_nullable="00",
                player_or_team_abbreviation=mode,
            ).get_data_frames()[0],
            ttl=self._season_ttl(season),
        )

    def standings(self, season: str | None = None) -> pd.DataFrame:
        season = season or current_season()
        return self._cached(
            f"standings/{season}",
            lambda: leaguestandings.LeagueStandings(season=season).get_data_frames()[0],
            ttl=self._season_ttl(season),
        )

    def schedule(self, season: str | None = None) -> pd.DataFrame:
        """Full season schedule (all games with dates, tricodes, status)."""
        season = season or current_season()
        return self._cached(
            f"schedule/{season}",
            lambda: scheduleleaguev2.ScheduleLeagueV2(season=season).get_data_frames()[0],
            ttl=self._season_ttl(season),
        )

    def lineups(self, season: str | None = None) -> pd.DataFrame:
        """5-man lineup advanced stats (total minutes, net rating) for a season."""
        season = season or current_season()
        return self._cached(
            f"lineups/5/{season}",
            lambda: leaguedashlineups.LeagueDashLineups(
                season=season,
                group_quantity=5,
                measure_type_detailed_defense="Advanced",
                per_mode_detailed="Totals",
            ).get_data_frames()[0],
            ttl=self._season_ttl(season),
        )

    # -- plumbing ---------------------------------------------------------------

    def _season_ttl(self, season: str) -> timedelta | None:
        return CURRENT_SEASON_TTL if season == current_season() else None

    def _cached(
        self,
        key: str,
        fetch: Callable[[], pd.DataFrame],
        ttl: timedelta | None,
    ) -> pd.DataFrame:
        return self.cache.get_or_fetch(key, lambda: self._call(fetch), ttl=ttl)

    # Empty responses are treated as transient upstream glitches and never
    # cached, so a later good response can still land (see Cache.get_or_fetch).

    def _call(self, fetch: Callable[[], pd.DataFrame]) -> pd.DataFrame:
        """Run a remote fetch with rate limiting and retry with backoff."""
        last_error: Exception | None = None
        for attempt in range(self.retries):
            wait = self.delay - (time.monotonic() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            self._last_call = time.monotonic()
            try:
                return fetch()
            except Exception as e:  # nba_api raises assorted requests/JSON errors
                last_error = e
                backoff = 2**attempt
                logger.warning(
                    "fetch failed (attempt %d): %s; retrying in %ss", attempt + 1, e, backoff
                )
                time.sleep(backoff)
        raise RuntimeError(f"NBA API fetch failed after {self.retries} attempts") from last_error
