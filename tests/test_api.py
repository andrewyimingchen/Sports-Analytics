import pandas as pd
import pytest
from fastapi.testclient import TestClient

from nba_insights.api import app
from nba_insights.api.app import (
    get_client,
    get_outcome_model,
    get_points_model,
    get_win_curve,
)
from nba_insights.config import prediction_seasons
from nba_insights.ml import GameOutcomeModel
from nba_insights.ml.features import game_matchup_frame, team_form_features
from test_ml import synthetic_team_games

ALICE = {"id": 1, "full_name": "Alice Hooper", "is_active": True}
BOB = {"id": 2, "full_name": "Bob Rimson", "is_active": True}


class FakeNBAClient:
    def __init__(self):
        self.career = pd.DataFrame(
            {
                "SEASON_ID": ["2024-25", "2025-26"],
                "TEAM_ID": [100, 100],
                "GP": [80, 50],
                "PTS": [2000, 1500],
                "AST": [400, 250],
                "REB": [600, 400],
            }
        )
        self.league = pd.DataFrame(
            {
                "PLAYER_ID": [1, 2, 3, 4],
                "PLAYER_NAME": ["Alice Hooper", "Bob Rimson", "Carol", "Dan"],
                "TEAM_ABBREVIATION": ["T1", "T2", "T3", "T4"],
                "AGE": [25.0, 28.0, 22.0, 31.0],
                "GP": [60, 58, 61, 55],
                "MIN": [36.0, 34.0, 30.0, 28.0],
                "PLUS_MINUS": [7.0, 3.0, 1.0, -2.0],
                "PTS": [30.0, 25.0, 20.0, 15.0],
                "AST": [8.0, 6.0, 4.0, 2.0],
                "REB": [7.0, 9.0, 5.0, 11.0],
                "STL": [1.5, 1.2, 1.0, 0.8],
                "BLK": [0.5, 0.7, 1.0, 1.5],
                "TOV": [3.0, 2.5, 2.0, 1.5],
                "FG3M": [3.0, 2.5, 2.0, 1.5],
                "FG3A": [8.0, 7.0, 6.0, 5.0],
                "FTA": [7.0, 6.0, 5.0, 4.0],
                "FG_PCT": [0.52, 0.49, 0.47, 0.50],
                "FG3_PCT": [0.39, 0.37, 0.35, 0.33],
                "FT_PCT": [0.88, 0.84, 0.80, 0.76],
            }
        )

    def search_players(self, name):
        return [p for p in (ALICE, BOB) if name.lower() in p["full_name"].lower()]

    def find_player(self, player_id):
        return next((p for p in (ALICE, BOB) if p["id"] == player_id), None)

    def career_stats(self, player_id):
        return self.career if player_id == 1 else pd.DataFrame()

    def league_player_stats(self, season=None, per_mode="PerGame"):
        return self.league

    def team_games(self, season=None):
        return synthetic_team_games(40)

    def game_log(self, player_id, season=None, season_type="Regular Season"):
        if player_id != 1:
            return pd.DataFrame()
        return pd.DataFrame(
            {
                "GAME_DATE": ["2026-01-02", "2026-01-04"],
                "MATCHUP": ["T1 vs. T2", "T1 @ T3"],
                "WL": ["W", "L"],
                "MIN": [36, 34],
                "PTS": [32, 24],
                "REB": [8, 6],
                "AST": [9, 7],
                "FGM": [12, 9],
                "FGA": [20, 19],
                "FG3M": [4, 2],
                "PLUS_MINUS": [10, -4],
            }
        )

    def player_games(self, season=None):
        rows = []
        for game in range(12):
            rows.append(
                {
                    "PLAYER_ID": 1,
                    "PLAYER_NAME": "Alice Hooper",
                    "TEAM_ID": 1,
                    "TEAM_ABBREVIATION": "T1",
                    "GAME_ID": f"P{game:03d}",
                    "GAME_DATE": f"2026-01-{game + 1:02d}",
                    "MATCHUP": "T1 vs. T2",
                    "WL": "W",
                    "MIN": 35.0,
                    "PTS": 24.0 + game % 4,
                    "FGA": 18.0,
                    "PLUS_MINUS": 5.0,
                }
            )
        return pd.DataFrame(rows)

    def schedule(self, season=None):
        return pd.DataFrame(
            {
                "gameId": ["001", "002"],
                "gameDate": ["2026-01-02", "2026-01-06"],
                "gameStatus": [3, 1],
                "gameStatusText": ["Final", "7:30 pm ET"],
                "homeTeam_teamTricode": ["T1", "T3"],
                "homeTeam_score": [110, None],
                "awayTeam_teamTricode": ["T2", "T4"],
                "awayTeam_score": [101, None],
                "pointsLeaders_0_firstName": ["Alice", None],
                "pointsLeaders_0_lastName": ["Hooper", None],
                "pointsLeaders_0_points": [32, None],
            }
        )

    def shot_chart(self, player_id, season=None, season_type="Regular Season"):
        return pd.DataFrame(
            {
                "LOC_X": [-10, 12, 220, -215],
                "LOC_Y": [5, 10, 40, 38],
                "SHOT_MADE_FLAG": [1, 0, 1, 0],
                "SHOT_ZONE_BASIC": [
                    "Restricted Area", "Restricted Area", "Right Corner 3", "Left Corner 3"
                ],
                "SHOT_ZONE_AREA": [
                    "Center(C)", "Center(C)", "Right Side(R)", "Left Side(L)"
                ],
                "SHOT_ZONE_RANGE": ["Less Than 8 ft.", "Less Than 8 ft.", "24+ ft.", "24+ ft."],
                "SHOT_TYPE": [
                    "2PT Field Goal", "2PT Field Goal", "3PT Field Goal", "3PT Field Goal"
                ],
            }
        )

    def shot_league_averages(self, season=None, season_type="Regular Season"):
        return pd.DataFrame(
            {
                "SHOT_ZONE_BASIC": ["Restricted Area", "Right Corner 3", "Left Corner 3"],
                "SHOT_ZONE_AREA": ["Center(C)", "Right Side(R)", "Left Side(L)"],
                "SHOT_ZONE_RANGE": ["Less Than 8 ft.", "24+ ft.", "24+ ft."],
                "FG_PCT": [0.65, 0.38, 0.37],
                "FGA": [1000, 300, 300],
                "FGM": [650, 114, 111],
            }
        )

    def team_player_on_off(self, team_id, season=None):
        return pd.DataFrame(
            {
                "VS_PLAYER_ID": [1, 1],
                "VS_PLAYER_NAME": ["Hooper, Alice", "Hooper, Alice"],
                "COURT_STATUS": ["On", "Off"],
                "MIN": [1500, 900],
                "OFF_RATING": [120, 110],
                "DEF_RATING": [108, 112],
                "NET_RATING": [12, -2],
            }
        )

    def lineups(self, season=None):
        return pd.DataFrame(
            {
                "TEAM_ABBREVIATION": ["T1"],
                "GROUP_ID": ["-1-2-3-4-5-"],
                "GROUP_NAME": ["Alice - Bob - Carol - Dan - Eve"],
                "GP": [20],
                "MIN": [180],
                "NET_RATING": [8.5],
                "OFF_RATING": [119.0],
                "DEF_RATING": [110.5],
                "EFG_PCT": [0.57],
                "POSS": [390],
            }
        )

    def standings(self, season=None):
        return pd.DataFrame(
            {
                "Conference": ["East", "East", "West", "West"],
                "PlayoffRank": [1, 2, 1, 2],
                "TeamCity": ["Team", "Team", "Team", "Team"],
                "TeamName": ["One", "Two", "Three", "Four"],
                "TeamID": [1, 2, 3, 4],
                "WINS": [50, 45, 52, 40],
                "LOSSES": [20, 25, 18, 30],
                "WinPCT": [0.714, 0.643, 0.743, 0.571],
                "L10": ["8-2", "6-4", "9-1", "5-5"],
                "strCurrentStreak": ["W 3", "L 1", "W 5", "W 1"],
            }
        )

    def player_contracts(self):
        return pd.DataFrame(
            {
                "PLAYER_NAME": ["Alice Hooper"],
                "TEAM_ABBREVIATION": ["T1"],
                "2025-26": [30_000_000],
                "2026-27": [32_000_000],
                "GUARANTEED": [62_000_000],
            }
        )

    def box_score(self, game_id):
        return pd.DataFrame(
            {
                "teamId": [1, 2],
                "teamTricode": ["T1", "T2"],
                "personId": [1, 2],
                "firstName": ["Alice", "Bob"],
                "familyName": ["Hooper", "Rimson"],
                "minutes": ["PT36M00.00S", "PT35M00.00S"],
                "fieldGoalsMade": [12, 9],
                "fieldGoalsAttempted": [20, 19],
                "threePointersMade": [4, 2],
                "threePointersAttempted": [8, 7],
                "freeThrowsMade": [4, 5],
                "freeThrowsAttempted": [5, 6],
                "reboundsOffensive": [2, 3],
                "reboundsDefensive": [6, 6],
                "reboundsTotal": [8, 9],
                "assists": [9, 6],
                "steals": [2, 1],
                "blocks": [1, 1],
                "turnovers": [3, 2],
                "points": [32, 25],
                "plusMinusPoints": [9, -9],
                "comment": ["", ""],
            }
        )

    def cached_play_by_play(self, game_id):
        if game_id != "001":
            return None
        return pd.DataFrame(
            {
                "period": [1, 1, 4],
                "clock": ["PT11M00.00S", "PT10M00.00S", "PT00M00.00S"],
                "teamId": [1, 2, 1],
                "personId": [1, 2, 1],
                "actionType": ["Made Shot", "Made Shot", "period"],
                "subType": ["Layup", "3PT", "end"],
                "scoreHome": ["2", "2", "110"],
                "scoreAway": ["0", "3", "101"],
                "isFieldGoal": [1, 1, 0],
                "xLegacy": [5, 220, None],
                "yLegacy": [8, 40, None],
                "shotDistance": [2, 24, None],
            }
        )

    def cached_rotation(self, game_id):
        return None


