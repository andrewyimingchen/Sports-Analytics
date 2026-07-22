import numpy as np
import pandas as pd
import pytest

from nba_insights.analysis import CUP_2026_GROUPS, season_forecast, simulate_cup_once


def test_official_2026_groups_assign_every_team_once():
    teams = [team for members in CUP_2026_GROUPS.values() for team in members]
    assert len(CUP_2026_GROUPS) == 6
    assert all(len(members) == 5 for members in CUP_2026_GROUPS.values())
    assert len(teams) == len(set(teams)) == 30


def test_official_cup_simulation_advances_six_winners_and_two_wild_cards():
    teams = [team for members in CUP_2026_GROUPS.values() for team in members]
    result = simulate_cup_once(
        teams,
        np.linspace(0.7, 0.3, 30),
        np.random.default_rng(3),
    )
    assert len(result["group_ranks"]) == 6
    assert all(len(ranked) == 5 for ranked in result["group_ranks"].values())
    assert len(set(result["qualifiers"])) == 8
    assert len(result["wild_cards"]) == 2
    assert len(result["finalists"]) == 2
    assert result["champion"] in result["finalists"]


def test_season_forecast_reports_official_cup_stage_probabilities():
    teams = [team for members in CUP_2026_GROUPS.values() for team in members]
    conferences = {
        team: ("East" if group.startswith("East") else "West")
        for group, members in CUP_2026_GROUPS.items()
        for team in members
    }
    snapshot = pd.DataFrame(
        {
            "form_win_pct": np.linspace(0.7, 0.3, 30),
            "form_net": np.linspace(10, -10, 30),
            "elo": np.linspace(1650, 1350, 30),
        },
        index=teams,
    )
    result = season_forecast(
        snapshot,
        conferences,
        n_sims=500,
        seed=8,
        cup_groups=CUP_2026_GROUPS,
    )
    assert result["CUP_GROUP_WIN_PROB"].sum() == pytest.approx(6)
    assert result["CUP_WILD_CARD_PROB"].sum() == pytest.approx(2)
    assert result["CUP_KNOCKOUT_PROB"].sum() == pytest.approx(8)
    assert result["CUP_FINAL_PROB"].sum() == pytest.approx(2)
    assert result["CUP_PROB"].sum() == pytest.approx(1)
