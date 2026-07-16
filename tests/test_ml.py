import numpy as np
import pandas as pd
import pytest

from nba_insights.ml import (
    GameOutcomeModel,
    PlayerPointsModel,
    WinCurve,
    blended_lineup_estimate,
    lineup_net_estimate,
    observed_lineup,
)
from nba_insights.ml.features import (
    availability_features,
    game_matchup_frame,
    matchup_features,
    player_game_features,
    player_next_game_features,
    prior_minute_rates,
    team_form_features,
    team_form_snapshot,
    upcoming_games,
)


def synthetic_team_games(
    n_games_per_team: int = 30,
    seed: int = 7,
    start: str = "2024-11-01",
    season_id: str = "22024",
    game_prefix: str = "G",
) -> pd.DataFrame:
    """A tiny league of 4 teams where team strength drives outcomes.

    *start*/*season_id*/*game_prefix* let callers build multi-season
    frames with distinct dates and unique GAME_IDs (e.g. for Elo).
    """
    rng = np.random.default_rng(seed)
    strength = {1: 8.0, 2: 3.0, 3: -3.0, 4: -8.0}
    teams = list(strength)
    rows = []
    date = pd.Timestamp(start)
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
                ftm, fg3m = 17, 12
                fgm = (pts - ftm - 3 * fg3m) / 2 + fg3m  # 2s + 3s reproduce PTS
                rows.append(
                    {
                        "SEASON_ID": season_id,
                        "TEAM_ID": team,
                        "TEAM_ABBREVIATION": f"T{team}",
                        "GAME_ID": f"{game_prefix}{game_id:04d}",
                        "GAME_DATE": date.strftime("%Y-%m-%d"),
                        "MATCHUP": f"T{team} vs. T{opp}" if home else f"T{team} @ T{opp}",
                        "WL": "W" if pm > 0 else "L",
                        "PTS": pts,
                        "PLUS_MINUS": float(pm),
                        "FGM": fgm,
                        "FGA": 88.0,
                        "FG3M": float(fg3m),
                        "FTM": float(ftm),
                        "FTA": 22.0,
                        "TOV": 14.0,
                        "OREB": 10.0,
                        "DREB": 33.0,
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
    loaded = PlayerPointsModel.load(path)
    assert loaded.predict(feats).equals(model.predict(feats))

    # 80% interval: fitted from training residuals, survives the round trip,
    # brackets the projection, and never goes below zero points
    assert loaded.resid_quantiles == model.resid_quantiles
    lo, hi = loaded.interval(20.0)
    assert 0 <= lo < 20.0 < hi
    assert loaded.interval(0.5)[0] == 0.0
    assert PlayerPointsModel(loaded.minutes, loaded.rate).interval(20.0) is None


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


def _availability_fixture():
    """One team, 3 games; player 1 plays 36/36 then misses game 3."""
    team_games = pd.DataFrame(
        {
            "SEASON_ID": "22024",
            "TEAM_ID": 1,
            "TEAM_ABBREVIATION": "T1",
            "GAME_ID": ["G1", "G2", "G3"],
            "GAME_DATE": ["2025-01-01", "2025-01-03", "2025-01-05"],
            "MATCHUP": "T1 vs. T2",
            "WL": "W",
            "PTS": 110,
            "PLUS_MINUS": 5.0,
        }
    )
    rows = []
    for game in ["G1", "G2", "G3"]:
        for pid, minutes in [(1, 36.0), (2, 20.0)]:
            if pid == 1 and game == "G3":
                continue  # star sits out game 3
            rows.append(
                {"GAME_ID": game, "TEAM_ID": 1, "PLAYER_ID": pid, "MIN": minutes}
            )
    return team_games, pd.DataFrame(rows)


def test_availability_weights_absent_star():
    team_games, player_games = _availability_fixture()
    av = availability_features(team_games, player_games).set_index("GAME_ID")
    assert av.loc["G1", "missing_min"] == 0.0  # no history yet, nothing to expect
    assert av.loc["G2", "missing_min"] == 0.0  # everyone played
    # game 3: player 1 absent; expected = 72 cum min / (2 games + 20 prior weight... no prior)
    assert av.loc["G3", "missing_min"] == pytest.approx(72 / 22)


def test_availability_prior_seeding_covers_cold_start():
    team_games, player_games = _availability_fixture()
    # star (player 1) misses game 1 too: drop their G1 row
    pg = player_games[~((player_games["PLAYER_ID"] == 1) & (player_games["GAME_ID"] == "G1"))]
    prior = pd.Series({1: 35.0})  # played 35 min/game last season
    av = availability_features(team_games, pg, prior_rates=prior, prior_weight=20).set_index(
        "GAME_ID"
    )
    # season opener: no current data, expectation comes wholly from the prior
    assert av.loc["G1", "missing_min"] == pytest.approx(35.0)


def test_prior_minute_rates():
    pg = pd.DataFrame({"PLAYER_ID": [1, 1, 2], "MIN": [30.0, 34.0, 10.0]})
    rates = prior_minute_rates(pg)
    assert rates[1] == pytest.approx(64 / 82)


def test_matchup_frame_missing_min_diff():
    games = synthetic_team_games()
    form = team_form_features(games, window=5)  # no player_games -> zeros
    matchups = game_matchup_frame(form)
    assert (matchups["missing_min_diff"] == 0).all()


def test_four_factor_math():
    games = synthetic_team_games(20)
    form = team_form_features(games, window=5).dropna()
    # eFG = (FGM + 0.5*3PM)/FGA with our constants: pts=110 -> fgm=28.5+12
    # sanity-band rather than exact: rolling means of plausible single games
    assert form["form_efg"].between(0.3, 0.8).all()
    assert form["form_tov_pct"].between(0.05, 0.25).all()
    assert form["form_oreb_pct"].between(0.1, 0.4).all()
    assert form["form_pace"].between(80, 120).all()
    # ortg - drtg should track scoring margin direction
    best = form[form["TEAM_ABBREVIATION"] == "T1"]
    worst = form[form["TEAM_ABBREVIATION"] == "T4"]
    assert best["form_ortg"].mean() - best["form_drtg"].mean() > 0
    assert worst["form_ortg"].mean() - worst["form_drtg"].mean() < 0


def test_fatigue_flags():
    dates = ["2025-01-01", "2025-01-02", "2025-01-04", "2025-01-10"]
    games = pd.DataFrame(
        {
            "SEASON_ID": "22024",
            "TEAM_ID": 1,
            "TEAM_ABBREVIATION": "T1",
            "GAME_ID": [f"G{i}" for i in range(4)],
            "GAME_DATE": dates,
            "MATCHUP": "T1 vs. T2",
            "WL": "W",
            "PTS": 110,
            "PLUS_MINUS": 5.0,
            "FGM": 40.0,
            "FGA": 88.0,
            "FG3M": 12.0,
            "FTM": 17.0,
            "FTA": 22.0,
            "TOV": 14.0,
            "OREB": 10.0,
            "DREB": 33.0,
        }
    )
    # opponent rows so the GAME_ID join finds a counterpart
    opp = games.assign(TEAM_ID=2, TEAM_ABBREVIATION="T2", MATCHUP="T2 @ T1", PLUS_MINUS=-5.0)
    form = team_form_features(pd.concat([games, opp]), window=2)
    t1 = form[form["TEAM_ABBREVIATION"] == "T1"].reset_index(drop=True)
    assert t1["b2b"].tolist() == [0, 1, 0, 0]  # Jan 2 is a back-to-back
    assert t1["three_in_four"].tolist() == [0, 0, 1, 0]  # Jan 4 is 3rd in 4 days


def test_upcoming_games_slate():
    schedule = pd.DataFrame(
        {
            "gameStatus": [3, 1, 1, 1],
            "gameDateTimeEst": [
                "2026-01-01T19:00:00Z",
                "2026-01-05T19:00:00Z",
                "2026-01-05T21:30:00Z",
                "2026-01-06T19:00:00Z",
            ],
            "homeTeam_teamTricode": ["AAA", "BBB", "CCC", "DDD"],
            "awayTeam_teamTricode": ["ZZZ", "YYY", "XXX", "WWW"],
        }
    )
    slate = upcoming_games(schedule, today=pd.Timestamp("2026-01-02", tz="UTC"))
    assert slate["home"].tolist() == ["BBB", "CCC"]  # next date only, played games skipped

    offseason = upcoming_games(schedule, today=pd.Timestamp("2026-08-01", tz="UTC"))
    assert offseason.empty


def test_observed_and_blended_lineup():
    lineups = pd.DataFrame(
        {
            "GROUP_ID": ["-1-2-3-4-5-", "-6-7-8-9-10-"],
            "MIN": [200.0, 30.0],
            "NET_RATING": [8.0, -5.0],
        }
    )
    league = pd.DataFrame(
        {
            "PLAYER_NAME": [f"P{i}" for i in range(1, 6)],
            "MIN": [36.0] * 5,
            "PLUS_MINUS": [2.0] * 5,  # proxy net = +2 per 36
        }
    )
    names, ids = [f"P{i}" for i in range(1, 6)], [5, 4, 3, 2, 1]  # unsorted on purpose
    row = observed_lineup(lineups, ids)
    assert row is not None and row["NET_RATING"] == 8.0

    est, minutes = blended_lineup_estimate(lineups, league, names, ids, shrinkage_minutes=200)
    assert minutes == 200.0
    assert est == pytest.approx(0.5 * 8.0 + 0.5 * 2.0)  # equal blend at 200 min

    est2, minutes2 = blended_lineup_estimate(lineups, league, names, [11, 12, 13, 14, 15])
    assert minutes2 == 0.0 and est2 == pytest.approx(2.0)  # pure proxy fallback


def test_prior_seeded_form_defined_from_game_one():
    from nba_insights.ml.features import FORM_PRIOR_WEIGHT, prior_team_form

    prior_season = synthetic_team_games(30, seed=11)
    season = synthetic_team_games(30, seed=12)
    priors = prior_team_form(prior_season)
    form = team_form_features(season, window=None, form_priors=priors)
    # no NaNs anywhere: every game has features, including each team's first
    assert form["form_net"].notna().all()
    # game 1 form equals the prior exactly (no current-season evidence yet)
    t1_first = form[form["TEAM_ID"] == 1].iloc[0]
    assert t1_first["form_net"] == pytest.approx(priors.loc[1, "PLUS_MINUS"])
    # game 2 blends prior (k pseudo-games) with one observed game
    t1 = form[form["TEAM_ID"] == 1].reset_index(drop=True)
    g1 = season[(season["TEAM_ID"] == 1)].sort_values("GAME_DATE").iloc[0]["PLUS_MINUS"]
    expected = (priors.loc[1, "PLUS_MINUS"] * FORM_PRIOR_WEIGHT + g1) / (FORM_PRIOR_WEIGHT + 1)
    assert t1["form_net"].iloc[1] == pytest.approx(expected)


def test_player_features_include_usage_and_ewm():
    pg = synthetic_player_games()
    feats = player_game_features(pg)
    assert {"rate_ewm", "min_ewm", "own_missing_min", "MIN"} <= set(feats.columns)
    one = feats[feats["PLAYER_ID"] == 1]
    # scorer's per-minute rate should exceed the role player's
    role = feats[feats["PLAYER_ID"] == 2]
    assert one["rate_ewm"].mean() > role["rate_ewm"].mean()


def test_elo_pregame_and_ordering():
    from nba_insights.ml.elo import BASE, elo_ratings

    games = synthetic_team_games(60)
    elo = elo_ratings(games)
    # pre-game: both teams enter the very first game at BASE
    tg = games.copy()
    first_gid = tg.sort_values("GAME_DATE")["GAME_ID"].iloc[0]
    assert (elo[elo["GAME_ID"] == first_gid]["elo"] == BASE).all()
    # by the end, the strongest synthetic team should out-rate the weakest
    last = elo.groupby("TEAM_ID").tail(1).set_index("TEAM_ID")["elo"]
    assert last[1] > last[4]


def test_current_elo_and_matchup_integration():
    from nba_insights.ml.elo import current_elo, elo_ratings

    games = synthetic_team_games(60)
    final = current_elo(games)
    assert final["T1"] > final["T4"]

    # elo merged into form flows through to matchup elo_diff
    form = team_form_features(games, window=5, elo=elo_ratings(games))
    matchups = game_matchup_frame(form)
    assert matchups["elo_diff"].abs().sum() > 0

    # snapshot + elo column -> matchup_features includes the diff
    snap = team_form_snapshot(games, window=10)
    snap["elo"] = final.reindex(snap.index)
    x = matchup_features(snap, "T1", "T4")
    assert x["elo_diff"].iloc[0] > 0

    # without elo anywhere, the diff is neutral
    form0 = team_form_features(games, window=5)
    assert (game_matchup_frame(form0)["elo_diff"] == 0).all()


def test_elo_season_rollover_regresses():
    from nba_insights.ml.elo import (
        BASE,
        CARRY,
        HOME_ADV,
        K,
        _expected_home,
        _mov_multiplier,
        elo_ratings,
    )

    def game(season, date, gid, margin):
        rows = []
        for team, opp, pm, home in [(1, 2, margin, True), (2, 1, -margin, False)]:
            rows.append(
                {
                    "SEASON_ID": season,
                    "TEAM_ID": team,
                    "TEAM_ABBREVIATION": f"T{team}",
                    "GAME_ID": gid,
                    "GAME_DATE": date,
                    "MATCHUP": f"T{team} vs. T{opp}" if home else f"T{team} @ T{opp}",
                    "WL": "W" if pm > 0 else "L",
                    "PTS": 110,
                    "PLUS_MINUS": float(pm),
                }
            )
        return rows

    games = pd.DataFrame(
        game("22024", "2025-01-01", "G1", 10) + game("22025", "2025-11-01", "G2", 10)
    )
    elo = elo_ratings(games)
    # replicate the single season-1 update by hand
    shift = K * _mov_multiplier(10, HOME_ADV) * (1 - _expected_home(BASE, BASE))
    end_t1 = BASE + shift
    expected_entry = CARRY * end_t1 + (1 - CARRY) * BASE
    entry_t1 = elo[(elo["GAME_ID"] == "G2") & (elo["TEAM_ID"] == 1)]["elo"].iloc[0]
    assert entry_t1 == pytest.approx(expected_entry)


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


def test_points_interval_binned_by_projection_level():
    feats = player_game_features(synthetic_player_games(60))
    model = PlayerPointsModel().fit(feats)
    rq = model.resid_quantiles
    assert set(rq) == {"edges", "quantiles"}
    assert len(rq["quantiles"]) == len(rq["edges"]) + 1
    # a projection above every edge uses the top bin's band
    top_lo, top_hi = rq["quantiles"][-1]
    hi_proj = rq["edges"][-1] + 10
    assert model.interval(hi_proj) == (
        max(0.0, hi_proj + top_lo),
        max(0.0, hi_proj + top_hi),
    )
    # legacy pooled-tuple artifacts still work
    legacy = PlayerPointsModel(model.minutes, model.rate, resid_quantiles=(-5.0, 6.0))
    assert legacy.interval(20.0) == (15.0, 26.0)
    # the nominal 80% band's coverage is measured, near nominal in-sample
    cov = model.evaluate(feats)["interval_coverage"]
    assert 0.7 <= cov <= 0.9


def test_tune_outcome_c_uses_dev_season_never_holdout():
    from nba_insights.ml.train import C_GRID, tune_outcome_c

    matchups = game_matchup_frame(team_form_features(synthetic_team_games(60), window=5))
    earlier = matchups.copy()
    earlier["GAME_DATE"] = earlier["GAME_DATE"] - pd.DateOffset(years=1)
    combined = pd.concat([earlier, matchups], ignore_index=True)
    c = tune_outcome_c(combined, dev_season_start="2024")
    assert c in C_GRID
    # degenerate split (no fit rows before the dev season) falls back safely
    assert tune_outcome_c(matchups, dev_season_start="2020") == 0.25


def test_snapshot_prior_seeding_matches_training_formula():
    from nba_insights.ml.features import FORM_PRIOR_WEIGHT, prior_team_form

    games = synthetic_team_games(60)
    priors = prior_team_form(games)  # stand-in for last season's means
    early = pd.concat(
        [g.head(4) for _, g in games.groupby("TEAM_ID")], ignore_index=True
    )
    raw = team_form_snapshot(early)
    seeded = team_form_snapshot(early, form_priors=priors)
    w, n = FORM_PRIOR_WEIGHT, 4
    expected = (priors.loc[1, "PLUS_MINUS"] * w + raw.loc["T1", "form_net"] * n) / (w + n)
    assert seeded.loc["T1", "form_net"] == pytest.approx(expected)
    # unknown teams fall back to the league-mean prior rather than NaN
    seeded_missing = team_form_snapshot(early, form_priors=priors.drop(index=1))
    assert not seeded_missing["form_net"].isna().any()


def test_team_rest_features_flags():
    from nba_insights.ml.features import team_rest_features

    games = synthetic_team_games()
    last_date = pd.to_datetime(games["GAME_DATE"]).max()
    # every team plays on a two-day cadence ending at last_date
    day_after = team_rest_features(games, tipoff=last_date + pd.Timedelta(days=1))
    assert (day_after["rest_days"] == 1).all()
    assert (day_after["b2b"] == 1).all()
    assert (day_after["three_in_four"] == 1).all()  # also played 3 days ago
    rested = team_rest_features(games, tipoff=last_date + pd.Timedelta(days=3))
    assert (rested["b2b"] == 0).all()
    assert (rested["three_in_four"] == 0).all()
    assert (rested["rest_days"] == 3).all()