@pytest.fixture
def api():
    app.dependency_overrides[get_client] = FakeNBAClient
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_search(api):
    r = api.get("/players/search", params={"q": "alice"})
    assert r.status_code == 200
    assert r.json() == [{"id": 1, "full_name": "Alice Hooper", "is_active": True}]


def test_search_query_too_short(api):
    assert api.get("/players/search", params={"q": "al"}).status_code == 422


def test_career_per_game(api):
    r = api.get("/players/1/career")
    assert r.status_code == 200
    seasons = r.json()
    assert seasons[0]["PTS"] == 25.0 and seasons[1]["PTS"] == 30.0


def test_career_unknown_player_404(api):
    assert api.get("/players/2/career").status_code == 404


def test_percentiles(api):
    r = api.get("/players/1/percentiles")
    assert r.status_code == 200
    body = r.json()
    assert body["player"] == "Alice Hooper"
    assert body["percentiles"]["PTS"] == 100.0


def test_percentiles_unknown_id_404(api):
    assert api.get("/players/99/percentiles").status_code == 404


def test_player_insights(api):
    response = api.get("/players/1/insights")
    assert response.status_code == 200
    body = response.json()
    assert body["player"] == "Alice Hooper"
    assert body["league_percentiles"]["PTS"] == 100.0
    assert body["position_group"] in {"Guard", "Wing", "Big"}
    assert body["scouting_take"]


