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

# Reference dataviz palette: categorical slots in fixed order, chrome inks.
SERIES = ["#2a78d6", "#1baf7a", "#eda100", "#008300", "#4a3aa7", "#e34948"]
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"

st.set_page_config(page_title="NBA Insights", page_icon="🏀", layout="wide")


@st.cache_resource
def get_client() -> NBAClient:
    return NBAClient()


def base_layout(fig: go.Figure, title: str) -> go.Figure:
    fig.update_layout(
        title=title,
        template="none",
        margin=dict(l=40, r=20, t=50, b=40),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
        hovermode="x unified",
    )
    fig.update_xaxes(showgrid=False, linecolor=GRIDLINE)
    fig.update_yaxes(gridcolor=GRIDLINE, zeroline=False)
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
                    line=dict(color=SERIES[i], width=2),
                    marker=dict(size=8),
                )
            )
    return base_layout(fig, "Career per-game trajectory")


def form_chart(form: pd.DataFrame, stat: str, window: int) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Bar(x=form["GAME_DATE"], y=form[stat], name=f"{stat} per game", marker_color=GRIDLINE)
    )
    fig.add_trace(
        go.Scatter(
            x=form["GAME_DATE"],
            y=form["ROLLING"],
            name=f"{window}-game rolling avg",
            mode="lines",
            line=dict(color=SERIES[0], width=2),
        )
    )
    return base_layout(fig, f"{stat} form, game by game")


def shot_chart_fig(shots: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for made, label, color, symbol in [
        (0, "Missed", INK_MUTED, "circle-open"),
        (1, "Made", SERIES[0], "circle"),
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
    fig = base_layout(fig, "Shot chart (half court, basket at origin)")
    fig.update_layout(hovermode="closest", height=560)
    fig.update_xaxes(range=[-260, 260], visible=False)
    fig.update_yaxes(range=[-60, 430], visible=False, scaleanchor="x", scaleratio=1)
    return fig


def percentile_chart(ranks: pd.Series) -> go.Figure:
    fig = go.Figure(
        go.Bar(
            x=ranks.values,
            y=ranks.index,
            orientation="h",
            marker_color=SERIES[0],
            text=[f"{v:.0f}" for v in ranks.values],
            textposition="outside",
        )
    )
    fig = base_layout(fig, f"League percentile, {current_season()}")
    fig.update_layout(hovermode="closest", showlegend=False)
    fig.update_xaxes(range=[0, 108], showgrid=True, gridcolor=GRIDLINE)
    fig.update_yaxes(autorange="reversed", showgrid=False)
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


def profile_page(client: NBAClient) -> None:
    player = pick_player(client, "Search for a player", "profile_search")
    if not player:
        st.info("Type a player name to build their profile.")
        return
    st.subheader(player["full_name"])

    with st.spinner("Loading career stats…"):
        totals = client.career_stats(player["id"])
    if totals.empty:
        st.error("No career data found for this player.")
        return

    per_game = career_per_game(totals)
    seasons = list(per_game["SEASON_ID"])
    st.plotly_chart(career_chart(per_game), width='stretch')

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
                    width='stretch',
                )
        except Exception as e:
            st.error(f"Could not load game log: {e}")

    with right:
        try:
            shots = client.shot_chart(player["id"], season=season)
            if shots.empty:
                st.info("No shot data for this season.")
            else:
                st.plotly_chart(shot_chart_fig(shots), width='stretch')
        except Exception as e:
            st.error(f"Could not load shot chart: {e}")

    if player["is_active"]:
        try:
            league = client.league_player_stats()
            ranks = percentile_ranks(league, player["full_name"])
            st.plotly_chart(percentile_chart(ranks), width='stretch')
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
        st.dataframe(table, width='stretch')

        ranks = pd.concat(
            [percentile_ranks(league, p["full_name"]) for p in (a, b)], axis=1
        )
        fig = go.Figure()
        for i, name in enumerate(ranks.columns):
            fig.add_trace(
                go.Bar(x=ranks[name].values, y=ranks.index, orientation="h",
                       name=name, marker_color=SERIES[i])
            )
        fig = base_layout(fig, "League percentile, side by side")
        fig.update_layout(barmode="group", hovermode="closest")
        fig.update_xaxes(range=[0, 100])
        fig.update_yaxes(autorange="reversed")
        st.plotly_chart(fig, width='stretch')
    except KeyError as e:
        st.warning(f"Comparison needs both players active this season: {e}")
    except Exception as e:
        st.error(f"Could not load comparison: {e}")


def main() -> None:
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
