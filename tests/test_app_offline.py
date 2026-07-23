"""AppTest smoke tests that run everywhere, including CI.

Unlike test_app.py (which drives the real local cache and skips without
it), these build a small synthetic fixture cache and point the client at
it, so the home page's render path — the app's most complex — is exercised
with no network and no pre-existing data. Includes the early-season and
empty-league shapes that only exist for a few weeks a year.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from nba_insights.config import current_season, past_seasons
from nba_insights.store import Cache
from test_ml import synthetic_team_games

APP = str(Path(__file__).parents[1] / "app" / "streamlit_app.py")


def synthetic_league(gp: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(per-game, advanced, clutch) league tables for 12 players."""
    ids = list(range(101, 113))
    league = pd.DataFrame(
        {
            "PLAYER_ID": ids,
            "PLAYER_NAME": [f"Player {i}" for i in ids],
            "TEAM_ABBREVIATION": ["T1", "T2", "T3", "T4"] * 3,
            "GP": [gp] * 12,
            "MIN": [36.0, 34.0, 32.0, 30.0, 28.0, 26.0, 24.0, 22.0, 20.0, 18.0, 16.0, 14.0],
            "PTS": [30.0 - i for i in range(12)],
            "AST": [9.0 - i * 0.5 for i in range(12)],
            "REB": [11.0 - i * 0.5 for i in range(12)],
            "FG3M": [4.0 - i * 0.25 for i in range(12)],
        }
    )
    advanced = pd.DataFrame({"PLAYER_ID": ids, "NET_RATING": [8.0 - i for i in range(12)]})
    clutch = pd.DataFrame(
        {"PLAYER_ID": ids, "GP": [gp] * 12, "NET_RATING": [6.0 - i for i in range(12)]}
    )
    return league, advanced, clutch


def build_fixture_cache(db_path: Path, gp: int = 55, empty_league: bool = False) -> None:
    """Every cache entry the home page reads, written as if fetched now."""
    cache = Cache(db_path)
    cur = current_season()
    if empty_league:
        league = advanced = clutch = darko = pd.DataFrame()
    else:
        league, advanced, clutch = synthetic_league(gp)
        darko = pd.DataFrame(
            {
                "PLAYER_ID": league["PLAYER_ID"],
                "PLAYER_NAME": league["PLAYER_NAME"],
                "DPM": [5.0 - i for i in range(len(league))],
            }
        )
    cache.put(f"league_player_stats/{cur}/PerGame", league)
    cache.put(f"league_player_advanced/{cur}", advanced)
    cache.put(f"league_player_clutch/{cur}", clutch)
    cache.put("darko/dpm", darko)
    seasons = [*past_seasons(2), cur]
    for n, season in enumerate(seasons):
        games = synthetic_team_games(
            30,
            seed=n,
            start=f"{2023 + n}-11-01",
            season_id=f"2{2023 + n}",
            game_prefix=f"S{n}G",
        )
        cache.put(f"game_finder/T/{season}", games)


@pytest.fixture
def offline_app(tmp_path, monkeypatch):
    """AppTest factory wired to a fixture cache; any network use fails loudly."""
    import streamlit as st

    import nba_insights.ingest.client as client_mod

    def _make(**cache_kwargs):
        from streamlit.testing.v1 import AppTest

        build_fixture_cache(tmp_path / "cache.sqlite3", **cache_kwargs)
        monkeypatch.setattr(client_mod, "CACHE_DB", tmp_path / "cache.sqlite3")

        def no_network(self, fetch):
            raise AssertionError("app hit the network despite a full fixture cache")

        monkeypatch.setattr(client_mod.NBAClient, "_call", no_network)
        # leader tiles fetch headshots from the NBA CDN; stub them offline
        import nba_insights.serve as serve_mod

        monkeypatch.setattr(serve_mod, "fetch_headshot", lambda player_id: None)
        # cached resources/frames from other tests (or a real local cache)
        # must not leak into the fixture run
        st.cache_data.clear()
        st.cache_resource.clear()
        return AppTest.from_file(APP, default_timeout=120)

    yield _make
    st.cache_data.clear()
    st.cache_resource.clear()


def test_home_page_renders_offline(offline_app):
    at = offline_app().run()
    assert not at.exception, [e.value for e in at.exception]
    assert not at.error, [e.value for e in at.error]
    titles = [t.value for t in at.title] + [t.value for t in at.sidebar.title]
    assert "🏀 POSSESSION LAB" in titles  # brand now lives in the sidebar
    assert any("League pulse" in t for t in titles)  # page headline names the page
    assert len(at.metric) >= 4  # leader tiles from the fixture league


def test_home_page_survives_early_season_sample_sizes(offline_app):
    # October shape: nobody near the 20-GP leaderboard floor. The floor
    # must scale down instead of leaving every board empty (which used to
    # crash on boards[label].iloc[0]).
    at = offline_app(gp=3).run()
    assert not at.exception, [e.value for e in at.exception]
    assert len(at.metric) >= 4


def test_home_page_survives_empty_league_table(offline_app):
    # offseason-start shape: upstream serves empty league tables
    at = offline_app(empty_league=True).run()
    assert not at.exception, [e.value for e in at.exception]
