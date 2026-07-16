"""NBA Insights — player profiles, form trends, shot charts, comparisons.

Run with: uv run streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))  # sibling modules (methodology, ui)

from nba_insights import serve
from nba_insights.analysis import (
    career_per_game,
    comparison_table,
    draft_class,
    league_leaders,
    percentile_ranks,
    player_draft_line,
    rolling_form,
    shot_quality,
    team_on_off,
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
from nba_insights.ml.train import METRICS_PATH, OUTCOME_PATH, POINTS_PATH, WIN_CURVE_PATH
from nba_insights.posters import compare_poster_png, prediction_poster_png
from nba_insights.viz import half_court_trace
from ui import inject_css

logger = logging.getLogger(__name__)

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
RATING_LABELS = {
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
def fetch_headshot(player_id: int) -> bytes | None:
    """Fetch the headshot server-side; the CDN rejects browser hotlinking."""
    return serve.fetch_headshot(player_id)


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
            # a percentile axis must stop at 100; long bars carry their
            # label inside instead of stretching the scale to fit it
            textposition=["inside" if v > 90 else "outside" for v in ranks.values],
        )
    )
    fig = base_layout(fig, f"League percentile, {current_season()}")
    fig.update_layout(hovermode="closest", showlegend=False)
    fig.update_xaxes(range=[0, 100], showgrid=True, gridcolor=PAL["grid"])
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


def win_prob_bar(home: str, away: str, prob: float) -> None:
    """One shared probability track — home fill vs away fill, labeled ends.

    Replaces twin metrics: a single mark makes the complementarity obvious
    and the favourite readable at a glance. Colors follow the entity
    (home=blue, away=red), matching the margin chart's convention.
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
    <div style="width:{(1 - prob) * 100:.1f}%; background:{PAL["series"][5]};"></div>
  </div>
