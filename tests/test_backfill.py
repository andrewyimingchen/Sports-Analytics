"""Offline tests for play-by-play backfill selection."""

from __future__ import annotations

import pandas as pd

from nba_insights.pbp.backfill import backfill_season


class RecordingClient:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def team_games(self, season):
        return pd.DataFrame(
            {
                "GAME_ID": ["002", "001"],
                "GAME_DATE": ["2026-10-20", "2026-10-01"],
            }
        )

    def play_by_play(self, game_id):
        self.calls.append(("pbp", game_id))

    def game_rotation(self, game_id):
        self.calls.append(("rotation", game_id))


def test_since_none_keeps_whole_season_behavior():
    client = RecordingClient()

    assert backfill_season(client, "2026-27", since=None) == 0
    assert client.calls == [
        ("pbp", "001"),
        ("rotation", "001"),
        ("pbp", "002"),
        ("rotation", "002"),
    ]
