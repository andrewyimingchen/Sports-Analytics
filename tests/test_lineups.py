"""Offline tests for the five-man lineups browser."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.analysis import most_used_lineups


def _lineups() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "TEAM_ABBREVIATION": ["OKC", "OKC", "OKC", "BOS"],
            "GROUP_ID": ["-1-2-3-4-5-", "-1-2-3-4-6-", "-2-3-4-6-7-", "-8-9-10-11-12-"],
            "GROUP_NAME": ["A-B-C-D-E", "A-B-C-D-F", "B-C-D-F-G", "H-I-J-K-L"],
            "MIN": [200.0, 40.0, 120.0, 300.0],
            "NET_RATING": [10.0, -2.0, 5.0, 8.0],
        }
    )


def test_most_used_sorts_and_filters_by_team():
    board = most_used_lineups(_lineups(), "OKC")
    assert len(board) == 3  # only OKC
    assert list(board["MIN"]) == [200.0, 120.0, 40.0]  # minutes descending


def test_must_include_ids_and_min_minutes():
    lu = _lineups()
    # player 1 is only in the first two OKC lineups
    with_p1 = most_used_lineups(lu, "OKC", must_include_ids=[1])
    assert list(with_p1["GROUP_NAME"]) == ["A-B-C-D-E", "A-B-C-D-F"]
    # add a minutes floor: the 40-min lineup drops out
    assert list(most_used_lineups(lu, "OKC", must_include_ids=[1], min_minutes=50)["MIN"]) == [
        200.0
    ]
    # both filters together: player 6 with 100+ minutes -> only the 120-min lineup
    assert list(
        most_used_lineups(lu, "OKC", must_include_ids=[6], min_minutes=100)["GROUP_NAME"]
    ) == ["B-C-D-F-G"]


def test_missing_columns_raise():
    with pytest.raises(KeyError, match="GROUP_ID"):
        most_used_lineups(_lineups().drop(columns=["GROUP_ID"]), "OKC")
