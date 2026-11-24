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


def test_preseason_data_stays_live_while_prior_season_is_current(tmp_path, monkeypatch):
    from datetime import date

    from nba_insights import config

    client = make_client(tmp_path)
    monkeypatch.setattr(config, "_today", lambda: date(2026, 10, 5))
    config.set_season_started_check(lambda season: False)
    assert config.current_season() == "2025-26"
    # the new season's preseason fetches must keep refreshing, not freeze
    assert client._season_ttl("2026-27") is not None
    assert client._season_fetched_after("2026-27") is None
    # the finished season is immutable once fetched after its Finals
    assert client._season_ttl("2025-26") is None
    assert client._season_fetched_after("2025-26") == datetime(2026, 7, 1, tzinfo=UTC)


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


def test_tracking_and_hustle_use_scoped_cache_keys(tmp_path, monkeypatch):
    calls = []
    expected = pd.DataFrame({"PLAYER_ID": [1], "DRIVES": [12.0]})

    class Endpoint:
        def get_data_frames(self):
            return [expected]

    def fake_tracking(**kwargs):
        calls.append(("tracking", kwargs["player_or_team"], kwargs["pt_measure_type"]))
        return Endpoint()

    def fake_hustle(**kwargs):
        calls.append(("hustle", kwargs["per_mode_time"]))
        return Endpoint()

    monkeypatch.setattr(
        "nba_insights.ingest.client.leaguedashptstats.LeagueDashPtStats",
        fake_tracking,
    )
    monkeypatch.setattr(
        "nba_insights.ingest.client.leaguehustlestatsplayer.LeagueHustleStatsPlayer",
        fake_hustle,
    )
    monkeypatch.setattr(
        "nba_insights.ingest.client.leaguehustlestatsteam.LeagueHustleStatsTeam",
        fake_hustle,
    )
    client = make_client(tmp_path)

    pd.testing.assert_frame_equal(client.tracking_stats("Drives", "2025-26"), expected)
    pd.testing.assert_frame_equal(client.tracking_stats("Drives", "2025-26"), expected)
    pd.testing.assert_frame_equal(client.tracking_stats("Drives", "2025-26", "Team"), expected)
    pd.testing.assert_frame_equal(client.hustle_stats("2025-26"), expected)
    pd.testing.assert_frame_equal(client.hustle_stats("2025-26"), expected)
    pd.testing.assert_frame_equal(client.hustle_stats("2025-26", "Team"), expected)
    assert calls == [
        ("tracking", "Player", "Drives"),
        ("tracking", "Team", "Drives"),
        ("hustle", "PerGame"),
        ("hustle", "PerGame"),
    ]


def test_player_salary_history_fetches_once_then_reads_cache(tmp_path, monkeypatch):
    calls = []
    expected = pd.DataFrame(
        {"SEASON": ["2024-25"], "TEAM": ["Denver Nuggets"], "SALARY": [51_415_938]}
    )

    def fake_fetch(slug):
        calls.append(slug)
        return expected

    monkeypatch.setattr("nba_insights.ingest.client.fetch_career_salaries", fake_fetch)
    client = make_client(tmp_path)
    slug = "j/jokicni01.html"
    pd.testing.assert_frame_equal(client.player_salary_history(slug), expected)
    pd.testing.assert_frame_equal(client.player_salary_history(slug), expected)
    assert calls == [slug]


def schedule_frame(statuses: list[int]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "gameStatus": statuses,
            "gameDateTimeUTC": ["2026-11-22T00:00:00Z", "2026-11-23T00:30:00Z"],
        }
    )


def test_schedule_fetched_during_games_is_due_once_they_end():
    from nba_insights.ingest.client import schedule_results_due

    # fetched at 20:09 ET while the 19:30 ET game was live
    fetched = datetime(2026, 11, 23, 1, 9, tzinfo=UTC)
    live = schedule_frame([3, 2])
    morning = datetime(2026, 11, 23, 11, 0, tzinfo=UTC)
    assert schedule_results_due(live, fetched, morning) == datetime(2026, 11, 23, 3, 30, tzinfo=UTC)
    # before the game could have ended, the fetch is still good
    assert schedule_results_due(live, fetched, datetime(2026, 11, 23, 2, tzinfo=UTC)) is None
    # refetched with the result in: nothing due
    assert schedule_results_due(schedule_frame([3, 3]), morning, morning) is None


def test_postponed_game_does_not_force_refetches():
    from nba_insights.ingest.client import schedule_results_due

    # the first game never went final, but it ended before this fetch
    fetched = datetime(2026, 11, 23, 11, 0, tzinfo=UTC)
    later = datetime(2026, 11, 24, 11, 0, tzinfo=UTC)
    assert schedule_results_due(schedule_frame([1, 3]), fetched, later) is None


def test_schedule_refetches_entry_cached_mid_game(tmp_path, monkeypatch):
    from nba_insights.config import calendar_season
    from nba_insights.store import Cache

    fetch_time = [datetime.now(UTC) - pd.Timedelta(hours=5)]
    cache = Cache(tmp_path / "cache.sqlite3", now=lambda: fetch_time[0])
    client = NBAClient(cache=cache)
    season = calendar_season()
    tip = (fetch_time[0] - pd.Timedelta(minutes=30)).isoformat()
    cache.put(
        f"schedule/{season}",
        pd.DataFrame({"gameStatus": [2], "gameDateTimeUTC": [tip]}),
    )
    final = pd.DataFrame({"gameStatus": [3], "gameDateTimeUTC": [tip]})
    calls = []
    monkeypatch.setattr(client, "_call", lambda fetch, key="": calls.append(key) or final)
    fetch_time[0] = datetime.now(UTC)
    assert client.schedule(season)["gameStatus"].tolist() == [3]
    assert client.schedule(season)["gameStatus"].tolist() == [3]
    assert len(calls) == 1
