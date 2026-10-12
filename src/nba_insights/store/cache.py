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

Process model: any number of threads and processes on one host may share
one cache file (e.g. several uvicorn workers plus Streamlit). The database
runs in WAL mode so readers never block the writer, every connection waits
up to :data:`BUSY_TIMEOUT_SECONDS` for a lock instead of failing, and a
miss is fetched once across processes: a per-key POSIX byte-range lock on
``<db>.lock`` (single-flight across processes) backs the per-key thread
lock (single-flight within one). The file must be on a local filesystem;
network filesystems break both WAL and POSIX locks. Without ``fcntl``
(Windows) only the in-process guarantee holds.
"""

from __future__ import annotations

import errno
import hashlib
import logging
import os
import sqlite3
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from io import BytesIO, StringIO
from pathlib import Path

import pandas as pd

from nba_insights.errors import UpstreamError

try:
    import fcntl
except ImportError:  # Windows: in-process single-flight only
    fcntl = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# How long a connection waits for another writer before raising "locked".
BUSY_TIMEOUT_SECONDS = 30.0

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

# POSIX record locks belong to the process and are all released when *any*
# descriptor for the file is closed, so each lock file is opened once per
# process and never closed.
_LOCK_FDS: dict[Path, int] = {}
_LOCK_FDS_GUARD = threading.Lock()


def _lock_fd(path: Path) -> int:
    with _LOCK_FDS_GUARD:
        if path not in _LOCK_FDS:
            _LOCK_FDS[path] = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        return _LOCK_FDS[path]


def _lock_offset(key: str) -> int:
    """A byte in a 2**31 range per key; a rare collision only serializes two keys."""
    digest = hashlib.blake2b(key.encode(), digest_size=4).digest()
    return int.from_bytes(digest, "big") & 0x7FFFFFFF


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
        # keys served through get_or_fetch, so a training run can record
        # exactly which source snapshots it read (see ml/manifest.py)
        self._accessed: set[str] = set()
        self._lock_path = self.db_path.with_name(self.db_path.name + ".lock")
        with self._connect() as conn:
            # Persistent per database file; a no-op once set. Returns the
            # previous mode when WAL is unsupported (e.g. network filesystem).
            self.journal_mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0])
            conn.execute(_SCHEMA)
        if self.journal_mode.lower() != "wal":
            logger.warning(
                "cache %s runs in %s mode; concurrent readers may block writers",
                self.db_path,
                self.journal_mode,
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A short-lived connection: committed on success, always closed."""
        conn = sqlite3.connect(self.db_path, timeout=BUSY_TIMEOUT_SECONDS)
        try:
            # WAL makes NORMAL durable against application crashes
            conn.execute("PRAGMA synchronous=NORMAL")
            with conn:
                yield conn
        finally:
            conn.close()

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

    def accessed_keys(self) -> list[str]:
        """Keys requested through :meth:`get_or_fetch` by this instance, sorted."""
        return sorted(self._accessed)

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
        self._accessed.add(key)
        cached = self._get_valid(key, ttl, fetched_after)
        if cached is not None:
            return cached
        with self._key_lock(key), self._process_lock(key):
            # another thread or process may have fetched while we waited
            cached = self._get_valid(key, ttl, fetched_after)
            if cached is not None:
                return cached
            try:
                df = fetcher()
            except (UpstreamError, OSError):
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

    @contextmanager
    def _process_lock(self, key: str) -> Iterator[None]:
        """Cross-process single-flight for *key* (no-op without fcntl)."""
        if fcntl is None:
            yield
            return
        fd = _lock_fd(self._lock_path)
        offset = _lock_offset(key)
        try:
            fcntl.lockf(fd, fcntl.LOCK_EX, 1, offset)
        except OSError as error:
            if error.errno != errno.EDEADLK:
                raise
            # two processes each hold a key the other's nested fetch needs;
            # fetching without the lock risks one duplicate request, not a hang
            logger.warning("cache lock deadlock avoided for %s; fetching unlocked", key)
            yield
            return
        try:
            yield
        finally:
            fcntl.lockf(fd, fcntl.LOCK_UN, 1, offset)

    def _load(self, key: str) -> tuple[datetime, pd.DataFrame] | None:
        row = self._read_row(f"{_FORMAT_VERSION}:{key}")
        if row is not None:
            if isinstance(row[1], bytes):
                return row[0], _deserialize(row[1])
            # parquet entries are always bytes: a foreign writer put this row
            # here. Treat it as a miss (the next fetch overwrites it) rather
            # than resurrecting older legacy data over it.
            logger.error("cache entry %s is not a parquet payload; ignoring it", key)
            return None
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
