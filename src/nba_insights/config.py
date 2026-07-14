"""Shared configuration: data locations and season helpers."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

DATA_DIR = Path(os.environ.get("NBA_INSIGHTS_DATA_DIR", "data"))
CACHE_DB = DATA_DIR / "cache.sqlite3"
MODELS_DIR = DATA_DIR / "models"


def past_seasons(n: int, today: date | None = None) -> list[str]:
    """The *n* completed seasons before the current one, oldest first."""
    current_start = int(current_season(today)[:4])
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(current_start - n, current_start)]


def current_season(today: date | None = None) -> str:
    """Return the NBA season string (e.g. "2025-26") for a given date.

    A new season starts in October; before that the date belongs to the
    season that began the previous calendar year.
    """
    today = today or date.today()
    start_year = today.year if today.month >= 10 else today.year - 1
    return f"{start_year}-{(start_year + 1) % 100:02d}"
