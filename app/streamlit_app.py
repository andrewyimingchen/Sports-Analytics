"""NBA Insights — player profiles, form trends, shot charts, comparisons.

Run with: uv run streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
import logging
import math
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))  # sibling modules (methodology, ui)

from nba_insights import serve
from nba_insights.analysis import (
    COLUMN_GLOSSARY,
    FACTOR_LABELS,
    attach_salary,
    box_score_table,
    career_averages,
    career_per_game,
    clutch_shooting_line,
    draft_class,
    filter_players,
    four_factors_table,
    game_log_table,
    hex_bins,
    league_leaders,
    most_used_lineups,
    per_minutes_table,
    percentile_ranks,
    player_contract,
    player_draft_line,
    player_scouting_take,
    player_splits,
    positional_percentile_ranks,
    query_players,
    rolling_form,
    salary_seasons,
    scoreboard,
    shot_breakdown,
    shot_quality,
    similar_players,
    team_contracts,
    team_on_off,
    team_payroll,
    team_scouting_take,
    zone_efficiency,
)
from nba_insights.analysis.shots import ZONE_KEY
from nba_insights.config import current_season, past_seasons, seasons_since
from nba_insights.ingest import NBAClient
from nba_insights.ml import (
    GameOutcomeModel,
    PlayerPointsModel,
    WinCurve,
    blended_lineup_estimate,
    sim_summary,
    simulate_matchup,
)
from nba_insights.ml.elo import current_elo
from nba_insights.ml.features import (
    matchup_features,
    player_next_game_features,
    prior_team_form,
    team_form_snapshot,
    team_rest_features,
    upcoming_games,
)
from nba_insights.ml.season import simulate_season
from nba_insights.ml.train import METRICS_PATH, OUTCOME_PATH, POINTS_PATH, WIN_CURVE_PATH
from nba_insights.pbp.lineups import load_season as load_stint_lineups
from nba_insights.posters import compare_poster_png, prediction_poster_png
from nba_insights.viz import half_court_path, half_court_trace, team_color
from ui import inject_css

logger = logging.getLogger(__name__)

# Reference dataviz palette: categorical slots in fixed order, chrome inks,
# a blue sequential ramp (near-zero end recedes toward each surface), and the
# diverging blue↔red midpoint gray. Dark values are the same hues re-stepped
# for the dark surface, not a flip.
_LIGHT = {
    "series": ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948"],
    "grid": "#e1e0d9",
    "muted": "#898781",
    "ink2": "#52514e",
    "mid": "#f0efec",
    "seq": ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"],
    "surface": "#fcfcfb",
}
_DARK = {
    "series": ["#3987e5", "#199e70", "#c98500", "#008300", "#9085e9", "#e66767"],
    "grid": "#2c2c2a",
    "muted": "#898781",
    "ink2": "#c3c2b7",
    "mid": "#383835",
    "seq": ["#104281", "#1c5cab", "#3987e5", "#6da7ec", "#b7d3f6"],
    "surface": "#1a1a19",
}


def _rgba(hex_color: str, alpha: float) -> str:
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r},{g},{b},{alpha})"


def _diverging_colorscale() -> list[tuple[float, str]]:
    """Red (below) → neutral gray → blue (above), per the palette's pair."""
    return [(0.0, PAL["series"][5]), (0.5, PAL["mid"]), (1.0, PAL["series"][0])]


def _diverging_color(value: float, span: float) -> str:
    """One color off the diverging scale, for marks drawn as shapes
    (layout shapes can't use a trace colorscale)."""
    t = (max(-span, min(span, value)) / span + 1) / 2
    lo, hi = (PAL["series"][5], PAL["mid"]) if t < 0.5 else (PAL["mid"], PAL["series"][0])
    f = t * 2 if t < 0.5 else t * 2 - 1
    channels = (
        round(int(lo[i : i + 2], 16) + f * (int(hi[i : i + 2], 16) - int(lo[i : i + 2], 16)))
        for i in (1, 3, 5)
    )
    return "#" + "".join(f"{c:02x}" for c in channels)

st.set_page_config(page_title="NBA Insights", page_icon="🏀", layout="wide")


def theme_palette() -> dict:
    theme = getattr(st.context, "theme", None)
    return _DARK if theme is not None and theme.type == "dark" else _LIGHT


# Populated in main(): the theme context isn't reliable at import time.
PAL = dict(_LIGHT)


@st.cache_resource
def get_client() -> NBAClient:
    return NBAClient()


# plain-language display names for stats.nba.com column codes — raw API
# names (FG_PCT, PLAYER_NAME) never reach the UI
STAT_LABELS = {
    "PLAYER_NAME": "PLAYER",
    "TEAM_ABBREVIATION": "TEAM",
    "FG_PCT": "FG%",
    "FG3_PCT": "3P%",
    "FT_PCT": "FT%",
    "NET_RATING": "NET RTG",
    "CLUTCH_NET_RATING": "CLUTCH NET",
    "DPM": "DARKO DPM",
}


@st.cache_data(ttl=3600, show_spinner=False)
def league_with_ratings(_client: NBAClient, season: str | None = None) -> pd.DataFrame:
    """Ratings-attached league table (see serve.league_with_ratings),
    cached at the app layer: pages call this several times per rerun and
    the frame shouldn't be re-read from SQLite each time."""
    return serve.league_with_ratings(_client, season)


@st.cache_data(ttl=3600, show_spinner=False)
def season_player_games(_client: NBAClient) -> pd.DataFrame:
    """Current-season player-game rows (~26k), cached at the app layer."""
    return _client.player_games()


@st.cache_data(ttl=3600, show_spinner="Building team form snapshot…")
def prediction_snapshot(_client: NBAClient) -> pd.DataFrame:
    """Season-to-date team form for the models, prior-seeded like training.

    The outcome model is trained on form shrunk toward prior-season means
    (10 pseudo-games); serving the raw small-sample means early in the
    season would feed it features it never saw.
    """
    games = _client.team_games()
    try:
        priors = prior_team_form(_client.team_games(past_seasons(1)[0]))
    except Exception:
        logger.warning("prior-season form unavailable; serving unseeded snapshot",
                       exc_info=True)
        priors = None
    return team_form_snapshot(games, form_priors=priors)


@st.cache_data(ttl=86400, show_spinner=False)
def contracts_table(_client: NBAClient) -> pd.DataFrame | None:
    """Scraped contracts (weekly cache underneath); None when unavailable.

    Personal-use data — surfaced only in this local app, never through
    the public API/PWA (see ingest.salaries).
    """
    try:
        return _client.player_contracts()
    except Exception:
        logger.warning("contracts unavailable", exc_info=True)
        return None


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_headshot(player_id: int) -> bytes | None:
    """Fetch the headshot server-side; the CDN rejects browser hotlinking."""
    return serve.fetch_headshot(player_id)


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_team_logo(team_id: int) -> str | None:
    """Team logo as SVG markup — st.image renders SVG from the markup string."""
    raw = serve.fetch_team_logo(team_id)
    if not raw:
        return None
    svg = raw.decode(errors="ignore")
    start = svg.find("<svg")
    return svg[start:] if start >= 0 else None


def base_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0.0, font=dict(size=15, color=PAL["ink2"])),
        template="none",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=PAL["ink2"]),
        margin=dict(l=40, r=20, t=50, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor=PAL["surface"],
            bordercolor=PAL["grid"],
            font=dict(color=PAL["ink2"], size=13),
        ),
        transition=dict(duration=350, easing="cubic-in-out"),
    )
    fig.update_xaxes(showgrid=False, linecolor=PAL["grid"], tickcolor=PAL["muted"])
    fig.update_yaxes(gridcolor=PAL["grid"], zeroline=False)
    return fig


def career_chart(per_game: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    stats = [s for s in ("PTS", "AST", "REB") if s in per_game.columns]
    for i, stat in enumerate(stats):
        fig.add_trace(
            go.Scatter(
                x=per_game["SEASON_ID"],
                y=per_game[stat],
                name=stat,
                mode="lines+markers",
                line=dict(color=PAL["series"][i], width=2.5, shape="spline", smoothing=0.6),
                marker=dict(size=7, line=dict(color=PAL["surface"], width=1.5)),
            )
        )
        # direct label at the line's end so identity never rides on color alone
        fig.add_annotation(
            x=per_game["SEASON_ID"].iloc[-1],
            y=float(per_game[stat].iloc[-1]),
            text=stat,
            showarrow=False,
            xanchor="left",
            xshift=10,
            font=dict(color=PAL["ink2"], size=12),
        )
    if "PTS" in per_game.columns and len(per_game) > 2:
        peak = per_game["PTS"].idxmax()
        fig.add_annotation(
            x=per_game.loc[peak, "SEASON_ID"],
            y=float(per_game.loc[peak, "PTS"]),
            text=f"career-high {per_game.loc[peak, 'PTS']:.1f}",
            showarrow=True,
            arrowhead=0,
            arrowcolor=PAL["muted"],
            ay=-28,
            ax=0,
            font=dict(color=PAL["muted"], size=11),
        )
    fig = base_layout(fig, "Career per-game trajectory")
    fig.update_layout(margin=dict(r=48))  # room for the end-of-line labels
    fig.update_xaxes(type="category")  # "2003-04" is a season label, not a date
    return fig


def form_chart(
    form: pd.DataFrame,
    stat: str,
    window: int,
    label: str | None = None,
    signed: bool = False,
    accent: str | None = None,
) -> go.Figure:
    """Game-by-game form: raw per-game values plus a rolling average.

    Two things keep this readable at real season length:

    * Density. Past ~32 games, bars in a half-width column collapse into a
      barcode of needles, so the mark switches to dots — the rolling line
      then carries the trend and the dots just show spread.
    * *signed*. For a point margin, each game is colored by the sign of its
      value (win blue / loss red, diverging around a zero baseline) rather
      than above/below the rolling average — a fan reads a margin chart by
      win and loss, not by "above his own average".
    """
    label = label or stat
    values = form[stat]
    dense = len(form) > 32
    if signed:
        colors = [PAL["series"][0] if v >= 0 else PAL["series"][5] for v in values]
    else:
        # games above the rolling average pick up a soft sequential step; the
        # rest recede to the grid tone, so hot streaks pop without a legend read
        above = values >= form["ROLLING"]
        colors = [PAL["seq"][1] if a else PAL["grid"] for a in above]

    fig = go.Figure()
    if dense:
        fig.add_trace(
            go.Scatter(
                x=form["GAME_DATE"],
                y=values,
                name=f"{label} per game",
                mode="markers",
                marker=dict(color=colors, size=6, line=dict(color=PAL["surface"], width=0.5)),
            )
        )
    else:
        fig.add_trace(
            go.Bar(
                x=form["GAME_DATE"],
                y=values,
                name=f"{label} per game",
                marker=dict(color=colors, cornerradius=3),
            )
        )
    # the rolling line rides on top; for a margin it defaults to neutral ink
    # (reads as "trend", not another blue "good" cue beside the win bars) but
    # an accent (e.g. the team's color) gives the trend line identity
    default_line = PAL["ink2"] if signed else PAL["series"][0]
    line = dict(width=2.5, shape="spline", smoothing=0.5, color=accent or default_line)
    roll = go.Scatter(
        x=form["GAME_DATE"],
        y=form["ROLLING"],
        name=f"{window}-game rolling avg",
        mode="lines",
        line=line,
    )
    if not signed:  # a faint fill anchors the scoring trend; skip it for margins
        roll.update(
            fill="tozeroy",
            fillgradient=dict(
                type="vertical",
                colorscale=[
                    (0.0, _rgba(PAL["series"][0], 0.0)),
                    (1.0, _rgba(PAL["series"][0], 0.08)),
                ],
            ),
        )
    fig.add_trace(roll)
    fig = base_layout(fig, f"{label} form, game by game")
    if signed:
        fig.add_hline(y=0, line_color=PAL["muted"], line_width=1)
    return fig


def shot_chart_fig(shots: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(half_court_trace(color=PAL["grid"]))
    for made, label, color, symbol in [
        (0, "Missed", PAL["muted"], "circle-open"),
        (1, "Made", PAL["series"][0], "circle"),
    ]:
        subset = shots[shots["SHOT_MADE_FLAG"] == made]
        fig.add_trace(
            go.Scatter(
                x=subset["LOC_X"],
                y=subset["LOC_Y"],
                name=label,
                mode="markers",
                marker=dict(color=color, size=5, symbol=symbol),
                hovertext=subset.get("SHOT_ZONE_BASIC"),
            )
        )
    fig = base_layout(fig, "Shot chart")
    fig.update_layout(hovermode="closest", height=560)
    fig.update_xaxes(range=[-260, 260], visible=False)
    fig.update_yaxes(range=[-60, 435], visible=False, scaleanchor="x", scaleratio=1)
    return fig


def shot_zone_fig(shots: pd.DataFrame, zones: pd.DataFrame) -> go.Figure:
    """Shots colored by how the player's zone FG% compares to the league."""
    merged = shots.merge(zones, on=ZONE_KEY, how="left")
    fig = go.Figure()
    fig.add_trace(half_court_trace(color=PAL["grid"]))
    buckets = [
        ("Above league", merged["DIFF"] >= 0.02, PAL["series"][0]),
        ("Near league", merged["DIFF"].abs() < 0.02, PAL["muted"]),
        ("Below league", merged["DIFF"] <= -0.02, PAL["series"][5]),
    ]
    for label, mask, color in buckets:
        sub = merged[mask & merged["DIFF"].notna()]
        fig.add_trace(
            go.Scatter(
                x=sub["LOC_X"],
                y=sub["LOC_Y"],
                name=label,
                mode="markers",
                marker=dict(color=color, size=5),
                hovertext=[
                    f"{r.SHOT_ZONE_BASIC}: {r.PLAYER_PCT:.0%} vs league "
                    f"{r.LEAGUE_PCT:.0%} ({int(r.FGA)} att)"
                    for r in sub.itertuples()
                ],
                hoverinfo="text",
            )
        )
    fig = base_layout(fig, "Zone efficiency vs league")
    fig.update_layout(hovermode="closest", height=560)
    fig.update_xaxes(range=[-260, 260], visible=False)
    fig.update_yaxes(range=[-60, 435], visible=False, scaleanchor="x", scaleratio=1)
    return fig


def hex_shot_fig(bins: pd.DataFrame, size: float = 22.0) -> go.Figure:
    """Hot zones, hexbin-style: hexagon size = shot volume, diverging color =
    hex FG% vs the league's expected FG% from those spots.

    Hexes are drawn as layout shapes in court coordinates, so at full
    volume they tile the grid edge-to-edge instead of floating as loose
    pixel-sized markers; an invisible scatter at the centers carries hover
    and the colorbar. *size* must match the hex_bins() grid.
    """
    span = 0.15  # ±15 FG points saturates the scale
    max_fga = float(bins["FGA"].max())
    # shrink each hex's diff toward neutral by its volume: a 2-shot hex at
    # 0-for-2 shouldn't scream as red as a 30-shot cold spot (8 pseudo-shots
    # of league-average shooting mixed into every hex)
    shrunk = bins["DIFF"].fillna(0.0) * (bins["FGA"] / (bins["FGA"] + 8.0))
    corners = [math.radians(90 + 60 * k) for k in range(6)]  # pointy-top
    shapes = []
    for row, diff in zip(bins.itertuples(), shrunk, strict=True):
        r = size * (0.40 + 0.60 * (row.FGA / max_fga) ** 0.5)
        pts = [(row.X + r * math.cos(a), row.Y + r * math.sin(a)) for a in corners]
        shapes.append(
            dict(
                type="path",
                path="M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + " Z",
                fillcolor=_diverging_color(diff, span),
                line=dict(color=PAL["surface"], width=1),
                layer="above",
            )
        )
    # court ink LAST, so the lines read on top of the tiles instead of ghosting
    # underneath them — a trace can't do this, but shapes stack in array order
    shapes.append(
        dict(
            type="path",
            path=half_court_path(),
            line=dict(color=PAL["ink2"], width=1.3),
            layer="above",
        )
    )

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=bins["X"],
            y=bins["Y"],
            mode="markers",
            showlegend=False,
            marker=dict(
                size=18,
                opacity=0,
                color=bins["DIFF"].fillna(0.0),
                cmin=-span,
                cmax=span,
                colorscale=_diverging_colorscale(),
                showscale=True,
                colorbar=dict(
                    title=dict(text="FG% vs league", side="top", font=dict(size=12)),
                    orientation="h",
                    y=-0.04,
                    yanchor="top",
                    x=0.5,
                    len=0.6,
                    thickness=13,
                    tickformat="+.0%",
                    tickvals=[-span, 0, span],
                    ticklabelposition="outside bottom",
                    outlinewidth=0,
                ),
            ),
            customdata=bins[["FGA", "PCT"]].assign(D=bins["DIFF"].fillna(0.0) * 100),
            hovertemplate=(
                "%{customdata[0]:.0f} shots · %{customdata[1]:.0%} FG "
                "(%{customdata[2]:+.0f} vs league)<extra></extra>"
            ),
        )
    )
    fig = base_layout(fig, "Hot zones — size is volume, color is FG% vs league")
    fig.update_layout(hovermode="closest", height=560, shapes=shapes)

    # call out the standout strength: the highest shot-value hot spot (volume ×
    # how far above league), so the chart states its headline instead of making
    # the reader decode every hexagon
    hot = bins[(bins["DIFF"] > 0.03) & (bins["FGA"] >= max(4, 0.15 * max_fga))]
    if not hot.empty:
        pick = hot.loc[(hot["FGA"] * hot["DIFF"]).idxmax()]
        fig.add_annotation(
            x=float(pick["X"]),
            y=float(pick["Y"]),
            text=f"<b>{pick['PCT']:.0%}</b> on {int(pick['FGA'])} shots<br>"
            f"+{pick['DIFF'] * 100:.0f} vs league",
            showarrow=True,
            arrowhead=0,
            arrowwidth=1.2,
            arrowcolor=PAL["ink2"],
            ax=0,
            ay=-46,
            align="center",
            bgcolor=_rgba(PAL["surface"], 0.9),
            bordercolor=PAL["grid"],
            borderpad=4,
            font=dict(color=PAL["ink2"], size=11),
        )
    # crop above the break: heaves past y≈330 are noise, and the tighter
    # frame lets the paint fill the figure
    fig.update_xaxes(range=[-260, 260], visible=False)
    fig.update_yaxes(range=[-55, 330], visible=False, scaleanchor="x", scaleratio=1)
    return fig


