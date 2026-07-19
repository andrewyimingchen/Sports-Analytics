"""Season-scale Monte Carlo: project the coming regular season and playoffs.

Where :mod:`nba_insights.ml.simulate` plays one game and
:mod:`nba_insights.ml.outcome` scores one matchup, this module plays a whole
82-game season thousands of times from a single set of Elo ratings, then runs
the play-in and a best-of-seven bracket on each simulated standings. It answers
*season* questions — projected win totals, who makes the playoffs, seeding, and
title odds — not game questions.

Only Elo drives it. Ratings are first regressed toward the mean for the coming
off-season (the same 25% pull :mod:`nba_insights.ml.elo` applies at every season
boundary), a representative NBA schedule is built once, and every game is a coin
flip weighted by the Elo gap plus home court. This deliberately ignores summer
roster moves — it projects "the season if the league entered it at its current
Elo". Pure numpy/pandas — no I/O.

Schedule realism: each team plays exactly 82 games with a balanced 41/41
home split — 4 vs each of 4 division rivals (16), 3-or-4 vs the 10 other
conference teams (36), and 2 vs each of the 15 other-conference teams (30).
Which conference rivals are three-game vs four-game series is set by a
circulant pattern that keeps every team at exactly six four-game and four
three-game series, none of them intra-division.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from nba_insights.ml.elo import HOME_ADV, regress_to_mean, win_prob

# Conference and division are stable reference data (unchanged since 2004).
_DIVISIONS: dict[str, list[str]] = {
    # East
    "Atlantic": ["BOS", "BKN", "NYK", "PHI", "TOR"],
    "Central": ["CHI", "CLE", "DET", "IND", "MIL"],
    "Southeast": ["ATL", "CHA", "MIA", "ORL", "WAS"],
    # West
    "Northwest": ["DEN", "MIN", "OKC", "POR", "UTA"],
    "Pacific": ["GSW", "LAC", "LAL", "PHX", "SAC"],
    "Southwest": ["DAL", "HOU", "MEM", "NOP", "SAS"],
}
_EAST_DIVS = ("Atlantic", "Central", "Southeast")
DIVISION = {t: d for d, ts in _DIVISIONS.items() for t in ts}
CONFERENCE = {
    t: ("East" if d in _EAST_DIVS else "West") for t, d in DIVISION.items()
}


def _conf_order(conf: str) -> list[str]:
    """The 15 conference teams interleaved by division (d0,d1,d2,d0,d1,d2,...)
    so a circulant C15(1,2) never connects two teams from the same division."""
    divs = _EAST_DIVS if conf == "East" else ("Northwest", "Pacific", "Southwest")
    cols = [_DIVISIONS[d] for d in divs]
    return [cols[i % 3][i // 3] for i in range(15)]


def _schedule(teams: list[str]) -> list[tuple[str, str]]:
    """A representative 82-game slate as (home, away) pairs.

    Every team lands on exactly 82 games and a 41/41 home split; see the
    module docstring for the structure. Deterministic — no RNG."""
    games: list[tuple[str, str]] = []

    def series(a: str, b: str, a_home: int, b_home: int) -> None:
        games.extend([(a, b)] * a_home)
        games.extend([(b, a)] * b_home)

    # Division rivals: 4 games, 2 home each.
    for div_teams in _DIVISIONS.values():
        for i in range(len(div_teams)):
            for j in range(i + 1, len(div_teams)):
                series(div_teams[i], div_teams[j], 2, 2)

    # Same-conference, non-division. A circulant C15(1,2) picks the four
    # three-game rivals per team; the other six are four-game series.
    for conf in ("East", "West"):
        order = _conf_order(conf)
        three_game: set[frozenset[str]] = set()
        for p in range(15):
            for k in (1, 2):
                a, b = order[p], order[(p + k) % 15]
                pair = frozenset((a, b))
                if pair in three_game:
                    continue
                three_game.add(pair)
                # p hosts 2, its +k neighbour hosts 1 — over each team's four
                # three-game series this nets to a 6/6 home/away balance.
                series(a, b, 2, 1)
        for i in range(15):
            for j in range(i + 1, 15):
                a, b = order[i], order[j]
                if DIVISION[a] == DIVISION[b]:
                    continue  # division series already added
                if frozenset((a, b)) in three_game:
                    continue  # three-game series already added
                series(a, b, 2, 2)  # four-game series

    # Cross-conference: 2 games, 1 home each.
    east = [t for t in teams if CONFERENCE[t] == "East"]
    west = [t for t in teams if CONFERENCE[t] == "West"]
    for a in east:
        for b in west:
            series(a, b, 1, 1)

    return games


# Best-of-seven home venues for the higher seed: 2-2-1-1-1 format
# (higher seed hosts games 1, 2, 5, 7).
_BO7_HI_HOME = np.array([True, True, False, False, True, False, True])


def _play_game(rng, ratings, home_idx, away_idx):
    """Vectorised single game: True where the home team wins, per sim."""
    p = win_prob(ratings[home_idx], ratings[away_idx], HOME_ADV)
    return rng.random(home_idx.shape) < p


def _play_series(rng, ratings, hi_idx, lo_idx):
    """Vectorised best-of-seven: winning team index per sim.

    The higher seed hosts on the 2-2-1-1-1 pattern. Playing all seven games
    and taking the majority is exact: whoever reaches four first always holds
    the majority of a fixed-venue seven-game set."""
    hi_wins = np.zeros(hi_idx.shape, dtype=int)
    for hi_home in _BO7_HI_HOME:
        hca = HOME_ADV if hi_home else -HOME_ADV
        p = win_prob(ratings[hi_idx], ratings[lo_idx], hca)
        hi_wins += rng.random(hi_idx.shape) < p
    return np.where(hi_wins >= 4, hi_idx, lo_idx)


def _conf_bracket(rng, ratings, seeds, add):
    """Run play-in + three playoff rounds for one conference.

    *seeds* is an ``[n_sims, 15]`` array of global team indices ordered by
    regular-season finish (column 0 = 1-seed). *add* accumulates per-team
    counters. Returns the conference champion's team index per sim."""
    s7, s8, s9, s10 = seeds[:, 6], seeds[:, 7], seeds[:, 8], seeds[:, 9]
    # Play-in: 7v8 (7 hosts) → winner is the 7-seed; loser drops to game C.
    a_home_wins = _play_game(rng, ratings, s7, s8)
    seed7 = np.where(a_home_wins, s7, s8)
    loser_a = np.where(a_home_wins, s8, s7)
    # 9v10 (9 hosts) → winner advances, loser is eliminated.
    b_home_wins = _play_game(rng, ratings, s9, s10)
    winner_b = np.where(b_home_wins, s9, s10)
    # Loser of 7v8 hosts the winner of 9v10 for the 8-seed.
    c_home_wins = _play_game(rng, ratings, loser_a, winner_b)
    seed8 = np.where(c_home_wins, loser_a, winner_b)

    bracket = [seeds[:, 0], seeds[:, 1], seeds[:, 2], seeds[:, 3],
               seeds[:, 4], seeds[:, 5], seed7, seed8]
    for team_idx in bracket:
        np.add.at(add["playoff"], team_idx, 1)

    # Round 1: 1v8, 4v5, 3v6, 2v7 (higher seed hosts).
    r2 = [
        _play_series(rng, ratings, bracket[0], bracket[7]),
        _play_series(rng, ratings, bracket[3], bracket[4]),
        _play_series(rng, ratings, bracket[2], bracket[5]),
        _play_series(rng, ratings, bracket[1], bracket[6]),
    ]
    # Semifinals: (1/8 v 4/5) and (3/6 v 2/7). Higher Elo hosts.
    def matchup(x, y):
        hi = np.where(ratings[x] >= ratings[y], x, y)
        lo = np.where(ratings[x] >= ratings[y], y, x)
        return _play_series(rng, ratings, hi, lo)

    sf1 = matchup(r2[0], r2[1])
    sf2 = matchup(r2[2], r2[3])
    for team_idx in (sf1, sf2):
        np.add.at(add["conf_finals"], team_idx, 1)
    champ = matchup(sf1, sf2)
    np.add.at(add["finals"], champ, 1)
    return champ


