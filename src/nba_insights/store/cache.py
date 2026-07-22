"""SQLite-backed DataFrame cache.

Every remote fetch goes through :meth:`Cache.get_or_fetch`, so a warm cache
means the app never hits stats.nba.com on a user request. Entries carry a
fetch timestamp; a TTL of ``None`` marks data as immutable (finished
seasons), while current-season data uses a short TTL and is refreshed when
stale. If a refresh fails but a stale copy exists, the stale copy is served
so the app degrades gracefully offline.

Two freshness dimensions:

- ``ttl`` — how old an entry may be, measured from its fetch time.
- ``fetched_after`` — the earliest fetch time an entry may have. A finished
  season is only truly immutable if it was fetched *after* the season
  ended; an entry fetched mid-season is a partial snapshot and must be
  refreshed even though its TTL says "never expires".

Empty frames are cached but trusted only for :data:`EMPTY_TTL`:
stats.nba.com intermittently serves empty row sets, so a glitch must not be
pinned for a whole TTL — but a legitimately empty response (a player with
no playoff games) must not trigger a network fetch on every render either.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO, StringIO
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
# v2 (orient="table" JSON) entries are migrated to v3 (parquet) on read,
# keeping their original fetch time.
_FORMAT_VERSION = "v3"
_LEGACY_JSON_VERSION = "v2"

# how long a cached *empty* frame is trusted before refetching
EMPTY_TTL = timedelta(hours=1)


class Cache:
    def __init__(
        self,
        db_path: str | Path,
        now: Callable[[], datetime] | None = None,
    ):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._now = now or (lambda: datetime.now(UTC))
        # single-flight: one fetch per key at a time, so concurrent sessions
        # missing the same key don't all hit the network
        self._key_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        with self._connect() as conn:
            conn.execute(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def get(
        self,
        key: str,
        max_age: timedelta | None = None,
        fetched_after: datetime | None = None,
    ) -> pd.DataFrame | None:
        """Return the cached frame for *key*, or None if absent or invalid.

        Invalid means older than *max_age*, or fetched before
        *fetched_after* (e.g. a finished-season entry fetched while the
        season was still in progress).
        """
        loaded = self._load(key)
        if loaded is None:
            return None
        fetched_at, df = loaded
        if max_age is not None and self._now() - fetched_at > max_age:
            return None
        if fetched_after is not None and fetched_at < fetched_after:
            return None
        return df

    def entry_info(self, key: str, ttl: timedelta | None = None) -> dict | None:
        """Non-payload cache metadata for freshness/status displays."""
        loaded = self._load(key)
        if loaded is None:
            return None
        fetched_at, frame = loaded
        age = self._now() - fetched_at
        return {
            "key": key,
            "fetched_at": fetched_at.isoformat(),
            "age_seconds": max(0.0, age.total_seconds()),
            "stale": ttl is not None and age > ttl,
            "rows": int(len(frame)),
        }

    def put(self, key: str, df: pd.DataFrame) -> None:
        self._write(key, self._now(), df)

    def _write(self, key: str, fetched_at: datetime, df: pd.DataFrame) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache_entries (key, fetched_at, payload) VALUES (?, ?, ?)",
                (f"{_FORMAT_VERSION}:{key}", fetched_at.isoformat(), _serialize(df)),
            )

    def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], pd.DataFrame],
        ttl: timedelta | None = None,
        fetched_after: datetime | None = None,
    ) -> pd.DataFrame:
        """Return fresh cached data, or fetch, store, and return it.

        ``ttl=None`` means the entry never expires (see *fetched_after* in
        the module docstring for the exception). On fetch failure a stale
        entry, if present, is returned instead of raising. Empty results
        are stored but only trusted for :data:`EMPTY_TTL`, so an upstream
        glitch can't pin an empty frame for a whole TTL while a genuinely
        empty response doesn't refetch on every call.
        """
        cached = self._get_valid(key, ttl, fetched_after)
        if cached is not None:
            return cached
        with self._key_lock(key):
            # another thread may have fetched while we waited for the lock
            cached = self._get_valid(key, ttl, fetched_after)
            if cached is not None:
                return cached
            try:
                df = fetcher()
            except Exception:
                stale = self.get(key)
                if stale is not None and not stale.empty:
                    logger.warning("fetch failed for %s; serving stale cache entry", key)
                    return stale
                raise
            self.put(key, df)
            return df

    def _get_valid(
        self, key: str, ttl: timedelta | None, fetched_after: datetime | None
    ) -> pd.DataFrame | None:
        cached = self.get(key, max_age=ttl, fetched_after=fetched_after)
        if cached is not None and cached.empty:
            empty_age = EMPTY_TTL if ttl is None else min(ttl, EMPTY_TTL)
            cached = self.get(key, max_age=empty_age, fetched_after=fetched_after)
        return cached

    def _key_lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._key_locks.setdefault(key, threading.Lock())

    def _load(self, key: str) -> tuple[datetime, pd.DataFrame] | None:
        row = self._read_row(f"{_FORMAT_VERSION}:{key}")
        if row is not None:
            fetched_at, payload = row
            return fetched_at, _deserialize(payload)
        # legacy JSON entry: migrate to parquet, keeping the fetch time
        row = self._read_row(f"{_LEGACY_JSON_VERSION}:{key}")
        if row is None:
            return None
        fetched_at, payload = row
        df = _deserialize_legacy_json(payload)
        self._write(key, fetched_at, df)
        return fetched_at, df

    def _read_row(self, versioned_key: str) -> tuple[datetime, str | bytes] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT fetched_at, payload FROM cache_entries WHERE key = ?",
                (versioned_key,),
            ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row[0]), row[1]


def _serialize(df: pd.DataFrame) -> bytes:
    # parquet keeps dtypes — notably ID columns like "0022401187" stay
    # strings with leading zeros — and is ~10x faster to parse than the
    # orient="table" JSON it replaced (see _deserialize_legacy_json).
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def _deserialize(payload: bytes) -> pd.DataFrame:
    return pd.read_parquet(BytesIO(payload))


def _deserialize_legacy_json(payload: str | bytes) -> pd.DataFrame:
    text = payload.decode() if isinstance(payload, bytes) else payload
    return pd.read_json(StringIO(text), orient="table").reset_index(drop=True)
