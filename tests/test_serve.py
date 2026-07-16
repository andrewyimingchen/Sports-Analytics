"""Offline tests for the serving-layer composition helpers."""

from __future__ import annotations

import pandas as pd

from nba_insights.serve import league_with_ratings


class RecordingClient:
    """Fake NBAClient that records which seasons were requested."""

    def __init__(self):
        self.seasons: list[str | None] = []
        self.darko_called = False

    def league_player_stats(self, season=None, per_mode="PerGame"):
        self.seasons.append(season)
        return pd.DataFrame(
            {"PLAYER_ID": [1], "PLAYER_NAME": ["Alice"], "GP": [50], "PTS": [20.0]}
        )

    def league_player_advanced(self, season=None):
        self.seasons.append(season)
        return pd.DataFrame({"PLAYER_ID": [1], "NET_RATING": [5.0]})

    def league_player_clutch(self, season=None):
        self.seasons.append(season)
        return pd.DataFrame({"PLAYER_ID": [1], "GP": [10], "NET_RATING": [2.0]})

    def darko_dpm(self):
        self.darko_called = True
        return pd.DataFrame({"PLAYER_ID": [1], "DPM": [3.0]})


def test_current_season_attaches_ratings_and_dpm():
    client = RecordingClient()
    out = league_with_ratings(client)
    assert client.darko_called
    assert out.loc[0, "DPM"] == 3.0
    assert out.loc[0, "NET_RATING"] == 5.0
    assert client.seasons == [None, None, None]


def test_past_season_passes_through_and_skips_dpm():
    client = RecordingClient()
    out = league_with_ratings(client, "1996-97")
    assert not client.darko_called  # DPM is today's projection, not 1997's
    assert "DPM" not in out.columns
    assert out.loc[0, "NET_RATING"] == 5.0
    assert client.seasons == ["1996-97"] * 3
