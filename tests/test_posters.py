"""Offline tests for the share poster renderers."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
import pytest

from nba_insights.posters import (
    compare_poster_html,
    compare_poster_png,
    prediction_poster_html,
    prediction_poster_png,
)


@pytest.fixture
def table():
    # comparison_table shape: stats as rows, players as columns
    return pd.DataFrame(
        {
            "Alice Hooper": [30.0, 8.0, 0.52, 3.0, float("nan")],
            "Bob Rimson": [25.0, 9.0, 0.48, 2.0, 4.5],
        },
        index=["PTS", "AST", "FG_PCT", "TOV", "DPM"],
    )


def test_compare_poster_html_contents(table):
    html = compare_poster_html(table, "2025-26")
    assert "Alice Hooper" in html and "Bob Rimson" in html
    assert "2025-26" in html
    assert "52.0%" in html  # FG_PCT formatted as a percentage
    assert "DARKO DPM" in html  # label mapping
    assert "—" in html  # NaN renders as a dash
    assert "http" not in html.split("</title>")[1]  # self-contained: no external assets


def test_prediction_poster_html_favors_the_right_team():
    html = prediction_poster_html("LAL", "BOS", 0.38, "2025-26")
    assert "LAL" in html and "BOS" in html
    assert "62%" in html  # away team is the favorite at 1 - 0.38
    assert "aspect-ratio: 16 / 9" in html


def png_size(data: bytes) -> tuple[int, int]:
    from PIL import Image

    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(BytesIO(data)).size


def test_compare_poster_png_is_square(table):
    assert png_size(compare_poster_png(table, "2025-26")) == (1080, 1080)


def test_compare_poster_png_handles_four_players(table):
    wide = table.assign(**{"Carol Longnamington-Smythe": 1.0, "Dan": 2.0})
    assert png_size(compare_poster_png(wide, "2025-26")) == (1080, 1080)


def test_prediction_poster_png_is_16_9():
    assert png_size(prediction_poster_png("LAL", "BOS", 0.62, "2025-26")) == (1200, 675)
