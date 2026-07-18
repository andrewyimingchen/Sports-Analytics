"""Helpers shared by the serving layers (Streamlit app and FastAPI).

Composition that both frontends need but that belongs to neither: joining
the rating tables onto the league dashboard, and proxying headshots from
the NBA CDN (which rejects browser hotlinking). Callers add their own
caching (st.cache_data / functools.lru_cache).
"""

from __future__ import annotations

import logging

import pandas as pd

from nba_insights.analysis import attach_dpm, attach_ratings
from nba_insights.config import current_season
from nba_insights.ingest import NBAClient

logger = logging.getLogger(__name__)

HEADSHOT_URL = "https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"
TEAM_LOGO_URL = "https://cdn.nba.com/logos/nba/{team_id}/global/L/logo.svg"


def league_with_ratings(client: NBAClient, season: str | None = None) -> pd.DataFrame:
    """League per-game stats enriched with net and clutch ratings.

    Works for any season the dashboards cover (1996-97 onward); DARKO DPM
    is today's projection, so it is only attached to the current season.
    Falls back to the plain per-game table if the rating endpoints are
    unreachable — downstream defaults skip the missing columns.
    """
    league = client.league_player_stats(season)
    try:
        league = attach_ratings(
            league, client.league_player_advanced(season), client.league_player_clutch(season)
        )
    except Exception:
        logger.warning(
            "rating endpoints unavailable; serving plain per-game table", exc_info=True
        )
    if season is None or season == current_season():
        try:
            league = attach_dpm(league, client.darko_dpm())
        except Exception:
            logger.warning("DARKO unavailable; serving table without DPM", exc_info=True)
    return league


def fetch_headshot(player_id: int) -> bytes | None:
    """Fetch a headshot server-side; None when the CDN has none."""
    return _fetch_cdn(HEADSHOT_URL.format(player_id=player_id))


def fetch_team_logo(team_id: int) -> bytes | None:
    """Fetch a team logo (SVG) server-side; None when the CDN has none."""
    return _fetch_cdn(TEAM_LOGO_URL.format(team_id=team_id))


def _fetch_cdn(url: str) -> bytes | None:
    import requests

    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.raise_for_status()
        return r.content
    except Exception:
        logger.warning("CDN fetch failed for %s", url, exc_info=True)
        return None
