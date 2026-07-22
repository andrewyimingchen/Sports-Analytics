from collections import Counter

import pandas as pd
import pytest

from nba_insights.ml.elo import BASE, regress_to_mean, win_prob
from nba_insights.ml.season import CONFERENCE, _schedule, simulate_season

TEAMS = list(CONFERENCE)


def flat_elo(value: float = BASE) -> pd.Series:
    return pd.Series({t: value for t in TEAMS}, name="elo")


# --- Elo helpers ---------------------------------------------------------


def test_win_prob_symmetry_and_home_edge():
    assert win_prob(1500, 1500) == pytest.approx(0.5)
    # complementary in a neutral game
    assert win_prob(1600, 1400) + win_prob(1400, 1600) == pytest.approx(1.0)
    # home court tilts a coin-flip matchup toward the host
    assert win_prob(1500, 1500, hca=70) > 0.5


def test_regress_to_mean_pulls_toward_base():
    s = pd.Series({"A": 1700.0, "B": 1300.0})
    out = regress_to_mean(s)
    assert out["A"] == pytest.approx(0.75 * 1700 + 0.25 * BASE)
    assert out["B"] == pytest.approx(0.75 * 1300 + 0.25 * BASE)


# --- Schedule ------------------------------------------------------------


def test_schedule_is_balanced_82_and_41_home():
    sched = _schedule(TEAMS)
    assert len(sched) == 30 * 82 // 2
    gp, home = Counter(), Counter()
    for h, a in sched:
        gp[h] += 1
        gp[a] += 1
        home[h] += 1
    assert set(gp.values()) == {82}
    assert set(home.values()) == {41}


def test_schedule_opponent_structure():
    sched = _schedule(TEAMS)
    counts = Counter()
    for h, a in sched:
        counts[frozenset((h, a))] += 1
    per_team = {t: Counter() for t in TEAMS}
    for pair, n in counts.items():
        a, b = pair
        per_team[a][n] += 1
        per_team[b][n] += 1
    for t in TEAMS:
        # 10 four-game (4 division + 6 conf), 4 three-game, 15 cross-conf
        assert per_team[t] == Counter({4: 10, 3: 4, 2: 15})


# --- Season simulation ---------------------------------------------------


def test_simulate_season_shape_and_seed():
    a = simulate_season(flat_elo(), n_sims=400, seed=1)
    b = simulate_season(flat_elo(), n_sims=400, seed=1)
    pd.testing.assert_frame_equal(a, b)
    assert len(a) == 30
    assert set(a["conf"]) == {"East", "West"}


def test_probabilities_sum_correctly():
    proj = simulate_season(flat_elo(), n_sims=2000, seed=3)
    assert proj["champ_pct"].sum() == pytest.approx(1.0)
    assert proj["finals_pct"].sum() == pytest.approx(2.0)  # two finalists
    assert proj["conf_finals_pct"].sum() == pytest.approx(4.0)  # four teams
    assert proj["playoff_pct"].sum() == pytest.approx(16.0)  # 8 per conference
    assert proj["seed1_pct"].sum() == pytest.approx(2.0)  # one per conference


def test_equal_teams_wins_center_on_41():
    proj = simulate_season(flat_elo(), n_sims=2000, seed=5)
    assert proj["proj_wins"].mean() == pytest.approx(41.0, abs=0.5)
    # nobody is a title lock when everyone is identical
    assert proj["champ_pct"].max() < 0.12


def test_stronger_team_dominates():
    elo = flat_elo()
    elo["BOS"] = 1800.0  # a clear favourite
    proj = simulate_season(elo, n_sims=2000, seed=9, regress=False)
    assert proj.loc["BOS", "proj_wins"] > 55
    assert proj.loc["BOS", "champ_pct"] == proj["champ_pct"].max()
    assert proj.loc["BOS", "playoff_pct"] > 0.95


def test_unknown_team_raises():
    bad = pd.Series({"BOS": 1500.0, "ZZZ": 1500.0})
    with pytest.raises(KeyError):
        simulate_season(bad, n_sims=10)
