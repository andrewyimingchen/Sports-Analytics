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


def test_empty_result_returned_but_not_cached(tmp_path, df):
    cache = make_cache(tmp_path)
    results = [pd.DataFrame(), df]

    def fetcher():
        return results.pop(0)

    first = cache.get_or_fetch("k", fetcher, ttl=None)
    assert first.empty
    second = cache.get_or_fetch("k", fetcher, ttl=None)  # refetches despite ttl=None
    pd.testing.assert_frame_equal(second, df)


def test_fetch_failure_without_stale_raises(tmp_path):
    cache = make_cache(tmp_path)

    def failing_fetcher():
        raise ConnectionError("offline")

    with pytest.raises(ConnectionError):
        cache.get_or_fetch("k", failing_fetcher, ttl=None)