def test_player_shots(api):
    response = api.get("/players/1/shots")
    assert response.status_code == 200
    body = response.json()
    assert len(body["attempts"]) == 4
    assert body["zones"]
    assert body["breakdown"]
    assert body["quality"]["FGA"] == 4


def test_player_splits_on_off_and_contract(api):
    splits = api.get("/players/1/splits")
    assert splits.status_code == 200
    assert set(splits.json()["splits"]) == {"home_away", "month", "rest", "opponent"}

    on_off = api.get("/players/1/on-off")
    assert on_off.status_code == 200
    assert on_off.json()["on_off"]["NET_DIFF"] == 14

    contract = api.get("/players/1/contract")
    assert contract.status_code == 200
    assert contract.json()["local_only"] is True
    assert contract.json()["salaries"]["2025-26"] == 30_000_000


def test_compare(api):
    r = api.get("/compare", params={"names": ["Alice Hooper", "Bob Rimson"]})
    assert r.status_code == 200
    body = r.json()
    stats = body["stats"]
    assert stats["Alice Hooper"]["PTS"] == 30.0
    assert stats["Bob Rimson"]["REB"] == 9.0
    assert body["career"]["Alice Hooper"]["PTS"] == 26.9
    assert {row["SEASON_ID"] for row in body["career_seasons"]["Alice Hooper"]} == {
        "2024-25",
        "2025-26",
    }
    assert body["poster_png"].endswith("format=png")


