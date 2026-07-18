"""Chart helpers shared by the app and shareable cards.

Court geometry uses stats.nba.com shot-chart coordinates: units are tenths
of feet, the hoop sits at the origin, the baseline at y=-47.5, and x spans
the court's width (-250..250).
"""

from __future__ import annotations

import math

import plotly.graph_objects as go

# Each team's primary color (stats.nba.com tricodes). Used for identity
# accents — chart dots carry a surface-colored ring for separation, and
# marks are always labeled, so near-duplicate hues (several reds/navies)
# never have to carry identity on their own.
TEAM_COLORS = {
    "ATL": "#E03A3E", "BOS": "#007A33", "BKN": "#3A3A3A", "CHA": "#00788C",
    "CHI": "#CE1141", "CLE": "#860038", "DAL": "#00538C", "DEN": "#0E2240",
    "DET": "#C8102E", "GSW": "#1D428A", "HOU": "#CE1141", "IND": "#002D62",
    "LAC": "#C8102E", "LAL": "#552583", "MEM": "#5D76A9", "MIA": "#98002E",
    "MIL": "#00471B", "MIN": "#236192", "NOP": "#0C2340", "NYK": "#006BB6",
    "OKC": "#007AC1", "ORL": "#0077C0", "PHI": "#006BB6", "PHX": "#1D1160",
    "POR": "#E03A3E", "SAC": "#5A2D81", "SAS": "#6C7A83", "TOR": "#CE1141",
    "UTA": "#002B5C", "WAS": "#002B5C",
}


def team_color(tricode: str, default: str = "#2a78d6") -> str:
    """A team's primary color by tricode; *default* (palette blue) if unknown."""
    return TEAM_COLORS.get(str(tricode).upper(), default)


def _arc(cx: float, cy: float, r: float, start_deg: float, end_deg: float, n: int = 40):
    xs, ys = [], []
    for i in range(n + 1):
        a = math.radians(start_deg + (end_deg - start_deg) * i / n)
        xs.append(cx + r * math.cos(a))
        ys.append(cy + r * math.sin(a))
    return xs, ys


def _court_segments() -> list[tuple[list[float], list[float]]]:
    return [
        # court boundary: baseline, sidelines, half-court line
        ([-250, 250, 250, -250, -250], [-47.5, -47.5, 422.5, 422.5, -47.5]),
        # backboard and hoop
        ([-30, 30], [-7.5, -7.5]),
        _arc(0, 0, 7.5, 0, 360),
        # paint (outer box) and free-throw circle
        ([-80, -80, 80, 80], [-47.5, 142.5, 142.5, -47.5]),
        _arc(0, 142.5, 60, 0, 360),
        # restricted area
        _arc(0, 0, 40, 0, 180),
        # three-point line: two corner segments joined by the arc
        ([-220, -220], [-47.5, 89.5]),
        _arc(0, 0, 237.5, 157.93, 22.07),
        ([220, 220], [89.5, -47.5]),
        # center circle (half shown at the half-court line)
        _arc(0, 422.5, 60, 180, 360),
    ]


def half_court_trace(color: str = "#c3c2b7") -> go.Scatter:
    """All half-court lines as one non-interactive Scatter trace.

    Segments are separated by None gaps so a single trace draws the whole
    court; it neither appears in the legend nor answers hover.
    """
    xs: list[float | None] = []
    ys: list[float | None] = []
    for seg_x, seg_y in _court_segments():
        xs.extend([*seg_x, None])
        ys.extend([*seg_y, None])

    return go.Scatter(
        x=xs,
        y=ys,
        mode="lines",
        line=dict(color=color, width=1),
        hoverinfo="skip",
        showlegend=False,
    )


def half_court_path() -> str:
    """The same half-court lines as one SVG path string.

    For charts that draw data as layout shapes (e.g. hexbin tiles): shapes
    stack in array order, so a court *shape* appended after the tiles keeps
    the court ink readable on top of them, which a trace cannot do.
    """
    parts = []
    for seg_x, seg_y in _court_segments():
        points = " L ".join(f"{x:.2f},{y:.2f}" for x, y in zip(seg_x, seg_y, strict=True))
        parts.append(f"M {points}")
    return " ".join(parts)
