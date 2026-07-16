import pandas as pd
import pytest

from nba_insights.analysis import (
    attach_ratings,
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


def test_attach_ratings_merges_and_keeps_everyone(league_stats):
    league = league_stats.assign(PLAYER_ID=[1, 2, 3, 4, 5])
    advanced = pd.DataFrame({"PLAYER_ID": [1, 2], "NET_RATING": [8.5, -2.0]})
    clutch = pd.DataFrame({"PLAYER_ID": [1], "GP": [30], "NET_RATING": [12.0]})
    out = attach_ratings(league, advanced, clutch)
    assert len(out) == len(league)  # nobody dropped
    alice = out[out["PLAYER_NAME"] == "Alice"].iloc[0]
    assert alice["NET_RATING"] == 8.5
    assert alice["CLUTCH_NET_RATING"] == 12.0
    assert alice["CLUTCH_GP"] == 30
    assert pd.isna(out.loc[out["PLAYER_NAME"] == "Carol", "NET_RATING"].iloc[0])


def test_zone_efficiency_diffs_against_league():
    from nba_insights.analysis import zone_efficiency

    shots = pd.DataFrame(
        {
            "SHOT_ZONE_BASIC": ["Restricted Area"] * 4 + ["Above the Break 3"] * 2,
            "SHOT_ZONE_AREA": ["Center(C)"] * 6,
            "SHOT_ZONE_RANGE": ["Less Than 8 ft."] * 4 + ["24+ ft."] * 2,
            "SHOT_MADE_FLAG": [1, 1, 1, 0, 0, 0],
        }
    )
    league = pd.DataFrame(
        {
            "SHOT_ZONE_BASIC": ["Restricted Area", "Above the Break 3"],
            "SHOT_ZONE_AREA": ["Center(C)", "Center(C)"],
            "SHOT_ZONE_RANGE": ["Less Than 8 ft.", "24+ ft."],
            "FG_PCT": [0.65, 0.35],
        }
    )
    out = zone_efficiency(shots, league).set_index("SHOT_ZONE_BASIC")
    assert out.loc["Restricted Area", "FGA"] == 4
    assert out.loc["Restricted Area", "PLAYER_PCT"] == 0.75
    assert out.loc["Restricted Area", "DIFF"] == pytest.approx(0.10)
    assert out.loc["Above the Break 3", "DIFF"] == pytest.approx(-0.35)
    with pytest.raises(KeyError, match="SHOT_MADE_FLAG"):
        zone_efficiency(shots.drop(columns=["SHOT_MADE_FLAG"]), league)


def test_shot_quality_separates_selection_from_making():
    from nba_insights.analysis import shot_quality

    shots = pd.DataFrame(
        {
            "SHOT_ZONE_BASIC": ["Restricted Area"] * 4 + ["Right Corner 3"] * 2,
            "SHOT_ZONE_AREA": ["Center(C)"] * 4 + ["Right Side(R)"] * 2,
            "SHOT_ZONE_RANGE": ["Less Than 8 ft."] * 4 + ["24+ ft."] * 2,
            "SHOT_TYPE": ["2PT Field Goal"] * 4 + ["3PT Field Goal"] * 2,
            "SHOT_MADE_FLAG": [1, 1, 1, 0, 1, 0],
        }
    )
    league = pd.DataFrame(
        {
            "SHOT_ZONE_BASIC": ["Restricted Area", "Right Corner 3"],
            "SHOT_ZONE_AREA": ["Center(C)", "Right Side(R)"],
            "SHOT_ZONE_RANGE": ["Less Than 8 ft.", "24+ ft."],
            "FG_PCT": [0.65, 0.40],
            "FGA": [100, 50],
            "FGM": [65, 20],
        }
    )
    sq = shot_quality(shots, league)
    assert sq["FGA"] == 6
    # expected: (4 * 0.65 + 2 * 0.40 * 1.5) / 6
    assert sq["XEFG"] == pytest.approx((4 * 0.65 + 2 * 0.40 * 1.5) / 6)
    # actual: (3 makes * 1.0 + 1 three * 1.5) / 6
    assert sq["EFG"] == pytest.approx(4.5 / 6)
    assert sq["MAKING"] == pytest.approx(sq["EFG"] - sq["XEFG"])
    # league: (65 * 1.0 + 20 * 1.5) / 150
    assert sq["LEAGUE_EFG"] == pytest.approx(95 / 150)


def test_shot_quality_drops_unmatched_zones_from_both_sides():
    from nba_insights.analysis import shot_quality

    shots = pd.DataFrame(
        {
            "SHOT_ZONE_BASIC": ["Restricted Area", "Backcourt"],
            "SHOT_ZONE_AREA": ["Center(C)", "Back Court(BC)"],
            "SHOT_ZONE_RANGE": ["Less Than 8 ft.", "Back Court Shot"],
            "SHOT_TYPE": ["2PT Field Goal", "3PT Field Goal"],
            "SHOT_MADE_FLAG": [1, 0],
        }
    )
    league = pd.DataFrame(
        {
            "SHOT_ZONE_BASIC": ["Restricted Area"],
            "SHOT_ZONE_AREA": ["Center(C)"],
            "SHOT_ZONE_RANGE": ["Less Than 8 ft."],
            "FG_PCT": [0.65],
        }
    )
    sq = shot_quality(shots, league)
    assert sq["FGA"] == 1  # the backcourt heave is not scored
    assert sq["EFG"] == pytest.approx(1.0)
    assert pd.isna(sq["LEAGUE_EFG"])  # no FGA/FGM in the league table
    with pytest.raises(KeyError, match="SHOT_TYPE"):
        shot_quality(shots.drop(columns=["SHOT_TYPE"]), league)


@pytest.fixture
def onoff_table():
    # concatenated on/off frames: Alice both sides, Bob on-court only
    return pd.DataFrame(
        {
            "VS_PLAYER_ID": [1, 2, 1],
            "VS_PLAYER_NAME": ["Alice", "Bob", "Alice"],
            "COURT_STATUS": ["On", "On", "Off"],
            "MIN": [1200.0, 300.0, 800.0],
            "OFF_RATING": [118.0, 110.0, 112.0],
            "DEF_RATING": [108.0, 112.0, 114.0],
            "NET_RATING": [10.0, -2.0, -2.0],
        }
    )


def test_team_on_off_pivots_and_diffs(onoff_table):
    from nba_insights.analysis import team_on_off

    out = team_on_off(onoff_table).set_index("PLAYER_NAME")
    alice = out.loc["Alice"]
    assert alice["MIN_ON"] == 1200.0
    assert alice["MIN_OFF"] == 800.0
    assert alice["NET_ON"] == 10.0
    assert alice["NET_OFF"] == -2.0
    assert alice["NET_DIFF"] == pytest.approx(12.0)
    assert alice["ORTG_ON"] == 118.0
    assert alice["DRTG_OFF"] == 114.0
    # Bob never sat: no off row, NaN diff, and Alice sorts first
    assert pd.isna(out.loc["Bob", "NET_DIFF"])
    assert list(out.index) == ["Alice", "Bob"]


def test_team_on_off_missing_column_raises(onoff_table):
    from nba_insights.analysis import team_on_off

    with pytest.raises(KeyError, match="COURT_STATUS"):
        team_on_off(onoff_table.drop(columns=["COURT_STATUS"]))


def test_attach_dpm_merges_and_keeps_everyone(league_stats):
    from nba_insights.analysis import attach_dpm

    league = league_stats.assign(PLAYER_ID=[1, 2, 3, 4, 5])
    darko = pd.DataFrame({"PLAYER_ID": [1, 2], "DPM": [5.5, -1.2], "O_DPM": [4.0, 0.3]})
    out = attach_dpm(league, darko)
    assert len(out) == len(league)
    assert out.loc[out["PLAYER_NAME"] == "Alice", "DPM"].iloc[0] == 5.5
    assert out.loc[out["PLAYER_NAME"] == "Alice", "O_DPM"].iloc[0] == 4.0
    assert pd.isna(out.loc[out["PLAYER_NAME"] == "Carol", "DPM"].iloc[0])


def test_attach_dpm_tolerates_missing_table(league_stats):
    from nba_insights.analysis import attach_dpm

    league = league_stats.assign(PLAYER_ID=range(5))
    assert attach_dpm(league, None) is league
    assert attach_dpm(league, pd.DataFrame({"PLAYER_ID": [1]})) is league  # no DPM column
    with pytest.raises(KeyError, match="PLAYER_ID"):
        attach_dpm(league_stats, None)


def test_attach_ratings_tolerates_missing_tables(league_stats):
    league = league_stats.assign(PLAYER_ID=range(5))
    out = attach_ratings(league, None, None)
    assert "NET_RATING" not in out.columns
    with pytest.raises(KeyError, match="PLAYER_ID"):
        attach_ratings(league_stats)