def shot_breakdown_fig(breakdown: pd.DataFrame) -> go.Figure:
    """Shot diet by range: bar length is the share of the player's shots,
    color is accuracy vs league (when known), labels carry FG% and points
    per shot — so volume, accuracy, and value read in one glance."""
    df = breakdown.iloc[::-1]  # rim at the top
    has_diff = "DIFF" in df.columns and df["DIFF"].notna().any()
    span = 0.10
    if has_diff:
        colors = [
            _diverging_color(0.0 if pd.isna(d) else float(d), span) for d in df["DIFF"]
        ]
    else:
        colors = PAL["series"][0]
    labels = [
        f"{pct:.0%} · {pps:.2f} PPS" for pct, pps in zip(df["FG_PCT"], df["PPS"], strict=True)
    ]
    fig = go.Figure(
        go.Bar(
            x=df["SHARE"],
            y=df["ZONE"],
            orientation="h",
            marker=dict(color=colors, cornerradius=4),
            text=labels,
            textposition="outside",
            cliponaxis=False,
            customdata=df[["FGA", "FGM"]],
            hovertemplate="%{y}: %{customdata[1]:.0f}/%{customdata[0]:.0f}<extra></extra>",
        )
    )
    fig = base_layout(fig, "Shot diet by range")
    fig.update_layout(hovermode="closest", showlegend=False, height=300, margin=dict(r=110))
    fig.update_xaxes(range=[0, float(df["SHARE"].max()) * 1.35], tickformat=".0%",
                     title="share of shots", gridcolor=PAL["grid"])
    fig.update_yaxes(showgrid=False, automargin=True)  # keep "Above-break 3" from clipping
    return fig


def percentile_chart(ranks: pd.Series, title: str | None = None) -> go.Figure:
    # a full bar to 100 crushes a star's every-stat-elite profile into a wall
    # of near-full bars; a dot on a 0–100 track discriminates by position, so
    # 96 vs 88 reads at a glance, and the dot's color says above/below median
    ranks = ranks.dropna()  # a missing rating would otherwise render a "nan" label
    stats = list(ranks.index)
    fig = go.Figure()
    # the faint 0–100 track each dot sits on — the scale, always in view
    track_x: list[float | None] = []
    track_y: list[str | None] = []
    for s in stats:
        track_x.extend([0.0, 100.0, None])
        track_y.extend([s, s, None])
    fig.add_trace(
        go.Scatter(
            x=track_x, y=track_y, mode="lines", hoverinfo="skip", showlegend=False,
            line=dict(color=PAL["grid"], width=5),
        )
    )
    colors = [PAL["series"][0] if v >= 50 else PAL["series"][5] for v in ranks.values]
    fig.add_trace(
        go.Scatter(
            x=ranks.values,
            y=stats,
            mode="markers+text",
            showlegend=False,
            marker=dict(color=colors, size=15, line=dict(color=PAL["surface"], width=1.5)),
            text=[f"{v:.0f}" for v in ranks.values],
            # label inside-left for near-max dots so it never clips past 100
            textposition=["middle left" if v > 92 else "middle right" for v in ranks.values],
            textfont=dict(color=PAL["ink2"], size=11),
            cliponaxis=False,
            hovertemplate="%{x:.0f}th percentile<extra></extra>",
        )
    )
    fig = base_layout(fig, title or f"League percentile, {current_season()}")
    fig.add_vline(x=50, line_dash="dot", line_color=PAL["muted"], line_width=1)
    fig.add_annotation(
        x=50, y=1.02, yref="paper", text="league median", showarrow=False,
        font=dict(color=PAL["muted"], size=11),
    )
    fig.update_layout(hovermode="closest", showlegend=False, height=110 + 32 * len(ranks))
    fig.update_xaxes(range=[-2, 106], showgrid=False, tickvals=[0, 25, 50, 75, 100])
    fig.update_yaxes(autorange="reversed", showgrid=False, automargin=True)
    return fig


def compare_careers_chart(careers: dict[str, pd.DataFrame], stat: str = "PTS") -> go.Figure:
    fig = go.Figure()
    for i, (name, per_game) in enumerate(careers.items()):
        fig.add_trace(
            go.Scatter(
                x=per_game["SEASON_ID"],
                y=per_game[stat],
                name=name,
                mode="lines+markers",
                line=dict(color=PAL["series"][i], width=2.5, shape="spline", smoothing=0.6),
                marker=dict(size=7, line=dict(color=PAL["surface"], width=1.5)),
            )
        )
    fig = base_layout(fig, f"Career {stat} per game, by season")
    # ascending sort: categories otherwise follow first-seen order, which
    # interleaves wrongly when the players' careers span different years
    fig.update_xaxes(type="category", categoryorder="category ascending")
    return fig


def elo_dot_chart(elo: pd.Series, top: int = 10) -> go.Figure:
    """Power rankings as a dot plot — Elo's origin is arbitrary, so
    zero-based bars would be misleading."""
    ranked = elo.dropna().sort_values(ascending=False).head(top)
    fig = go.Figure(
        go.Scatter(
            x=ranked.values,
            y=ranked.index,
            mode="markers+text",
            marker=dict(
                color=PAL["series"][0], size=12,
                line=dict(color=PAL["surface"], width=1.5),
            ),
            text=[f"{v:.0f}" for v in ranked.values],
            textposition="middle right",
            textfont=dict(color=PAL["muted"]),
        )
    )
    fig = base_layout(fig, f"Elo power rankings — top {top}")
    pad = (ranked.max() - ranked.min()) * 0.18 + 1
    fig.update_layout(hovermode="closest", showlegend=False, height=360)
    fig.update_xaxes(range=[ranked.min() - pad, ranked.max() + pad], showgrid=True,
                     gridcolor=PAL["grid"])
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return fig


def league_landscape_chart(snapshot: pd.DataFrame) -> go.Figure:
    """Every team on offense (x) vs defense (y), the classic NBA quadrant.

    Defense axis is inverted so better defense is *up*: the top-right corner
    is elite on both ends. Dots wear team colors and tricode labels, with
    reference lines at the league averages splitting the four identities.
    """
    df = snapshot.dropna(subset=["form_ortg", "form_drtg"]).copy()
    df["tri"] = df.index.astype(str)
    ox, oy = df["form_ortg"].mean(), df["form_drtg"].mean()

    fig = go.Figure()
    fig.add_vline(x=ox, line_dash="dot", line_color=PAL["muted"], line_width=1)
    fig.add_hline(y=oy, line_dash="dot", line_color=PAL["muted"], line_width=1)
    fig.add_trace(
        go.Scatter(
            x=df["form_ortg"],
            y=df["form_drtg"],
            mode="markers+text",
            text=df["tri"],
            textposition="top center",
            textfont=dict(size=9, color=PAL["ink2"]),
            marker=dict(
                size=14,
                color=[team_color(t) for t in df["tri"]],
                line=dict(color=PAL["surface"], width=1.5),
            ),
            customdata=df[["form_net"]] if "form_net" in df.columns else None,
            hovertemplate=(
                "%{text} — ORtg %{x:.1f}, DRtg %{y:.1f}"
                + (" (net %{customdata[0]:+.1f})" if "form_net" in df.columns else "")
                + "<extra></extra>"
            ),
        )
    )
    # name the four corners (y is reversed, so "top" = strong defense)
    span_x, span_y = df["form_ortg"], df["form_drtg"]
    for xq, yq, ax, ay, txt in [
        (span_x.max(), span_y.min(), "right", "top", "elite both ends"),
        (span_x.min(), span_y.min(), "left", "top", "defense-first"),
        (span_x.max(), span_y.max(), "right", "bottom", "offense-first"),
        (span_x.min(), span_y.max(), "left", "bottom", "rebuilding"),
    ]:
        fig.add_annotation(
            x=xq, y=yq, text=txt, showarrow=False, xanchor=ax, yanchor=ay,
            font=dict(size=10, color=PAL["muted"]),
        )
    fig = base_layout(fig, "League landscape — offense vs defense")
    fig.update_layout(hovermode="closest", showlegend=False, height=520)
    fig.update_xaxes(title="Offensive rating →", gridcolor=PAL["grid"])
    fig.update_yaxes(
        title="← Defensive rating (better is up)",
        autorange="reversed",
        gridcolor=PAL["grid"],
    )
    return fig


def net_rating_chart(snapshot: pd.DataFrame, n: int = 5) -> go.Figure:
    """Best and worst teams by season-to-date net rating; diverging around 0."""
    net = snapshot["form_net"].dropna().sort_values(ascending=False)
    ends = pd.concat([net.head(n), net.tail(n)])
    colors = [PAL["series"][0] if v > 0 else PAL["series"][5] for v in ends.values]
    fig = go.Figure(
        go.Bar(
            x=ends.values,
            y=ends.index,
            orientation="h",
            marker=dict(color=colors, cornerradius=3),
            text=[f"{v:+.1f}" for v in ends.values],
            textposition="outside",
            cliponaxis=False,
        )
    )
    fig = base_layout(fig, f"Net rating — best and worst {n}")
    fig.update_layout(hovermode="closest", showlegend=False, height=360)
    pad = float(ends.abs().max()) * 0.25  # room for the outside labels
    fig.update_xaxes(
        range=[ends.min() - pad, ends.max() + pad],
        zeroline=True,
        zerolinecolor=PAL["muted"],
        gridcolor=PAL["grid"],
    )
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return fig


def win_prob_bar(home: str, away: str, prob: float) -> None:
    """One shared probability track — home fill vs away fill, labeled ends.

    Replaces twin metrics: a single mark makes the complementarity obvious
    and the favourite readable at a glance. The away side is neutral gray,
    not red — red stays reserved for "below/negative" app-wide, and an away
    team isn't bad.
    """
    st.markdown(
        f"""
<div class="duel">
  <div class="duel-labels">
    <span><b>{home}</b> win probability (home) · <b>{prob:.0%}</b></span>
    <span><b>{1 - prob:.0%}</b> · {away} (away)</span>
  </div>
  <div class="duel-track">
    <div style="width:{prob * 100:.1f}%; background:{PAL["series"][0]};"></div>
    <div style="width:{(1 - prob) * 100:.1f}%; background:{PAL["muted"]};"></div>
  </div>
</div>""",
        unsafe_allow_html=True,
    )


def matchup_header(
    home: str, away: str, prob: float, tri_to_id: pd.Series, snapshot: pd.DataFrame
) -> None:
    """A matchup card: both team logos flanking the win probability, then the
    shared probability track and a compact home-vs-away form comparison — so
    the prediction reads as a game, not a lone bar."""
    left, center, right = st.columns([3, 2, 3], vertical_alignment="center")
    for col, team, side in ((left, home, "home"), (right, away, "away")):
        with col:
            logo_col, name_col = st.columns([1, 2], vertical_alignment="center")
            logo = fetch_team_logo(int(tri_to_id[team])) if team in tri_to_id.index else None
            if logo:
                logo_col.image(logo, width=72)
            name_col.markdown(
                f"<div class='mu-abbr' style='color:{team_color(team)}'>{team}</div>"
                f"<div class='mu-side'>{side}</div>",
                unsafe_allow_html=True,
            )
    center.markdown(
        f"<div class='mu-prob'>{prob:.0%}</div>"
        f"<div class='mu-vs'>{home} win probability</div>",
        unsafe_allow_html=True,
    )
    win_prob_bar(home, away, prob)

    # compact form context — lower Def rating is better, so no "winner" tint
    rows = {
        "Net rating": ("form_net", "{:+.1f}"),
        "Off rating": ("form_ortg", "{:.1f}"),
        "Def rating": ("form_drtg", "{:.1f}"),
        "Elo": ("elo", "{:.0f}"),
    }
    data = {}
    for team in (home, away):
        data[team] = [
            fmt.format(snapshot.loc[team, col])
            if col in snapshot.columns and pd.notna(snapshot.loc[team, col])
            else "—"
            for col, fmt in rows.values()
        ]
    st.dataframe(pd.DataFrame(data, index=list(rows)), width="stretch")


# profile badge labels: stat code -> plain-language skill
_BADGE_LABELS = {
    "PTS": "Scoring",
    "AST": "Playmaking",
    "REB": "Rebounding",
    "STL": "Steals",
    "BLK": "Rim protection",
    "FG%": "Shooting efficiency",
    "3P%": "3-point shooting",
    "FT%": "Free throws",
    "NET RTG": "Impact",
    "CLUTCH NET": "Clutch",
}


