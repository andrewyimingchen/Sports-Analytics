"""Official 2026 NBA Cup groups, tiebreaks, and tournament simulation."""

from __future__ import annotations

from itertools import combinations

import numpy as np

CUP_2026_SOURCE_URL = "https://www.nba.com/news/emirates-nba-cup-2026-groups-announced"
CUP_2026_RULES_URL = "https://www.nba.com/news/nba-cup-101"
CUP_2026_SOURCE_DATE = "2026-07-01"
CUP_2026_SCHEDULE_COMPLETE = False

CUP_2026_GROUPS = {
    "West A": ["DEN", "HOU", "PHX", "DAL", "UTA"],
    "West B": ["OKC", "MIN", "LAC", "NOP", "MEM"],
    "West C": ["SAS", "LAL", "POR", "GSW", "SAC"],
    "East A": ["DET", "TOR", "ORL", "MIL", "BKN"],
    "East B": ["NYK", "CLE", "PHI", "MIA", "IND"],
    "East C": ["BOS", "ATL", "CHA", "CHI", "WAS"],
}


def _probability(strength_a: float, strength_b: float, home: bool = False) -> float:
    a = np.clip(strength_a, 0.03, 0.97)
    b = np.clip(strength_b, 0.03, 0.97)
    edge = np.log(a / (1 - a)) - np.log(b / (1 - b))
    return float(1 / (1 + np.exp(-(0.82 * edge + (0.12 if home else 0.0)))))


def _play_game(
    team_a: int,
    team_b: int,
    strength: np.ndarray,
    rng: np.random.Generator,
    *,
    home_a: bool = False,
) -> tuple[int, int, int]:
    probability = _probability(strength[team_a], strength[team_b], home=home_a)
    a_wins = rng.random() < probability
    margin = max(1, int(round(abs(rng.normal(8 + abs(probability - 0.5) * 12, 6)))))
    total = max(160, int(round(rng.normal(228, 15))))
    score_a = (total + margin) // 2 if a_wins else (total - margin) // 2
    score_b = total - score_a
    return (team_a if a_wins else team_b), score_a, score_b


def _rank_group(
    members: list[int],
    wins: dict[int, int],
    differential: dict[int, int],
    points: dict[int, int],
    head_to_head: dict[tuple[int, int], int],
    prior: np.ndarray,
    rng: np.random.Generator,
) -> list[int]:
    """Official sequential criteria; head-to-head is evaluated within each tie."""
    ranked = []
    for win_total in sorted({wins[team] for team in members}, reverse=True):
        tied = [team for team in members if wins[team] == win_total]
        h2h_wins = {
            team: sum(
                head_to_head.get(tuple(sorted((team, opponent)))) == team
                for opponent in tied
                if opponent != team
            )
            for team in tied
        }
        random_order = {team: rng.random() for team in tied}
        ranked.extend(
            sorted(
                tied,
                key=lambda team: (
                    h2h_wins[team],
                    differential[team],
                    points[team],
                    prior[team],
                    random_order[team],
                ),
                reverse=True,
            )
        )
    return ranked


def simulate_cup_once(
    teams: list[str],
    strength: np.ndarray,
    rng: np.random.Generator,
    groups: dict[str, list[str]] = CUP_2026_GROUPS,
) -> dict:
    """Simulate official group play, wild cards, knockouts, and champion."""
    team_index = {team: index for index, team in enumerate(teams)}
    if set(team_index) != {team for members in groups.values() for team in members}:
        raise ValueError("Cup groups must assign every forecast team exactly once")
    group_ranks: dict[str, list[int]] = {}
    records: dict[int, tuple[int, int, int]] = {}
    for name, tricodes in groups.items():
        members = [team_index[team] for team in tricodes]
        wins = {team: 0 for team in members}
        differential = {team: 0 for team in members}
        points = {team: 0 for team in members}
        head_to_head = {}
        for team_a, team_b in combinations(members, 2):
            winner, score_a, score_b = _play_game(team_a, team_b, strength, rng)
            wins[winner] += 1
            differential[team_a] += score_a - score_b
            differential[team_b] += score_b - score_a
            points[team_a] += score_a
            points[team_b] += score_b
            head_to_head[tuple(sorted((team_a, team_b)))] = winner
        ranked = _rank_group(
            members, wins, differential, points, head_to_head, strength, rng
        )
        group_ranks[name] = ranked
        records.update(
            {team: (wins[team], differential[team], points[team]) for team in members}
        )

    qualifiers = []
    wild_cards = []
    for conference in ("East", "West"):
        winners = [group_ranks[f"{conference} {letter}"][0] for letter in "ABC"]
        seconds = [group_ranks[f"{conference} {letter}"][1] for letter in "ABC"]
        random_order = {team: rng.random() for team in [*winners, *seconds]}

        def seed_key(team: int, order: dict[int, float] = random_order) -> tuple:
            return (*records[team], strength[team], order[team])

        winners = sorted(winners, key=seed_key, reverse=True)
        wild_card = max(seconds, key=seed_key)
        qualifiers.extend([*winners, wild_card])
        wild_cards.append(wild_card)
        quarter_one = _play_game(winners[0], wild_card, strength, rng, home_a=True)[0]
        quarter_two = _play_game(winners[1], winners[2], strength, rng, home_a=True)[0]
        conference_finalist = _play_game(
            quarter_one,
            quarter_two,
            strength,
            rng,
            home_a=seed_key(quarter_one) >= seed_key(quarter_two),
        )[0]
        if conference == "East":
            east_finalist = conference_finalist
        else:
            west_finalist = conference_finalist
    champion = _play_game(east_finalist, west_finalist, strength, rng)[0]
    return {
        "group_ranks": group_ranks,
        "qualifiers": qualifiers,
        "wild_cards": wild_cards,
        "finalists": [east_finalist, west_finalist],
        "champion": champion,
    }
