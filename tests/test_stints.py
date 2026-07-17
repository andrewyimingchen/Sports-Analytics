"""Offline tests for stint-level lineup analysis."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.pbp.stints import (
    clock_to_tenths,
    garbage_time_onset,
    lineup_ratings,
    stint_table,
)

HOME, AWAY = 1610612744, 1610612746


def test_clock_to_tenths_regulation_and_overtime():
    assert clock_to_tenths(1, "PT12M00.00S") == 0
    assert clock_to_tenths(1, "PT06M00.00S") == 3600
    assert clock_to_tenths(4, "PT00M00.00S") == 28800
    assert clock_to_tenths(5, "PT05M00.00S") == 28800  # OT tips off where Q4 ended
    assert clock_to_tenths(6, "PT04M59.00S") == 28800 + 3000 + 10
    with pytest.raises(ValueError):
        clock_to_tenths(1, "12:00")


def rotation(subbed_home_starter: int = 101, sub_in: int = 106, sub_t: float = 3600):
    """Full-game fives, except one home starter swapped at *sub_t*."""
    rows = []
    for pid in range(101, 106):  # home
        out_t = sub_t if pid == subbed_home_starter else 28800
        rows.append((HOME, pid, 0.0, out_t, True))
    rows.append((HOME, sub_in, sub_t, 28800.0, True))
    for pid in range(201, 206):  # away, never sub
        rows.append((AWAY, pid, 0.0, 28800.0, False))
    return pd.DataFrame(
        rows, columns=["TEAM_ID", "PERSON_ID", "IN_TIME_REAL", "OUT_TIME_REAL", "IS_HOME"]
    )


def pbp_events(rows):
    """rows: (actionNumber, period, clock, teamId, actionType, home, away)."""
    cols = ["actionNumber", "period", "clock", "teamId", "actionType", "scoreHome", "scoreAway"]
    return pd.DataFrame(rows, columns=cols)


@pytest.fixture
def close_game():
    # sub happens at 3600 tenths = 6:00 left in Q1; home scores twice
    # before it, away answers twice after it
    return pbp_events(
        [
            (1, 1, "PT10M00.00S", HOME, "Made Shot", "2", "0"),
            (2, 1, "PT08M00.00S", AWAY, "Missed Shot", "2", "0"),
            (3, 1, "PT07M59.00S", HOME, "Rebound", "2", "0"),
            (4, 1, "PT07M00.00S", HOME, "Made Shot", "4", "0"),
            (5, 1, "PT02M00.00S", AWAY, "Made Shot", "4", "2"),
            (6, 4, "PT00M01.00S", AWAY, "Made Shot", "4", "4"),
        ]
    )


def test_stint_table_slices_and_attributes_margin(close_game):
    out = stint_table(rotation(), close_game)
    assert len(out) == 2
    first, second = out.iloc[0], out.iloc[1]
    assert first["START"] == 0 and first["END"] == 3600 and first["MIN"] == 6.0
    assert first["HOME_LINEUP"] == (101, 102, 103, 104, 105)
    assert second["HOME_LINEUP"] == (102, 103, 104, 105, 106)
    assert first["AWAY_LINEUP"] == (201, 202, 203, 204, 205)
    # both home makes before the sub, both answers after
    assert first["MARGIN"] == 4.0
    assert second["MARGIN"] == -4.0
    # possessions, first stint: home 2 FGA; away 1 FGA, def-rebounded (no OREB) → mean 1.5
    assert first["POSS"] == pytest.approx(1.5)


def test_stint_table_offensive_rebound_extends_possession():
    events = pbp_events(
        [
            (1, 1, "PT10M00.00S", AWAY, "Missed Shot", "0", "0"),
            (2, 1, "PT09M59.00S", AWAY, "Rebound", "0", "0"),  # own miss: OREB
            (3, 1, "PT09M50.00S", AWAY, "Made Shot", "0", "2"),
        ]
    )
    out = stint_table(rotation(sub_t=28800), events)  # no subs: one stint
    # away: 2 FGA − 1 OREB = 1 possession; home: 0 → mean 0.5
    assert out.iloc[0]["POSS"] == pytest.approx(0.5)


def test_stint_table_strips_garbage_time():
    blowout = pbp_events(
        [
            (1, 1, "PT06M00.00S", HOME, "Made Shot", "20", "0"),
            (2, 4, "PT09M00.00S", HOME, "Made Shot", "40", "10"),  # Q4, lead ≥ 20 → onset
            (3, 4, "PT01M00.00S", HOME, "Made Shot", "60", "10"),
        ]
    )
    onset = garbage_time_onset(blowout)
    assert onset == clock_to_tenths(4, "PT09M00.00S")
    out = stint_table(rotation(sub_t=25000), blowout)
    # stint truncated at onset: margin frozen at 40-10, like the parse rule
    assert out["END"].max() == onset
    assert out["MARGIN"].sum() == 30.0


def test_garbage_time_onset_none_when_game_stays_close(close_game):
    assert garbage_time_onset(close_game) is None


def test_stint_table_skips_broken_intervals(close_game):
    broken = rotation().drop(index=[8])  # an away player vanishes: 4 on floor
    out = stint_table(broken, close_game)
    assert out.empty


def test_lineup_ratings_aggregates_both_sides(close_game):
    stints = stint_table(rotation(), close_game)
    out = lineup_ratings(stints)
    # 2 home lineups + 1 away lineup
    assert len(out) == 3
    away = out[out["GROUP_ID"] == "-201-202-203-204-205-"].iloc[0]
    assert away["MIN"] == 48.0
    assert away["PLUS_MINUS"] == 0.0  # -4 then +4
    starters = out[out["GROUP_ID"] == "-101-102-103-104-105-"].iloc[0]
    assert starters["PLUS_MINUS"] == 4.0
    assert starters["NET_RATING"] > 0
    assert list(out["MIN"])[0] == 48.0  # sorted by minutes


def test_build_and_load_season_roundtrip(tmp_path, close_game):
    from nba_insights.pbp.lineups import build_season, load_season
    from nba_insights.store import Cache

    class FakeClient:
        cache = Cache(tmp_path / "cache.sqlite3")

        def team_games(self, season=None):
            return pd.DataFrame({"GAME_ID": ["G1", "G1"]})  # two team rows, one game

        def cached_rotation(self, game_id):
            return rotation()

        def play_by_play(self, game_id):
            return close_game

    built = build_season(FakeClient(), "2025-26")
    loaded = load_season(FakeClient.cache, "2025-26")
    assert list(loaded["GROUP_ID"]) == list(built["GROUP_ID"])
    assert "LINEUP" not in loaded.columns  # tuples dropped before parquet
    assert load_season(FakeClient.cache, "1999-00") is None  # never built


def test_build_season_enforces_coverage_floor(tmp_path, close_game):
    from nba_insights.pbp.lineups import build_season
    from nba_insights.store import Cache

    class GappyRotations:
        cache = Cache(tmp_path / "cache.sqlite3")

        def __init__(self, cached_every: int):
            self.cached_every = cached_every

        def team_games(self, season=None):
            return pd.DataFrame({"GAME_ID": [f"G{i}" for i in range(50)]})

        def cached_rotation(self, game_id):
            if int(game_id[1:]) % self.cached_every == 0:
                return None  # not backfilled yet
            return rotation()

        def play_by_play(self, game_id):
            return close_game

    # 20% of games missing: below the default 90% floor → refuse to store
    with pytest.raises(RuntimeError, match="below the 90% floor"):
        build_season(GappyRotations(cached_every=5), "2024-25")
    # scattered 2% gaps clear the floor and aggregate fine
    table = build_season(GappyRotations(cached_every=50), "2024-25")
    assert len(table) == 3


def test_lineup_ratings_minutes_floor(close_game):
    stints = stint_table(rotation(), close_game)
    # away five played 48; post-sub home five 42; starters only 6
    out = lineup_ratings(stints, min_minutes=45)
    assert list(out["GROUP_ID"]) == ["-201-202-203-204-205-"]