def test_compare_missing_player_404(api):
    r = api.get("/compare", params={"names": ["Alice Hooper", "Zelda"]})
    assert r.status_code == 404


def test_compare_keeps_career_view_when_player_is_not_active(api):
    client = FakeNBAClient()
    client.league = client.league.loc[client.league["PLAYER_NAME"] != "Bob Rimson"]
    app.dependency_overrides[get_client] = lambda: client

    response = api.get("/compare", params={"names": ["Alice Hooper", "Bob Rimson"]})

    assert response.status_code == 200
    assert response.json()["stats"] == {}
    assert response.json()["career"]["Alice Hooper"]["PTS"] == 26.9
    assert response.json()["poster_png"] is None


@pytest.fixture
def api_with_model(api):
    matchups = game_matchup_frame(team_form_features(synthetic_team_games(60), window=5))
    model = GameOutcomeModel().fit(matchups)
    app.dependency_overrides[get_outcome_model] = lambda: model
    return api


class FakePointsModel:
    def predict(self, features):
        return pd.Series([26.4])

    def interval(self, prediction):
        return (19.0, 35.0)


class FakeCurve:
    def win_probability(self, net):
        return 0.5 + net * 0.02


@pytest.fixture
def api_with_models(api_with_model):
    app.dependency_overrides[get_points_model] = FakePointsModel
    app.dependency_overrides[get_win_curve] = FakeCurve
    return api_with_model


def test_teams(api):
    r = api.get("/teams")
    assert r.status_code == 200
    assert r.json() == ["T1", "T2", "T3", "T4"]


def test_league_pulse(api):
    r = api.get("/league/pulse")
    assert r.status_code == 200
    body = r.json()
    assert body["leaders"]["points"][0]["PLAYER_NAME"] == "Alice Hooper"
    assert body["leaders"]["rebounds"][0]["PLAYER_NAME"] == "Dan"
    assert {row["team"] for row in body["team_form"]} == {"T1", "T2", "T3", "T4"}


