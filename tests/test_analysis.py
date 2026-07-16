import pandas as pd
import pytest

from nba_insights.analysis import (
    career_per_game,
    comparison_table,
    league_leaders,
    percentile_ranks,
    rolling_form,
)


@pytest.fixture
def game_log():
    # deliberately out of chronological order to prove sorting
    return pd.DataFrame(
        {
            "GAME_DATE": ["JAN 05, 2026", "JAN 01, 2026", "JAN 03, 2026"],
            "PTS": [30, 10, 20],
            "AST": [5, 8, 2],
        }
    )


@pytest.fixture
def league_stats():
    return pd.DataFrame(
        {
            "PLAYER_NAME": ["Alice", "Bob", "Carol", "Dan", "Bench Guy"],
            "GP": [60, 58, 61, 55, 3],
            "MIN": [36.0, 34.0, 30.0, 28.0, 5.0],
            "PTS": [30.0, 25.0, 20.0, 15.0, 50.0],
            "AST": [8.0, 6.0, 4.0, 2.0, 0.0],
            "REB": [7.0, 9.0, 5.0, 11.0, 1.0],
            "FG_PCT": [0.52, 0.48, 0.45, 0.55, 1.0],
        }
    )


def test_rolling_form_sorts_and_averages(game_log):
    out = rolling_form(game_log, "PTS", window=2)
    assert list(out["PTS"]) == [10, 20, 30]  # chronological
    assert list(out["ROLLING"]) == [10.0, 15.0, 25.0]


def test_rolling_form_unknown_stat_raises(game_log):
    with pytest.raises(KeyError):
        rolling_form(game_log, "XG")


def test_career_per_game_divides_by_gp():
    totals = pd.DataFrame(
        {
            "SEASON_ID": ["2023-24", "2024-25"],
            "GP": [80, 50],
            "PTS": [2000, 1500],
            "AST": [400, 250],
        }
    )
    out = career_per_game(totals, ["PTS", "AST"])
    assert list(out["PTS"]) == [25.0, 30.0]
    assert list(out["AST"]) == [5.0, 5.0]


def test_career_per_game_collapses_trade_season_rows():
    # traded mid-season: two team rows + TOT row share a SEASON_ID
    totals = pd.DataFrame(
        {
            "SEASON_ID": ["2024-25", "2024-25", "2024-25"],
            "GP": [30, 20, 50],
            "PTS": [600, 500, 1100],
        }
    )
    out = career_per_game(totals, ["PTS"])
    assert len(out) == 1
    assert out["GP"].iloc[0] == 50  # keeps the combined (TOT) row
    assert out["PTS"].iloc[0] == 22.0


def test_career_per_game_drops_zero_gp_seasons():
    totals = pd.DataFrame({"SEASON_ID": ["2024-25"], "GP": [0], "PTS": [0]})
    assert career_per_game(totals, ["PTS"]).empty


def test_percentile_ranks_orders_players(league_stats):
    top = percentile_ranks(league_stats, "Alice", ["PTS", "AST"])
    bottom = percentile_ranks(league_stats, "Dan", ["PTS", "AST"])
    assert top["PTS"] == 100.0
    assert bottom["PTS"] == 25.0
    assert top["AST"] > bottom["AST"]


def test_percentile_ranks_excludes_small_samples(league_stats):
    # Bench Guy's 50 PPG over 3 games must not beat Alice
    top = percentile_ranks(league_stats, "Alice", ["PTS"], min_games=10)
    assert top["PTS"] == 100.0
    with pytest.raises(KeyError):
        percentile_ranks(league_stats, "Bench Guy", min_games=10)


def test_comparison_table_shape_and_order(league_stats):
    out = comparison_table(league_stats, ["Carol", "Alice"], ["PTS", "REB"])
    assert list(out.columns) == ["Carol", "Alice"]
    assert list(out.index) == ["PTS", "REB"]
    assert out.loc["PTS", "Alice"] == 30.0


def test_comparison_table_missing_player_raises(league_stats):
    with pytest.raises(KeyError, match="Zelda"):
        comparison_table(league_stats, ["Alice", "Zelda"])


def test_league_leaders_ranks_and_filters_small_samples(league_stats):
    out = league_leaders(league_stats, "PTS", top=2, min_gp=10)
    # Bench Guy's 50 PPG over 3 games doesn't qualify
    assert list(out["PLAYER_NAME"]) == ["Alice", "Bob"]
    assert list(out["PTS"]) == [30.0, 25.0]


def test_league_leaders_unknown_stat_raises(league_stats):
    with pytest.raises(KeyError, match="XG"):
        league_leaders(league_stats, "XG")
