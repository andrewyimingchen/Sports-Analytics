"""NBA Insights — player profiles, form trends, shot charts, comparisons.

Run with: uv run streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))  # sibling modules (methodology, ui)

from nba_insights.analysis import (
    attach_ratings,
    career_per_game,
    comparison_table,
    league_leaders,
    percentile_ranks,
    rolling_form,
    zone_efficiency,
)
from nba_insights.analysis.shots import ZONE_KEY
from nba_insights.config import current_season, past_seasons
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
    team_form_snapshot,
    upcoming_games,
)
from nba_insights.ml.train import OUTCOME_PATH, POINTS_PATH, WIN_CURVE_PATH
from nba_insights.viz import half_court_trace
from ui import inject_css

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


# display names for the rating columns on charts and tables
RATING_LABELS = {"NET_RATING": "NET RTG", "CLUTCH_NET_RATING": "CLUTCH NET"}


def league_with_ratings(client: NBAClient) -> pd.DataFrame:
    """League per-game stats enriched with net and clutch ratings.

    Falls back to the plain per-game table if the rating endpoints are
    unreachable — downstream defaults skip the missing columns.
    """
    league = client.league_player_stats()
    try:
        return attach_ratings(
            league, client.league_player_advanced(), client.league_player_clutch()
        )
    except Exception:
        return league


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
        transition=dict(duration=350, easing="cubic-in-out"),
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


def form_chart(form: pd.DataFrame, stat: str, window: int, label: str | None = None) -> go.Figure:
    label = label or stat
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=form["GAME_DATE"], y=form[stat], name=f"{label} per game", marker_color=PAL["grid"]
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
    return base_layout(fig, f"{label} form, game by game")


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
    fig.update_layout(hovermode="closest", showlegend=False)
    fig.update_xaxes(range=[0, 108], showgrid=True, gridcolor=PAL["grid"])
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
                line=dict(color=PAL["series"][i], width=2),
                marker=dict(size=8),
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
            marker=dict(color=PAL["series"][0], size=10),
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
            marker_color=colors,
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


def profile_header(
    player: dict,
    totals: pd.DataFrame,
    per_game: pd.DataFrame,
    ratings: pd.Series | None = None,
) -> None:
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

        has_ratings = ratings is not None and pd.notna(ratings.get("NET_RATING"))
        tiles = st.columns(5 if has_ratings else 3)
        career_games = totals["GP"].sum()
        for col, stat in zip(tiles, ("PTS", "AST", "REB"), strict=False):
            career_avg = totals[stat].sum() / career_games if career_games else 0
            col.metric(
                f"{stat} / game",
                f"{latest[stat]:.1f}",
                delta=f"{latest[stat] - career_avg:+.1f} vs career",
            )
        if has_ratings:
            tiles[3].metric("Net rating", f"{ratings['NET_RATING']:+.1f}")
            clutch = ratings.get("CLUTCH_NET_RATING")
            tiles[4].metric(
                "Clutch net",
                f"{clutch:+.1f}" if pd.notna(clutch) else "—",
                help="Net rating in the last 5 minutes with the score within 5 points.",
            )


@st.fragment
def season_detail(client: NBAClient, player: dict, seasons: list[str]) -> None:
    """Season-scoped charts; a fragment so switching season or stat only
    re-renders this section instead of rerunning the whole page."""
    pick = st.columns([3, 2])
    season = pick[0].selectbox("Season", list(reversed(seasons)))
    games_kind = pick[1].radio("Games", ["Regular season", "Playoffs"], horizontal=True)
    season_type = "Playoffs" if games_kind == "Playoffs" else "Regular Season"
    left, right = st.columns(2)

    with left:
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
                )
        except Exception as e:
            st.error(f"Could not load game log: {e}")

    with right:
        view = st.radio("Shot view", ["Makes & misses", "Zones vs league"], horizontal=True)
        try:
            shots = client.shot_chart(player["id"], season=season, season_type=season_type)
            if shots.empty:
                st.info(f"No {games_kind.lower()} shot data for this season.")
            elif view == "Zones vs league":
                zones = zone_efficiency(
                    shots, client.shot_league_averages(season=season, season_type=season_type)
                )
                st.plotly_chart(shot_zone_fig(shots, zones), width="stretch")
                st.caption(
                    "Color compares the player's FG% in each zone to the league "
                    "(±2 percentage points counts as even)."
                )
            else:
                st.plotly_chart(shot_chart_fig(shots), width="stretch")
        except Exception as e:
            st.error(f"Could not load shot chart: {e}")


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
    ratings = None
    if player["is_active"]:
        try:
            row = league_with_ratings(client)
            row = row[row["PLAYER_ID"] == player["id"]]
            ratings = row.iloc[0] if not row.empty else None
        except Exception:
            pass
    profile_header(player, totals, per_game, ratings)

    seasons = list(per_game["SEASON_ID"])
    st.plotly_chart(career_chart(per_game), width="stretch")

    season_detail(client, player, seasons)

    if player["is_active"]:
        try:
            league = league_with_ratings(client)
            ranks = percentile_ranks(league, player["full_name"]).rename(RATING_LABELS)
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
        leader_suggestions(client, "cmp_a", "cmp_b")
        return
    try:
        league = league_with_ratings(client)
        table = comparison_table(league, [a["full_name"], b["full_name"]])
        st.dataframe(table.rename(index=RATING_LABELS), width="stretch")

        ranks = pd.concat(
            [percentile_ranks(league, p["full_name"]).rename(RATING_LABELS) for p in (a, b)],
            axis=1,
        )
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
        fig.update_layout(barmode="group", hovermode="closest")
        fig.update_xaxes(range=[0, 100])
        fig.update_yaxes(autorange="reversed", automargin=True)
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


@st.cache_resource
def load_models() -> dict | None:
    if not (OUTCOME_PATH.exists() and POINTS_PATH.exists() and WIN_CURVE_PATH.exists()):
        return None
    return {
        "outcome": GameOutcomeModel.load(OUTCOME_PATH),
        "points": PlayerPointsModel.load(POINTS_PATH),
        "curve": WinCurve.load(WIN_CURVE_PATH),
    }


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

    league = client.league_player_stats()
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
    m = st.columns(2)
    m[0].metric(f"{home} win probability (home)", f"{prob:.0%}")
    m[1].metric(f"{away} win probability (away)", f"{1 - prob:.0%}")
    st.caption(
        "Logistic regression on season-to-date form differentials — win%, net "
        "rating, four factors (eFG%, TOV%, OREB%, FT rate), pace, ORtg/DRtg, "
        "rest, back-to-backs, and expected minutes out — plus home court. "
        "Holdout accuracy on the current season: ~69% (always-pick-home "
        "scores ~55%)."
    )
    with st.expander("Season-to-date form"):
        st.dataframe(
            snapshot.loc[[home, away]].drop(columns="last_game_date").round(3),
            width="stretch",
        )

    st.divider()
    slate_section(client, models, snapshot)


def slate_section(client: NBAClient, models: dict, snapshot: pd.DataFrame) -> None:
    st.subheader("Next slate")
    try:
        slate = upcoming_games(client.schedule())
    except Exception:
        slate = pd.DataFrame()
    if slate.empty:
        st.caption("No upcoming games on the schedule (offseason).")
        return
    rows = []
    for _, g in slate.iterrows():
        if g["home"] not in snapshot.index or g["away"] not in snapshot.index:
            continue
        gx = matchup_features(snapshot, g["home"], g["away"])
        p = float(models["outcome"].predict_proba(gx).iloc[0])
        tipoff = pd.Timestamp(g["tipoff"]).tz_convert("US/Eastern")
        rows.append(
            {
                "matchup": f"{g['away']} @ {g['home']}",
                "tipoff (ET)": tipoff.strftime("%b %d, %I:%M %p"),
                "home win prob": f"{p:.0%}",
            }
        )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    st.caption("Slate probabilities assume both teams at full strength.")


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
            marker_color=colors,
            width=3.4,
            customdata=[f"{iv.left:+.0f} to {iv.right:+.0f}" for iv in counts.index],
            hovertemplate="%{customdata}: %{y:.1%}<extra></extra>",
        )
    )
    fig = base_layout(fig, f"Simulated margin — {home} minus {away}")
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

    league = client.league_player_stats()
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

    m = st.columns(4)
    m[0].metric(f"{home} wins (10,000 sims)", f"{s['home_win_prob']:.0%}")
    favorite = home if s["median_margin"] >= 0 else away
    m[1].metric("Median margin", f"{favorite} by {abs(s['median_margin']):.0f}")
    m[2].metric("Median total", f"{s['median_total']:.0f} pts")
    m[3].metric("Overtime", f"{s['overtime_prob']:.1%}")

    st.plotly_chart(margin_chart(sims["home_pts"] - sims["away_pts"], home, away),
                    width="stretch")
    st.caption(
        f"80% of sims land between {home} {s['margin_p10']:+.0f} and "
        f"{s['margin_p90']:+.0f}. Monte Carlo over pace and ratings — "
        "possessions drawn around the teams' average pace, each side's "
        "scoring around its offensive rating against the opponent's defense, "
        "plus home court (fitted: 2.2 points) and minutes out. Holdout log "
        "loss 0.601 vs the outcome model's 0.585 — trust the model's win "
        "probability as the headline; the simulator adds the distributions."
    )
    try:
        x = matchup_features(
            snapshot, home, away,
            home_missing_min=missing[home], away_missing_min=missing[away],
        )
        model_p = float(models["outcome"].predict_proba(x).iloc[0])
        st.caption(f"For comparison, the outcome model gives {home} {model_p:.0%}.")
    except Exception:
        pass

    with st.expander("Total points distribution"):
        total = sims["home_pts"] + sims["away_pts"]
        fig = go.Figure(
            go.Histogram(x=total, nbinsx=40, marker_color=PAL["series"][0])
        )
        fig = base_layout(fig, "Simulated total points")
        fig.update_layout(hovermode="closest", showlegend=False, height=320)
        fig.update_yaxes(gridcolor=PAL["grid"])
        st.plotly_chart(fig, width="stretch")


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

    season_games = client.player_games()
    rows = season_games[season_games["PLAYER_ID"] == player["id"]]
    if rows.empty:
        st.warning("No games for this player in the current season.")
        return
    x = player_next_game_features(
        rows,
        home=venue == "Home",
        opp_form_net=float(snapshot.loc[opponent, "form_net"]),
        opp_form_drtg=float(snapshot.loc[opponent, "form_drtg"]),
        opp_form_pace=float(snapshot.loc[opponent, "form_pace"]),
    )
    pred = float(models["points"].predict(x).iloc[0])
    m = st.columns(3)
    interval = models["points"].interval(pred)
    m[0].metric("Projected points", f"{pred:.1f}")
    if interval:
        m[0].caption(f"80% range: {interval[0]:.0f}–{interval[1]:.0f}")
    m[1].metric("Last 5 games", f"{x['pts_r5'].iloc[0]:.1f}")
    m[2].metric("Last 10 games", f"{x['pts_r10'].iloc[0]:.1f}")
    st.caption(
        "Ridge regression on recent scoring, minutes, and shot volume, venue, rest, "
        "and opponent form — trained on three seasons of league-wide player games."
    )


@st.fragment
def lineup_tab(client: NBAClient, models: dict) -> None:
    league = client.league_player_stats()
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
    if minutes > 0:
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


@st.cache_data(ttl=86400, show_spinner=False)
def league_elo() -> pd.Series:
    """Current Elo per team, warmed up over the two prior seasons."""
    client = get_client()
    seasons = [*past_seasons(2), current_season()]
    return current_elo(pd.concat([client.team_games(s) for s in seasons], ignore_index=True))


def predictions_page(client: NBAClient) -> None:
    models = load_models()
    if models is None:
        st.info(
            "Models not trained yet. Run `uv run python -m nba_insights.ml.train` "
            "and reload this page."
        )
        return
    try:
        snapshot = team_form_snapshot(client.team_games())
    except Exception:
        snapshot = pd.DataFrame()
    if snapshot.empty:  # season hasn't started: fall back to last season's form
        snapshot = team_form_snapshot(client.team_games(past_seasons(1)[0]))
        st.caption("Season hasn't started — using last season's form (Elo already regressed).")
    try:
        snapshot["elo"] = league_elo().reindex(snapshot.index)
    except Exception:
        pass  # matchup_features degrades to a neutral elo_diff
    tabs = st.tabs(["Game outcome", "Simulate", "Player points", "Starting five"])
    with tabs[0]:
        outcome_tab(client, models, snapshot)
    with tabs[1]:
        simulate_tab(client, models, snapshot)
    with tabs[2]:
        points_tab(client, models, snapshot)
    with tabs[3]:
        lineup_tab(client, models)


@st.fragment
def team_detail(client: NBAClient, games: pd.DataFrame, snapshot: pd.DataFrame) -> None:
    """One team's season at a glance; a fragment so switching teams is light."""
    teams = sorted(snapshot.index)
    team = st.selectbox("Team", teams, index=teams.index("OKC") if "OKC" in teams else 0)
    log = games[games["TEAM_ABBREVIATION"] == team].sort_values("GAME_DATE")
    form = snapshot.loc[team]

    tiles = st.columns(4)
    wins, losses = int((log["WL"] == "W").sum()), int((log["WL"] == "L").sum())
    tiles[0].metric("Record", f"{wins}-{losses}")
    tiles[1].metric("Net rating", f"{form['form_net']:+.1f}")
    tiles[2].metric("ORtg / DRtg", f"{form['form_ortg']:.0f} / {form['form_drtg']:.0f}")
    try:
        tiles[3].metric("Elo", f"{league_elo()[team]:.0f}")
    except Exception:
        pass

    st.plotly_chart(
        form_chart(rolling_form(log, "PLUS_MINUS", 10), "PLUS_MINUS", 10, label="Point margin"),
        width="stretch",
    )

    left, right = st.columns(2)
    with left:
        st.subheader("Roster")
        try:
            league = league_with_ratings(client)
            roster = league[league["TEAM_ABBREVIATION"] == team].sort_values(
                "MIN", ascending=False
            )
            keep = [
                c
                for c in ("PLAYER_NAME", "GP", "MIN", "PTS", "AST", "REB", "NET_RATING")
                if c in roster.columns
            ]
            st.dataframe(
                roster[keep].rename(columns=RATING_LABELS),
                width="stretch",
                hide_index=True,
                height=390,
            )
        except Exception as e:
            st.error(f"Could not load roster: {e}")
    with right:
        st.subheader("Last 10 games")
        recent = log.tail(10).iloc[::-1]
        st.dataframe(
            recent[["GAME_DATE", "MATCHUP", "WL", "PTS", "PLUS_MINUS"]].rename(
                columns={"PLUS_MINUS": "MARGIN"}
            ),
            width="stretch",
            hide_index=True,
            height=390,
        )