def skill_badges(ranks: pd.Series, floor: float = 85.0, top: int = 4) -> None:
    """Percentile-derived skill pills — the profile's TL;DR.

    Shows up to *top* stats at or above the *floor* percentile; players
    without an elite skill this season simply get no pill row.
    """
    elite = ranks[ranks >= floor].sort_values(ascending=False).head(top)
    if elite.empty:
        return
    pills = "".join(
        f'<span class="pill"><b>{_BADGE_LABELS.get(str(stat), str(stat))}</b>'
        f" · {value:.0f}th pct</span>"
        for stat, value in elite.items()
    )
    st.markdown(
        f'<div class="pills"><span class="pills-lead">Elite this season</span>{pills}</div>',
        unsafe_allow_html=True,
    )


def scouting_callout(text: str, accent: str | None = None) -> None:
    """A one-line rule-based read of the entity, in an accented card — the
    'so what' the numbers add up to (see analysis.insights). *accent* tints
    the border and tag (e.g. a team's color) for identity."""
    style = ""
    if accent:
        style = (
            f' style="border-left-color:{accent}; '
            f'background:{_rgba(accent, 0.07)};"'
        )
        tag = f'<span class="scout-tag" style="color:{accent}">Scouting take</span>'
    else:
        tag = '<span class="scout-tag">Scouting take</span>'
    st.markdown(f'<div class="scout"{style}>{tag}{text}</div>', unsafe_allow_html=True)


def pick_player(client: NBAClient, label: str, key: str) -> dict | None:
    query = st.text_input(label, key=key, placeholder="e.g. LeBron James")
    if not query:
        return None
    if len(query) < 3:
        st.caption("Keep typing — search needs at least 3 characters.")
        return None
    matches = client.search_players(query)
    if not matches:
        st.warning(f"No player matching “{query}”.")
        return None
    if len(matches) == 1:
        return matches[0]
    names = {m["full_name"]: m for m in matches}
    choice = st.selectbox("Multiple matches — pick one", list(names), key=f"{key}_pick")
    return names[choice]


def profile_header(
    player: dict,
    totals: pd.DataFrame,
    per_game: pd.DataFrame,
    ratings: pd.Series | None = None,
    draft_note: str | None = None,
    salary_note: str | None = None,
) -> None:
    """Headshot, team context, and headline stat tiles with career deltas."""
    latest_totals = totals[totals["GP"] > 0].sort_values("SEASON_ID").iloc[-1]
    latest = per_game.iloc[-1]

    photo, info = st.columns([1, 4], vertical_alignment="center")
    with photo:
        headshot = fetch_headshot(player["id"])
        if headshot:
            st.image(headshot, width=190)
    with info:
        st.subheader(player["full_name"])
        team = latest_totals.get("TEAM_ABBREVIATION", "")
        context = f"{team} · {latest['SEASON_ID']} · {int(latest['GP'])} games"
        if draft_note:
            context += f" · {draft_note}"
        if salary_note:
            context += f" · {salary_note}"
        st.caption(context)

        has_ratings = ratings is not None and pd.notna(ratings.get("NET_RATING"))
        has_dpm = ratings is not None and pd.notna(ratings.get("DPM"))
        # two rows of three, not one cramped row of six — the delta text
        # ("+5.8 vs career") truncates below ~180px per tile
        tiles = st.columns(3)
        career_games = totals["GP"].sum()
        for col, stat in zip(tiles, ("PTS", "AST", "REB"), strict=False):
            career_avg = totals[stat].sum() / career_games if career_games else 0
            col.metric(
                f"{stat} / game",
                f"{latest[stat]:.1f}",
                delta=f"{latest[stat] - career_avg:+.1f} vs career",
            )
        if has_ratings or has_dpm:
            row = st.columns(3)
            if has_ratings:
                row[0].metric("Net rating", f"{ratings['NET_RATING']:+.1f}")
                clutch = ratings.get("CLUTCH_NET_RATING")
                row[1].metric(
                    "Clutch net",
                    f"{clutch:+.1f}" if pd.notna(clutch) else "—",
                    help="Net rating in the last 5 minutes with the score within 5 points.",
                )
            if has_dpm:
                row[2].metric(
                    "DARKO DPM",
                    f"{ratings['DPM']:+.1f}",
                    help="Daily plus-minus projection from darko.app "
                    "(K. Medvedovsky & A. Patton).",
                )


def shot_quality_tiles(
    client: NBAClient, shots: pd.DataFrame, season: str, season_type: str
) -> None:
    """Expected vs actual eFG% under the shot chart: selection vs making."""
    try:
        sq = shot_quality(
            shots, client.shot_league_averages(season=season, season_type=season_type)
        )
    except Exception:
        logger.warning("shot quality unavailable", exc_info=True)
        return
    if not sq["FGA"] or pd.isna(sq["EFG"]):
        return
    cols = st.columns(3)
    cols[0].metric(
        "Shot diet (xeFG%)",
        f"{sq['XEFG'] * 100:.1f}%",
        help="The eFG% a league-average shooter would post on this player's "
        "shot locations — higher means better shot selection.",
    )
    cols[1].metric("Actual eFG%", f"{sq['EFG'] * 100:.1f}%")
    cols[2].metric(
        "Shot making",
        f"{sq['MAKING'] * 100:+.1f}",
        help="Actual minus expected eFG%, in points of eFG — finishing above "
        "or below what the shot locations alone predict.",
    )
    if pd.notna(sq["LEAGUE_EFG"]):
        st.caption(f"League eFG% this {season_type.lower()}: {sq['LEAGUE_EFG'] * 100:.1f}%.")


def on_off_tiles(client: NBAClient, player: dict, totals: pd.DataFrame) -> None:
    """Team net rating with the player on vs off the floor this season."""
    try:
        latest = totals[totals["GP"] > 0].sort_values("SEASON_ID").iloc[-1]
        team_id = int(latest.get("TEAM_ID", 0))
        if not team_id:  # a TOT row after a mid-season trade has no team
            return
        table = team_on_off(client.team_player_on_off(team_id))
        row = table[table["PLAYER_ID"] == player["id"]]
    except Exception:
        logger.warning("on/off splits unavailable for profile", exc_info=True)
        return
    if row.empty:
        return
    r = row.iloc[0]
    if pd.isna(r["NET_DIFF"]):
        return
    cols = st.columns(3)
    cols[0].metric("Team net, on floor", f"{r['NET_ON']:+.1f}")
    cols[1].metric("Team net, off floor", f"{r['NET_OFF']:+.1f}")
    cols[2].metric(
        "On/off swing",
        f"{r['NET_DIFF']:+.1f}",
        help="Team net rating with the player on court minus off court. "
        "Raw minutes, no lineup adjustment — bench context matters.",
    )
    st.caption(
        f"{current_season()} · {r['MIN_ON']:,.0f} min on / {r['MIN_OFF']:,.0f} min off."
    )


def contract_section(player: dict, contracts: pd.DataFrame | None) -> None:
    """Season-by-season contract breakdown from the scraped B-Ref table.

    Local personal-use data (see ingest.salaries) — shown only in this app.
    """
    if contracts is None:
        return
    try:
        row = player_contract(contracts, player["full_name"])
    except KeyError:
        return
    seasons = salary_seasons(contracts)
    salaries = pd.to_numeric(row[seasons], errors="coerce").dropna()
    if salaries.empty:
        return
    # surfaced inline (not tucked in an expander) so the salary chart is visible
    st.subheader("Contract & salary")
    tiles = st.columns(3)
    tiles[0].metric(f"Salary, {salaries.index[0]}", f"${salaries.iloc[0] / 1e6:.2f}M")
    tiles[1].metric(
        "Committed total",
        f"${salaries.sum() / 1e6:.2f}M",
        delta=f"{len(salaries)} season{'s' if len(salaries) > 1 else ''}",
        delta_color="off",
    )
    guaranteed = row.get("GUARANTEED")
    tiles[2].metric(
        "Guaranteed",
        f"${guaranteed / 1e6:.2f}M" if pd.notna(guaranteed) else "—",
        help="Total guaranteed money remaining on the deal.",
    )
    fig = go.Figure(
        go.Bar(
            x=list(salaries.index),
            y=salaries.values / 1e6,
            marker=dict(color=PAL["series"][0], cornerradius=4),
            text=[f"${v / 1e6:.1f}M" for v in salaries.values],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{x}: $%{y:.2f}M<extra></extra>",
        )
    )
    fig = base_layout(fig, "Salary by season")
    fig.update_layout(hovermode="closest", showlegend=False, height=300, margin=dict(t=60))
    fig.update_xaxes(type="category")
    fig.update_yaxes(tickprefix="$", ticksuffix="M", gridcolor=PAL["grid"])
    st.plotly_chart(fig, width="stretch", key="profile_contract")
    st.caption(
        "Contract data scraped weekly from Basketball-Reference; "
        "personal use only. Blank future seasons mean no committed money."
    )


# split dimension -> (menu label, help caption)
_SPLIT_CHOICES = {
    "Home / Away": "home_away",
    "By month": "month",
    "By rest": "rest",
    "By opponent": "opponent",
}
_SPLIT_PCT = {"FG_PCT": "FG%", "FG3_PCT": "3P%", "FT_PCT": "FT%"}


def splits_section(log: pd.DataFrame) -> None:
    """Situational splits — home/away, monthly, by rest, by opponent — reshaped
    from the game log the profile already loaded."""
    st.subheader("Splits")
    st.caption("How the season breaks down by situation. Shooting % is aggregate, not per-game.")
    choice = st.radio(
        "Split by", list(_SPLIT_CHOICES), horizontal=True, label_visibility="collapsed",
        key="splits_dim",
    )
    try:
        table = player_splits(log, _SPLIT_CHOICES[choice])
    except Exception as e:
        st.caption(f"Splits unavailable: {e}")
        return
    if table.empty:
        st.caption("Not enough games for this split yet.")
        return
    # show shooting fractions as percentage points (0.482 -> 48.2)
    show = table.rename(columns={**STAT_LABELS, **_SPLIT_PCT, "FG3M": "3PM", "PLUS_MINUS": "+/-"})
    for pct in _SPLIT_PCT.values():
        if pct in show.columns:
            show[pct] = (show[pct] * 100).round(1)
    st.dataframe(
        show,
        width="stretch",
        hide_index=True,
        height=min(430, 44 + 36 * len(show)),
        column_config={
            "Split": st.column_config.TextColumn(width="medium"),
            "+/-": st.column_config.NumberColumn(format="%+.1f"),
            **{p: st.column_config.NumberColumn(format="%.1f%%") for p in _SPLIT_PCT.values()},
        },
    )


def clutch_shooting_section(
    client: NBAClient, player: dict, season: str, season_type: str
) -> None:
    """A clutch shooting line — how a player shoots in the last 5 min, margin <=5.

    The one situational split the game log can't give us (clutch is per-possession
    within games), so it comes from the league clutch (Base) table.
    """
    try:
        clutch = client.league_player_clutch_base(season=season, season_type=season_type)
        line = clutch_shooting_line(clutch, player["id"])
    except Exception:
        logger.warning("clutch shooting unavailable", exc_info=True)
        return
    if not line:
        return

    st.subheader("Clutch shooting")
    st.caption(
        "Shooting in the last 5 minutes with the score within 5 points"
        + (f" · {int(line['GP'])} clutch games" if line.get("GP") else "")
        + "."
    )
    cells = [
        ("eFG%", line.get("EFG_PCT")),
        ("FG%", line.get("FG_PCT")),
        ("3P%", line.get("FG3_PCT")),
        ("FT%", line.get("FT_PCT")),
        ("PTS", line.get("PTS")),
    ]
    cols = st.columns(len(cells))
    for col, (label, value) in zip(cols, cells, strict=True):
        if value is None:
            col.metric(label, "—")
        elif label == "PTS":
            col.metric(label, f"{value:.1f}")
        else:
            col.metric(label, f"{value * 100:.1f}%")


