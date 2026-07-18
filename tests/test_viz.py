"""Offline tests for chart-helper presentation constants."""

from __future__ import annotations

from nba_insights.viz import TEAM_COLORS, half_court_path, team_color


def test_team_color_known_and_fallback():
    assert team_color("LAL") == "#552583"
    assert team_color("lal") == "#552583"  # case-insensitive
    assert team_color("ZZZ") == "#2a78d6"  # palette-blue default
    assert team_color("ZZZ", default="#000000") == "#000000"


def test_team_colors_cover_all_thirty_teams():
    assert len(TEAM_COLORS) == 30
    assert all(v.startswith("#") and len(v) == 7 for v in TEAM_COLORS.values())


def test_half_court_path_is_a_closed_svg_path():
    path = half_court_path()
    assert path.startswith("M ")
    assert "L" in path  # line segments present