def simulate_season(
    elo: pd.Series,
    *,
    n_sims: int = 3000,
    seed: int | None = None,
    regress: bool = True,
) -> pd.DataFrame:
    """Project a full season from Elo ratings; one row per team (tricode index).

    *elo* maps team tricode to current Elo rating (30 teams expected). With
    ``regress`` (default) the ratings are aged toward the mean for the coming
    off-season before simulating, so end-of-season Elo becomes opening-night
    Elo. Returns projected records and probabilities:

    - ``proj_wins`` / ``proj_losses`` — mean simulated record (wins to 1 dp)
    - ``wins_p10`` / ``wins_p90`` — 10th/90th percentile win totals
    - ``avg_seed`` — mean conference finish (1 = best)
    - ``playoff_pct`` — reached the 8-team bracket (survived any play-in)
    - ``top6_pct`` — finished top-6 (a guaranteed berth, no play-in)
    - ``seed1_pct`` — finished 1st in the conference
    - ``conf_finals_pct`` / ``finals_pct`` / ``champ_pct`` — postseason odds

    Raises ``KeyError`` if any team is missing from the conference map.
    """
    teams = list(elo.index)
    missing = [t for t in teams if t not in CONFERENCE]
    if missing:
        raise KeyError(f"teams not in conference map: {missing}")

    rng = np.random.default_rng(seed)
    base = regress_to_mean(elo) if regress else elo.astype(float)
    ratings = base.to_numpy(dtype=float)
    n = len(teams)
    idx = {t: i for i, t in enumerate(teams)}

    # Regular season: precompute each game's home win probability once, then
    # draw the whole league of sims per game.
    wins = np.zeros((n_sims, n), dtype=np.int16)
    for home, away in _schedule(teams):
        h, a = idx[home], idx[away]
        p = win_prob(ratings[h], ratings[a], HOME_ADV)
        home_won = rng.random(n_sims) < p
        wins[:, h] += home_won
        wins[:, a] += ~home_won

    east = np.array([i for i, t in enumerate(teams) if CONFERENCE[t] == "East"])
    west = np.array([i for i, t in enumerate(teams) if CONFERENCE[t] == "West"])

    # Random tiebreak so ties resolve fairly across sims.
    key = wins + rng.random((n_sims, n))

    add = {k: np.zeros(n) for k in ("playoff", "conf_finals", "finals", "champ")}
    seed_sum = np.zeros(n)
    top6 = np.zeros(n)
    seed1 = np.zeros(n)

    champs = {}
    for conf_glob in (east, west):
        # seeds_glob[:, s] = global team index finishing seed s+1 in this conf.
        order = np.argsort(-key[:, conf_glob], axis=1)
        seeds_glob = conf_glob[order]
        # per-team conference finish (1..15). Fancy-indexed += only counts a
        # repeated index once, so accumulate with np.add.at across the sims.
        for s in range(15):
            np.add.at(seed_sum, seeds_glob[:, s], s + 1)
        for s in range(6):
            np.add.at(top6, seeds_glob[:, s], 1)
        np.add.at(seed1, seeds_glob[:, 0], 1)
        champs[id(conf_glob)] = _conf_bracket(rng, ratings, seeds_glob, add)

    # Finals: the two conference champions, higher regular-season win total hosts.
    ec, wc = champs[id(east)], champs[id(west)]
    ec_better = wins[np.arange(n_sims), ec] >= wins[np.arange(n_sims), wc]
    hi = np.where(ec_better, ec, wc)
    lo = np.where(ec_better, wc, ec)
    title = _play_series(rng, ratings, hi, lo)
    np.add.at(add["champ"], title, 1)

    out = pd.DataFrame(
        {
            "conf": [CONFERENCE[t] for t in teams],
            "proj_wins": wins.mean(axis=0).round(1),
            "proj_losses": (82 - wins.mean(axis=0)).round(1),
            "wins_p10": np.percentile(wins, 10, axis=0).round(0).astype(int),
            "wins_p90": np.percentile(wins, 90, axis=0).round(0).astype(int),
            "avg_seed": (seed_sum / n_sims).round(1),
            "playoff_pct": add["playoff"] / n_sims,
            "top6_pct": top6 / n_sims,
            "seed1_pct": seed1 / n_sims,
            "conf_finals_pct": add["conf_finals"] / n_sims,
            "finals_pct": add["finals"] / n_sims,
            "champ_pct": add["champ"] / n_sims,
        },
        index=teams,
    )
    return out.sort_values("proj_wins", ascending=False)
