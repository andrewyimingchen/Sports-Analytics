"""Shared configuration: data locations and season helpers."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(os.environ.get("NBA_INSIGHTS_DATA_DIR", "data"))
CACHE_DB = DATA_DIR / "cache.sqlite3"
MODELS_DIR = DATA_DIR / "models"


def past_seasons(n: int, today: date | None = None) -> list[str]:
    """The *n* completed seasons before the current one, oldest first."""
    current_start = int(current_season(today)[:4])
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(current_start - n, current_start)]


# stats.nba.com league dashboards (and shot locations) go back to 1996-97;
# earlier seasons return empty tables, so the app never offers them
FIRST_DASHBOARD_SEASON = 1996


def seasons_since(start_year: int = FIRST_DASHBOARD_SEASON, today: date | None = None) -> list[str]:
    """Every season from *start_year* through the current one, newest first."""
    current_start = int(current_season(today)[:4])
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(current_start, start_year - 1, -1)]


def next_season(season: str | None = None, today: date | None = None) -> str:
    """Season immediately after *season* (or the date-derived current season)."""
    start_year = int((season or current_season(today))[:4]) + 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def prediction_seasons(today: date | None = None) -> list[str]:
    """Seasons offered by forecasts: current data plus next-year carry-forward."""
    current = current_season(today)
    return [current, next_season(current)]


def _today() -> date:
    """Today's date; the single seam tests pin to stay calendar-independent."""
    return date.today()


def calendar_season(today: date | None = None) -> str:
    """The season a date falls in by calendar alone (e.g. "2025-26").

    A season is counted from October 1, before its regular season has
    actually tipped off. Cache lifetimes use this rule: anything from the
    calendar season onward is still changing.
    """
    today = today or _today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


def previous_season(season: str) -> str:
    start_year = int(season[:4]) - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"


# Whether a season's regular season has started is a data question (opening
# night moves year to year), so the app registers a check backed by its
# client. Results are memoized: a started season stays started, and a
# not-yet-started answer is rechecked hourly instead of on every call.
_season_started_check: Callable[[str], bool] | None = None
_season_started_memo: dict[str, tuple[bool, float]] = {}
_RECHECK_SECONDS = 3600.0
_checking = False


def set_season_started_check(check: Callable[[str], bool] | None) -> None:
    """Register (or clear, with None) the regular-season-has-started check."""
    global _season_started_check
    _season_started_check = check
    _season_started_memo.clear()


def _season_started(season: str) -> bool:
    global _checking
    if _season_started_check is None or _checking:
        return True
    cached = _season_started_memo.get(season)
    if cached and (cached[0] or time.monotonic() - cached[1] < _RECHECK_SECONDS):
        return cached[0]
    _checking = True  # the check itself fetches data, which may ask for the season
    try:
        started = bool(_season_started_check(season))
    except Exception:
        logger.warning("season-start check failed for %s", season, exc_info=True)
        started = False
    finally:
        _checking = False
    _season_started_memo[season] = (started, time.monotonic())
    return started


def current_season(today: date | None = None) -> str:
    """The season the app treats as current (e.g. "2025-26").

    With an explicit *today* this is the pure calendar rule. Otherwise a new
    season only becomes current once its regular season has games: between
    October 1 and opening night the just-finished season stays current, so
    current-season views never open on an empty season.
    """
    season = calendar_season(today)
    if today is not None:
        return season
    if int(season[:4]) == _today().year and not _season_started(season):
        return previous_season(season)
    return season
