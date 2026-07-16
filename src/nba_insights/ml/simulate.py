"""Monte Carlo game simulator: possessions from pace, efficiency from ratings.

Where the outcome model answers "who wins?" with one calibrated probability,
the simulator plays the game thousands of times and returns the whole
distribution — margins, totals, overtime — so the app can show *how* a
matchup tends to unfold and what a full-strength edge is worth in points.

Mechanics per simulated game: a shared possession count drawn around the
teams' average pace; each side's points-per-100 drawn around its offensive
rating adjusted by the opponent's defensive rating (league-relative), home
court, and expected minutes out; tied regulation scores go to overtime.

Default parameters are fitted on the three training seasons and the win
probabilities are scored on the same temporal holdout as every model
(log loss 0.601 vs the outcome model's 0.585 — see docs/DATA_ROADMAP.md),
which is why the app keeps the model's number as the headline and uses
the simulator for distributions. Pure numpy/pandas — no I/O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# fitted on the three training seasons (2022-23 .. 2024-25, 3,685 games):
# HCA_PTS is the mean home margin net of form expectation; SIGMA_PPP the
# per-team scoring noise reproducing the observed 13.8-point margin
# residual sd (sd ~= sigma * pace * sqrt(2))
HCA_PTS = 2.2
SIGMA_PPP = 0.096
SIGMA_PACE = 3.0
# efficiency dent per expected minute out: a 36-minute star ~2.5 net points
PTS_PER_MISSING_MIN = 0.07

_OT_SHARE = 5.0 / 48.0  # overtime possessions as a share of regulation


def simulate_game(
    home_ortg: float,
    home_drtg: float,
    away_ortg: float,
    away_drtg: float,
    pace: float,
    league_ortg: float,
    *,
    n_sims: int = 10_000,
    hca_pts: float = HCA_PTS,
    sigma_ppp: float = SIGMA_PPP,
    sigma_pace: float = SIGMA_PACE,
    home_missing_min: float = 0.0,
    away_missing_min: float = 0.0,
    pts_per_missing_min: float = PTS_PER_MISSING_MIN,
    seed: int | None = None,
) -> pd.DataFrame:
    """Simulate final scores; returns a frame of ints with no ties.

    Ratings are points per 100 possessions (stats.nba.com convention);
    *pace* is possessions per 48 minutes. Expected efficiency is the
    team's offense met by the opponent's defense, relative to league
    average, shifted by half the home-court advantage each way and any
    expected minutes out.
    """
    rng = np.random.default_rng(seed)

    mu_home = home_ortg + away_drtg - league_ortg + hca_pts / 2
    mu_away = away_ortg + home_drtg - league_ortg - hca_pts / 2
    mu_home -= home_missing_min * pts_per_missing_min
    mu_away -= away_missing_min * pts_per_missing_min

    poss = rng.normal(pace, sigma_pace, n_sims)  # shared: pace is mutual
    eff_home = rng.normal(mu_home / 100, sigma_ppp, n_sims)
    eff_away = rng.normal(mu_away / 100, sigma_ppp, n_sims)
    home_pts = np.rint(poss * eff_home)
    away_pts = np.rint(poss * eff_away)
    overtimes = np.zeros(n_sims, dtype=int)

    tied = home_pts == away_pts
    while tied.any():
        n = int(tied.sum())
        ot_poss = poss[tied] * _OT_SHARE
        home_pts[tied] += np.rint(ot_poss * rng.normal(mu_home / 100, sigma_ppp, n))
        away_pts[tied] += np.rint(ot_poss * rng.normal(mu_away / 100, sigma_ppp, n))
        overtimes[tied] += 1
        tied = home_pts == away_pts

    return pd.DataFrame(
        {
            "home_pts": home_pts.astype(int),
            "away_pts": away_pts.astype(int),
            "overtimes": overtimes,
        }
    )


def simulate_matchup(
    snapshot: pd.DataFrame, home_team: str, away_team: str, **kwargs
) -> pd.DataFrame:
    """Simulate from a team_form_snapshot; raises KeyError on unknown teams."""
    for team in (home_team, away_team):
        if team not in snapshot.index:
            raise KeyError(f"team not in snapshot: {team}")
    home, away = snapshot.loc[home_team], snapshot.loc[away_team]
    return simulate_game(
        home_ortg=float(home["form_ortg"]),
        home_drtg=float(home["form_drtg"]),
        away_ortg=float(away["form_ortg"]),
        away_drtg=float(away["form_drtg"]),
        pace=float((home["form_pace"] + away["form_pace"]) / 2),
        league_ortg=float(snapshot["form_ortg"].mean()),
        **kwargs,
    )


def sim_summary(sims: pd.DataFrame) -> dict:
    """Headline numbers from a simulate_game frame."""
    margin = sims["home_pts"] - sims["away_pts"]
    total = sims["home_pts"] + sims["away_pts"]
    return {
        "home_win_prob": float((margin > 0).mean()),
        "median_margin": float(margin.median()),
        "margin_p10": float(margin.quantile(0.10)),
        "margin_p90": float(margin.quantile(0.90)),
        "median_total": float(total.median()),
        "overtime_prob": float((sims["overtimes"] > 0).mean()),
    }
