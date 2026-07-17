"""Model methodology & analysis page for the Streamlit app.

Static content states the protocol and the measured record (numbers are
facts of record from docs/DATA_ROADMAP.md); the coefficient and calibration
analyses are computed live from the saved pipelines and the true holdout,
so they always describe the models actually being served.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from nba_insights.config import current_season
from nba_insights.ml.features import OUTCOME_FEATURES
from nba_insights.ml.performance import MIN_FEATURES, RATE_FEATURES
from nba_insights.ml.train import build_elo, build_matchups

# measured record: (label, holdout accuracy %, what changed)
JOURNEY = [
    ("Always pick home", 54.9, "no model — the baseline every stage is judged against"),
    ("Last-10 form", 65.1, "win%, net rating, scoring, rest"),
    ("Season + four factors", 68.3, "eFG/TOV/OREB/FT rate, pace, ORtg/DRtg, fatigue"),
    ("+ Availability", 69.2, "expected minutes out, derived from absences"),
    ("+ Elo", 70.0, "margin-aware, 75% kept across seasons"),
    ("+ Seeded form", 70.2, "covers opening weeks; full 1,225-game season"),
]

REJECTED = pd.DataFrame(
    [
        ("Venue-split form", "log loss 0.594 vs 0.588", "intercept already carries home court"),
        ("SOS-adjusted net", "log loss 0.593", "double-counts net + four factors"),
        (
            "Garbage-time filtering",
            "log loss flat (0.5878→0.5881)",
            "season averages already dilute blowouts",
        ),
        ("Gradient boosting", "log loss 0.621", "overfits smooth collinear features at n≈3.5k"),
        ("Neural nets (5 MLP configs)", "best 69.8% / 0.598", "classifier isn't the bottleneck"),
    ],
    columns=["Candidate", "Holdout result", "Why it lost"],
)


def _coef_chart(pipeline, features: list[str], title: str, pal: dict) -> go.Figure:
    scaler = pipeline.named_steps.get("standardscaler")
    model = pipeline.steps[-1][1]
    coefs = model.coef_.ravel() if hasattr(model.coef_, "ravel") else model.coef_
    df = (
        pd.DataFrame({"feature": features, "coef": coefs})
        .sort_values("coef")
        .reset_index(drop=True)
    )
    # diverging encoding: sign is the polarity, blue helps home / red hurts
    colors = ["#2a78d6" if c > 0 else "#e34948" for c in df["coef"]]
    fig = go.Figure(
        go.Bar(x=df["coef"], y=df["feature"], orientation="h", marker_color=colors)
    )
    fig.update_layout(
        title=title,
        template="none",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=pal["ink2"]),
        margin=dict(l=150, r=20, t=50, b=40),
        height=30 * len(features) + 90,
        showlegend=False,
    )
    fig.update_xaxes(gridcolor=pal["grid"], zeroline=True, zerolinecolor=pal["muted"])
    fig.update_yaxes(showgrid=False)
    _ = scaler  # inputs are standardized, so coefficients are comparable
    return fig


@st.cache_data(ttl=86400, show_spinner="Scoring the holdout season…")
def _holdout_predictions(_client, _outcome_model) -> pd.DataFrame:
    """Shipped-model predictions over the true holdout (current season)."""
    season = current_season()
    elo = build_elo(_client, [season])
    matchups = build_matchups(_client, [season], elo)
    matchups["p"] = _outcome_model.predict_proba(matchups)
    return matchups[["p", "home_win"]]


def _calibration_chart(preds: pd.DataFrame, pal: dict) -> go.Figure:
    bins = pd.cut(preds["p"], bins=[0, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0])
    cal = preds.groupby(bins, observed=True).agg(
        predicted=("p", "mean"), actual=("home_win", "mean"), n=("home_win", "size")
    )
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="perfect",
                   line=dict(color=pal["grid"], width=1, dash="dot"))
    )
    fig.add_trace(
        go.Scatter(
            x=cal["predicted"], y=cal["actual"], mode="lines+markers",
            name="model", line=dict(color="#2a78d6", width=2),
            marker=dict(size=(cal["n"] / cal["n"].max() * 14 + 6)),
            text=[f"{n} games" for n in cal["n"]],
        )
    )
    fig.update_layout(
        title="Calibration on the holdout season (marker size = games in bin)",
        template="none",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=pal["ink2"]),
        xaxis_title="predicted home-win probability",
        yaxis_title="actual home-win rate",
        margin=dict(l=50, r=20, t=50, b=45),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1.0),
    )
    fig.update_xaxes(range=[0, 1], gridcolor=pal["grid"])
    fig.update_yaxes(range=[0, 1], gridcolor=pal["grid"])
    return fig


def render(client, models: dict, pal: dict) -> None:
    st.markdown(
        """
