from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from nba_insights.store import Cache


@pytest.fixture
def df():
    return pd.DataFrame({"PLAYER_NAME": ["A", "B"], "PTS": [30.1, 25.4]})


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=UTC)

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


def make_cache(tmp_path, clock=None):
    return Cache(tmp_path / "cache.sqlite3", now=clock)


def test_round_trip(tmp_path, df):
    cache = make_cache(tmp_path)
    cache.put("k", df)
    pd.testing.assert_frame_equal(cache.get("k"), df)


def test_round_trip_preserves_string_ids(tmp_path):
    # numeric-looking IDs must stay strings (leading zeros are meaningful)
    df = pd.DataFrame({"GAME_ID": ["0022401187", "0022401196"], "PTS": [93, 100]})
    cache = make_cache(tmp_path)
    cache.put("k", df)
    out = cache.get("k")
    assert out["GAME_ID"].tolist() == ["0022401187", "0022401196"]


def test_miss_returns_none(tmp_path):
    assert make_cache(tmp_path).get("nope") is None


def test_get_or_fetch_fetches_once(tmp_path, df):
    cache = make_cache(tmp_path)
    calls = []

    def fetcher():
        calls.append(1)
        return df

    for _ in range(3):
        result = cache.get_or_fetch("k", fetcher, ttl=None)
    assert len(calls) == 1
    pd.testing.assert_frame_equal(result, df)


def test_ttl_expiry_triggers_refetch(tmp_path, df):
    clock = FakeClock()
    cache = make_cache(tmp_path, clock)
    calls = []

    def fetcher():
        calls.append(1)
        return df

    cache.get_or_fetch("k", fetcher, ttl=timedelta(hours=24))
    clock.advance(hours=25)
    cache.get_or_fetch("k", fetcher, ttl=timedelta(hours=24))
    assert len(calls) == 2


def test_none_ttl_never_expires(tmp_path, df):
    clock = FakeClock()
    cache = make_cache(tmp_path, clock)
    cache.put("k", df)
    clock.advance(days=3650)
    assert cache.get("k", max_age=None) is not None


def test_stale_served_when_fetch_fails(tmp_path, df):
    clock = FakeClock()
    cache = make_cache(tmp_path, clock)
    cache.put("k", df)
    clock.advance(hours=48)

    def failing_fetcher():
        raise ConnectionError("offline")

    result = cache.get_or_fetch("k", failing_fetcher, ttl=timedelta(hours=24))
    pd.testing.assert_frame_equal(result, df)


def test_empty_result_cached_only_briefly(tmp_path, df):
    clock = FakeClock()
    cache = make_cache(tmp_path, clock)
    results = [pd.DataFrame(), df]

    def fetcher():
        return results.pop(0)

    first = cache.get_or_fetch("k", fetcher, ttl=None)
    assert first.empty
    # within EMPTY_TTL the cached empty frame is served — no refetch storm
    again = cache.get_or_fetch("k", fetcher, ttl=None)
    assert again.empty and len(results) == 1
    # past EMPTY_TTL the empty entry is distrusted and refetched
    clock.advance(hours=2)
    second = cache.get_or_fetch("k", fetcher, ttl=None)
    pd.testing.assert_frame_equal(second, df)


def test_fetched_after_invalidates_older_entries(tmp_path, df):
    clock = FakeClock()  # starts 2026-01-01: mid-season
    cache = make_cache(tmp_path, clock)
    calls = []

    def fetcher():
        calls.append(1)
        return df

    cache.get_or_fetch("k", fetcher, ttl=None)
    # entry fetched before the cutoff (season end) is a partial snapshot
    cutoff = datetime(2026, 7, 1, tzinfo=UTC)
    clock.advance(days=365)
    cache.get_or_fetch("k", fetcher, ttl=None, fetched_after=cutoff)
    assert len(calls) == 2
    # the refetched entry now postdates the cutoff and is served as immutable
    cache.get_or_fetch("k", fetcher, ttl=None, fetched_after=cutoff)
    assert len(calls) == 2


def test_legacy_json_entry_migrated_in_place(tmp_path, df):
    import sqlite3

    clock = FakeClock()
    cache = make_cache(tmp_path, clock)
    payload = df.to_json(orient="table", date_format="iso")
    with sqlite3.connect(tmp_path / "cache.sqlite3") as conn:
        conn.execute(
            "INSERT INTO cache_entries (key, fetched_at, payload) VALUES (?, ?, ?)",
            ("v2:k", datetime(2025, 6, 1, tzinfo=UTC).isoformat(), payload),
        )
    out = cache.get("k")
    pd.testing.assert_frame_equal(out, df)
    # migrated to the current format keeping the original fetch time
    with sqlite3.connect(tmp_path / "cache.sqlite3") as conn:
        row = conn.execute(
            "SELECT fetched_at FROM cache_entries WHERE key = 'v3:k'"
        ).fetchone()
    assert row is not None and row[0] == datetime(2025, 6, 1, tzinfo=UTC).isoformat()


def test_fetch_failure_without_stale_raises(tmp_path):
    cache = make_cache(tmp_path)

    def failing_fetcher():
        raise ConnectionError("offline")

    with pytest.raises(ConnectionError):
        cache.get_or_fetch("k", failing_fetcher, ttl=None)