@st.fragment
def season_detail(client: NBAClient, player: dict, seasons: list[str]) -> None:
    """Season-scoped charts; a fragment so switching season or stat only
    re-renders this section instead of rerunning the whole page."""
    pick = st.columns([3, 2])
    season = pick[0].selectbox("Season", list(reversed(seasons)))
    games_kind = pick[1].radio("Games", ["Regular season", "Playoffs"], horizontal=True)
    season_type = "Playoffs" if games_kind == "Playoffs" else "Regular Season"

    # charts stacked vertically (full width) rather than squeezed side by side
    st.subheader("Game-by-game form")
    stat = st.selectbox("Form stat", ["PTS", "AST", "REB", "STL", "BLK"])
    try:
        log = client.game_log(player["id"], season=season, season_type=season_type)
        if log.empty:
            st.info(f"No {games_kind.lower()} games logged for this season.")
        else:
            window = min(10, max(2, len(log) // 3))
            st.plotly_chart(
                form_chart(rolling_form(log, stat, window), stat, window),
                width="stretch",
                key="profile_form",
            )
            with st.expander(f"Game log ({len(log)} games)"):
                st.dataframe(
                    game_log_table(log),
                    width="stretch",
                    hide_index=True,
                    height=380,
                    column_config={
                        "DATE": st.column_config.DateColumn("DATE", format="MMM DD"),
                        "+/-": st.column_config.NumberColumn(format="%+d"),
                    },
                )
            splits_section(log)
            clutch_shooting_section(client, player, season, season_type)
    except Exception as e:
        st.error(f"Could not load game log: {e}")

    st.subheader("Shooting")
    view = st.radio(
        "Shot view", ["Hot zones", "Makes & misses", "Zones vs league"], horizontal=True
    )
    try:
        shots = client.shot_chart(player["id"], season=season, season_type=season_type)
        if shots.empty:
            st.info(f"No {games_kind.lower()} shot data for this season.")
        elif view == "Hot zones":
            bins = hex_bins(
                shots,
                client.shot_league_averages(season=season, season_type=season_type),
                min_fga=3,  # drop 1–2 attempt speckle in the midrange
            )
            if bins.empty:
                st.plotly_chart(shot_chart_fig(shots), width="stretch", key="profile_shots")
            else:
                st.plotly_chart(hex_shot_fig(bins), width="stretch", key="profile_shots")
                st.caption(
                    "Each hexagon groups nearby attempts: bigger means more "
                    "shots, blue means finishing above the league's FG% from "
                    "those spots, red below."
                )
        elif view == "Zones vs league":
            zones = zone_efficiency(
                shots, client.shot_league_averages(season=season, season_type=season_type)
            )
            st.plotly_chart(shot_zone_fig(shots, zones), width="stretch", key="profile_shots")
            st.caption(
                "Color compares the player's FG% in each zone to the league "
                "(±2 percentage points counts as even)."
            )
        else:
            st.plotly_chart(shot_chart_fig(shots), width="stretch", key="profile_shots")
        if not shots.empty:
            shot_quality_tiles(client, shots, season, season_type)
            try:
                breakdown = shot_breakdown(
                    shots,
                    client.shot_league_averages(season=season, season_type=season_type),
                )
                if not breakdown.empty:
                    # surfaced inline (not hidden in an expander): it's a graph
                    st.plotly_chart(
                        shot_breakdown_fig(breakdown),
                        width="stretch",
                        key="profile_breakdown",
                    )
                    st.caption(
                        "Bar length is the share of this player's shots from "
                        "each range; color is FG% vs league (blue above, red "
                        "below); labels show FG% and points per shot."
                    )
            except Exception:
                logger.warning("shot breakdown unavailable", exc_info=True)
    except Exception as e:
        st.error(f"Could not load shot chart: {e}")


def _leaderboard_card(label: str, board: pd.DataFrame, stat: str) -> str:
    """One category's top-ten as a compact ranked-list card (HTML)."""
    from html import escape

    lis = []
    for i, (_, r) in enumerate(board.iterrows(), start=1):
        value = f"{r[stat]:+.1f}" if "RATING" in stat else f"{r[stat]:.1f}"
        lis.append(
            f"<li><span class='lb-rank'>{i}</span>"
            f"<span class='lb-name'>{escape(str(r['PLAYER_NAME']))}</span>"
            f"<span class='lb-val'>{value}</span></li>"
        )
    return (
        f"<div class='lb-card'><div class='lb-title'>{escape(label)}</div>"
        f"<ol class='lb-list'>{''.join(lis)}</ol></div>"
    )


def _fill_widgets(**values: str) -> None:
    """on_click callback: pre-fill search inputs before the next run."""
    st.session_state.update(values)


def leader_suggestions(client: NBAClient, *keys: str) -> None:
    """Clickable current-scoring-leader chips that fill the search box(es)."""
    try:
        leaders = league_leaders(client.league_player_stats(), "PTS", top=5)
    except Exception:
        return
    names = list(leaders["PLAYER_NAME"])
    if len(keys) == 1:
        st.caption("Or jump straight to a scoring leader:")
        for col, name in zip(st.columns(len(names)), names, strict=True):
            col.button(
                name,
                key=f"suggest_{keys[0]}_{name}",
                on_click=_fill_widgets,
                kwargs={keys[0]: name},
                width="stretch",
            )
    elif len(names) >= 2:
        st.button(
            f"Try {names[0]} vs {names[1]}",
            on_click=_fill_widgets,
            kwargs=dict(zip(keys, names[:2], strict=False)),
        )


def profile_page(client: NBAClient) -> None:
    # a drill-down (leaderboard/roster/comps click) stashes the target here;
    # seed the search widget before it's created (its key can't be set after)
    pending = st.session_state.pop("_pending_profile", None)
    if pending is not None:
        st.session_state["profile_search"] = pending
    player = pick_player(client, "Search for a player", "profile_search")
    if not player:
        st.info("Type a player name to build their profile.")
        leader_suggestions(client, "profile_search")
        return

    with st.spinner("Loading career stats…"):
        totals = client.career_stats(player["id"])
    if totals.empty:
        st.error("No career data found for this player.")
        return

    per_game = career_per_game(totals)
    ratings, ranks, take = None, None, ""
    if player["is_active"]:
        try:
            league = league_with_ratings(client)
            row = league[league["PLAYER_ID"] == player["id"]]
            ratings = row.iloc[0] if not row.empty else None
            raw_ranks = percentile_ranks(league, player["full_name"])
            take = player_scouting_take(raw_ranks)  # takes the raw stat codes
            ranks = raw_ranks.rename(STAT_LABELS)
        except KeyError:
            ranks = None  # not enough games for league ranks this season
        except Exception:
            logger.warning("league ratings unavailable for profile", exc_info=True)
    draft_note = None
    try:
        draft_note = player_draft_line(client.draft_history(), player["id"])
    except Exception:
        logger.warning("draft history unavailable for profile", exc_info=True)
    salary_note = None
    contracts = contracts_table(client)
    if contracts is not None:
        try:
            row = attach_salary(pd.DataFrame({"PLAYER_NAME": [player["full_name"]]}), contracts)
            salary = row["SALARY"].iloc[0] if "SALARY" in row.columns else None
            if pd.notna(salary):
                salary_note = f"${salary / 1e6:.1f}M in {salary_seasons(contracts)[0]}"
        except Exception:
            logger.warning("salary lookup failed for profile", exc_info=True)
    profile_header(player, totals, per_game, ratings, draft_note, salary_note)
    # narrative take first (the headline), then the percentile pills reinforce it
    if take:
        scouting_callout(take)
    if ranks is not None:
        skill_badges(ranks)
    if player["is_active"]:
        on_off_tiles(client, player, totals)
        contract_section(player, contracts)

    seasons = list(per_game["SEASON_ID"])
    st.plotly_chart(career_chart(per_game), width="stretch", key="profile_career")

    season_detail(client, player, seasons)

    percentile_section(client, player, seasons)

    comps_section(client, player)


def comps_section(client: NBAClient, player: dict) -> None:
    """Statistical comparables — 'players like X' — with click-through to
    each comp's profile. Current-season only, so retired players get none."""
    try:
        league = league_with_ratings(client)
        comps = similar_players(league, player["full_name"], n=8)
    except KeyError:
        return  # not in this season's pool (retired / too few minutes)
    except Exception:
        logger.warning("player comps unavailable", exc_info=True)
        return
    if comps.empty:
        return
    st.subheader("Similar players")
    st.caption(
        "Statistical comps by per-36 rates and shooting profile, standardized "
        "across the league. Click a player to open their profile."
    )
    display = comps.rename(
        columns={"PLAYER_NAME": "PLAYER", "TEAM_ABBREVIATION": "TEAM", "SIMILARITY": "MATCH"}
    )
    event = st.dataframe(
        display[["PLAYER", "TEAM", "MATCH", "PTS", "REB", "AST"]],
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="comps_table",
        column_config={
            "MATCH": st.column_config.ProgressColumn(
                "MATCH", min_value=0.0, max_value=100.0, format="%.0f%%"
            ),
            "PTS": st.column_config.NumberColumn(format="%.1f"),
            "REB": st.column_config.NumberColumn(format="%.1f"),
            "AST": st.column_config.NumberColumn(format="%.1f"),
        },
    )
    if event.selection.rows:
        open_profile(str(comps.iloc[event.selection.rows[0]]["PLAYER_NAME"]))


@st.fragment
def percentile_section(client: NBAClient, player: dict, seasons: list[str]) -> None:
    """League percentile ranks for any of the player's seasons since 1996-97.

    Retired players get their historical seasons too — the league
    dashboards go back that far, so 1997-98 Jordan ranks against the
    1997-98 league.
    """
    options = [s for s in seasons if s in set(seasons_since())]
    if not options:
        st.caption("League percentile ranks cover seasons from 1996-97 onward.")
        return
    head = st.columns([3, 2])
    season = head[0].selectbox("Percentile season", list(reversed(options)), key="pct_season")
    scope = head[1].radio(
        "Compare against", ["League", "Position"], horizontal=True, key="pct_scope"
    )
    try:
        league = league_with_ratings(client, None if season == current_season() else season)
        if scope == "Position":
            raw, group = positional_percentile_ranks(league, player["full_name"])
            ranks = raw.rename(STAT_LABELS)
            title = f"Percentile vs {group}s, {season}"
        else:
            ranks = percentile_ranks(league, player["full_name"]).rename(STAT_LABELS)
            title = f"League percentile, {season}"
    except KeyError:
        st.caption(f"Not enough games in {season} for percentile ranks.")
        return
    except Exception as e:
        st.caption(f"Percentiles unavailable: {e}")
        return
    st.plotly_chart(percentile_chart(ranks, title=title), width="stretch", key="profile_pct")
    if scope == "Position":
        st.caption(
            f"Ranked against other {group}s. Position is inferred from role stats "
            "(rebounding, blocks, assists, shot profile), so it's a rough grouping — "
            "a playmaking or stretch big may straddle two positions."
        )


# stats where a smaller number wins the row
_LOWER_BETTER = {"TOV"}
# count stats shown as whole numbers; every other row gets a fixed 2 decimals
# so a row never mixes "4" with "3.70" (per-value rounding did exactly that)
_INTEGER_STATS = {"GP"}


def _best_value_style(table: pd.DataFrame):
    """Tint the best value in each stat row so the table answers 'who wins
    this stat' without reading every number. Ink stays the text color; the
    tinted background carries the highlight."""
    tint = f"background: {PAL['series'][0]}22; font-weight: 600;"

    def highlight(row: pd.Series) -> list[str]:
        values = row.dropna()
        if values.empty:
            return ["" for _ in row]
        best = values.min() if row.name in _LOWER_BETTER else values.max()
        return [tint if pd.notna(v) and v == best else "" for v in row]

    # format per row, not per value: count rows whole, all others fixed 2dp
    styler = table.style.apply(highlight, axis=1)
    int_rows = [r for r in table.index if r in _INTEGER_STATS]
    float_rows = [r for r in table.index if r not in _INTEGER_STATS]
    if int_rows:
        styler = styler.format("{:,.0f}", subset=pd.IndexSlice[int_rows, :], na_rep="—")
    if float_rows:
        styler = styler.format("{:,.2f}", subset=pd.IndexSlice[float_rows, :], na_rep="—")
    return styler


def compare_page(client: NBAClient) -> None:
    st.caption(
        "Career averages, plus this season's league percentiles. "
        "Compare up to four players."
    )
    labels = ["First player", "Second player", "Third (optional)", "Fourth (optional)"]
    keys = ["cmp_a", "cmp_b", "cmp_c", "cmp_d"]
    picks = []
    for col, label, key in zip(st.columns(4), labels, keys, strict=True):
        with col:
            picks.append(pick_player(client, label, key))
    players, seen = [], set()
    for p in picks:
        if p and p["id"] not in seen:
            players.append(p)
            seen.add(p["id"])
    if len(players) < 2:
        st.info("Pick at least two players to compare.")
        leader_suggestions(client, "cmp_a", "cmp_b")
        return
    # career averages (works for retired players too), raw stat codes as index
    try:
        totals_by = {p["full_name"]: client.career_stats(p["id"]) for p in players}
        table = pd.DataFrame({name: career_averages(t) for name, t in totals_by.items()})
        careers = {name: career_per_game(t) for name, t in totals_by.items()}
        row_order = [
            s
            for s in ("GP", "MIN", "PTS", "AST", "REB", "STL", "BLK", "TOV",
                      "FG_PCT", "FG3_PCT", "FT_PCT")
            if s in table.index
        ]
        table = table.loc[row_order]
    except Exception as e:
        st.error(f"Could not load career comparison: {e}")
        return
    st.subheader("Career averages")
    display = table.copy()
    pct_rows = [r for r in ("FG_PCT", "FG3_PCT", "FT_PCT") if r in display.index]
    display.loc[pct_rows] *= 100  # percent stats read as percentages
    st.dataframe(_best_value_style(display.rename(index=STAT_LABELS)), width="stretch")
    st.caption("Career per-game averages; FG%/3P%/FT% are volume-weighted over the career.")
    st.download_button(
        "Download share poster (PNG)",
        compare_poster_png(table, "Career"),
        file_name=f"{' vs '.join(table.columns)}.png",
        mime="image/png",
        help="1080×1080 image of this comparison, ready to post.",
    )

    # season-by-season: one row per season, a column per player, for a stat
    st.subheader("Season by season")
    season_stats = [s for s in ("PTS", "AST", "REB", "STL", "BLK", "TOV", "MIN")
                    if any(s in c.columns for c in careers.values())]
    stat = st.selectbox(
        "Stat", season_stats, format_func=lambda s: STAT_LABELS.get(s, s), key="cmp_season_stat"
    )
    season_tbl = pd.DataFrame(
        {name: cpg.set_index("SEASON_ID")[stat] for name, cpg in careers.items()
         if stat in cpg.columns}
    ).sort_index(ascending=False)
    season_tbl.index.name = "Season"
    st.dataframe(
        season_tbl,
        width="stretch",
        column_config={
            c: st.column_config.NumberColumn(format="%.1f") for c in season_tbl.columns
        },
    )
    if all(not df.empty for df in careers.values()):
        st.plotly_chart(compare_careers_chart(careers), width="stretch", key="cmp_careers")

    # league percentiles are this-season only, so this needs active players
    try:
        league = league_with_ratings(client)
        ranks = pd.concat(
            [percentile_ranks(league, p["full_name"]).rename(STAT_LABELS) for p in players],
            axis=1,
        )
    except KeyError:
        st.caption("League percentiles need every player active this season — skipped.")
        ranks = None
    except Exception as e:
        st.caption(f"League percentiles unavailable: {e}")
        ranks = None
    if ranks is not None:
        # dot-strip rows instead of grouped bars: one row per stat, a hairline
        # connecting each row's spread, a ringed dot per player
        fig = go.Figure()
        xs: list[float | None] = []
        ys: list[str | None] = []
        for stat in ranks.index:
            row = ranks.loc[stat].dropna()
            if row.empty:
                continue
            xs.extend([float(row.min()), float(row.max()), None])
            ys.extend([stat, stat, None])
        fig.add_trace(
            go.Scatter(
                x=xs, y=ys, mode="lines", showlegend=False, hoverinfo="skip",
                line=dict(color=PAL["grid"], width=2),
            )
        )
        for i, name in enumerate(ranks.columns):
            fig.add_trace(
                go.Scatter(
                    x=ranks[name].values,
                    y=ranks.index,
                    mode="markers",
                    name=name,
                    marker=dict(
                        color=PAL["series"][i], size=11,
                        line=dict(color=PAL["surface"], width=1.5),
                    ),
                    hovertemplate=f"{name}: %{{x:.0f}}th pct<extra></extra>",
                )
            )
        fig = base_layout(fig, "League percentile this season, head to head")
        fig.add_vline(x=50, line_dash="dot", line_color=PAL["muted"], line_width=1)
        fig.update_layout(hovermode="closest")
        fig.update_xaxes(range=[-3, 103], showgrid=True, gridcolor=PAL["grid"])
        fig.update_yaxes(autorange="reversed", automargin=True, showgrid=False)
        st.plotly_chart(fig, width="stretch", key="cmp_pct")

    st.subheader("Shot quality (xeFG), this season")
    try:
        league_avgs = client.shot_league_averages()
        quality = pd.concat(
            {
                p["full_name"]: shot_quality(client.shot_chart(p["id"]), league_avgs)
                for p in players
            },
            axis=1,
        )
        sq_table = (quality.loc[["XEFG", "EFG", "MAKING"]] * 100).rename(
            index={
                "XEFG": "Shot diet (xeFG%)",
                "EFG": "Actual eFG%",
                "MAKING": "Shot making (eFG pts)",
            }
        )
        st.dataframe(_best_value_style(sq_table.round(2)), width="stretch")
        st.caption(
            "xeFG% is the eFG% a league-average shooter would post on each "
            "player's shot locations; shot making is actual minus expected. "
            "Current-season shots; per-season shot quality lives on each player's profile."
        )
    except Exception as e:
        st.caption(f"Shot quality unavailable: {e}")


@st.cache_resource
def load_models() -> dict | None:
    if not (OUTCOME_PATH.exists() and POINTS_PATH.exists() and WIN_CURVE_PATH.exists()):
        return None
    return {
        "outcome": GameOutcomeModel.load(OUTCOME_PATH),
        "points": PlayerPointsModel.load(POINTS_PATH),
        "curve": WinCurve.load(WIN_CURVE_PATH),
        "metrics": _load_metrics(),
    }


def _load_metrics() -> dict:
    """Holdout metrics recorded by ml.train — the single source of truth
    for every number quoted in captions. Empty when trained before
    metrics.json existed."""
    try:
        return json.loads(METRICS_PATH.read_text())
    except Exception:
        return {}


def _outcome_record(models: dict) -> str:
    """Holdout sentence for the outcome model, from recorded metrics."""
    metrics = models.get("metrics") or {}
    o = metrics.get("outcome")
    if not o:
        return ""
    return (
        f" Holdout accuracy on {metrics.get('holdout_season', 'the current season')}: "
        f"{o['accuracy']:.1%} (always-pick-home scores {o['baseline_accuracy']:.1%})."
    )


def missing_minutes_picker(
    league: pd.DataFrame, home: str, away: str, key_prefix: str
) -> dict[str, float]:
    """Two per-team multiselects; returns expected minutes out per team."""
    missing = {}
    for col, team in zip(st.columns(2), (home, away), strict=True):
        roster = league[league["TEAM_ABBREVIATION"] == team].sort_values(
            "MIN", ascending=False
        )
        out = col.multiselect(
            f"{team} out", list(roster["PLAYER_NAME"]), key=f"{key_prefix}_{team}"
        )
        missing[team] = float(roster.loc[roster["PLAYER_NAME"].isin(out), "MIN"].sum())
    return missing


@st.fragment
def outcome_tab(client: NBAClient, models: dict, snapshot: pd.DataFrame) -> None:
    teams = sorted(snapshot.index)
    cols = st.columns(2)
    home = cols[0].selectbox("Home team", teams, index=teams.index("LAL") if "LAL" in teams else 0)
    away = cols[1].selectbox("Away team", [t for t in teams if t != home])

    league = league_with_ratings(client)
    with st.expander("Who's out? (adjusts win probability)"):
        missing = missing_minutes_picker(league, home, away, key_prefix="out")

    x = matchup_features(
        snapshot,
        home,
        away,
        home_missing_min=missing[home],
        away_missing_min=missing[away],
    )
    prob = float(models["outcome"].predict_proba(x).iloc[0])
    tri_to_id = (
        league.dropna(subset=["TEAM_ID", "TEAM_ABBREVIATION"])
        .drop_duplicates("TEAM_ABBREVIATION")
        .set_index("TEAM_ABBREVIATION")["TEAM_ID"]
    )
    matchup_header(home, away, prob, tri_to_id, snapshot)
    st.caption(
        "Logistic regression on season-to-date form differentials — win%, net "
        "rating, four factors (eFG%, TOV%, OREB%, FT rate), pace, ORtg/DRtg, "
        "rest, back-to-backs, and expected minutes out — plus home court."
        + _outcome_record(models)
    )
    st.download_button(
        "Download share poster (PNG)",
        prediction_poster_png(home, away, prob, current_season()),
        file_name=f"{home}-vs-{away}.png",
        mime="image/png",
        help="1200×675 image of this prediction, ready to post.",
    )

    slate_section(client, models, snapshot)


def slate_section(client: NBAClient, models: dict, snapshot: pd.DataFrame) -> None:
    """Predicted win probabilities for the next slate. Renders nothing at all
    (no header, no divider) in the offseason — an empty stub is worse than
    absence."""
    try:
        slate = upcoming_games(client.schedule())
    except Exception:
        logger.warning("schedule unavailable for the slate", exc_info=True)
        slate = pd.DataFrame()
    if slate.empty:
        return
    st.divider()
    st.subheader("Next slate")
    # real rest/fatigue flags per team entering the slate — the model is
    # trained on them, so defaulting to "everyone equally rested" wastes
    # a feature we already have
    rest = None
    try:
        rest = team_rest_features(client.team_games(), tipoff=slate["tipoff"].iloc[0])
    except Exception:
        logger.warning("rest features unavailable; slate assumes neutral rest",
                       exc_info=True)
    rows = []
    for _, g in slate.iterrows():
        if g["home"] not in snapshot.index or g["away"] not in snapshot.index:
            continue
        fatigue = {}
        if rest is not None and g["home"] in rest.index and g["away"] in rest.index:
            h, a = rest.loc[g["home"]], rest.loc[g["away"]]
            fatigue = dict(
                rest_diff=float(h["rest_days"] - a["rest_days"]),
                b2b_diff=float(h["b2b"] - a["b2b"]),
                three_in_four_diff=float(h["three_in_four"] - a["three_in_four"]),
            )
        gx = matchup_features(snapshot, g["home"], g["away"], **fatigue)
        p = float(models["outcome"].predict_proba(gx).iloc[0])
        tipoff = pd.Timestamp(g["tipoff"]).tz_convert("US/Eastern")
        rows.append(
            {
                "matchup": f"{g['away']} @ {g['home']}",
                "tipoff (ET)": tipoff.strftime("%b %d, %I:%M %p"),
                "home win prob": p * 100,
            }
        )
    st.dataframe(
        pd.DataFrame(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "home win prob": st.column_config.ProgressColumn(
                "home win prob", min_value=0.0, max_value=100.0, format="%.0f%%"
            ),
        },
    )
    st.caption(
        "Slate probabilities account for rest and back-to-backs, and assume "
        "both teams at full strength."
    )


def margin_chart(margin: pd.Series, home: str, away: str) -> go.Figure:
    """Histogram of simulated margins, diverging around zero."""
    bins = pd.interval_range(
        start=(margin.min() // 4) * 4, end=margin.max() + 4, freq=4
    )
    counts = pd.cut(margin, bins).value_counts().sort_index()
    centers = [iv.mid for iv in counts.index]
    share = counts / len(margin)
    colors = [PAL["series"][0] if c > 0 else PAL["series"][5] for c in centers]
    fig = go.Figure(
        go.Bar(
            x=centers,
            y=share.values,
            marker=dict(color=colors, cornerradius=2),
            width=3.4,
            customdata=[f"{iv.left:+.0f} to {iv.right:+.0f}" for iv in counts.index],
            hovertemplate="%{customdata}: %{y:.1%}<extra></extra>",
        )
    )
    fig = base_layout(fig, f"Simulated margin — {home} minus {away}")
    med = float(margin.median())
    fig.add_vline(x=med, line_dash="dot", line_color=PAL["muted"], line_width=1)
    fig.add_annotation(
        x=med, y=1.05, yref="paper", text=f"median {med:+.0f}", showarrow=False,
        font=dict(color=PAL["muted"], size=11),
    )
    fig.update_layout(hovermode="closest", showlegend=False, height=380)
    fig.update_xaxes(zeroline=True, zerolinecolor=PAL["muted"], title="points")
    fig.update_yaxes(tickformat=".0%", gridcolor=PAL["grid"])
    return fig


@st.fragment
def simulate_tab(client: NBAClient, models: dict, snapshot: pd.DataFrame) -> None:
    import zlib

    teams = sorted(snapshot.index)
    cols = st.columns(2)
    home = cols[0].selectbox(
        "Home team", teams, index=teams.index("LAL") if "LAL" in teams else 0, key="sim_home"
    )
    away = cols[1].selectbox("Away team", [t for t in teams if t != home], key="sim_away")

    league = league_with_ratings(client)
    with st.expander("Who's out? (dents scoring efficiency)"):
        missing = missing_minutes_picker(league, home, away, key_prefix="sim_out")

    # stable seed per scenario: same inputs always show the same 10,000 games
    seed = zlib.crc32(f"{home}|{away}|{missing[home]}|{missing[away]}".encode())
    sims = simulate_matchup(
        snapshot,
        home,
        away,
        home_missing_min=missing[home],
        away_missing_min=missing[away],
        n_sims=10_000,
        seed=seed,
    )
    s = sim_summary(sims)

    home_med = int(sims["home_pts"].median())
    away_med = int(sims["away_pts"].median())
    st.markdown(
        f'<div class="scoreline">{home} <b>{home_med}</b> — <b>{away_med}</b> {away}'
        '<span class="scoreline-note">median of 10,000 simulations</span></div>',
        unsafe_allow_html=True,
    )
    m = st.columns(4)
    m[0].metric(f"{home} wins (10,000 sims)", f"{s['home_win_prob']:.0%}")
    favorite = home if s["median_margin"] >= 0 else away
    m[1].metric("Median margin", f"{favorite} by {abs(s['median_margin']):.0f}")
    m[2].metric("Median total", f"{s['median_total']:.0f} pts")
    m[3].metric("Overtime", f"{s['overtime_prob']:.1%}")

    st.plotly_chart(margin_chart(sims["home_pts"] - sims["away_pts"], home, away),
                    width="stretch", key="sim_margin")
    st.caption(
        f"80% of sims land between {home} {s['margin_p10']:+.0f} and "
        f"{s['margin_p90']:+.0f}. Monte Carlo over pace and ratings — "
        "possessions drawn around the teams' average pace, each side's "
        "scoring around its offensive rating against the opponent's defense, "
        "plus home court (fitted: 2.2 points) and minutes out. The outcome "
        "model is better calibrated on holdout — trust its win probability "
        "as the headline; the simulator adds the distributions."
    )
    try:
        x = matchup_features(
            snapshot, home, away,
            home_missing_min=missing[home], away_missing_min=missing[away],
        )
        model_p = float(models["outcome"].predict_proba(x).iloc[0])
        st.caption(f"For comparison, the outcome model gives {home} {model_p:.0%}.")
    except Exception:
        logger.warning("outcome-model comparison unavailable in simulate tab",
                       exc_info=True)

    with st.expander("Total points distribution"):
        total = sims["home_pts"] + sims["away_pts"]
        fig = go.Figure(
            go.Histogram(x=total, nbinsx=40, marker_color=PAL["series"][0])
        )
        fig = base_layout(fig, "Simulated total points")
        fig.update_layout(hovermode="closest", showlegend=False, height=320)
        fig.update_yaxes(gridcolor=PAL["grid"])
        st.plotly_chart(fig, width="stretch", key="sim_total")


@st.fragment
def points_tab(client: NBAClient, models: dict, snapshot: pd.DataFrame) -> None:
    player = pick_player(client, "Player", "pred_player")
    if not player:
        st.info("Pick a player to project their next game.")
        return
    cols = st.columns(2)
    teams = sorted(snapshot.index)
    opponent = cols[0].selectbox("Opponent", teams)
    venue = cols[1].radio("Venue", ["Home", "Away"], horizontal=True)

    season_games = season_player_games(client)
    rows = season_games[season_games["PLAYER_ID"] == player["id"]]
    if rows.empty:
        st.warning("No games for this player in the current season.")
        return

    # teammates out -> usage boost; leave empty for a league-average absence load
    own_missing = None
    own_team = rows.sort_values("GAME_DATE").iloc[-1].get("TEAM_ABBREVIATION")
    if own_team:
        league = league_with_ratings(client)
        mates = league[
            (league["TEAM_ABBREVIATION"] == own_team)
            & (league["PLAYER_ID"] != player["id"])
        ].sort_values("MIN", ascending=False)
        with st.expander(f"Teammates out? ({own_team} — boosts the projection)"):
            out = st.multiselect(
                "Out",
                list(mates["PLAYER_NAME"]),
                key="pts_out",
                help="Leave empty to assume a league-average absence load.",
            )
            if out:
                own_missing = float(
                    mates.loc[mates["PLAYER_NAME"].isin(out), "MIN"].sum()
                )

    feature_kwargs = {} if own_missing is None else {"own_missing_min": own_missing}
    x = player_next_game_features(
        rows,
        home=venue == "Home",
        opp_form_net=float(snapshot.loc[opponent, "form_net"]),
        opp_form_drtg=float(snapshot.loc[opponent, "form_drtg"]),
        opp_form_pace=float(snapshot.loc[opponent, "form_pace"]),
        **feature_kwargs,
    )
    pred = float(models["points"].predict(x).iloc[0])
    m = st.columns(3)
    interval = models["points"].interval(pred)
    m[0].metric("Projected points", f"{pred:.1f}")
    if interval:
        m[0].caption(f"80% range: {interval[0]:.0f}–{interval[1]:.0f}")
    m[1].metric("Last 5 games", f"{x['pts_r5'].iloc[0]:.1f}")
    m[2].metric("Last 10 games", f"{x['pts_r10'].iloc[0]:.1f}")
    if len(rows) < 10:
        st.warning(
            f"Only {len(rows)} games this season — the model trained on players "
            "with at least a 10-game history, so treat this projection loosely."
        )
    st.caption(
        "Ridge regression on recent scoring, minutes, and shot volume, venue, rest, "
        "and opponent form — trained on three seasons of league-wide player games."
        + _points_record(models)
    )


def _points_record(models: dict) -> str:
    """Holdout sentence for the points model, from recorded metrics."""
    metrics = models.get("metrics") or {}
    p = metrics.get("points")
    if not p:
        return ""
    sentence = (
        f" Holdout MAE {p['mae']:.2f} points "
        f"(10-game-average baseline: {p['baseline_mae']:.2f})."
    )
    if "interval_coverage" in p:
        sentence += f" The 80% range covered {p['interval_coverage']:.0%} of holdout games."
    return sentence


@st.cache_data(ttl=3600, show_spinner=False)
def stint_lineup_table(_client: NBAClient) -> pd.DataFrame | None:
    """Prebuilt stint-level lineup table (garbage-time filtered), if built.

    Built offline by `python -m nba_insights.pbp.lineups`; the app only
    loads it, so a missing table just means the season-aggregate fallback.
    """
    try:
        return load_stint_lineups(_client.cache)
    except Exception:
        logger.warning("stint lineup table unavailable", exc_info=True)
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def all_lineups(_client: NBAClient) -> pd.DataFrame:
    """League 5-man lineup dashboard (~2k rows), cached at the app layer."""
    return _client.lineups()


@st.fragment
def lineup_tab(client: NBAClient, models: dict) -> None:
    league = league_with_ratings(client)
    teams = sorted(league["TEAM_ABBREVIATION"].dropna().unique())
    team = st.selectbox("Team", teams, index=teams.index("LAL") if "LAL" in teams else 0)
    roster = league[league["TEAM_ABBREVIATION"] == team].sort_values("MIN", ascending=False)
    default_five = list(roster["PLAYER_NAME"].head(5))
    five = st.multiselect(
        "Starting five", list(roster["PLAYER_NAME"]), default=default_five, max_selections=5
    )
    if len(five) != 5:
        st.info("Select exactly five players.")
        return
    ids = [int(roster.loc[roster["PLAYER_NAME"] == n, "PLAYER_ID"].iloc[0]) for n in five]
    stint_based = stint_lineup_table(client)
    if stint_based is not None:
        lineups = stint_based
    else:
        try:
            lineups = client.lineups()
        except Exception:
            lineups = pd.DataFrame(columns=["GROUP_ID", "MIN", "NET_RATING"])
    net, minutes = blended_lineup_estimate(lineups, league, five, ids)
    prob = models["curve"].win_probability(net)
    m = st.columns(3)
    m[0].metric("Estimated net rating", f"{net:+.1f}")
    m[1].metric("Win probability vs average opponent", f"{prob:.0%}")
    m[2].metric("Minutes together", f"{minutes:.0f}")
    if minutes > 0 and stint_based is not None:
        st.caption(
            "Blend of this lineup's stint-level net rating this season — exact "
            "shared-floor spans from rotation data, garbage time stripped — "
            "weighted by minutes together, with the per-36 plus-minus proxy, "
            "mapped through a win curve fitted on three seasons of team results."
        )
    elif minutes > 0:
        st.caption(
            "Blend of this lineup's observed net rating this season (weighted by "
            "minutes played together) and the per-36 plus-minus proxy, mapped "
            "through a win curve fitted on three seasons of team results."
        )
    else:
        st.caption(
            "This five hasn't played together this season, so the estimate is the "
            "per-36 plus-minus proxy alone — it ignores lineup fit and synergy. "
            "Treat it as a conversation starter, not a projection."
        )


@st.cache_data(ttl=86400, show_spinner="Warming Elo ratings (two prior seasons)…")
def league_elo() -> pd.Series:
    """Current Elo per team, warmed up over the two prior seasons."""
    client = get_client()
    seasons = [*past_seasons(2), current_season()]
    return current_elo(pd.concat([client.team_games(s) for s in seasons], ignore_index=True))


def _next_season_label() -> str:
    """The season being projected: the one after the latest completed data."""
    start = int(current_season()[:4]) + 1
    return f"{start}-{(start + 1) % 100:02d}"


@st.cache_data(ttl=6 * 3600, show_spinner="Simulating the season…")
def _season_projection(_client: NBAClient, n_sims: int = 5000) -> pd.DataFrame:
    """Monte-Carlo projection of the coming season from current Elo.

    Cached for six hours — the ratings only move when new games land. The
    seed is fixed so the standings don't reshuffle on every rerun."""
    seasons = [*past_seasons(2), current_season()]
    games = pd.concat([_client.team_games(s) for s in seasons], ignore_index=True)
    elo = current_elo(games)
    return simulate_season(elo, n_sims=n_sims, seed=0)


def title_odds_chart(proj: pd.DataFrame, n: int = 12) -> go.Figure:
    """Championship odds for the top *n* contenders, East vs West colored."""
    top = proj.sort_values("champ_pct", ascending=False).head(n)
    colors = [
        PAL["series"][0] if proj.loc[t, "conf"] == "East" else PAL["series"][2]
        for t in top.index
    ]
    fig = go.Figure(
        go.Bar(
            x=top["champ_pct"].values,
            y=top.index,
            orientation="h",
            marker=dict(color=colors, cornerradius=3),
            text=[f"{v:.0%}" for v in top["champ_pct"].values],
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{x:.1%} title odds<extra></extra>",
        )
    )
    fig = base_layout(fig, f"Championship odds — top {n}")
    fig.update_layout(hovermode="closest", showlegend=False, height=380)
    pad = float(top["champ_pct"].max()) * 0.18
    fig.update_xaxes(
        range=[0, float(top["champ_pct"].max()) + pad],
        tickformat=".0%",
        gridcolor=PAL["grid"],
    )
    fig.update_yaxes(autorange="reversed", showgrid=False)
    return fig


def _standings_table(proj: pd.DataFrame, conf: str, id_to_tri: pd.Series) -> None:
    """Projected standings for one conference, click-through to the team."""
    rows = proj[proj["conf"] == conf].sort_values("proj_wins", ascending=False)
    table = pd.DataFrame(
        {
            "#": range(1, len(rows) + 1),
            "Team": rows.index,
            "Proj W": rows["proj_wins"],
            "Proj L": rows["proj_losses"],
            "Range": [
                f"{lo}–{hi}"
                for lo, hi in zip(rows["wins_p10"], rows["wins_p90"], strict=True)
            ],
            "Playoffs": rows["playoff_pct"] * 100,
            "Top-6": rows["top6_pct"] * 100,
            "#1 seed": rows["seed1_pct"] * 100,
            "Title": rows["champ_pct"] * 100,
        }
    )
    st.caption(conf)
    event = st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        height=563,
        on_select="rerun",
        selection_mode="single-row",
        key=f"proj_standings_{conf}",
        column_config={
            "Proj W": st.column_config.NumberColumn(format="%.1f"),
            "Proj L": st.column_config.NumberColumn(format="%.1f"),
            "Range": st.column_config.TextColumn(
                "10–90%", help="10th–90th percentile win total across simulations"
            ),
            "Playoffs": st.column_config.ProgressColumn(
                "Playoffs", min_value=0.0, max_value=100.0, format="%.0f%%",
                help="Reached the 8-team bracket (survived any play-in)",
            ),
            "Top-6": st.column_config.NumberColumn(
                format="%.0f%%", help="Finished top-6 — a berth with no play-in"
            ),
            "#1 seed": st.column_config.NumberColumn(format="%.0f%%"),
            "Title": st.column_config.NumberColumn(format="%.1f%%"),
        },
    )
    if event.selection.rows:
        tri = table.iloc[event.selection.rows[0]]["Team"]
        open_team(str(tri))


def season_outlook_page(client: NBAClient) -> None:
    label = _next_season_label()
    st.caption(
        f"Projected {label} season — 5,000 Monte-Carlo seasons from each team's "
        "current Elo, regressed toward the mean for the off-season."
    )
    try:
        proj = _season_projection(client)
    except Exception as e:
        st.error(f"Could not build the season projection: {e}")
        logger.warning("season projection unavailable", exc_info=True)
        return

    # TeamID -> tricode so a projected-standings click can open that team.
    try:
        id_to_tri = (
            client.team_games(current_season())
            .dropna(subset=["TEAM_ID", "TEAM_ABBREVIATION"])
            .drop_duplicates("TEAM_ID")
            .set_index("TEAM_ABBREVIATION")["TEAM_ID"]
        )
    except Exception:
        id_to_tri = pd.Series(dtype="int64")

    tabs = st.tabs(["Regular season", "Postseason"])

    with tabs[0]:
        st.subheader(f"Projected standings · {label}")
        st.caption("Click a team to open it on the Teams page.")
        cols = st.columns(2)
        with cols[0]:
            _standings_table(proj, "East", id_to_tri)
        with cols[1]:
            _standings_table(proj, "West", id_to_tri)
        st.caption(
            "Projected wins are the mean of 5,000 simulated 82-game seasons on a "
            "balanced schedule; the range is the 10th–90th percentile. Elo carries "
            "last season's results but not summer roster moves."
        )

    with tabs[1]:
        st.subheader(f"Postseason odds · {label}")
        st.caption(
            "The play-in and a best-of-seven bracket run on every simulated "
            "standings — reseeding by finish, home court to the better team."
        )
        st.plotly_chart(title_odds_chart(proj), width="stretch")
        odds = proj.sort_values("champ_pct", ascending=False)
        odds = odds[odds["playoff_pct"] > 0.005]
        table = pd.DataFrame(
            {
                "Team": odds.index,
                "Conf": odds["conf"],
                "Playoffs": odds["playoff_pct"] * 100,
                "Conf finals": odds["conf_finals_pct"] * 100,
                "Finals": odds["finals_pct"] * 100,
                "Champion": odds["champ_pct"] * 100,
            }
        )
        st.dataframe(
            table,
            width="stretch",
            hide_index=True,
            column_config={
                "Playoffs": st.column_config.NumberColumn(format="%.0f%%"),
                "Conf finals": st.column_config.NumberColumn(format="%.0f%%"),
                "Finals": st.column_config.ProgressColumn(
                    "Finals", min_value=0.0, max_value=100.0, format="%.0f%%",
                    help="Reached the NBA Finals (won the conference)",
                ),
                "Champion": st.column_config.NumberColumn(format="%.1f%%"),
            },
        )
        st.caption(
            "Odds are shares of simulated postseasons. Blue = East, gold = West."
        )


def predictions_page(client: NBAClient) -> None:
    models = load_models()
    if models is None:
        st.info(
            "Models not trained yet. Run `uv run python -m nba_insights.ml.train` "
            "and reload this page."
        )
        return
    try:
        snapshot = prediction_snapshot(client)
    except Exception:
        logger.warning("team form snapshot unavailable", exc_info=True)
        snapshot = pd.DataFrame()
    if snapshot.empty:  # season hasn't started: fall back to last season's form
        snapshot = team_form_snapshot(client.team_games(past_seasons(1)[0]))
        st.caption("Season hasn't started — using last season's form (Elo already regressed).")
    try:
        snapshot["elo"] = league_elo().reindex(snapshot.index)
    except Exception:
        # matchup_features degrades to a neutral elo_diff
        logger.warning("Elo unavailable; predictions use a neutral elo_diff", exc_info=True)
        st.caption("Elo ratings unavailable — predictions fall back to a neutral Elo edge.")
    tabs = st.tabs(["Game outcome", "Simulate", "Player points", "Starting five"])
    with tabs[0]:
        outcome_tab(client, models, snapshot)
    with tabs[1]:
        simulate_tab(client, models, snapshot)
    with tabs[2]:
        points_tab(client, models, snapshot)
    with tabs[3]:
        lineup_tab(client, models)


# which factors read as a percentage vs. a raw ratio (FT rate)
_FF_PCT = {"off_efg", "off_tov_pct", "off_oreb_pct", "def_efg", "def_tov_pct", "def_dreb_pct"}
_FF_OFFENSE = ["off_efg", "off_tov_pct", "off_oreb_pct", "off_ft_rate"]
_FF_DEFENSE = ["def_efg", "def_tov_pct", "def_dreb_pct", "def_ft_rate"]


def four_factors_panel(games: pd.DataFrame, team: str) -> None:
    """Dean Oliver's four factors as a team identity, offense vs defense.

    Each factor carries its league rank (1 = best) so a value reads in context —
    the same way NBA.com and Cleaning the Glass frame team profiles.
    """
    try:
        ff = four_factors_table(games)
    except Exception:
        logger.warning("four factors unavailable", exc_info=True)
        return
    if team not in ff.index:
        return
    row = ff.loc[team]
    n = len(ff)

    st.subheader("Four factors")
    st.caption(
        "Shooting, turnovers, rebounding, and free throws — what wins games, "
        f"with each team's league rank (of {n}). Green = a strength."
    )
    for title, factors in (("Offense", _FF_OFFENSE), ("Defense", _FF_DEFENSE)):
        st.caption(title)
        cols = st.columns(4)
        for col, factor in zip(cols, factors, strict=True):
            value = row[factor]
            shown = f"{value * 100:.1f}%" if factor in _FF_PCT else f"{value:.3f}"
            rank = int(row[f"{factor}_rank"])
            # top third is a strength (green), bottom third a weakness (red)
            tone = "green" if rank <= n / 3 else "red" if rank > 2 * n / 3 else "gray"
            col.metric(FACTOR_LABELS[factor], shown)
            col.markdown(f":{tone}[**#{rank}** of {n}]")


@st.fragment
def team_detail(client: NBAClient, games: pd.DataFrame, snapshot: pd.DataFrame) -> None:
    """One team's season at a glance; a fragment so switching teams is light."""
    teams = sorted(snapshot.index)
    # seed the picker before the widget exists: a standings-row click stashes
    # _pending_team, then reruns here (a widget key can't be set once created)
    pending = st.session_state.pop("_pending_team", None)
    if pending in teams:
        st.session_state["team_select"] = pending
    if st.session_state.get("team_select") not in teams:
        st.session_state["team_select"] = "OKC" if "OKC" in teams else teams[0]
    team = st.selectbox("Team", teams, key="team_select")
    log = games[games["TEAM_ABBREVIATION"] == team].sort_values("GAME_DATE")
    form = snapshot.loc[team]

    header = st.columns([1, 2, 2, 2, 2], vertical_alignment="center")
    with header[0]:
        logo = fetch_team_logo(int(log["TEAM_ID"].iloc[0]))
        if logo:
            st.image(logo, width=96)
    tiles = header[1:]
    wins, losses = int((log["WL"] == "W").sum()), int((log["WL"] == "L").sum())
    tiles[0].metric("Record", f"{wins}-{losses}")
    tiles[1].metric("Net rating", f"{form['form_net']:+.1f}")
    tiles[2].metric("ORtg / DRtg", f"{form['form_ortg']:.0f} / {form['form_drtg']:.0f}")
    try:
        tiles[3].metric("Elo", f"{league_elo()[team]:.0f}")
    except Exception:
        logger.warning("Elo unavailable for team tile", exc_info=True)
        tiles[3].metric("Elo", "—", help="Elo ratings unavailable right now.")

    color = team_color(team)
    try:
        recent = log.tail(10)["WL"]
        take = team_scouting_take(
            form, wins, losses, snapshot,
            recent=(int((recent == "W").sum()), int((recent == "L").sum())),
        )
        if take:
            scouting_callout(take, accent=color)
    except Exception:
        logger.warning("team scouting take unavailable", exc_info=True)

    st.plotly_chart(
        form_chart(
            rolling_form(log, "PLUS_MINUS", 10), "PLUS_MINUS", 10,
            label="Point margin", signed=True, accent=color,
        ),
        width="stretch",
        key="team_form",
    )

    four_factors_panel(games, team)

    st.subheader("Roster")
    try:
        league = league_with_ratings(client)
        roster = league[league["TEAM_ABBREVIATION"] == team].sort_values(
            "MIN", ascending=False
        )
        contracts = contracts_table(client)
        if contracts is not None:
            try:
                roster = attach_salary(roster, contracts)
                roster["SALARY"] = roster["SALARY"] / 1e6  # display in $M
                payroll = team_payroll(contracts)
                if team in payroll.index:
                    st.caption(
                        f"Committed payroll, {salary_seasons(contracts)[0]}: "
                        f"${payroll[team] / 1e6:.0f}M"
                    )
            except Exception:
                logger.warning("salary columns unavailable for roster", exc_info=True)
        # full width now, so the 9 columns breathe instead of scrolling
        keep = [
            c
            for c in (
                "PLAYER_NAME", "GP", "MIN", "PTS", "AST", "REB",
                "NET_RATING", "DPM", "SALARY",
            )
            if c in roster.columns
        ]
        st.caption("Click a player to open their profile.")
        event = st.dataframe(
            roster[keep].rename(columns={**STAT_LABELS, "SALARY": "SAL ($M)"}),
            width="stretch",
            hide_index=True,
            height=422,
            on_select="rerun",
            selection_mode="single-row",
            key="team_roster",
            column_config={
                "MIN": st.column_config.ProgressColumn(
                    "MIN", min_value=0.0, max_value=40.0, format="%.1f"
                ),
                "PTS": st.column_config.NumberColumn(format="%.1f"),
                "AST": st.column_config.NumberColumn(format="%.1f"),
                "REB": st.column_config.NumberColumn(format="%.1f"),
                "NET RTG": st.column_config.NumberColumn(format="%.1f"),
                "DARKO DPM": st.column_config.NumberColumn(format="%+.1f"),
                "SAL ($M)": st.column_config.NumberColumn(format="$%.2f"),
            },
        )
        if event.selection.rows:
            open_profile(str(roster.iloc[event.selection.rows[0]]["PLAYER_NAME"]))
    except Exception as e:
        st.error(f"Could not load roster: {e}")

    st.subheader("Last 10 games")
    recent = log.tail(10).iloc[::-1].copy()
    recent["GAME_DATE"] = pd.to_datetime(recent["GAME_DATE"]).dt.date
    st.dataframe(
        recent[["GAME_DATE", "MATCHUP", "WL", "PTS", "PLUS_MINUS"]].rename(
            columns={"PLUS_MINUS": "MARGIN"}
        ),
        width="stretch",
        hide_index=True,
        height=390,
        column_config={
            "GAME_DATE": st.column_config.DateColumn("DATE", format="MMM DD"),
            "MARGIN": st.column_config.NumberColumn(format="%+d"),
        },
    )

    contracts = contracts_table(client)
    if contracts is not None:
        try:
            book = team_contracts(contracts, team)
        except KeyError:
            book = pd.DataFrame()
        if not book.empty:
            st.subheader("Contract book")
            season_cols = salary_seasons(contracts)
            totals = book[season_cols].sum() / 1e6
            fig = go.Figure(
                go.Bar(
                    x=list(totals.index),
                    y=totals.values,
                    marker=dict(color=team_color(team), cornerradius=4),
                    text=[f"${v:.0f}M" for v in totals.values],
                    textposition="outside",
                    cliponaxis=False,
                    hovertemplate="%{x}: $%{y:.2f}M<extra></extra>",
                )
            )
            fig = base_layout(fig, "Committed payroll by season")
            fig.update_layout(hovermode="closest", showlegend=False, height=280,
                              margin=dict(t=60))
            fig.update_xaxes(type="category")
            fig.update_yaxes(tickprefix="$", ticksuffix="M", gridcolor=PAL["grid"])
            st.plotly_chart(fig, width="stretch", key="team_payroll")

            money_cols = [c for c in book.columns if c != "PLAYER_NAME"]
            display = book.copy()
            display[money_cols] = (display[money_cols] / 1e6).round(2)
            st.dataframe(
                display.rename(columns={"PLAYER_NAME": "PLAYER"}),
                width="stretch",
                hide_index=True,
                height=390,
                column_config={
                    c: st.column_config.NumberColumn(format="$%.2f") for c in money_cols
                },
            )
            st.caption(
                "Salaries in $M. Scraped weekly from Basketball-Reference; "
                "personal use only. Blank cells: no committed money that season."
            )

    st.subheader("Lineups")
    try:
        lineups = all_lineups(client)
        team_players = league_with_ratings(client)
        team_players = team_players[team_players["TEAM_ABBREVIATION"] == team].sort_values(
            "MIN", ascending=False
        )
        roster_ids = dict(
            zip(team_players["PLAYER_NAME"], team_players["PLAYER_ID"], strict=False)
        )
        on_court = st.multiselect(
            "Players on court", list(roster_ids), key="lineup_filter",
            help="Show only five-man units containing every selected player.",
        )
        min_min = st.slider("Min minutes together", 0, 200, 20, step=10, key="lineup_minmin")
        board = most_used_lineups(
            lineups, team,
            must_include_ids=[int(roster_ids[n]) for n in on_court] or None,
            min_minutes=float(min_min),
        )
        if board.empty:
            st.caption("No five-man units meet these filters.")
        else:
            st.dataframe(
                board.rename(columns={
                    "GROUP_NAME": "LINEUP", "NET_RATING": "NET", "OFF_RATING": "ORtg",
                    "DEF_RATING": "DRtg", "EFG_PCT": "eFG%", "POSS": "POSS",
                }),
                width="stretch",
                hide_index=True,
                height=380,
                column_config={
                    "MIN": st.column_config.NumberColumn(format="%.0f"),
                    "NET": st.column_config.NumberColumn(format="%+.1f"),
                    "ORtg": st.column_config.NumberColumn(format="%.1f"),
                    "DRtg": st.column_config.NumberColumn(format="%.1f"),
                    "eFG%": st.column_config.NumberColumn(format="%.3f"),
                    "POSS": st.column_config.NumberColumn(format="%d"),
                },
            )
            st.caption(
                f"{team}'s most-used five-man lineups this season (net/off/def rating, "
                "possessions). Filter by a player to see only the units they play in."
            )
    except Exception as e:
        st.caption(f"Lineup data unavailable: {e}")

    st.subheader("On/off impact")
    try:
        onoff = team_on_off(client.team_player_on_off(int(log["TEAM_ID"].iloc[0])))
    except Exception as e:
        st.caption(f"On/off splits unavailable: {e}")
        return
    onoff = onoff[onoff["MIN_ON"] >= 100]
    if onoff.empty:
        st.caption("Not enough on-court minutes yet this season.")
        return
    st.dataframe(
        onoff[["PLAYER_NAME", "MIN_ON", "NET_ON", "NET_OFF", "NET_DIFF"]].rename(
            columns={
                "PLAYER_NAME": "PLAYER",
                "MIN_ON": "MIN ON",
                "NET_ON": "TEAM NET, ON",
                "NET_OFF": "TEAM NET, OFF",
                "NET_DIFF": "SWING",
            }
        ),
        width="stretch",
        hide_index=True,
        column_config={
            "MIN ON": st.column_config.NumberColumn(format="%.0f"),
            "TEAM NET, ON": st.column_config.NumberColumn(format="%+.1f"),
            "TEAM NET, OFF": st.column_config.NumberColumn(format="%+.1f"),
            "SWING": st.column_config.NumberColumn(format="%+.1f"),
        },
    )
    st.caption(
        "Team net rating with each player on vs off the floor (raw minutes, "
        "no lineup adjustment). Players under 100 on-court minutes excluded."
    )


def teams_page(client: NBAClient) -> None:
    st.caption(
        f"Team form, roster, contracts, lineups, and on/off impact · {current_season()}"
    )
    try:
        games = client.team_games()
        snapshot = team_form_snapshot(games)
    except Exception as e:
        st.error(f"Could not load team data: {e}")
        return
    if snapshot.empty:
        st.info("No team games yet this season.")
        return

    team_detail(client, games, snapshot)

    st.divider()
    st.subheader("Standings")
    try:
        standings = client.standings()
    except Exception as e:
        st.caption(f"Standings unavailable: {e}")
        return
    # TeamID -> tricode, so a standings-row click can open that team above
    id_to_tri = (
        games.dropna(subset=["TEAM_ID", "TEAM_ABBREVIATION"])
        .drop_duplicates("TEAM_ID")
        .set_index("TEAM_ID")["TEAM_ABBREVIATION"]
    )
    st.caption("Click a team to load it above.")
    conf_cols = st.columns(2)
    for col, conf in zip(conf_cols, ("East", "West"), strict=True):
        rows = standings[standings["Conference"] == conf].sort_values("PlayoffRank")
        table = pd.DataFrame(
            {
                "#": rows["PlayoffRank"].astype(int),
                "Team": rows["TeamCity"] + " " + rows["TeamName"],
                "W": rows["WINS"].astype(int),
                "L": rows["LOSSES"].astype(int),
                "Win%": rows["WinPCT"].round(2),
                "L10": rows["L10"].str.strip(),
                "Streak": rows["strCurrentStreak"].str.strip(),
            }
        )
        with col:
            st.caption(conf)
            event = st.dataframe(
                table,
                width="stretch",
                hide_index=True,
                height=390,
                on_select="rerun",
                selection_mode="single-row",
                key=f"standings_{conf}",
                column_config={
                    "Win%": st.column_config.ProgressColumn(
                        "Win%", min_value=0.0, max_value=1.0, format="%.2f"
                    ),
                },
            )
            if event.selection.rows:
                team_id = int(rows.iloc[event.selection.rows[0]]["TeamID"])
                if team_id in id_to_tri.index:
                    open_team(str(id_to_tri.loc[team_id]))


def games_page(client: NBAClient) -> None:
    """Scores & schedule: every game's final and top scorer, plus what's next."""
    st.caption("Every game — final scores and top scorer, plus upcoming tip-offs.")
    head = st.columns([2, 3])
    season = head[0].selectbox("Season", seasons_since(), key="games_season")
    is_current = season == current_season()
    try:
        with st.spinner("Loading the schedule (first view fetches live)…"):
            board = scoreboard(client.schedule(None if is_current else season))
    except Exception as e:
        st.error(f"Could not load the schedule: {e}")
        return
    if board.empty:
        st.info(f"No games scheduled for {season}.")
        return

    teams = sorted(set(board["HOME"]) | set(board["AWAY"]))
    pick = head[1].multiselect("Filter by team", teams, key="games_team")
    if pick:
        board = board[board["HOME"].isin(pick) | board["AWAY"].isin(pick)]

    upcoming = board[board["STATUS"].isin(["Scheduled", "Live"])].sort_values("GAME_DATE")
    finals = board[board["STATUS"] == "Final"].sort_values("GAME_DATE", ascending=False)

    if not upcoming.empty:
        st.subheader("Upcoming")
        up = pd.DataFrame(
            {
                "Date": upcoming["GAME_DATE"],
                "Matchup": upcoming["AWAY"] + " @ " + upcoming["HOME"],
                "Tip / status": upcoming["STATUS_TEXT"],
            }
        )
        st.dataframe(up, width="stretch", hide_index=True, height=min(360, 40 + 36 * len(up)))

    if finals.empty:
        return
    st.subheader("Scores")
    if upcoming.empty:
        st.caption(f"Offseason — showing the completed {season} season. Sort by any column.")
    scores = pd.DataFrame(
        {
            "Date": finals["GAME_DATE"],
            "Matchup": finals["AWAY"] + " @ " + finals["HOME"],
            "Score": (
                finals["AWAY_PTS"].astype("Int64").astype(str)
                + "–"
                + finals["HOME_PTS"].astype("Int64").astype(str)
            ),
            "Winner": finals["WINNER"],
            "Top scorer": finals["TOP_SCORER"],
        }
    )
    st.caption(f"{len(scores)} games. Click a row for the full box score.")
    event = st.dataframe(
        scores,
        width="stretch",
        hide_index=True,
        height=560,
        on_select="rerun",
        selection_mode="single-row",
        key="games_scores",
    )
    if not event.selection.rows:
        return

    selected = finals.iloc[event.selection.rows[0]]
    matchup = f"{selected['AWAY']} @ {selected['HOME']}"
    st.subheader(f"Box score · {matchup}")
    st.caption(
        f"{selected['AWAY']} {int(selected['AWAY_PTS'])} — "
        f"{selected['HOME']} {int(selected['HOME_PTS'])} · {selected['GAME_DATE']:%b %d, %Y}"
    )
    try:
        box = box_score_table(client.box_score(str(selected["GAME_ID"])))
    except Exception as e:
        st.error(f"Could not load the box score: {e}")
        return
    if box.empty:
        st.info("No player box score is available for this game.")
        return
    for team in (selected["AWAY"], selected["HOME"]):
        rows = box[box["TEAM"] == team].drop(columns="TEAM")
        if rows.empty:
            continue
        st.markdown(f"#### {team}")
        st.dataframe(
            rows,
            width="stretch",
            hide_index=True,
            height=min(540, 40 + 36 * len(rows)),
            column_config={
                "MIN": st.column_config.NumberColumn(format="%.1f"),
                "+/-": st.column_config.NumberColumn(format="%+d"),
            },
        )


# Explore page column presets (raw stat codes). Base columns always lead.
_EXPLORE_BASE = ["PLAYER_NAME", "TEAM_ABBREVIATION", "GP", "MIN"]
_EXPLORE_GROUPS = {
    "Scoring": ["PTS", "FGA", "FG_PCT", "FG3M", "FG3A", "FG3_PCT", "FTA", "FT_PCT"],
    "Playmaking": ["PTS", "AST", "TOV"],
    "Rebounding & defense": ["REB", "OREB", "DREB", "STL", "BLK", "PF"],
    "Impact": ["PTS", "NET_RATING", "CLUTCH_NET_RATING", "DPM", "O_DPM", "D_DPM", "PLUS_MINUS"],
    "Everything": [
        "PTS", "REB", "AST", "STL", "BLK", "TOV", "FG_PCT", "FG3_PCT", "FT_PCT",
        "FG3M", "NET_RATING", "CLUTCH_NET_RATING", "DPM", "PLUS_MINUS",
    ],
}
_EXPLORE_PCT = ("FG_PCT", "FG3_PCT", "FT_PCT")
_EXPLORE_SIGNED = ("NET_RATING", "CLUTCH_NET_RATING", "DPM", "O_DPM", "D_DPM", "PLUS_MINUS")


def explore_page(client: NBAClient) -> None:
    """The master table: every player, sortable and filterable — the
    exploration backbone the leaderboards can only hint at."""
    st.caption(
        "Every player, sortable and filterable. Sort by clicking a column header; "
        "click a row to open that player's profile."
    )
    ctrl = st.columns([2, 2, 3])
    season = ctrl[0].selectbox("Season", seasons_since(), key="explore_season")
    is_current = season == current_season()
    mode = ctrl[1].radio("Rate", ["Per game", "Per 36 min"], horizontal=True, key="explore_mode")
    group = ctrl[2].radio(
        "Columns", list(_EXPLORE_GROUPS), horizontal=True, key="explore_group"
    )
    try:
        with st.spinner("Loading the league table (first view fetches live)…"):
            league = league_with_ratings(client, None if is_current else season)
    except Exception as e:
        st.error(f"Could not load league stats: {e}")
        return
    if league.empty:
        st.info(f"No league stats for {season} yet.")
        return
    if mode == "Per 36 min":
        league = per_minutes_table(league, 36)

    flt = st.columns([1, 1, 2, 2])
    max_gp = int(league["GP"].max()) if "GP" in league.columns and len(league) else 1
    min_gp = flt[0].slider("Min games", 0, max(1, max_gp), 0, key="explore_gp")
    max_min = float(league["MIN"].max()) if "MIN" in league.columns and len(league) else 1.0
    min_min = flt[1].slider(
        "Min minutes/game", 0.0, max(1.0, round(max_min, 0)), 0.0, step=1.0, key="explore_min"
    )
    all_teams = (
        sorted(league["TEAM_ABBREVIATION"].dropna().unique())
        if "TEAM_ABBREVIATION" in league.columns
        else []
    )
    pick_teams = flt[2].multiselect("Teams", all_teams, key="explore_teams")
    name_q = flt[3].text_input("Player name contains", key="explore_name")

    filtered = filter_players(
        league, min_gp=min_gp, min_min=min_min,
        teams=pick_teams or None, name_query=name_q,
    )
    cols = _EXPLORE_BASE + [
        c for c in _EXPLORE_GROUPS[group]
        if c in filtered.columns and c not in _EXPLORE_BASE
    ]
    cols = [c for c in cols if c in filtered.columns]
    view = filtered[cols].reset_index(drop=True)
    display = view.copy()
    for c in _EXPLORE_PCT:  # fractions -> percentages, like the rest of the app
        if c in display.columns:
            display[c] = display[c] * 100

    st.caption(f"{len(view)} players.")
    colcfg: dict = {}
    if "GP" in display.columns:
        colcfg["GP"] = st.column_config.NumberColumn(format="%d")
    for c in display.columns:
        if c in _EXPLORE_SIGNED:
            colcfg[c] = st.column_config.NumberColumn(format="%+.1f")
        elif c not in ("PLAYER_NAME", "TEAM_ABBREVIATION", "GP"):
            colcfg[c] = st.column_config.NumberColumn(format="%.1f")
    event = st.dataframe(
        display.rename(columns=STAT_LABELS),
        width="stretch",
        hide_index=True,
        height=560,
        on_select="rerun",
        selection_mode="single-row",
        key="explore_table",
        column_config={STAT_LABELS.get(k, k): v for k, v in colcfg.items()},
    )
    if event.selection.rows:
        open_profile(str(view.iloc[event.selection.rows[0]]["PLAYER_NAME"]))
    st.download_button(
        "Download CSV",
        display.to_csv(index=False).encode(),
        file_name=f"nba_{season}_{mode.replace(' ', '')}.csv",
        mime="text/csv",
    )
    st.caption(
        "Per-36 rescales counting stats by minutes; percentages and ratings are "
        "unchanged. DPM is DARKO daily plus-minus (current season)."
    )


def ask_page(client: NBAClient) -> None:
    """Natural-language Q&A over the league table, answered by Claude through
    a single structured query tool (no LLM-generated code runs). Gated: needs
    the optional `anthropic` package and an Anthropic credential."""
    import os

    st.caption("Ask about this season in plain English — answered over the live league table.")
    try:
        import anthropic
        from anthropic import beta_tool
    except ImportError:
        st.info(
            "The Ask page needs the optional `anthropic` package. Install it with "
            "`uv sync --extra ai`, set `ANTHROPIC_API_KEY`, then reload."
        )
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        st.info(
            "Set `ANTHROPIC_API_KEY` in your environment (or run `ant auth login`) "
            "to enable AI answers. Your other pages work without it."
        )

    question = st.text_input(
        "Ask a question",
        placeholder="e.g. Who leads the league in assists among 30+ minute players?",
        key="ask_q",
    )
    st.caption(
        "Try: “Best 3-point shooters with 5+ makes a game”, “Which players average a "
        "20-10?”, “Highest net rating among 30-minute players”."
    )
    if not question:
        return

    league = league_with_ratings(client)
    glossary = "\n".join(f"- {c}: {d}" for c, d in COLUMN_GLOSSARY.items())

    @beta_tool
    def query_league(
        filters: dict | None = None,
        name_contains: str = "",
        teams: list | None = None,
        sort_by: str = "",
        ascending: bool = False,
        top_n: int = 10,
        columns: list | None = None,
    ) -> str:
        """Query this season's per-player league table and return JSON rows.

        Args:
            filters: column -> minimum value; keeps rows meeting every floor,
                e.g. {"MIN": 30, "AST": 5} for 30+ minutes and 5+ assists.
            name_contains: case-insensitive substring match on player name.
            teams: team tricodes to keep, e.g. ["LAL", "BOS"].
            sort_by: column to order by (descending unless ascending is true).
            ascending: sort ascending instead of descending.
            top_n: maximum number of rows to return.
            columns: which columns to include in each returned row.
        """
        import json

        return json.dumps(
            query_players(
                league,
                filters=filters,
                name_contains=name_contains,
                teams=teams or None,
                sort_by=sort_by or None,
                ascending=ascending,
                top_n=top_n,
                columns=columns,
            )
        )

    system = (
        f"You answer NBA questions for the {current_season()} season using ONLY the "
        "query_league tool over the cached league table. Never invent numbers — call the "
        "tool and cite what it returns. Percentages come back as fractions (0.48 means "
        "48%); present them as percentages. Keep answers short and direct. Available "
        "columns:\n" + glossary
    )
    model = os.environ.get("NBA_ASK_MODEL", "claude-opus-4-8")
    try:
        with st.spinner("Thinking…"):
            runner = anthropic.Anthropic().beta.messages.tool_runner(
                model=model,
                max_tokens=2048,
                system=system,
                tools=[query_league],
                messages=[{"role": "user", "content": question}],
            )
            final = None
            for message in runner:
                final = message
        answer = (
            "".join(b.text for b in final.content if b.type == "text") if final else ""
        )
        st.markdown(answer or "_(no answer produced)_")
    except anthropic.AuthenticationError:
        st.warning(
            "No Anthropic credential found. Set `ANTHROPIC_API_KEY` or run `ant auth login`."
        )
    except Exception as e:
        st.error(f"Could not answer: {e}")
    st.caption(
        f"Answered by {model}. Numbers are pulled from the cached stats.nba.com league "
        "table; the wording is the model's — verify anything important."
    )


def home_page(client: NBAClient) -> None:
    """League pulse: the app opens with content, not an empty search box."""
    head = st.columns([5, 1])
    season = head[1].selectbox(
        "Season", seasons_since(), key="pulse_season", label_visibility="collapsed",
        help="Dashboards go back to 1996-97. Past seasons load live on first view.",
    )
    is_current = season == current_season()
    head[0].caption(f"League-wide leaders and team form · {season}")
    try:
        with st.spinner("Loading the league dashboard (first view fetches live)…"):
            league = league_with_ratings(client, None if is_current else season)
    except Exception as e:
        st.error(f"Could not load league stats: {e}")
        return

    specs = [
        ("PTS", "Points"),
        ("AST", "Assists"),
        ("REB", "Rebounds"),
        ("FG3M", "Threes"),
        ("NET_RATING", "Net rating"),
        ("CLUTCH_NET_RATING", "Clutch net"),
    ]
    # GP floors scale down early in the season so the boards (and tiles)
    # aren't empty from opening night to December
    max_gp = int(league["GP"].max()) if "GP" in league.columns and len(league) else 0
    min_gp = min(20, max(1, max_gp // 2))
    # Net and clutch rating are team-context stats: a bench player on a great
    # team can top raw net rating in 15 minutes a night. A hero tile is the
    # most prominent number in the app, so the rate-stat tiles qualify only
    # genuine rotation regulars (~starter minutes) — the box-score tiles keep
    # the plain games floor.
    rate_min = 24.0
    tiles = st.columns(len(specs))
    boards: dict[str, pd.DataFrame] = {}
    used_rate_floor = False
    for col, (stat, label) in zip(tiles, specs, strict=True):
        pool = league
        if stat == "NET_RATING" and "MIN" in league.columns:
            pool = league[league["MIN"] >= rate_min]
            used_rate_floor = True
        elif stat == "CLUTCH_NET_RATING" and {"MIN", "CLUTCH_GP"} <= set(league.columns):
            # a real rotation player who has logged enough clutch games
            pool = league[(league["MIN"] >= rate_min) & (league["CLUTCH_GP"] >= min_gp)]
            used_rate_floor = True
        try:
            board = league_leaders(pool, stat, top=10, min_gp=min_gp)
        except KeyError:
            continue
        if board.empty:  # early season / empty upstream table: skip the tile
            continue
        boards[label] = board
        row = board.iloc[0]
        team = row.get("TEAM_ABBREVIATION", "")
        value = f"{row[stat]:+.1f}" if "RATING" in stat else f"{row[stat]:.1f}"
        with col:
            if "PLAYER_ID" in row.index:  # face the number: the leader's headshot
                photo = fetch_headshot(int(row["PLAYER_ID"]))
                if photo:
                    st.image(photo, width=90)
                else:  # reserve the photo's slot so the tile row stays aligned
                    st.markdown('<div style="height:66px"></div>', unsafe_allow_html=True)
            st.metric(label, value)
            st.caption(f"{row['PLAYER_NAME']} · {team}")
    if boards:
        note = f"Leaders qualify at {min_gp}+ games"
        if used_rate_floor:
            note += f"; net and clutch tiles also require {rate_min:.0f}+ minutes a game"
        # surfaced inline as a grid of ranked cards (one per category) — not
        # a wide dense table, and not hidden in an expander
        st.subheader("League leaders")
        st.caption(f"Top ten per category. {note}.")
        label_to_stat = {label: stat for stat, label in specs}
        items = list(boards.items())
        for chunk_start in range(0, len(items), 3):
            cols = st.columns(3)
            chunk = items[chunk_start:chunk_start + 3]
            for col, (label, board) in zip(cols, chunk, strict=False):
                col.markdown(
                    _leaderboard_card(label, board, label_to_stat[label]),
                    unsafe_allow_html=True,
                )
    else:
        st.info(f"No league stats for {season} — leaderboards appear after opening night.")

    try:
        snapshot = team_form_snapshot(client.team_games(None if is_current else season))
    except Exception:
        logger.warning("team form unavailable on home page", exc_info=True)
        snapshot = pd.DataFrame()
    if not snapshot.empty:
        if is_current:
            left, right = st.columns(2)
            with left:
                try:
                    st.plotly_chart(elo_dot_chart(league_elo()), width="stretch", key="home_elo")
                    st.caption(
                        "Elo rates each team from game results: everyone starts at "
                        "1500, and a team gains points for a win — more for beating a "
                        "strong opponent or winning big — and loses them for a defeat. "
                        "Warmed over the two prior seasons, so it carries momentum in."
                    )
                except Exception as e:
                    st.caption(f"Elo rankings unavailable: {e}")
            with right:
                st.plotly_chart(net_rating_chart(snapshot), width="stretch", key="home_net")
        else:
            # Elo and the slate are "now" widgets; a past season keeps form only
            st.plotly_chart(net_rating_chart(snapshot), width="stretch", key="home_net")
        # the league landscape fills the space below the fold with the one
        # chart that shows all 30 teams at once, in their own colors
        if {"form_ortg", "form_drtg"} <= set(snapshot.columns):
            st.plotly_chart(
                league_landscape_chart(snapshot), width="stretch", key="home_landscape"
            )
            st.caption(
                "Each team by offensive and defensive rating (defense inverted, so "
                "up is better). Top-right is elite on both ends. Click a team in the "
                "standings on the Teams page to dig in."
            )
        st.subheader("Team form — all teams")
        st.dataframe(
            snapshot.drop(columns="last_game_date").round(2).sort_values(
                "form_net", ascending=False
            ),
            width="stretch",
        )
        st.caption(f"Data through {snapshot['last_game_date'].max():%b %d, %Y}.")

    models = load_models()
    if models is not None and not snapshot.empty and is_current:
        try:
            slate_snapshot = prediction_snapshot(client)  # prior-seeded, like training
        except Exception:
            logger.warning("seeded snapshot unavailable; slate uses raw form", exc_info=True)
            slate_snapshot = snapshot
        try:
            slate_snapshot["elo"] = league_elo().reindex(slate_snapshot.index)
        except Exception:
            logger.warning("Elo unavailable for the slate", exc_info=True)
        slate_section(client, models, slate_snapshot)


def draft_page(client: NBAClient) -> None:
    """Draft classes with combine measurements, back to the first draft."""
    try:
        history = client.draft_history()
    except Exception as e:
        st.error(f"Could not load draft history: {e}")
        return
    years = sorted(history["SEASON"].astype(str).unique(), reverse=True)
    head = st.columns([2, 4])
    year = head[0].selectbox("Draft year", years, key="draft_year")
    combine = None
    try:
        combine = client.draft_combine(year)
    except Exception:
        logger.warning("combine data unavailable for %s", year, exc_info=True)
    try:
        table = draft_class(history, combine, year)
    except KeyError as e:
        st.error(f"Draft table has an unexpected shape: {e}")
        return
    if table.empty:
        st.info(f"No picks recorded for {year}.")
        return

    show = table.drop(columns=["PERSON_ID", "SEASON"], errors="ignore").rename(
        columns={
            "PLAYER_NAME": "PLAYER",
            "ROUND_NUMBER": "RD",
            "OVERALL_PICK": "PICK",
            "TEAM_ABBREVIATION": "TEAM",
            "ORGANIZATION": "FROM",
            "POSITION": "POS",
            "HEIGHT_WO_SHOES": "HEIGHT",
            "WEIGHT": "LBS",
            "STANDING_REACH": "REACH",
            "MAX_VERTICAL_LEAP": "VERT",
            "THREE_QUARTER_SPRINT": "SPRINT",
            "WINGSPAN_DIFF": "WING±",
        }
    )
    st.dataframe(
        show,
        width="stretch",
        hide_index=True,
        height=620,
        column_config={
            "HEIGHT": st.column_config.NumberColumn(format="%.2f"),
            "WINGSPAN": st.column_config.NumberColumn(format="%.2f"),
            "REACH": st.column_config.NumberColumn(format="%.2f"),
            "VERT": st.column_config.NumberColumn(format="%.1f"),
            "SPRINT": st.column_config.NumberColumn(format="%.2f"),
            "WING±": st.column_config.NumberColumn(
                format="%+.2f", help="Wingspan minus barefoot height, in inches."
            ),
        },
    )
    st.caption(
        "Measurements from the NBA Draft Combine (inches, pounds, seconds; "
        "combine data starts in 2000). Blank cells: the player skipped the "
        "combine or the drill."
    )


def methodology_page(client: NBAClient) -> None:
    import methodology

    methodology.render(client, load_models(), PAL)


# the page objects (StreamlitPage), keyed for programmatic drill-down
# (leaderboard/roster clicks jump here). Rebuilt each run in main().
PAGES: dict = {}


def open_profile(name: str) -> None:
    """Jump to a player's profile with the search box pre-filled. Stashes the
    target in _pending_profile (profile_page seeds the search widget from it
    before the widget exists — the widget's own key can't be written once
    instantiated, which matters when the jump comes from the profile page
    itself, e.g. a comps click) and triggers a full app rerun that main()
    turns into the page switch."""
    st.session_state["_pending_profile"] = name
    st.session_state["_nav_to"] = "profile"
    st.rerun(scope="app")


def open_team(tricode: str) -> None:
    """Select a team on the Teams page. Same page as the standings table, so
    this just stashes the pick and reruns — team_detail seeds its selectbox
    from _pending_team before the widget exists (the widget's own key can't
    be written once instantiated)."""
    st.session_state["_pending_team"] = tricode
    st.session_state["_nav_to"] = "teams"
    st.rerun(scope="app")


def main() -> None:
    PAL.update(theme_palette())
    inject_css()
    client = get_client()
    PAGES.clear()
    PAGES["home"] = st.Page(
        lambda: home_page(client), title="League pulse", icon="📈", default=True
    )
    PAGES["profile"] = st.Page(
        lambda: profile_page(client), title="Player profile", icon="🏀", url_path="profile"
    )
    PAGES["explore"] = st.Page(
        lambda: explore_page(client), title="Explore stats", icon="🔎", url_path="explore"
    )
    PAGES["compare"] = st.Page(
        lambda: compare_page(client), title="Compare players", icon="⚖️", url_path="compare"
    )
    PAGES["teams"] = st.Page(
        lambda: teams_page(client), title="Teams", icon="🏆", url_path="teams"
    )
    PAGES["games"] = st.Page(
        lambda: games_page(client), title="Games", icon="📅", url_path="games"
    )
    PAGES["ask"] = st.Page(
        lambda: ask_page(client), title="Ask (AI)", icon="💬", url_path="ask"
    )
    # Draft page hidden for now (owner request, 2026-07-17); the page code
    # stays so re-enabling is uncommenting this line.
    # PAGES["draft"] = st.Page(lambda: draft_page(client), title="Draft", icon="🎓",
    #                          url_path="draft")
    PAGES["predictions"] = st.Page(
        lambda: predictions_page(client), title="Predictions", icon="🔮", url_path="predictions"
    )
    PAGES["season"] = st.Page(
        lambda: season_outlook_page(client), title="Season outlook", icon="🗓️",
        url_path="season",
    )
    PAGES["methodology"] = st.Page(
        lambda: methodology_page(client), title="Methodology", icon="📐", url_path="methodology"
    )
    nav = st.navigation(list(PAGES.values()))

    # honor a pending drill-down jump requested by a table click last run
    goto = st.session_state.pop("_nav_to", None)
    if goto in PAGES and goto != nav.url_path:
        st.switch_page(PAGES[goto])

    # brand lives in the sidebar; the page headline names the page, so the
    # same "NBA Insights" wordmark no longer eats the top of all six pages
    st.sidebar.title("🏀 NBA Insights")
    st.sidebar.caption(
        "Data: stats.nba.com via nba_api. Responses are cached locally; "
        "current-season data refreshes daily."
    )
    st.title(f"{nav.icon} {nav.title}")
    nav.run()


main()