def test_team_profile(api):
    r = api.get("/teams/T1/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["team"] == "T1"
    assert body["roster"][0]["PLAYER_NAME"] == "Alice Hooper"
    assert "form_net" in body["form"]
    assert body["scouting_take"]
    assert body["four_factors"]["off_efg_rank"] >= 1
    assert body["recent_games"]
    assert body["lineups"][0]["MIN"] == 180
    assert body["on_off"][0]["NET_DIFF"] == 14
    assert body["standings"]
    assert body["finances"]["payroll"] == 30_000_000
    assert api.get("/teams/ZZZ/profile").status_code == 404


def test_player_recent_games(api):
    r = api.get("/players/1/games", params={"limit": 1})
    assert r.status_code == 200
    assert r.json()["games"][0]["PTS"] == 24
    assert len(r.json()["games"]) == 1
    assert api.get("/players/99/games").status_code == 404


def test_similar_players(api):
    r = api.get("/players/1/similar", params={"limit": 2})
    assert r.status_code == 200
    assert len(r.json()["similar"]) == 2
    assert all(row["PLAYER_NAME"] != "Alice Hooper" for row in r.json()["similar"])


def test_explore_league(api):
    r = api.get(
        "/league/explore",
        params={"teams": "T2", "rate": "per_36", "sort": "AST"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["players"][0]["PLAYER_NAME"] == "Bob Rimson"
    assert body["players"][0]["PTS"] > 25  # rescaled from 34 to 36 minutes


def test_games_center(api):
    r = api.get("/games")
    assert r.status_code == 200
    games = r.json()["games"]
    assert games[0]["STATUS"] == "Final"
    assert games[0]["WINNER"] == "T1"
    assert games[0]["TOP_SCORER"] == "Alice Hooper · 32"
    assert games[1]["STATUS"] == "Scheduled"


def test_game_box_score(api):
    response = api.get("/games/001/box-score")
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "traditional_box_score"
    assert body["teams"]["T1"][0]["PLAYER"] == "Alice Hooper"
    assert body["teams"]["T1"][-1]["PLAYER"] == "TEAM TOTAL"


def test_game_story_has_timeline_shots_and_explicit_lineup_availability(api):
    response = api.get("/games/001/story", params={"season": "2025-26"})
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["availability"] == {
        "timeline": True,
        "shot_locations": True,
        "lineups": False,
        "play_by_play": True,
    }
    assert body["timeline"][-1]["HOME_WIN_PROB"] == 1
    assert len(body["advanced"]) == 2
    assert body["shots"]


def test_game_story_for_scheduled_game_is_explicitly_unavailable(api):
    response = api.get("/games/002/story", params={"season": "2025-26"})
    assert response.status_code == 200
    assert response.json() == {
        "game_id": "002",
        "available": False,
        "reason": "Game story becomes available after the game is final.",
    }


def test_ask_requires_optional_credential(api, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    response = api.post("/ask", json={"question": "Who leads in assists?"})
    assert response.status_code == 503
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


def test_predict_game(api_with_model):
    r = api_with_model.get("/predict/game", params={"home": "T1", "away": "T4"})
    assert r.status_code == 200
    body = r.json()
    assert 0 < body["home_win_prob"] < 1
    assert body["home_win_prob"] > 0.5  # strongest synthetic team at home


def test_predict_game_supports_upcoming_season(api_with_model):
    current, upcoming = prediction_seasons()
    response = api_with_model.get(
        "/predict/game",
        params={"home": "T1", "away": "T4", "season": upcoming},
    )
    assert response.status_code == 200
    assert response.json()["season"] == upcoming
    assert response.json()["basis_season"] == current
    assert response.json()["projection_mode"] == "preseason_carry_forward"


def test_predict_game_rejects_unsupported_season(api_with_model):
    response = api_with_model.get(
        "/predict/game",
        params={"home": "T1", "away": "T4", "season": "2035-36"},
    )
    assert response.status_code == 422


def test_predict_unknown_team_404(api_with_model):
    r = api_with_model.get("/predict/game", params={"home": "T1", "away": "ZZZ"})
    assert r.status_code == 404


def test_predict_same_team_422(api_with_model):
    r = api_with_model.get("/predict/game", params={"home": "T1", "away": "T1"})
    assert r.status_code == 422


def test_simulation_and_player_points(api_with_models):
    simulation = api_with_models.get(
        "/predict/simulate", params={"home": "T1", "away": "T4", "n_sims": 1000}
    )
    assert simulation.status_code == 200
    body = simulation.json()
    assert body["n_sims"] == 1000
    assert body["margin_histogram"] and body["total_histogram"]
    assert 0 < body["summary"]["home_win_prob"] < 1

    points = api_with_models.get(
        "/predict/player/1", params={"opponent": "T4", "home": True}
    )
    assert points.status_code == 200
    assert points.json()["projected_points"] == 26.4
    assert points.json()["interval_80"] == [19.0, 35.0]


def test_season_prediction_tables(api, monkeypatch):
    import importlib

    api_module = importlib.import_module("nba_insights.api.app")
    table = pd.DataFrame(
        {
            "TEAM": ["T1", "T2", "T3", "T4"],
            "CONFERENCE": ["East", "East", "West", "West"],
            "PROJECTED_SEED": [1.2, 2.1, 1.1, 2.4],
            "PROJECTED_WINS": [55.0, 48.0, 58.0, 45.0],
            "PROJECTED_LOSSES": [27.0, 34.0, 24.0, 37.0],
            "PLAYOFF_PROB": [0.95, 0.8, 0.97, 0.7],
            "CHAMP_PROB": [0.25, 0.1, 0.4, 0.05],
            "CUP_PROB": [0.2, 0.1, 0.3, 0.1],
            "CUP_GROUP": ["East A", "East A", "West A", "West A"],
            "CUP_PROJECTED_GROUP_RANK": [1.2, 2.0, 1.1, 2.4],
            "CUP_GROUP_WIN_PROB": [0.7, 0.3, 0.8, 0.2],
            "CUP_WILD_CARD_PROB": [0.1, 0.2, 0.1, 0.1],
            "CUP_KNOCKOUT_PROB": [0.8, 0.5, 0.9, 0.3],
            "CUP_FINAL_PROB": [0.4, 0.2, 0.5, 0.1],
        }
    )
    monkeypatch.setattr(api_module, "_season_forecast_table", lambda *args: table)
    upcoming = prediction_seasons()[1]

    response = api.get(
        "/predict/season",
        params={"season": upcoming, "n_sims": 1_000},
    )

    assert response.status_code == 200
    assert response.json()["season"] == upcoming
    assert len(response.json()["conferences"]["East"]) == 2
    assert response.json()["favorites"]["championship"]["team"] == "T3"
    assert response.json()["favorites"]["nba_cup"]["team"] == "T3"
    assert response.json()["nba_cup"]["source_date"] == "2026-07-01"
    assert response.json()["nba_cup"]["schedule_complete"] is False


def test_roster_forecast_inputs_are_auditable(api):
    upcoming = prediction_seasons()[1]
    response = api.get(
        "/predict/season/roster-inputs",
        params={"season": upcoming, "team": "T1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["metadata"]["version"] == "roster-minutes-v1"
    assert body["teams"][0]["TEAM"] == "T1"
    assert body["players"][0]["PLAYER_NAME"] == "Alice Hooper"
    assert body["players"][0]["PROJECTED_MIN"] == pytest.approx(240)


def test_player_season_projection_exposes_ranges_and_award_method(api):
    upcoming = prediction_seasons()[1]
    response = api.get("/predict/players", params={"season": upcoming, "limit": 10})
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == "player-season-v1"
    assert body["players"][0]["PTS_LOW"] <= body["players"][0]["PROJECTED_PTS"]
    assert "field-calibrated" in body["awards_method"]
    assert body["holdout"]["metrics"]["players"] == 241


def test_lineup_prediction(api_with_models, monkeypatch):
    import importlib

    api_module = importlib.import_module("nba_insights.api.app")
    roster = pd.DataFrame(
        {
            "PLAYER_ID": [1, 2, 3, 4, 5],
            "PLAYER_NAME": ["Alice", "Bob", "Carol", "Dan", "Eve"],
            "TEAM_ABBREVIATION": ["T1"] * 5,
            "MIN": [35.0, 34.0, 33.0, 32.0, 31.0],
            "PLUS_MINUS": [5.0, 4.0, 3.0, 2.0, 1.0],
        }
    )
    monkeypatch.setattr(api_module, "league_with_ratings", lambda client: roster)
    response = api_with_models.get(
        "/predict/lineup",
        params=[("team", "T1"), *[("player_ids", player_id) for player_id in range(1, 6)]],
    )
    assert response.status_code == 200
    assert response.json()["minutes_together"] == 180
    assert response.json()["source"] == "observed_blend"


def test_methodology(api):
    response = api.get("/methodology")
    assert response.status_code == 200
    body = response.json()
    assert body["journey"][-1]["accuracy"] == 70.2
    assert set(body["models"]) == {"outcome", "simulator", "points", "lineup", "season"}
    assert set(body["registry"]) == {
        "outcome",
        "player_points",
        "player_season",
        "lineup",
        "score_simulator",
        "season_forecast",
    }
    assert "status" in body["registry"]["season_forecast"]
    registry = api.get("/methodology/registry")
    assert registry.status_code == 200
    assert registry.json()["models"]["lineup"]["kind"] == "observed/proxy blend"


def test_headshot_proxy(api, monkeypatch):
    import importlib

    api_module = importlib.import_module("nba_insights.api.app")
    monkeypatch.setattr(
        api_module, "_fetch_headshot", lambda pid: b"fakepng" if pid == 1 else None
    )
    ok = api.get("/players/1/headshot")
    assert ok.status_code == 200
    assert ok.headers["content-type"] == "image/png"
    assert ok.content == b"fakepng"
    assert api.get("/players/2/headshot").status_code == 404


def test_mobile_app_shell_served(api):
    r = api.get("/app/")
    assert r.status_code == 200
    assert "NBA Insights" in r.text
    assert "Shot intelligence" in r.text
    assert "Ask the league" in r.text
    assert "Methodology" in r.text
    assert 'id="prediction-season"' in r.text
    assert 'id="season-forecast"' in r.text
    assert "East, West, playoffs and trophies" in r.text
    assert "Model registry" in r.text
    assert "Season forecast backtest" in r.text
    assert 'id="lineup-slots"' in r.text
    assert "The player box score becomes available after the game is final" in r.text
    assert api.get("/app/manifest.json").status_code == 200
    service_worker = api.get("/app/sw.js")
    assert service_worker.status_code == 200
    assert "fetch(e.request)" in service_worker.text
    assert api.get("/", follow_redirects=False).status_code in (302, 307)


def test_app_metadata(api):
    response = api.get("/meta")
    assert response.status_code == 200
    assert response.json()["current_season"] in response.json()["seasons"]
    assert response.json()["prediction_seasons"] == prediction_seasons()


def test_compare_poster_endpoint(api):
    params = {"names": ["Alice Hooper", "Bob Rimson"]}
    html = api.get("/posters/compare", params=params)
    assert html.status_code == 200
    assert html.headers["content-type"].startswith("text/html")
    assert "Alice Hooper" in html.text

    png = api.get("/posters/compare", params={**params, "format": "png"})
    assert png.status_code == 200
    assert png.headers["content-type"] == "image/png"
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"

    missing = api.get("/posters/compare", params={"names": ["Alice Hooper", "Zelda"]})
    assert missing.status_code == 404
    assert api.get("/posters/compare", params={**params, "format": "gif"}).status_code == 422


def test_game_poster_endpoint(api_with_model):
    html = api_with_model.get("/posters/game", params={"home": "T1", "away": "T4"})
    assert html.status_code == 200
    assert "T1" in html.text and "T4" in html.text

    png = api_with_model.get(
        "/posters/game", params={"home": "T1", "away": "T4", "format": "png"}
    )
    assert png.status_code == 200
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"

    bad = api_with_model.get("/posters/game", params={"home": "T1", "away": "ZZZ"})
    assert bad.status_code == 404


def test_card_html(api):
    r = api.get("/players/1/card")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Alice Hooper" in r.text
    assert "PTS / game" in r.text
    assert "League percentile" in r.text