</div>""",
        unsafe_allow_html=True,
    )


# profile badge labels: stat code -> plain-language skill
_BADGE_LABELS = {
    "PTS": "Scoring",
    "AST": "Playmaking",
    "REB": "Rebounding",
    "STL": "Steals",
    "BLK": "Rim protection",
    "FG_PCT": "Shooting efficiency",
    "FG3_PCT": "3-point shooting",
    "FT_PCT": "Free throws",
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
    st.markdown(f'<div class="pills">{pills}</div>', unsafe_allow_html=True)


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
        context = f"{team} · {latest['SEASON_ID']} · {int(latest['GP'])} games"
        if draft_note:
            context += f" · {draft_note}"
        st.caption(context)

        has_ratings = ratings is not None and pd.notna(ratings.get("NET_RATING"))
        has_dpm = ratings is not None and pd.notna(ratings.get("DPM"))
        tiles = st.columns(3 + (2 if has_ratings else 0) + (1 if has_dpm else 0))
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
        if has_dpm:
            tiles[-1].metric(
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
            if not shots.empty:
                shot_quality_tiles(client, shots, season, season_type)
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
    ratings, ranks = None, None
    if player["is_active"]:
        try:
            league = league_with_ratings(client)
            row = league[league["PLAYER_ID"] == player["id"]]
            ratings = row.iloc[0] if not row.empty else None
            ranks = percentile_ranks(league, player["full_name"]).rename(RATING_LABELS)
        except KeyError:
            ranks = None  # not enough games for league ranks this season
        except Exception:
            logger.warning("league ratings unavailable for profile", exc_info=True)
    draft_note = None
    try:
        draft_note = player_draft_line(client.draft_history(), player["id"])
    except Exception:
        logger.warning("draft history unavailable for profile", exc_info=True)
    profile_header(player, totals, per_game, ratings, draft_note)
    if ranks is not None:
        skill_badges(ranks)
    if player["is_active"]:
        on_off_tiles(client, player, totals)

    seasons = list(per_game["SEASON_ID"])
    st.plotly_chart(career_chart(per_game), width="stretch")

    season_detail(client, player, seasons)

    percentile_section(client, player, seasons)


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
    season = st.selectbox("Percentile season", list(reversed(options)), key="pct_season")
    try:
        league = league_with_ratings(client, None if season == current_season() else season)
        ranks = percentile_ranks(league, player["full_name"]).rename(RATING_LABELS)
    except KeyError:
        st.caption(f"Not enough games in {season} for league percentile ranks.")
        return
    except Exception as e:
        st.caption(f"Percentiles unavailable: {e}")
        return
    st.plotly_chart(percentile_chart(ranks), width="stretch")
    with st.expander("Percentile data as table"):
        st.dataframe(ranks.to_frame("percentile"))


# stats where a smaller number wins the row
_LOWER_BETTER = {"TOV"}


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

    return table.style.apply(highlight, axis=1)


def compare_page(client: NBAClient) -> None:
    st.caption(f"Per-game stats, {current_season()} season. Compare up to four players.")
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
    try:
        league = league_with_ratings(client)
        table = comparison_table(league, [p["full_name"] for p in players])
        st.dataframe(_best_value_style(table.rename(index=RATING_LABELS)), width="stretch")

        ranks = pd.concat(
            [percentile_ranks(league, p["full_name"]).rename(RATING_LABELS) for p in players],
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

        st.download_button(
            "Download share poster (PNG)",
            compare_poster_png(table, current_season()),
            file_name=f"{' vs '.join(table.columns)}.png",
            mime="image/png",
            help="1080×1080 image of this comparison, ready to post.",
        )
    except KeyError as e:
        st.warning(f"Comparison needs every player active this season: {e}")
    except Exception as e:
        st.error(f"Could not load comparison: {e}")
        return

    with st.expander("Shot quality (xeFG)"):
        try:
            league_avgs = client.shot_league_averages()
            quality = pd.concat(
                {
                    p["full_name"]: shot_quality(client.shot_chart(p["id"]), league_avgs)
                    for p in players
                },
                axis=1,
            )
            table = (quality.loc[["XEFG", "EFG", "MAKING"]] * 100).rename(
                index={
                    "XEFG": "Shot diet (xeFG%)",
                    "EFG": "Actual eFG%",
                    "MAKING": "Shot making (eFG pts)",
                }
            )
            st.dataframe(_best_value_style(table.round(1)), width="stretch")
            st.caption(
                "xeFG% is the eFG% a league-average shooter would post on each "
                "player's shot locations; shot making is actual minus expected."
            )
        except Exception as e:
            st.caption(f"Shot quality unavailable: {e}")

    try:
        careers = {
            p["full_name"]: career_per_game(client.career_stats(p["id"])) for p in players
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
    win_prob_bar(home, away, prob)
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
        logger.warning("schedule unavailable for the slate", exc_info=True)
        slate = pd.DataFrame()
    if slate.empty:
        st.caption("No upcoming games on the schedule (offseason).")
        return
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
                    width="stretch")
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


@st.cache_data(ttl=86400, show_spinner="Warming Elo ratings (two prior seasons)…")
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
        logger.warning("Elo unavailable for team tile", exc_info=True)
        tiles[3].metric("Elo", "—", help="Elo ratings unavailable right now.")

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
                for c in ("PLAYER_NAME", "GP", "MIN", "PTS", "AST", "REB", "NET_RATING", "DPM")
                if c in roster.columns
            ]
            st.dataframe(
                roster[keep].rename(columns=RATING_LABELS),
                width="stretch",
                hide_index=True,
                height=390,
                column_config={
                    "MIN": st.column_config.ProgressColumn(
                        "MIN", min_value=0.0, max_value=40.0, format="%.1f"
                    ),
                    "PTS": st.column_config.NumberColumn(format="%.1f"),
                    "AST": st.column_config.NumberColumn(format="%.1f"),
                    "REB": st.column_config.NumberColumn(format="%.1f"),
                    "NET RTG": st.column_config.NumberColumn(format="%.1f"),
                    "DARKO DPM": st.column_config.NumberColumn(format="%+.1f"),
                },
            )
        except Exception as e:
            st.error(f"Could not load roster: {e}")
    with right:
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
            st.dataframe(
                table,
                width="stretch",
                hide_index=True,
                height=390,
                column_config={
                    "Win%": st.column_config.ProgressColumn(
                        "Win%", min_value=0.0, max_value=1.0, format="%.3f"
                    ),
                },
            )


def home_page(client: NBAClient) -> None:
    """League pulse: the app opens with content, not an empty search box."""
    head = st.columns([5, 1])
    season = head[1].selectbox(
        "Season", seasons_since(), key="pulse_season", label_visibility="collapsed",
        help="Dashboards go back to 1996-97. Past seasons load live on first view.",
    )
    is_current = season == current_season()
    head[0].caption(f"League pulse · {season}")
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
    tiles = st.columns(len(specs))
    boards: dict[str, pd.DataFrame] = {}
    for col, (stat, label) in zip(tiles, specs, strict=True):
        pool = league
        if stat == "NET_RATING" and "MIN" in league.columns:
            pool = league[league["MIN"] >= 15]  # rotation players only
        elif stat == "CLUTCH_NET_RATING" and "CLUTCH_GP" in league.columns:
            pool = league[league["CLUTCH_GP"] >= min(15, min_gp)]  # enough clutch games
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
                    st.image(photo, width=76)
            st.metric(label, value)
            st.caption(f"{row['PLAYER_NAME']} · {team}")
    if boards:
        with st.expander("Top-ten leaderboards"):
            for tab, label in zip(st.tabs(list(boards)), boards, strict=True):
                with tab:
                    st.dataframe(
                        boards[label].drop(columns="PLAYER_ID", errors="ignore").round(1),
                        width="stretch",
                        hide_index=True,
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
                    st.plotly_chart(elo_dot_chart(league_elo()), width="stretch")
                except Exception as e:
                    st.caption(f"Elo rankings unavailable: {e}")
            with right:
                st.plotly_chart(net_rating_chart(snapshot), width="stretch")
        else:
            # Elo and the slate are "now" widgets; a past season keeps form only
            st.plotly_chart(net_rating_chart(snapshot), width="stretch")
        with st.expander("Full team form table"):
            st.dataframe(
                snapshot.drop(columns="last_game_date").round(3).sort_values(
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
        st.divider()
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
            st.Page(lambda: draft_page(client), title="Draft", icon="🎓", url_path="draft"),
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