def teams_page(client: NBAClient) -> None:
    st.caption(f"Teams · {current_season()}")
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
    conf_cols = st.columns(2)
    for col, conf in zip(conf_cols, ("East", "West"), strict=True):
        rows = standings[standings["Conference"] == conf].sort_values("PlayoffRank")
        table = pd.DataFrame(
            {
                "#": rows["PlayoffRank"].astype(int),
                "Team": rows["TeamCity"] + " " + rows["TeamName"],
                "W": rows["WINS"].astype(int),
                "L": rows["LOSSES"].astype(int),
                "Win%": rows["WinPCT"].round(3),
                "L10": rows["L10"].str.strip(),
                "Streak": rows["strCurrentStreak"].str.strip(),
            }
        )
        with col:
            st.caption(conf)
            st.dataframe(table, width="stretch", hide_index=True, height=390)


def home_page(client: NBAClient) -> None:
    """League pulse: the app opens with content, not an empty search box."""
    st.caption(f"League pulse · {current_season()}")
    try:
        league = league_with_ratings(client)
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
    tiles = st.columns(len(specs))
    boards: dict[str, pd.DataFrame] = {}
    for col, (stat, label) in zip(tiles, specs, strict=True):
        pool = league
        if stat == "NET_RATING":
            pool = league[league["MIN"] >= 15]  # rotation players only
        elif stat == "CLUTCH_NET_RATING" and "CLUTCH_GP" in league.columns:
            pool = league[league["CLUTCH_GP"] >= 15]  # enough clutch games
        try:
            boards[label] = league_leaders(pool, stat, top=10)
        except KeyError:
            continue
        row = boards[label].iloc[0]
        team = row.get("TEAM_ABBREVIATION", "")
        value = f"{row[stat]:+.1f}" if "RATING" in stat else f"{row[stat]:.1f}"
        col.metric(label, value)
        col.caption(f"{row['PLAYER_NAME']} · {team}")
    with st.expander("Top-ten leaderboards"):
        for tab, label in zip(st.tabs(list(boards)), boards, strict=True):
            with tab:
                st.dataframe(boards[label].round(1), width="stretch", hide_index=True)

    try:
        snapshot = team_form_snapshot(client.team_games())
    except Exception:
        snapshot = pd.DataFrame()
    if not snapshot.empty:
        left, right = st.columns(2)
        with left:
            try:
                st.plotly_chart(elo_dot_chart(league_elo()), width="stretch")
            except Exception as e:
                st.caption(f"Elo rankings unavailable: {e}")
        with right:
            st.plotly_chart(net_rating_chart(snapshot), width="stretch")
        with st.expander("Full team form table"):
            st.dataframe(
                snapshot.drop(columns="last_game_date").round(3).sort_values(
                    "form_net", ascending=False
                ),
                width="stretch",
            )

    models = load_models()
    if models is not None and not snapshot.empty:
        try:
            snapshot["elo"] = league_elo().reindex(snapshot.index)
        except Exception:
            pass
        st.divider()
        slate_section(client, models, snapshot)


def methodology_page(client: NBAClient) -> None:
    import methodology

    methodology.render(client, load_models(), PAL)


def main() -> None:
    PAL.update(theme_palette())
    inject_css()
    client = get_client()
    nav = st.navigation(
        [
            st.Page(lambda: home_page(client), title="League pulse", icon="📈", default=True),
            st.Page(
                lambda: profile_page(client),
                title="Player profile",
                icon="🏀",
                url_path="profile",
            ),
            st.Page(
                lambda: compare_page(client),
                title="Compare players",
                icon="⚖️",
                url_path="compare",
            ),
            st.Page(lambda: teams_page(client), title="Teams", icon="🏟️", url_path="teams"),
            st.Page(
                lambda: predictions_page(client),
                title="Predictions",
                icon="🔮",
                url_path="predictions",
            ),
            st.Page(
                lambda: methodology_page(client),
                title="Methodology",
                icon="📐",
                url_path="methodology",
            ),
        ]
    )
    st.title("🏀 NBA Insights")
    st.sidebar.caption(
        "Data: stats.nba.com via nba_api. Responses are cached locally; "
        "current-season data refreshes daily."
    )
    nav.run()


main()
