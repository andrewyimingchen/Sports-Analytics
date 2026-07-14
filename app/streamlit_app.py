"""NBA Insights — player profiles, form trends, shot charts, comparisons.

Run with: uv run streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from nba_insights.analysis import (
    career_per_game,
    comparison_table,
    percentile_ranks,
    rolling_form,
)
from nba_insights.config import current_season
from nba_insights.ingest import NBAClient
from nba_insights.viz import half_court_trace

HEADSHOT_URL = "https://cdn.nba.com/headshots/nba/latest/1040x760/{player_id}.png"

# Reference dataviz palette: categorical slots in fixed order, chrome inks.
# Dark values are the same hues re-stepped for the dark surface, not a flip.
_LIGHT = {
    "series": ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948"],
    "grid": "#e1e0d9",
    "muted": "#898781",
    "ink2": "#52514e",
}
_DARK = {
    "series": ["#3987e5", "#199e70", "#c98500", "#008300", "#9085e9", "#e66767"],
    "grid": "#2c2c2a",
    "muted": "#898781",
    "ink2": "#c3c2b7",
}

st.set_page_config(page_title="NBA Insights", page_icon="🏀", layout="wide")


def theme_palette() -> dict:
    theme = getattr(st.context, "theme", None)
    return _DARK if theme is not None and theme.type == "dark" else _LIGHT


# Populated in main(): the theme context isn't reliable at import time.
PAL = dict(_LIGHT)


@st.cache_resource
def get_client() -> NBAClient:
    return NBAClient()


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_headshot(player_id: int) -> bytes | None:
    """Fetch the headshot server-side; the CDN rejects browser hotlinking."""
    import requests

    try:
        r = requests.get(
            HEADSHOT_URL.format(player_id=player_id),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=10,
        )
        r.raise_for_status()
        return r.content
    except Exception:
        return None


def base_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=title,
        template="none",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=PAL["ink2"]),
        margin=dict(l=40, r=20, t=50, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False, linecolor=PAL["grid"], tickcolor=PAL["muted"])
    fig.update_yaxes(gridcolor=PAL["grid"], zeroline=False)
    return fig


def career_chart(per_game: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for i, stat in enumerate(["PTS", "AST", "REB"]):
        if stat in per_game.columns:
            fig.add_trace(
                go.Scatter(
                    x=per_game["SEASON_ID"],
                    y=per_game[stat],
                    name=stat,
                    mode="lines+markers",
                    line=dict(color=PAL["series"][i], width=2),
                    marker=dict(size=8),
                )
            )
    fig = base_layout(fig, "Career per-game trajectory")
    fig.update_xaxes(type="category")  # "2003-04" is a season label, not a date
    return fig


def form_chart(form: pd.DataFrame, stat: str, window: int) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=form["GAME_DATE"], y=form[stat], name=f"{stat} per game", marker_color=PAL["grid"]
        )
    )
    fig.add_trace(
        go.Scatter(
            x=form["GAME_DATE"],
            y=form["ROLLING"],
            name=f"{window}-game rolling avg",
            mode="lines",
            line=dict(color=PAL["series"][0], width=2),
        )
    )
    return base_layout(fig, f"{stat} form, game by game")


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


def percentile_chart(ranks: pd.Series) -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=ranks.values,
            y=ranks.index,
            orientation="h",
            marker_color=PAL["series"][0],
            text=[f"{v:.0f}" for v in ranks.values],
            textposition="outside",
        )
    )
    fig = base_layout(fig, f"League percentile, {current_season()}")
    fig.update_layout(hovermode="closest", showlegend=False, margin=dict(l=70))
    fig.update_xaxes(range=[0, 108], showgrid=True, gridcolor=PAL["grid"])
    fig.update_yaxes(autorange="reversed", showgrid=False)
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
                line=dict(color=PAL["series"][i], width=2),
                marker=dict(size=8),
            )
        )
    fig = base_layout(fig, f"Career {stat} per game, by season")
    # ascending sort: categories otherwise follow first-seen order, which
    # interleaves wrongly when the players' careers span different years
    fig.update_xaxes(type="category", categoryorder="category ascending")
    return fig


def pick_player(client: NBAClient, label: str, key: str) -> dict | None:
    query = st.text_input(label, key=key, placeholder="e.g. LeBron James")
    if not query or len(query) < 3:
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


def profile_header(player: dict, totals: pd.DataFrame, per_game: pd.DataFrame) -> None:
    """Headshot, team context, and headline stat tiles with career deltas."""
    latest_totals = totals[totals["GP"] > 0].sort_values("SEASON_ID").iloc[-1]
    latest = per_game.iloc[-1]

    photo, info = st.columns([1, 5])
    with photo:
        headshot = fetch_headshot(player["id"])
        if headshot:
            st.image(headshot, width=130)
    with info:
        st.subheader(player["full_name"])
        team = latest_totals.get("TEAM_ABBREVIATION", "")
        st.caption(f"{team} · {latest['SEASON_ID']} · {int(latest['GP'])} games")

        tiles = st.columns(3)
        career_games = totals["GP"].sum()
        for col, stat in zip(tiles, ("PTS", "AST", "REB"), strict=False):
            career_avg = totals[stat].sum() / career_games if career_games else 0
            col.metric(
                f"{stat} / game",
                f"{latest[stat]:.1f}",
                delta=f"{latest[stat] - career_avg:+.1f} vs career",
            )


def profile_page(client: NBAClient) -> None:
    player = pick_player(client, "Search for a player", "profile_search")
    if not player:
        st.info("Type a player name to build their profile.")
        return

    with st.spinner("Loading career stats…"):
        totals = client.career_stats(player["id"])
    if totals.empty:
        st.error("No career data found for this player.")
        return

    per_game = career_per_game(totals)
    profile_header(player, totals, per_game)

    seasons = list(per_game["SEASON_ID"])
    st.plotly_chart(career_chart(per_game), width="stretch")

    season = st.selectbox("Season", list(reversed(seasons)))
    left, right = st.columns(2)

    with left:
        stat = st.selectbox("Form stat", ["PTS", "AST", "REB", "STL", "BLK"])
        try:
            log = client.game_log(player["id"], season=season)
            if log.empty:
                st.info("No games logged for this season.")
            else:
                window = min(10, max(2, len(log) // 3))
                st.plotly_chart(
                    form_chart(rolling_form(log, stat, window), stat, window),
                    width="stretch",
                )
        except Exception as e:
            st.error(f"Could not load game log: {e}")

    with right:
        try:
            shots = client.shot_chart(player["id"], season=season)
            if shots.empty:
                st.info("No shot data for this season.")
            else:
                st.plotly_chart(shot_chart_fig(shots), width="stretch")
        except Exception as e:
            st.error(f"Could not load shot chart: {e}")

    if player["is_active"]:
        try:
            league = client.league_player_stats()
            ranks = percentile_ranks(league, player["full_name"])
            st.plotly_chart(percentile_chart(ranks), width="stretch")
            with st.expander("Percentile data as table"):
                st.dataframe(ranks.to_frame("percentile"))
        except KeyError:
            st.caption("Not enough games this season for league percentile ranks.")
        except Exception as e:
            st.error(f"Could not load league stats: {e}")


def compare_page(client: NBAClient) -> None:
    st.caption(f"Per-game stats, {current_season()} season.")
    cols = st.columns(2)
    with cols[0]:
        a = pick_player(client, "First player", "cmp_a")
    with cols[1]:
        b = pick_player(client, "Second player", "cmp_b")
    if not (a and b):
        st.info("Pick two players to compare.")
        return
    try:
        league = client.league_player_stats()
        table = comparison_table(league, [a["full_name"], b["full_name"]])
        st.dataframe(table, width="stretch")

        ranks = pd.concat([percentile_ranks(league, p["full_name"]) for p in (a, b)], axis=1)
        fig = go.Figure()
        for i, name in enumerate(ranks.columns):
            fig.add_trace(
                go.Bar(
                    x=ranks[name].values,
                    y=ranks.index,
                    orientation="h",
                    name=name,
                    marker_color=PAL["series"][i],
                )
            )
        fig = base_layout(fig, "League percentile, side by side")
        fig.update_layout(barmode="group", hovermode="closest", margin=dict(l=70))
        fig.update_xaxes(range=[0, 100])
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, width="stretch")
    except KeyError as e:
        st.warning(f"Comparison needs both players active this season: {e}")
    except Exception as e:
        st.error(f"Could not load comparison: {e}")
        return

    try:
        careers = {
            p["full_name"]: career_per_game(client.career_stats(p["id"])) for p in (a, b)
        }
        if all(not df.empty for df in careers.values()):
            st.plotly_chart(compare_careers_chart(careers), width="stretch")
    except Exception as e:
        st.error(f"Could not load career comparison: {e}")


def main() -> None:
    PAL.update(theme_palette())
    st.title("🏀 NBA Insights")
    client = get_client()
    page = st.sidebar.radio("View", ["Player profile", "Compare players"])
    st.sidebar.caption(
        "Data: stats.nba.com via nba_api. Responses are cached locally; "
        "current-season data refreshes daily."
    )
    if page == "Player profile":
        profile_page(client)
    else:
        compare_page(client)


main()
