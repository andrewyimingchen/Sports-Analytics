"""Deterministic league-wide preseason simulation.

The forecast deliberately starts from the latest known team form rather than
pretending future rosters, schedules, or injuries are already known. An
offseason uncertainty draw makes the next-season table less certain than an
in-season projection. Play-in, playoff, Finals, and NBA Cup outcomes are then
simulated from each draw's team strength.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from nba_insights.analysis.cup import simulate_cup_once


def _sigmoid(value: float | np.ndarray) -> float | np.ndarray:
    return 1.0 / (1.0 + np.exp(-value))


def _logit(value: float | np.ndarray) -> float | np.ndarray:
    clipped = np.clip(value, 0.03, 0.97)
    return np.log(clipped / (1.0 - clipped))


def _game_probability(strength_a: float, strength_b: float, home: bool = False) -> float:
    edge = float(_logit(strength_a) - _logit(strength_b))
    return float(_sigmoid(0.82 * edge + (0.12 if home else 0.0)))


def _series_probability(strength_a: float, strength_b: float) -> float:
    """Chance A wins a best-of-seven, approximated by four-plus wins in seven."""
    game = _game_probability(strength_a, strength_b)
    return sum(
        math.comb(7, wins) * game**wins * (1.0 - game) ** (7 - wins)
        for wins in range(4, 8)
    )


def _winner(
    team_a: int,
    team_b: int,
    strength: np.ndarray,
    rng: np.random.Generator,
    *,
    series: bool,
    home_a: bool = False,
) -> int:
    probability = (
        _series_probability(strength[team_a], strength[team_b])
        if series
        else _game_probability(strength[team_a], strength[team_b], home=home_a)
    )
    return team_a if rng.random() < probability else team_b


def _conference_playoffs(
    seeds: np.ndarray,
    strength: np.ndarray,
    rng: np.random.Generator,
) -> tuple[list[int], int]:
    """Resolve the play-in, then a standard 1–8 conference bracket."""
    seven_eight_winner = _winner(seeds[6], seeds[7], strength, rng, series=False, home_a=True)
    seven_eight_loser = seeds[7] if seven_eight_winner == seeds[6] else seeds[6]
    nine_ten_winner = _winner(seeds[8], seeds[9], strength, rng, series=False, home_a=True)
    eighth = _winner(
        seven_eight_loser,
        nine_ten_winner,
        strength,
        rng,
        series=False,
        home_a=True,
    )
    playoff_teams = [*seeds[:6], seven_eight_winner, eighth]
    first_round = [
        _winner(playoff_teams[0], playoff_teams[7], strength, rng, series=True),
        _winner(playoff_teams[3], playoff_teams[4], strength, rng, series=True),
        _winner(playoff_teams[2], playoff_teams[5], strength, rng, series=True),
        _winner(playoff_teams[1], playoff_teams[6], strength, rng, series=True),
    ]
    semifinals = [
        _winner(first_round[0], first_round[1], strength, rng, series=True),
        _winner(first_round[2], first_round[3], strength, rng, series=True),
    ]
    champion = _winner(semifinals[0], semifinals[1], strength, rng, series=True)
    return playoff_teams, champion


def season_forecast(
    snapshot: pd.DataFrame,
    conferences: dict[str, str],
    *,
    n_sims: int = 5_000,
    seed: int = 202627,
    cup_groups: dict[str, list[str]] | None = None,
    roster_adjustments: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Simulate an 82-game season, play-in/playoffs, title, and NBA Cup.

    ``snapshot`` is indexed by team tricode and must provide form win rate and
    net rating; Elo is used when present. ``conferences`` maps every team to
    ``East`` or ``West``. Returned probabilities are fractions.
    """
    required = {"form_win_pct", "form_net"}
    missing = required - set(snapshot.columns)
    if missing:
        raise KeyError(f"forecast snapshot missing columns: {sorted(missing)}")
    teams = [str(team) for team in snapshot.index if team in conferences]
    if len(teams) != 30:
        raise ValueError(f"forecast requires 30 conference-mapped teams, got {len(teams)}")
    conference_indices = {
        conference: np.array(
            [index for index, team in enumerate(teams) if conferences[team] == conference]
        )
        for conference in ("East", "West")
    }
    if any(len(indices) != 15 for indices in conference_indices.values()):
        raise ValueError("forecast requires 15 teams in each conference")

    scoped = snapshot.reindex(teams)
    win_component = scoped["form_win_pct"].fillna(0.5).clip(0.1, 0.9).to_numpy(float)
    net_component = _sigmoid(scoped["form_net"].fillna(0.0).to_numpy(float) / 11.0)
    if "elo" in scoped:
        elo_component = _sigmoid(
            (scoped["elo"].fillna(1500.0).to_numpy(float) - 1500.0) / 145.0
        )
    else:
        elo_component = np.full(len(teams), 0.5)
    known_strength = 0.45 * win_component + 0.35 * net_component + 0.20 * elo_component
    base_strength = 0.5 + 0.78 * (known_strength - 0.5)  # offseason regression
    uncertainty = np.full(len(teams), 0.20)
    if roster_adjustments is not None:
        roster = roster_adjustments.reindex(teams)
        strength_adjustment = pd.to_numeric(
            roster.get("STRENGTH_ADJUSTMENT"), errors="coerce"
        ).fillna(0.0)
        base_strength = _sigmoid(_logit(base_strength) + strength_adjustment.to_numpy())
        uncertainty = pd.to_numeric(
            roster.get("UNCERTAINTY"), errors="coerce"
        ).fillna(0.20).clip(0.08, 0.50).to_numpy()

    rng = np.random.default_rng(seed)
    wins_total = np.zeros(len(teams))
    seed_total = np.zeros(len(teams))
    playoff_count = np.zeros(len(teams), dtype=int)
    title_count = np.zeros(len(teams), dtype=int)
    cup_count = np.zeros(len(teams), dtype=int)
    cup_group_rank_total = np.zeros(len(teams))
    cup_group_win_count = np.zeros(len(teams), dtype=int)
    cup_wild_card_count = np.zeros(len(teams), dtype=int)
    cup_knockout_count = np.zeros(len(teams), dtype=int)
    cup_final_count = np.zeros(len(teams), dtype=int)
    wins_samples = np.zeros((n_sims, len(teams)), dtype=np.int16)
    for simulation in range(n_sims):
        strength = _sigmoid(_logit(base_strength) + rng.normal(0.0, uncertainty))
        wins = rng.binomial(82, strength)
        wins_samples[simulation] = wins
        wins_total += wins
        conference_champions = []
        for indices in conference_indices.values():
            ordered = indices[np.lexsort((-strength[indices], -wins[indices]))]
            seed_total[ordered] += np.arange(1, 16)
            playoff_teams, champion = _conference_playoffs(ordered, strength, rng)
            playoff_count[playoff_teams] += 1
            conference_champions.append(champion)
        champion = _winner(
            conference_champions[0],
            conference_champions[1],
            strength,
            rng,
            series=True,
        )
        title_count[champion] += 1

        if cup_groups:
            cup = simulate_cup_once(teams, strength, rng, cup_groups)
            for ranked in cup["group_ranks"].values():
                cup_group_rank_total[ranked] += np.arange(1, 6)
                cup_group_win_count[ranked[0]] += 1
            cup_wild_card_count[cup["wild_cards"]] += 1
            cup_knockout_count[cup["qualifiers"]] += 1
            cup_final_count[cup["finalists"]] += 1
            cup_count[cup["champion"]] += 1
        else:
            # Historical groups are not stored in the forecast artifact. This
            # generic short-event approximation remains for old-season backtests.
            cup_score = _logit(strength) + rng.gumbel(0.0, 0.72, len(teams))
            cup_count[int(np.argmax(cup_score))] += 1

    group_by_team = {
        team: group
        for group, members in (cup_groups or {}).items()
        for team in members
    }

    result = pd.DataFrame(
        {
            "TEAM": teams,
            "CONFERENCE": [conferences[team] for team in teams],
            "PROJECTED_SEED": seed_total / n_sims,
            "PROJECTED_WINS": wins_total / n_sims,
            "PESSIMISTIC_WINS": np.quantile(wins_samples, 0.10, axis=0),
            "MEDIAN_WINS": np.quantile(wins_samples, 0.50, axis=0),
            "OPTIMISTIC_WINS": np.quantile(wins_samples, 0.90, axis=0),
            "PLAYOFF_PROB": playoff_count / n_sims,
            "CHAMP_PROB": title_count / n_sims,
            "CUP_PROB": cup_count / n_sims,
            "CUP_GROUP": [group_by_team.get(team) for team in teams],
            "CUP_PROJECTED_GROUP_RANK": (
                cup_group_rank_total / n_sims if cup_groups else np.nan
            ),
            "CUP_GROUP_WIN_PROB": cup_group_win_count / n_sims,
            "CUP_WILD_CARD_PROB": cup_wild_card_count / n_sims,
            "CUP_KNOCKOUT_PROB": cup_knockout_count / n_sims,
            "CUP_FINAL_PROB": cup_final_count / n_sims,
        }
    )
    result["PROJECTED_LOSSES"] = 82.0 - result["PROJECTED_WINS"]
    return result.sort_values(["CONFERENCE", "PROJECTED_SEED"]).reset_index(drop=True)
