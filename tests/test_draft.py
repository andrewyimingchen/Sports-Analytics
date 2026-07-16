"""Offline tests for draft-class analysis."""

from __future__ import annotations

import pandas as pd
import pytest

from nba_insights.analysis import draft_class, player_draft_line


@pytest.fixture
def history():
    return pd.DataFrame(
        {
            "PERSON_ID": [10, 11, 12],
            "PLAYER_NAME": ["First Pick", "Second Pick", "Old Timer"],
            "SEASON": ["2024", "2024", "1984"],
            "ROUND_NUMBER": [1, 1, 1],
            "OVERALL_PICK": [1, 2, 3],
            "TEAM_ABBREVIATION": ["ATL", "WAS", "CHI"],
            "ORGANIZATION": ["Duke", "UConn", "North Carolina"],
        }
    )


@pytest.fixture
def combine():
    # only the first pick attended the combine
    return pd.DataFrame(
        {
            "PLAYER_ID": [10],
            "POSITION": ["PG"],
            "HEIGHT_WO_SHOES": [75.5],
            "WEIGHT": [190.0],
            "WINGSPAN": [80.0],
            "STANDING_REACH": [100.0],
            "MAX_VERTICAL_LEAP": [38.5],
            "THREE_QUARTER_SPRINT": [3.1],
        }
    )


def test_draft_class_joins_combine_and_sorts(history, combine):
    out = draft_class(history, combine, 2024)
    assert list(out["PLAYER_NAME"]) == ["First Pick", "Second Pick"]  # 1984 excluded
    first = out.iloc[0]
    assert first["WINGSPAN"] == 80.0
    assert first["WINGSPAN_DIFF"] == pytest.approx(4.5)
    assert pd.isna(out.iloc[1]["WINGSPAN"])  # skipped the combine, kept anyway


def test_draft_class_survives_missing_combine(history):
    out = draft_class(history, None, "1984")
    assert list(out["PLAYER_NAME"]) == ["Old Timer"]
    assert "WINGSPAN" not in out.columns


def test_draft_class_missing_column_raises(history, combine):
    with pytest.raises(KeyError, match="OVERALL_PICK"):
        draft_class(history.drop(columns=["OVERALL_PICK"]), combine, 2024)


def test_player_draft_line(history):
    assert player_draft_line(history, 11) == "#2 overall, 2024 (WAS)"
    assert player_draft_line(history, 999) is None  # undrafted