"""Margin-aware Elo ratings that carry across seasons.

Unlike the season-to-date form features (which need ~10 games of history
and drop early-season games), Elo has an opinion from opening night: teams
keep 75% of last season's rating and regress 25% toward the mean. The
update uses FiveThirtyEight's margin-of-victory multiplier so blowouts move
ratings more than squeakers, damped when the favourite wins big.
"""

from __future__ import annotations

import pandas as pd

from nba_insights.ml.features import _prepare

BASE = 1500.0
K = 20.0
HOME_ADV = 70.0  # Elo points; roughly the historical home edge
CARRY = 0.75  # share of rating kept across the off-season


def _expected_home(elo_home: float, elo_away: float) -> float:
    return 1.0 / (1.0 + 10 ** (-(elo_home + HOME_ADV - elo_away) / 400.0))


def win_prob(elo_a, elo_b, hca: float = 0.0):
    """P(team A beats team B), giving A an *hca*-point edge (Elo points).

    Scalar or numpy-array in, same out — the season simulator calls it with
    whole arrays of ratings. Pass ``hca=HOME_ADV`` when A is at home, its
    negative when A is on the road, and 0 for a neutral floor.
    """
    return 1.0 / (1.0 + 10 ** (-((elo_a - elo_b) + hca) / 400.0))


def regress_to_mean(elo, carry: float = CARRY):
    """Pull ratings toward the mean by the off-season share, as the update
    loop does at every season boundary. Use it to age end-of-season ratings
    into opening-night ratings for the next season."""
    return carry * elo + (1 - carry) * BASE


def _mov_multiplier(margin: float, elo_winner_diff: float) -> float:
    return ((abs(margin) + 3) ** 0.8) / (7.5 + 0.006 * elo_winner_diff)


def _run_elo(team_games: pd.DataFrame) -> tuple[pd.DataFrame, dict[int, float]]:
    """Shared update loop: (pre-game ratings per team-game, final ratings)."""
    df = _prepare(team_games)
    home = df[df["home"] == 1][["SEASON_ID", "GAME_ID", "GAME_DATE", "TEAM_ID", "PLUS_MINUS"]]
    away = df[df["home"] == 0][["GAME_ID", "TEAM_ID"]]
    games = home.merge(away, on="GAME_ID", suffixes=("_h", "_a")).sort_values(
        ["GAME_DATE", "GAME_ID"]
    )

    ratings: dict[int, float] = {}
    season: str | None = None
    rows = []
    for g in games.itertuples(index=False):
        if g.SEASON_ID != season:
            season = g.SEASON_ID
            ratings = {t: CARRY * r + (1 - CARRY) * BASE for t, r in ratings.items()}
        eh = ratings.get(g.TEAM_ID_h, BASE)
        ea = ratings.get(g.TEAM_ID_a, BASE)
        rows.append({"GAME_ID": g.GAME_ID, "TEAM_ID": g.TEAM_ID_h, "elo": eh})
        rows.append({"GAME_ID": g.GAME_ID, "TEAM_ID": g.TEAM_ID_a, "elo": ea})

        margin = float(g.PLUS_MINUS)  # home perspective
        home_won = margin > 0
        expected = _expected_home(eh, ea)
        winner_diff = (eh + HOME_ADV - ea) if home_won else (ea - eh - HOME_ADV)
        shift = K * _mov_multiplier(margin, winner_diff) * ((1.0 if home_won else 0.0) - expected)
        ratings[g.TEAM_ID_h] = eh + shift
        ratings[g.TEAM_ID_a] = ea - shift

    return pd.DataFrame(rows), ratings


def elo_ratings(team_games: pd.DataFrame) -> pd.DataFrame:
    """Pre-game Elo per (GAME_ID, TEAM_ID) from a multi-season games frame.

    *team_games* is LeagueGameFinder team-mode rows, ideally including a
    warm-up season or two before the period of interest so ratings have
    converged by the time they're used. Ratings are strictly pre-game:
    the row's rating never includes the row's own result.
    """
    rows, _ = _run_elo(team_games)
    return rows


def current_elo(team_games: pd.DataFrame) -> pd.Series:
    """Ratings after every game played: TEAM_ABBREVIATION -> elo.

    Feed the same multi-season frame as :func:`elo_ratings`; the result is
    each team's rating entering its next game.
    """
    _, ratings = _run_elo(team_games)
    abbrev = (
        team_games.sort_values("GAME_DATE")
        .groupby("TEAM_ID")["TEAM_ABBREVIATION"]
        .last()
    )
    return pd.Series(
        {abbrev[t]: r for t, r in ratings.items() if t in abbrev.index}, name="elo"
    )
