"""Shared UI chrome: entrance animations, hover transitions, motion polish.

Pure CSS over Streamlit's stable data-testid hooks — no JS components, so it
degrades gracefully if a selector stops matching, and all motion is disabled
for users who prefer reduced motion.
"""

from __future__ import annotations

import streamlit as st

_CSS = """
<style>
@keyframes rise-in {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: none; }
}

/* page content eases in on every navigation / full rerun */
[data-testid="stMainBlockContainer"] { animation: rise-in 0.4s ease-out; }

/* charts, tables and expanders get their own entrance so fragment
   reruns (which skip the page container) still feel alive */
.stPlotlyChart,
[data-testid="stDataFrame"],
[data-testid="stExpander"] {
  animation: rise-in 0.5s ease-out both;
}

/* the Plotly modebar (camera/zoom icons) floats over the chart title on
   hover and none of its tools matter for these fixed-frame charts */
.stPlotlyChart .modebar { display: none !important; }

/* charts sit on a card like the stat tiles, lifting slightly on hover */
.stPlotlyChart {
  border: 1px solid rgba(128, 128, 128, 0.25);
  border-radius: 0.75rem;
  padding: 0.6rem 0.5rem 0.2rem;
  background: rgba(128, 128, 128, 0.05);
  transition: box-shadow 0.18s ease, border-color 0.18s ease;
}
.stPlotlyChart:hover {
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.1);
  border-color: rgba(128, 128, 128, 0.45);
}

/* equal-height card rows: any column row holding stat tiles stretches its
   columns, and the card fills the column — so tiles with short and long
   captions still bottom-align. Rows with images (profile header, leader
   tiles) keep their own alignment. */
[data-testid="stHorizontalBlock"]:not(:has([data-testid="stImage"])):has([data-testid="stMetric"]) {
  align-items: stretch;
}
[data-testid="stHorizontalBlock"]:not(:has([data-testid="stImage"]))
  [data-testid="stColumn"]:has([data-testid="stMetric"])
  [data-testid="stVerticalBlock"] {
  height: 100%;
}
[data-testid="stMetric"] { height: 100%; }

/* stat tiles: cards that lift on hover, staggered entrance per column */
[data-testid="stMetric"] {
  border: 1px solid rgba(128, 128, 128, 0.25);
  border-radius: 0.75rem;
  padding: 0.8rem 1rem;
  background: rgba(128, 128, 128, 0.06);
  transition: transform 0.18s ease, box-shadow 0.18s ease,
    border-color 0.18s ease;
  animation: rise-in 0.45s ease-out both;
}
[data-testid="stMetric"]:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.12);
  border-color: rgba(128, 128, 128, 0.5);
}
[data-testid="stColumn"]:nth-of-type(2) [data-testid="stMetric"] {
  animation-delay: 0.07s;
}
[data-testid="stColumn"]:nth-of-type(3) [data-testid="stMetric"] {
  animation-delay: 0.14s;
}

/* tabs: soft hover state on top of the built-in sliding highlight */
.stTabs [data-baseweb="tab"] {
  border-radius: 0.4rem 0.4rem 0 0;
  transition: color 0.15s ease, background 0.15s ease;
}
.stTabs [data-baseweb="tab"]:hover { background: rgba(128, 128, 128, 0.1); }

/* sidebar navigation links nudge right on hover */
[data-testid="stSidebarNav"] a {
  transition: transform 0.15s ease, background 0.15s ease;
}
[data-testid="stSidebarNav"] a:hover { transform: translateX(3px); }

/* player headshots */
[data-testid="stImage"] img {
  border-radius: 0.75rem;
  transition: transform 0.2s ease;
}
[data-testid="stImage"] img:hover { transform: scale(1.03); }

/* app title: tighter tracking + a small brand accent under it */
h1 { letter-spacing: -0.02em; }
h1::after {
  content: "";
  display: block;
  width: 72px;
  height: 4px;
  border-radius: 2px;
  margin-top: 0.35rem;
  background: linear-gradient(90deg, #2a78d6, #1baf7a);
}

/* league-leaders cards: a compact ranked list per category, in a grid */
.lb-card {
  border: 1px solid rgba(128, 128, 128, 0.25);
  border-radius: 0.75rem;
  padding: 0.6rem 0.85rem 0.7rem;
  background: rgba(128, 128, 128, 0.05);
  animation: rise-in 0.45s ease-out both;
}
.lb-title {
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #2a78d6;
  margin-bottom: 0.35rem;
}
.lb-list { list-style: none; margin: 0; padding: 0; }
.lb-list li {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  padding: 3px 0;
  font-size: 0.92rem;
  border-top: 1px solid rgba(128, 128, 128, 0.14);
}
.lb-list li:first-child { border-top: none; }
.lb-rank {
  width: 1.2rem;
  flex: none;
  text-align: right;
  color: #898781;
  font-variant-numeric: tabular-nums;
  font-size: 0.8rem;
}
.lb-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.lb-val { font-weight: 600; font-variant-numeric: tabular-nums; }
.lb-list li:first-child .lb-name { font-weight: 600; }

/* scouting take: the rule-based one-line read, an accented card that reads
   as an editorial callout rather than another stat block */
.scout {
  margin: 0.2rem 0 0.9rem;
  padding: 0.7rem 1rem 0.7rem 0.9rem;
  border-left: 3px solid #2a78d6;
  border-radius: 0.4rem;
  background: rgba(42, 120, 214, 0.06);
  font-size: 1.02rem;
  line-height: 1.5;
  animation: rise-in 0.45s ease-out both;
}
.scout-tag {
  display: inline-block;
  margin-right: 0.5rem;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  color: #2a78d6;
  vertical-align: 1px;
}

/* skill pills: percentile-derived badges on the player profile */
.pills { display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
  margin: 0.1rem 0 0.9rem; }
.pills-lead { font-size: 0.72rem; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; color: #898781; margin-right: 2px; }
.pill {
  border: 1px solid rgba(128, 128, 128, 0.35);
  border-radius: 999px;
  padding: 2px 12px;
  font-size: 0.85rem;
  background: rgba(128, 128, 128, 0.08);
  animation: rise-in 0.45s ease-out both;
}
.pill b { font-weight: 600; }

/* duel bar: one shared track for a win probability, home vs away */
.duel { margin: 0.5rem 0 0.9rem; }
.duel-labels {
  display: flex;
  justify-content: space-between;
  gap: 1rem;
  font-size: 0.95rem;
  margin-bottom: 6px;
}
.duel-track {
  display: flex;
  gap: 2px;               /* spacer between adjacent fills */
  height: 14px;           /* thin mark */
  border-radius: 4px;     /* rounded data ends */
  overflow: hidden;
}
.duel-track > div { transition: width 0.4s ease; min-width: 4px; }

/* prediction matchup card: logos flank a big win-probability figure */
.mu-abbr { font-size: 1.6rem; font-weight: 700; line-height: 1.1; }
.mu-side { font-size: 0.8rem; opacity: 0.6; text-transform: uppercase;
  letter-spacing: 0.06em; }
.mu-prob { font-size: 2.6rem; font-weight: 700; text-align: center; line-height: 1; }
.mu-vs { font-size: 0.8rem; opacity: 0.65; text-align: center; margin-top: 2px; }

/* simulated median scoreline */
.scoreline { font-size: 1.45rem; margin: 0.3rem 0 0.6rem; }
.scoreline b { font-weight: 700; }
.scoreline-note { font-size: 0.8rem; opacity: 0.65; margin-left: 0.6rem; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation: none !important;
    transition: none !important;
  }
}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
