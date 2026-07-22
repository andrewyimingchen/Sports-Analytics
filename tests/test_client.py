"""Offline tests for NBAClient's non-network plumbing."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from nba_insights.ingest import NBAClient


def make_client(tmp_path) -> NBAClient:
    from nba_insights.store import Cache

    return NBAClient(cache=Cache(tmp_path / "cache.sqlite3"))


def test_search_players_escapes_regex_metacharacters(tmp_path):
    client = make_client(tmp_path)
    # nba_api compiles the query as a regex; raw "(" used to raise re.error
    assert client.search_players("(((") == []
    assert client.search_players("*lebron*") == []


def test_search_players_still_matches_names(tmp_path):
    client = make_client(tmp_path)
    names = [p["full_name"] for p in client.search_players("LeBron James")]
    assert "LeBron James" in names


def test_find_player_by_id(tmp_path):
    client = make_client(tmp_path)
    player = client.find_player(2544)
    assert player is not None and player["full_name"] == "LeBron James"
    assert client.find_player(-1) is None


def test_season_fetched_after_past_vs_current(tmp_path):
    client = make_client(tmp_path)
    from nba_insights.config import current_season

    assert client._season_fetched_after(current_season()) is None
    cutoff = client._season_fetched_after("2023-24")
    assert cutoff == datetime(2024, 7, 1, tzinfo=UTC)


def test_box_score_fetches_once_then_reads_cache(tmp_path, monkeypatch):
    calls = []
    expected = pd.DataFrame({"gameId": ["0022600001"], "points": [30]})

    class PlayerStats:
        def get_data_frame(self):
            return expected

    class Endpoint:
        player_stats = PlayerStats()

    def fake_endpoint(*, game_id):
        calls.append(game_id)
        return Endpoint()

    monkeypatch.setattr(
        "nba_insights.ingest.client.boxscoretraditionalv3.BoxScoreTraditionalV3",
        fake_endpoint,
    )
    client = make_client(tmp_path)
    pd.testing.assert_frame_equal(client.box_score("0022600001"), expected)
    pd.testing.assert_frame_equal(client.box_score("0022600001"), expected)
    assert calls == ["0022600001"]


def test_cached_play_by_play_prefers_coordinate_aware_version(tmp_path):
    client = make_client(tmp_path)
    legacy = pd.DataFrame({"actionNumber": [1]})
    current = pd.DataFrame({"actionNumber": [1], "xLegacy": [25]})
    client.cache.put("pbp/v3/001", legacy)
    pd.testing.assert_frame_equal(client.cached_play_by_play("001"), legacy)
    client.cache.put("pbp/v4/001", current)
    pd.testing.assert_frame_equal(client.cached_play_by_play("001"), current)
