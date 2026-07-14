import numpy as np
import pandas as pd
import pytest

from nba_insights.ml import GameOutcomeModel, PlayerPointsModel, WinCurve, lineup_net_estimate
from nba_insights.ml.features import (
    game_matchup_frame,
    matchup_features,
    player_game_features,
    player_next_game_features,
    team_form_features,
    team_form_snapshot,
)


def synthetic_team_games(n_games_per_team: int = 30, seed: int = 7) -> pd.DataFrame:
    """A tiny league of 4 teams where team strength drives outcomes."""
    rng = np.random.default_rng(seed)
    strength = {1: 8.0, 2: 3.0, 3: -3.0, 4: -8.0}
    teams = list(strength)
    rows = []
    date = pd.Timestamp("2024-11-01")
    game_id = 0
    for _ in range(n_games_per_team):
        order = rng.permutation(teams)
        for h, a in [(order[0], order[1]), (order[2], order[3])]:
            game_id += 1
            margin = strength[h] - strength[a] + 2.5 + rng.normal(0, 10)
            h_pts = int(110 + margin / 2)
            a_pts = int(110 - margin / 2)
            for team, opp, pts, pm, home in [
                (h, a, h_pts, h_pts - a_pts, True),
                (a, h, a_pts, a_pts - h_pts, False),
            ]:
                rows.append(
                    {
                        "SEASON_ID": "22024",
                        "TEAM_ID": team,
                        "TEAM_ABBREVIATION": f"T{team}",
                        "GAME_ID": f"G{game_id:04d}",
                        "GAME_DATE": date.strftime("%Y-%m-%d"),
                        "MATCHUP": f"T{team} vs. T{opp}" if home else f"T{team} @ T{opp}",
                        "WL": "W" if pm > 0 else "L",
                        "PTS": pts,
                        "PLUS_MINUS": float(pm),
                    }
                )
        date += pd.Timedelta(days=2)
    return pd.DataFrame(rows)


def synthetic_player_games(n_games: int = 40, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for pid, base in [(1, 25.0), (2, 12.0)]:
        date = pd.Timestamp("2024-11-01")
        for g in range(n_games):
            pts = max(0, rng.normal(base, 5))
            rows.append(
                {
                    "PLAYER_ID": pid,
                    "PLAYER_NAME": f"Player {pid}",
                    "TEAM_ID": pid,
                    "GAME_ID": f"G{g:04d}",
                    "GAME_DATE": date.strftime("%Y-%m-%d"),
                    "MATCHUP": f"T{pid} vs. OPP" if g % 2 else f"T{pid} @ OPP",
                    "WL": "W",
                    "MIN": 34 + rng.normal(0, 3),
                    "PTS": pts,
                    "FGA": pts * 0.8,
                    "PLUS_MINUS": 0.0,
                }
            )
            date += pd.Timedelta(days=2)
    return pd.DataFrame(rows)


# -- features ----------------------------------------------------------------


def test_team_form_is_pregame_only():
    games = synthetic_team_games()
    form = team_form_features(games, window=5)
    one_team = form[form["TEAM_ID"] == 1].reset_index(drop=True)
    # feature at game i must equal the mean of the label over games i-5..i-1
    i = 12
    expected = one_team["win"].iloc[i - 5 : i].mean()
    assert one_team["form_win_pct"].iloc[i] == pytest.approx(expected)


def test_matchup_frame_pairs_home_and_away():
    games = synthetic_team_games()
    matchups = game_matchup_frame(team_form_features(games, window=5))
    assert not matchups.empty
    assert matchups["GAME_ID"].is_unique
    assert set(matchups["home_win"].unique()) <= {0, 1}


def test_snapshot_and_matchup_features():
    games = synthetic_team_games()
    snap = team_form_snapshot(games, window=10)
    assert len(snap) == 4
    # strongest team should have the best recent net rating
    assert snap.loc["T1", "form_net"] > snap.loc["T4", "form_net"]
    x = matchup_features(snap, "T1", "T4")
    assert x["form_net_diff"].iloc[0] > 0


def test_player_features_no_leakage():
    pg = synthetic_player_games()
    feats = player_game_features(pg)
    one = feats[feats["PLAYER_ID"] == 1].reset_index(drop=True)
    # pts_r5 at row i is the mean of the 5 PTS values before that game
    merged = pg[pg["PLAYER_ID"] == 1].reset_index(drop=True)
    i = 20
    game_id = one["GAME_ID"].iloc[i]
    pos = merged.index[merged["GAME_ID"] == game_id][0]
    expected = merged["PTS"].iloc[pos - 5 : pos].mean()
    assert one["pts_r5"].iloc[i] == pytest.approx(expected)


def test_player_next_game_features_shape():
    pg = synthetic_player_games()
    x = player_next_game_features(pg[pg["PLAYER_ID"] == 1], home=True, opp_form_net=-2.0)
    assert len(x) == 1
    assert x["home"].iloc[0] == 1
    assert x["opp_form_net"].iloc[0] == -2.0


# -- models -------------------------------------------------------------------


def test_outcome_model_beats_coin_flip_and_round_trips(tmp_path):
    matchups = game_matchup_frame(team_form_features(synthetic_team_games(60), window=5))
    model = GameOutcomeModel().fit(matchups)
    metrics = model.evaluate(matchups)
    assert metrics["accuracy"] > 0.5
    proba = model.predict_proba(matchups)
    assert proba.between(0, 1).all()

    path = tmp_path / "outcome.joblib"
    model.save(path)
    reloaded = GameOutcomeModel.load(path)
    pd.testing.assert_series_equal(reloaded.predict_proba(matchups), proba)


def test_points_model_learns_player_level(tmp_path):
    feats = player_game_features(synthetic_player_games(60))
    model = PlayerPointsModel().fit(feats)
    metrics = model.evaluate(feats)
    assert metrics["mae"] < 8  # players average 25 and 12; forecasting noise σ=5

    # the scorer's prediction should exceed the role player's
    scorer = model.predict(feats[feats["PLAYER_ID"] == 1]).mean()
    role = model.predict(feats[feats["PLAYER_ID"] == 2]).mean()
    assert scorer > role + 5

    path = tmp_path / "points.joblib"
    model.save(path)
    assert PlayerPointsModel.load(path).predict(feats).equals(model.predict(feats))


def test_win_curve_monotonic_and_bounded(tmp_path):
    curve = WinCurve().fit(synthetic_team_games(60))
    assert curve.slope > 0
    probs = [curve.win_probability(n) for n in (-15, -5, 0, 5, 15)]
    assert probs == sorted(probs)
    assert all(0 < p < 1 for p in probs)
    assert curve.win_probability(0) == pytest.approx(0.5)

    path = tmp_path / "curve.joblib"
    curve.save(path)
    assert WinCurve.load(path).slope == curve.slope


def test_lineup_net_estimate():
    league = pd.DataFrame(
        {
            "PLAYER_NAME": [f"P{i}" for i in range(6)],
            "MIN": [36.0] * 6,
            "PLUS_MINUS": [9.0, 3.0, 0.0, -3.0, -9.0, 100.0],
        }
    )
    five = ["P0", "P1", "P2", "P3", "P4"]
    assert lineup_net_estimate(league, five) == pytest.approx(0.0)
    with pytest.raises(ValueError):
        lineup_net_estimate(league, five[:4])
    with pytest.raises(KeyError):
        lineup_net_estimate(league, [*five[:4], "Nobody"])
