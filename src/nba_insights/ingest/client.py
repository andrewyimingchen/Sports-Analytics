"""Rate-limited, cached client for the endpoints the product needs.

Wraps `nba_api` (stats.nba.com). Player/team lookup uses the static tables
bundled with nba_api, so it works offline. Everything else is fetched through
the cache: finished seasons never expire, current-season data refreshes daily.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pandas as pd
from nba_api.stats.endpoints import (
    draftcombinestats,
    drafthistory,
    leaguedashlineups,
    leaguedashplayerclutch,
    leaguedashplayerstats,
    leaguegamefinder,
    leaguestandings,
    playbyplayv3,
    playercareerstats,
    playergamelog,
    playergamelogs,
    playerprofilev2,
    scheduleleaguev2,
    shotchartdetail,
    teamplayeronoffsummary,
)
from nba_api.stats.static import players

from nba_insights.config import CACHE_DB, current_season
from nba_insights.ingest.darko import fetch_darko
from nba_insights.ingest.salaries import fetch_contracts
from nba_insights.store import Cache

logger = logging.getLogger(__name__)

CURRENT_SEASON_TTL = timedelta(hours=24)
# contracts change rarely outside July; a weekly refresh keeps scrape
# volume at the guardrailed minimum (one page/week — see ingest.salaries)
CONTRACTS_TTL = timedelta(days=7)


def _type_suffix(season_type: str) -> str:
    """Cache-key suffix for non-default season types ('' for Regular Season)."""
    return "" if season_type == "Regular Season" else f"/{season_type.lower().replace(' ', '-')}"


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
        # one client is shared across Streamlit sessions / API worker
        # threads; the lock keeps the rate limiter honest under concurrency
        self._rate_lock = threading.Lock()

    # -- static lookups (offline) --------------------------------------------

    def search_players(self, name: str) -> list[dict]:
        """Match players by full-name fragment using nba_api's bundled table.

        nba_api compiles the query as a regex, so user input is escaped —
        a stray "(" or "*" in a search box must not raise re.error.
        """
        return players.find_players_by_full_name(re.escape(name))

    def find_player(self, player_id: int) -> dict | None:
        """Look up one player by ID in nba_api's bundled table (offline)."""
        return players.find_player_by_id(player_id)

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

    def game_log(
        self,
        player_id: int,
        season: str | None = None,
        season_type: str = "Regular Season",
    ) -> pd.DataFrame:
        season = season or current_season()
        return self._cached(
            # v2: key bumped when fetcher changed; regular-season keys keep
            # their historical shape so the existing cache stays valid
            f"game_log/v2/{player_id}/{season}{_type_suffix(season_type)}",
            lambda: self._fetch_game_log(player_id, season, season_type),
            ttl=self._season_ttl(season),
            fetched_after=self._season_fetched_after(season),
        )

    @staticmethod
    def _fetch_game_log(
        player_id: int, season: str, season_type: str = "Regular Season"
    ) -> pd.DataFrame:
        # PlayerGameLogs (plural) is primary: the singular endpoint serves
        # truncated logs for some player IDs (same upstream per-ID corruption
        # as career stats — see _fetch_career_stats).
        df = playergamelogs.PlayerGameLogs(
            player_id_nullable=player_id,
            season_nullable=season,
            season_type_nullable=season_type,
        ).get_data_frames()[0]
        if df.empty:
            df = playergamelog.PlayerGameLog(
                player_id=player_id, season=season, season_type_all_star=season_type
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
            fetched_after=self._season_fetched_after(season),
        )

    def league_player_advanced(self, season: str | None = None) -> pd.DataFrame:
        """One row per player: advanced metrics (net/off/def rating, usage)."""
        season = season or current_season()
        return self._cached(
            f"league_player_advanced/{season}",
            lambda: leaguedashplayerstats.LeagueDashPlayerStats(
                season=season, measure_type_detailed_defense="Advanced"
            ).get_data_frames()[0],
            ttl=self._season_ttl(season),
            fetched_after=self._season_fetched_after(season),
        )

    def league_player_clutch(self, season: str | None = None) -> pd.DataFrame:
        """Per-player advanced stats in the clutch (last 5 min, margin <= 5).

        GP and MIN in this table are clutch games and clutch minutes per
        game, not season-wide values.
        """
        season = season or current_season()
        return self._cached(
            f"league_player_clutch/{season}",
            lambda: leaguedashplayerclutch.LeagueDashPlayerClutch(
                season=season,
                measure_type_detailed_defense="Advanced",
                clutch_time="Last 5 Minutes",
                ahead_behind="Ahead or Behind",
                point_diff=5,
            ).get_data_frames()[0],
            ttl=self._season_ttl(season),
            fetched_after=self._season_fetched_after(season),
        )

    def shot_chart(
        self,
        player_id: int,
        season: str | None = None,
        season_type: str = "Regular Season",
    ) -> pd.DataFrame:
        season = season or current_season()
        return self._cached(
            f"shot_chart/{player_id}/{season}{_type_suffix(season_type)}",
            lambda: shotchartdetail.ShotChartDetail(
                team_id=0,
                player_id=player_id,
                season_nullable=season,
                season_type_all_star=season_type,
                context_measure_simple="FGA",
            ).get_data_frames()[0],
            ttl=self._season_ttl(season),
            fetched_after=self._season_fetched_after(season),
        )

    def shot_league_averages(
        self, season: str | None = None, season_type: str = "Regular Season"
    ) -> pd.DataFrame:
        """League FG% by shot zone (~20 rows) for a season.

        Same endpoint as shot_chart with player_id=0; only the small
        LeagueAverages frame is kept — the league-wide shot rows are not.
        """
        season = season or current_season()
        return self._cached(
            f"shot_league_avg/{season}{_type_suffix(season_type)}",
            lambda: shotchartdetail.ShotChartDetail(
                team_id=0,
                player_id=0,
                season_nullable=season,
                season_type_all_star=season_type,
                context_measure_simple="FGA",
            ).get_data_frames()[1],
            ttl=self._season_ttl(season),
            fetched_after=self._season_fetched_after(season),
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
            fetched_after=self._season_fetched_after(season),
        )

    def standings(self, season: str | None = None) -> pd.DataFrame:
        season = season or current_season()
        return self._cached(
            f"standings/{season}",
            lambda: leaguestandings.LeagueStandings(season=season).get_data_frames()[0],
            ttl=self._season_ttl(season),
            fetched_after=self._season_fetched_after(season),
        )

    # columns kept from PlayByPlayV3: enough for score-timeline analysis
    # (garbage time, clutch) and future stint work, without the bulky
    # description/coordinate columns (shot x/y already comes via shot_chart)
    _PBP_COLS = [
        "gameId",
        "actionNumber",
        "period",
        "clock",
        "teamId",
        "personId",
        "actionType",
        "subType",
        "scoreHome",
        "scoreAway",
        "isFieldGoal",
    ]

    def play_by_play(self, game_id: str) -> pd.DataFrame:
        """Trimmed event log for one completed game. Immutable once played."""
        return self._cached(
            f"pbp/v3/{game_id}",
            lambda: self._fetch_pbp(game_id),
            ttl=None,  # only fetched for finished games; the log never changes
        )

    def _fetch_pbp(self, game_id: str) -> pd.DataFrame:
        df = playbyplayv3.PlayByPlayV3(game_id=game_id).get_data_frames()[0]
        return df[[c for c in self._PBP_COLS if c in df.columns]]

    def schedule(self, season: str | None = None) -> pd.DataFrame:
        """Full season schedule (all games with dates, tricodes, status)."""
        season = season or current_season()
        return self._cached(
            f"schedule/{season}",
            lambda: scheduleleaguev2.ScheduleLeagueV2(season=season).get_data_frames()[0],
            ttl=self._season_ttl(season),
            fetched_after=self._season_fetched_after(season),
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
            fetched_after=self._season_fetched_after(season),
        )

    def team_player_on_off(self, team_id: int, season: str | None = None) -> pd.DataFrame:
        """Per-player on/off splits for one team: total minutes and team
        ORtg/DRtg/net rating with each player on vs off the floor
        (COURT_STATUS "On"/"Off"; the on and off frames are concatenated)."""
        season = season or current_season()
        return self._cached(
            f"team_on_off/{team_id}/{season}",
            lambda: self._fetch_team_on_off(team_id, season),
            ttl=self._season_ttl(season),
            fetched_after=self._season_fetched_after(season),
        )

    @staticmethod
    def _fetch_team_on_off(team_id: int, season: str) -> pd.DataFrame:
        frames = teamplayeronoffsummary.TeamPlayerOnOffSummary(
            team_id=team_id, season=season
        ).get_data_frames()
        # frames[1] and [2] are the per-player splits (one per court status);
        # frame[0] is the team's overall line and is not kept
        return pd.concat(frames[1:3], ignore_index=True)

    def draft_history(self) -> pd.DataFrame:
        """Every NBA draft pick ever, one row per pick (~8k rows).

        The table only grows on draft night, but a daily TTL keeps the
        newest class appearing without a bespoke invalidation rule."""
        return self._cached(
            "draft_history",
            lambda: drafthistory.DraftHistory(league_id="00").get_data_frames()[0],
            ttl=CURRENT_SEASON_TTL,
        )

    def draft_combine(self, year: str) -> pd.DataFrame:
        """Combine measurements for one draft year (e.g. "2014").

        Past years are immutable; the current season's year stays on the
        daily TTL while its combine results are still being published."""
        past = int(year) < int(current_season()[:4])
        return self._cached(
            f"draft_combine/{year}",
            lambda: draftcombinestats.DraftCombineStats(
                season_all_time=year
            ).get_data_frames()[0],
            ttl=None if past else CURRENT_SEASON_TTL,
        )

    def player_contracts(self) -> pd.DataFrame:
        """Current contracts (scraped, weekly refresh): one row per player,
        salary per forward season plus guaranteed total. Personal use only —
        never serve through the public API/PWA (see ingest.salaries)."""
        return self._cached("contracts/bref", fetch_contracts, ttl=CONTRACTS_TTL)

    def darko_dpm(self) -> pd.DataFrame:
        """Today's DARKO plus-minus projections (darko.app), one row per
        active player. Not a stats.nba.com endpoint, but fetched through
        the same cache/rate limiter so the app stays offline-friendly."""
        return self._cached("darko/dpm", fetch_darko, ttl=CURRENT_SEASON_TTL)

    # -- plumbing ---------------------------------------------------------------

    def _season_ttl(self, season: str) -> timedelta | None:
        return CURRENT_SEASON_TTL if season == current_season() else None

    def _season_fetched_after(self, season: str) -> datetime | None:
        """Earliest fetch time a past season's entry may have.

        A finished season is only immutable if it was fetched after the
        season actually ended; an entry cached mid-season is a partial
        snapshot and must be refetched once the season rolls over. July 1
        after the season's end year is safely past the Finals.
        """
        if season == current_season():
            return None
        end_year = int(season[:4]) + 1
        return datetime(end_year, 7, 1, tzinfo=UTC)

    def _cached(
        self,
        key: str,
        fetch: Callable[[], pd.DataFrame],
        ttl: timedelta | None,
        fetched_after: datetime | None = None,
    ) -> pd.DataFrame:
        return self.cache.get_or_fetch(
            key, lambda: self._call(fetch), ttl=ttl, fetched_after=fetched_after
        )

    # Empty responses are cached only briefly (see Cache.get_or_fetch): a
    # transient upstream glitch can't get pinned for a whole TTL, and a
    # legitimately empty response doesn't refetch on every render.

    def _call(self, fetch: Callable[[], pd.DataFrame]) -> pd.DataFrame:
        """Run a remote fetch with rate limiting and retry with backoff."""
        last_error: Exception | None = None
        for attempt in range(self.retries):
            with self._rate_lock:
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
