"""SQLite-backed DataFrame cache.

Every remote fetch goes through :meth:`Cache.get_or_fetch`, so a warm cache
means the app never hits stats.nba.com on a user request. Entries carry a
fetch timestamp; a TTL of ``None`` marks data as immutable (finished
seasons), while current-season data uses a short TTL and is refreshed when
stale. If a refresh fails but a stale copy exists, the stale copy is served
so the app degrades gracefully offline.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    key        TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    payload    TEXT NOT NULL
)
"""

# Bump when the payload format changes: keys are namespaced by version, so
# entries written by an older format are orphaned rather than misread.
_FORMAT_VERSION = "v2"


class Cache:
    def __init__(
        self,
        db_path: str | Path,
        now: Callable[[], datetime] | None = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now or (lambda: datetime.now(UTC))
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def get(self, key: str, max_age: timedelta | None = None) -> pd.DataFrame | None:
        """Return the cached frame for *key*, or None if absent or older than *max_age*."""
        row = self._read(key)
        if row is None:
            return None
        fetched_at, payload = row
        if max_age is not None and self._now() - fetched_at > max_age:
            return None
        return _deserialize(payload)

    def put(self, key: str, df: pd.DataFrame) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache_entries (key, fetched_at, payload) VALUES (?, ?, ?)",
                (f"{_FORMAT_VERSION}:{key}", self._now().isoformat(), _serialize(df)),
            )

    def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], pd.DataFrame],
        ttl: timedelta | None = None,
    ) -> pd.DataFrame:
        """Return fresh cached data, or fetch, store, and return it.

        ``ttl=None`` means the entry never expires. On fetch failure a stale
        entry, if present, is returned instead of raising. Empty results are
        returned but never stored: stats.nba.com intermittently serves empty
        row sets, and caching one would pin the glitch for the whole TTL.
        """
        cached = self.get(key, max_age=ttl)
        if cached is not None:
            return cached
        try:
            df = fetcher()
        except Exception:
            stale = self.get(key)
            if stale is not None:
                logger.warning("fetch failed for %s; serving stale cache entry", key)
                return stale
            raise
        if not df.empty:
            self.put(key, df)
        return df

    def _read(self, key: str) -> tuple[datetime, str] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT fetched_at, payload FROM cache_entries WHERE key = ?",
                (f"{_FORMAT_VERSION}:{key}",),
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row[0]), row[1]


def _serialize(df: pd.DataFrame) -> str:
    # orient="table" embeds a schema, so dtypes survive the round trip —
    # notably ID columns like "0022401187" stay strings with leading zeros.
    return df.to_json(orient="table", date_format="iso")


def _deserialize(payload: str) -> pd.DataFrame:
    return pd.read_json(StringIO(payload), orient="table").reset_index(drop=True)