### How these models are built and judged

**Data.** Everything comes from stats.nba.com via `nba_api`, cached locally
in SQLite: league-wide team and player game logs, schedules, lineups, and
play-by-play. No scraping, no paid feeds.

**Evaluation protocol.** Every change is judged on a *temporal holdout*:
models train on the three seasons before the current one and are scored on
the current season — games they have genuinely never seen, in
chronological order, exactly as a forecast would face them. Log loss (for
probabilities) and MAE (for points) are the decision metrics. Changes that
don't improve the holdout are reverted, and the failures are documented
below just like the successes.

**Holdout hygiene.** Hyperparameters are tuned on a *dev season* — the most
recent training season — never on the holdout; the holdout is scored once,
after all choices are locked. One honest caveat: the feature-set decisions
recorded in the journey and rejected tables below were historically
adjudicated on the holdout season itself, so treat those specific numbers
as the best of several looks rather than a single clean draw. The training
pipeline (`ml/train.py`) now enforces the dev-season protocol, and
`data/models/metrics.json` records the once-only holdout numbers the app
quotes.

**Leakage discipline.** Every rolling feature is shifted one game: a row's
features describe what was knowable *before* tipoff. Elo ratings are
strictly pre-game; availability expectations use only prior games.
"""
    )

    st.divider()
    st.markdown("### Descriptive metrics on the player and team pages")
    st.markdown(
        """
**On/off splits.** Team offensive/defensive/net rating with a player on
vs off the floor, straight from stats.nba.com's team on/off dashboard
(total minutes, no adjustment). The swing is a *description*, not an
impact estimate: it inherits whoever else shared or replaced those
minutes, so small samples and bench context can dominate — the teams
table floors it at 100 on-court minutes.

**Shot quality (xeFG%).** Each attempt is scored at the league's FG% for
its zone (threes weighted 1.5×), giving the eFG% a league-average
shooter would post on the same shot diet. Actual eFG% minus that
expectation isolates *shot making* from *shot selection*. Zone-level
expectation is deliberately coarse — no defender distance or shot clock —
so treat it as a first-order split, not a full shot-quality model.

**DARKO DPM.** The daily plus-minus projection from
[darko.app](https://darko.app) (Kostya Medvedovsky & Andrew Patton),
shown alongside our net/clutch ratings as an external reference point.
It is displayed, never used as a model feature, and refreshed daily
through the same cache as everything else.
"""
    )

    st.divider()
    st.markdown("### Game outcome model")
    st.markdown(
        """
Logistic regression (scaled; regularization strength tuned on the dev
season) on **home-minus-away differentials**
of season-to-date form: win%, net rating, Dean Oliver's four factors
(eFG%, TOV%, OREB%, FT rate), pace and per-100 ratings — plus rest and
back-to-back flags, expected minutes out (derived from who actually missed
games, seeded with prior-season minutes), and a margin-aware Elo carried
across seasons. Form is seeded with prior-season team means (fading over
~10 games), so the model predicts from opening night. The intercept
absorbs home-court advantage.

Simpler wins: gradient boosting and five neural-net configurations were
each tried and lost — with ~3,200 training games of smooth, hand-built
features, the classifier is not the bottleneck.
"""
    )
    journey = pd.DataFrame(JOURNEY, columns=["stage", "accuracy", "what changed"])
    fig = go.Figure(
        go.Bar(
            x=journey["accuracy"],
            y=journey["stage"],
            orientation="h",
            marker_color=["#898781"] + ["#2a78d6"] * (len(journey) - 1),
            text=[f"{a:.1f}%" for a in journey["accuracy"]],
            textposition="outside",
        )
    )
    fig.update_layout(
        title="Holdout accuracy by modeling round",
        template="none",
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=pal["ink2"]), showlegend=False,
        margin=dict(l=160, r=40, t=50, b=40), height=300,
    )
    fig.update_xaxes(range=[50, 74], gridcolor=pal["grid"])
    fig.update_yaxes(autorange="reversed", showgrid=False)
    st.plotly_chart(fig, width="stretch")
    with st.expander("What changed at each stage"):
        st.dataframe(journey, width="stretch", hide_index=True)

    if models:
        st.plotly_chart(
            _coef_chart(
                models["outcome"].pipeline,
                OUTCOME_FEATURES,
                "Standardized coefficients (blue helps the home team)",
                pal,
            ),
            width="stretch",
        )
        try:
            preds = _holdout_predictions(client, models["outcome"])
            st.plotly_chart(_calibration_chart(preds, pal), width="stretch")
            st.caption(
                "A well-calibrated 65% means teams given 65% really win about "
                "65% of the time — this is what log loss optimizes for, and why "
                "the predictions can be read as honest probabilities."
            )
        except Exception as e:
            st.caption(f"Calibration analysis unavailable: {e}")

    st.divider()
    st.markdown("### Game simulator")
    st.markdown(
        """
The Simulate tab plays each matchup 10,000 times: possessions drawn around
the teams' average pace, each side's points-per-100 drawn around its
offensive rating against the opponent's defensive rating (league-relative),
plus home court and expected minutes out; tied regulation scores go to
overtime. Home court (**2.20 points**) and scoring noise (**σ = 0.096
points per possession**, reproducing the observed 13.8-point margin
spread) are fitted on the three training seasons.

Scored on the same holdout as everything else, its win probabilities come
in at **log loss 0.601 / 68.6%** — worse than the outcome model (0.585 /
70.2%), because it sees only ratings and pace. That is why the model keeps
the headline probability and the simulator is used for what a classifier
cannot produce: margin and total distributions, overtime rates, and
score-level what-ifs.
"""
    )

    st.divider()
    st.markdown("### Player points model")
    st.markdown(
        """
**Two-stage: minutes × rate.** Most of the variance in a player's points
is variance in playing time, so the model predicts them separately and
multiplies:

- **Minutes stage** — rotation trend (5-game and exponentially-weighted
  averages), rest, venue, and the team's expected minutes out (injuries
  and rest days open up playing time).
