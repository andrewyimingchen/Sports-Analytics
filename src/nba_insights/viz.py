"""Chart helpers shared by the app and shareable cards.

Court geometry uses stats.nba.com shot-chart coordinates: units are tenths
of feet, the hoop sits at the origin, the baseline at y=-47.5, and x spans
the court's width (-250..250).
"""

from __future__ import annotations

import math

import plotly.graph_objects as go


def _arc(cx: float, cy: float, r: float, start_deg: float, end_deg: float, n: int = 40):
    xs, ys = [], []
    for i in range(n + 1):
        a = math.radians(start_deg + (end_deg - start_deg) * i / n)
        xs.append(cx + r * math.cos(a))
        ys.append(cy + r * math.sin(a))
    return xs, ys


def half_court_trace(color: str = "#c3c2b7") -> go.Scatter:
    """All half-court lines as one non-interactive Scatter trace.

    Segments are separated by None gaps so a single trace draws the whole
    court; it neither appears in the legend nor answers hover.
    """
    segments: list[tuple[list[float], list[float]]] = [
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

    xs: list[float | None] = []
    ys: list[float | None] = []
    for seg_x, seg_y in segments:
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
