import pandas as pd
import pytest

from nba_insights.ml import sim_summary, simulate_game, simulate_matchup

LEAGUE = 112.0


def sim(seed=7, **kw):
    defaults = dict(
        home_ortg=LEAGUE,
        home_drtg=LEAGUE,
        away_ortg=LEAGUE,
        away_drtg=LEAGUE,
        pace=100.0,
        league_ortg=LEAGUE,
        n_sims=8000,
        seed=seed,
    )
    return simulate_game(**{**defaults, **kw})


def test_seed_makes_it_deterministic():
    pd.testing.assert_frame_equal(sim(seed=42), sim(seed=42))


def test_no_ties_and_overtime_happens():
    out = sim()
    assert (out["home_pts"] != out["away_pts"]).all()
    assert 0 < (out["overtimes"] > 0).mean() < 0.15


def test_equal_teams_home_court_edge():
    p = sim_summary(sim())["home_win_prob"]
    assert 0.5 < p < 0.62  # home court alone, not a blowout


def test_stronger_team_wins_more():
    strong = sim_summary(sim(home_ortg=LEAGUE + 5, home_drtg=LEAGUE - 5))
    assert strong["home_win_prob"] > 0.7
    assert strong["median_margin"] > 3


def test_missing_minutes_hurt():
    full = sim_summary(sim())["home_win_prob"]
    depleted = sim_summary(sim(home_missing_min=60.0))["home_win_prob"]
    assert depleted < full - 0.05


def test_margin_spread_is_nba_like():
    margin = sim()["home_pts"] - sim()["away_pts"]
    assert 10 < margin.std() < 17


def test_scores_are_plausible():
    out = sim()
    assert out["home_pts"].between(70, 160).mean() > 0.99


def test_simulate_matchup_reads_snapshot_and_raises():
    snapshot = pd.DataFrame(
        {
            "form_ortg": [115.0, 109.0],
            "form_drtg": [110.0, 114.0],
            "form_pace": [99.0, 101.0],
        },
        index=["AAA", "BBB"],
    )
    out = simulate_matchup(snapshot, "AAA", "BBB", n_sims=4000, seed=1)
    assert sim_summary(out)["home_win_prob"] > 0.6  # better team at home
    with pytest.raises(KeyError, match="ZZZ"):
        simulate_matchup(snapshot, "AAA", "ZZZ")


def test_summary_keys_and_ranges():
    s = sim_summary(sim())
    assert set(s) == {
        "home_win_prob",
        "median_margin",
        "margin_p10",
        "margin_p90",
        "median_total",
        "overtime_prob",
    }
    assert s["margin_p10"] < s["median_margin"] < s["margin_p90"]
    assert 180 < s["median_total"] < 260
    assert 0 <= s["overtime_prob"] <= 1
