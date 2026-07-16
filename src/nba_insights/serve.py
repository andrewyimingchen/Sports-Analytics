"""Helpers shared by the serving layers (Streamlit app and FastAPI).

Composition that both frontends need but that belongs to neither: joining
the rating tables onto the league dashboard, and proxying headshots from
the NBA CDN (which rejects browser hotlinking). Callers add their own
caching (st.cache_data / functools.lru_cache).
"""

from __future__ import annotations

import logging

import pandas as pd

from nba_insights.analysis import attach_ratings
from nba_insights.ingest import NBAClient

logger = logging.getLogger(__name__)

HEADSHOT_URL = "https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"


def league_with_ratings(client: NBAClient) -> pd.DataFrame:
    """League per-game stats enriched with net and clutch ratings.

    Falls back to the plain per-game table if the rating endpoints are
    unreachable — downstream defaults skip the missing columns.
    """
    league = client.league_player_stats()
    try:
        return attach_ratings(
            league, client.league_player_advanced(), client.league_player_clutch()
        )
    except Exception:
        logger.warning(
            "rating endpoints unavailable; serving plain per-game table", exc_info=True
        )
        return league


def fetch_headshot(player_id: int) -> bytes | None:
    """Fetch a headshot server-side; None when the CDN has none."""
    import requests

    try:
        r = requests.get(
            HEADSHOT_URL.format(player_id=player_id),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        return r.content
    except Exception:
        logger.warning("headshot fetch failed for player %s", player_id, exc_info=True)
        return None
