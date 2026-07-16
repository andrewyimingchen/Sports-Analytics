"""Offline tests for the DARKO payload decoder."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.ingest.darko import decode_darko


def make_payload() -> dict:
    # SvelteKit devalue layout: data[0] is the route root; objects hold
    # indices into the same flat array. Two players, second with a NaN dpm.
    data = [
        {"players": 1, "seasons": 20},
        [2, 11],
        {"nba_id": 3, "player_name": 4, "tm_id": 5, "dpm": 6, "o_dpm": 7, "d_dpm": 8,
         "box_dpm": 9, "on_off_dpm": 10},
        203999,
        "Nikola Jokic",
        1610612743,
        7.02,
        5.12,
        1.9,
        5.47,
        7.23,
        {"nba_id": 12, "player_name": 13, "tm_id": 14, "dpm": -3, "o_dpm": -3, "d_dpm": -3,
         "box_dpm": -3, "on_off_dpm": -3},
        2544,
        "LeBron James",
        1610612747,
        # trailing node the decoder must ignore
        {"seasons": "not-players"},
    ]
    return {"nodes": [None, {"type": "data", "data": data}]}


def test_decode_darko_flattens_payload():
    df = decode_darko(make_payload())
    assert list(df["PLAYER_ID"]) == [203999, 2544]
    jokic = df.set_index("PLAYER_NAME").loc["Nikola Jokic"]
    assert jokic["DPM"] == 7.02
    assert jokic["O_DPM"] == 5.12
    assert jokic["TEAM_ID"] == 1610612743
    # devalue NaN sentinel (-3) resolves to NaN, not to data[-3]
    assert pd.isna(df.set_index("PLAYER_NAME").loc["LeBron James", "DPM"])


def test_decode_darko_rejects_shapeless_payload():
    with pytest.raises(ValueError):
        decode_darko({"nodes": [None, {"type": "data", "data": [{"seasons": 1}, 2026]}]})
    with pytest.raises(ValueError):
        decode_darko({"nodes": []})
    with pytest.raises(ValueError):
        decode_darko({})