- **Rate stage** — per-minute scoring (EWMA, halflife 10 games), shot
  volume, opponent defensive rating and pace, and teammate absences
  (usage rises when stars sit).

Holdout MAE **4.58** vs 4.72 for the honest baseline (the player's own
10-game average) across 21,204 player-games. For context: predicting a
single game's points is noise-dominated — star players' scoring has a
game-to-game standard deviation near 8 points.

The projection ships with an **empirical 80% interval**: the 10th/90th
percentiles of training residuals, binned by projection level (a 28-point
projection has far more spread than an 8-point one), added to the
prediction and floored at zero. Residuals are asymmetric — single-game
scoring is right-skewed — and the measured holdout coverage of the band is
recorded in `metrics.json` and shown in the app.
"""
    )
    if models:
        cols = st.columns(2)
        with cols[0]:
            st.plotly_chart(
                _coef_chart(models["points"].minutes, MIN_FEATURES, "Minutes stage", pal),
                width="stretch",
            )
        with cols[1]:
            st.plotly_chart(
                _coef_chart(models["points"].rate, RATE_FEATURES, "Rate stage", pal),
                width="stretch",
            )

    st.divider()
    st.markdown("### Starting-five estimator")
    st.markdown(
        """
A blend, not a full model: when the chosen five have actually played
together this season, their observed net rating (weighted by minutes
together, shrunk toward a proxy below 200 minutes) is mapped through a win
curve fitted on three seasons of team results (~2.8% win probability per
net point). Lineups that never shared the floor fall back to the mean of
the players' per-36 plus-minus — a proxy that ignores fit and synergy,
and is labelled as such in the UI.

**Where the observed net rating comes from.** Preferred source is our own
stint table: the rotation feed gives each player's exact on/off intervals,
so slicing the game at every substitution boundary yields spans where all
ten players are fixed. Each stint carries its score change and an
estimated possession count (FGA − OREB + TOV + 0.44·FTA, offensive
rebounds inferred from the preceding miss), and **garbage time is
stripped** with the same fourth-quarter blowout rule the form features
use. Built offline (`python -m nba_insights.pbp.lineups`); when the table
hasn't been built the tab falls back to the league's season-aggregate
lineup dashboard, which counts garbage time.
"""
    )

    st.divider()
    st.markdown("### What didn't work")
    st.markdown(
        "Every idea below was built, measured on the same holdout, and "
        "rejected. Keeping the failures on record is part of the method — "
        "it's how the numbers above stay believable."
    )
    st.dataframe(REJECTED, width="stretch", hide_index=True)
    st.caption(
        "Full experiment log: docs/DATA_ROADMAP.md in the repository. "
        "Known open lever: an automated injury feed at prediction time "
        "(the 'who's out' picker currently relies on you)."
    )
