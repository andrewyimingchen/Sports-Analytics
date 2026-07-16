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
