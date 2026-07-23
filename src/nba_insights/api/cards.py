"""Shareable player cards: self-contained HTML, no external assets."""

from __future__ import annotations

from html import escape

import pandas as pd

from nba_insights.config import current_season

# Reference dataviz palette (light / dark pairs)
_CSS = """
:root {
  color-scheme: light dark;
  --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --accent: #2a78d6; --ring: rgba(11,11,11,.10);
}
@media (prefers-color-scheme: dark) {
  :root {
    --surface: #1a1a19; --ink: #ffffff; --ink-2: #c3c2b7;
    --grid: #2c2c2a; --accent: #3987e5; --ring: rgba(255,255,255,.10);
  }
}
body { margin: 0; display: grid; place-items: center; min-height: 100vh;
       background: var(--surface);
       font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
.card { width: min(420px, 92vw); padding: 28px; border-radius: 16px;
        background: var(--surface); box-shadow: 0 0 0 1px var(--ring);
        color: var(--ink); }
h1 { margin: 0; font-size: 1.4rem; }
.season { color: var(--muted); font-size: .85rem; margin: 2px 0 18px; }
.tiles { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.tile { border: 1px solid var(--grid); border-radius: 10px; padding: 10px 12px; }
.tile .v { font-size: 1.5rem; font-weight: 650; }
.tile .k { color: var(--ink-2); font-size: .75rem; letter-spacing: .04em; }
.pct { margin-top: 20px; }
.pct .row { display: grid; grid-template-columns: 64px 1fr 34px; gap: 8px;
            align-items: center; margin: 6px 0; font-size: .8rem; }
.pct .label { color: var(--ink-2); }
.pct .bar { height: 8px; border-radius: 4px; background: var(--grid); }
.pct .fill { height: 100%; border-radius: 4px; background: var(--accent); }
.pct .num { text-align: right; font-variant-numeric: tabular-nums; }
.foot { margin-top: 18px; color: var(--muted); font-size: .7rem; }
"""


def render_player_card(
    name: str,
    latest_season: pd.Series,
    percentiles: pd.Series | None = None,
) -> str:
    """Render a share card from one `career_per_game` row and optional ranks."""
    tiles = "".join(
        f'<div class="tile"><div class="v">{latest_season[stat]:.1f}</div>'
        f'<div class="k">{stat} / game</div></div>'
        for stat in ("PTS", "AST", "REB")
        if stat in latest_season
    )

    pct_html = ""
    if percentiles is not None and not percentiles.empty:
        rows = "".join(
            f'<div class="row"><span class="label">{escape(str(stat))}</span>'
            f'<div class="bar"><div class="fill" style="width:{value:.0f}%"></div></div>'
            f'<span class="num">{value:.0f}</span></div>'
            for stat, value in percentiles.items()
        )
        pct_html = f'<div class="pct"><div class="label">League percentile</div>{rows}</div>'

    season = str(latest_season.get("SEASON_ID", current_season()))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(name)} — POSSESSION LAB</title><style>{_CSS}</style></head>
<body><div class="card">
<h1>{escape(name)}</h1>
<div class="season">{escape(season)} regular season</div>
<div class="tiles">{tiles}</div>
{pct_html}
<div class="foot">POSSESSION LAB · data: stats.nba.com</div>
</div></body></html>"""
