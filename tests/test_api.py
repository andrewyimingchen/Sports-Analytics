import pandas as pd
import pytest
from fastapi.testclient import TestClient

from nba_insights.api import app
from nba_insights.api.app import get_client, get_outcome_model
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
                "GP": [80, 50],
                "PTS": [2000, 1500],
                "AST": [400, 250],
                "REB": [600, 400],
            }
        )
        self.league = pd.DataFrame(
            {
                "PLAYER_NAME": ["Alice Hooper", "Bob Rimson", "Carol", "Dan"],
                "GP": [60, 58, 61, 55],
                "MIN": [36.0, 34.0, 30.0, 28.0],
                "PTS": [30.0, 25.0, 20.0, 15.0],
                "AST": [8.0, 6.0, 4.0, 2.0],
                "REB": [7.0, 9.0, 5.0, 11.0],
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


def test_compare(api):
    r = api.get("/compare", params={"names": ["Alice Hooper", "Bob Rimson"]})
    assert r.status_code == 200
    stats = r.json()["stats"]
    assert stats["Alice Hooper"]["PTS"] == 30.0
    assert stats["Bob Rimson"]["REB"] == 9.0


def test_compare_missing_player_404(api):
    r = api.get("/compare", params={"names": ["Alice Hooper", "Zelda"]})
    assert r.status_code == 404


@pytest.fixture
def api_with_model(api):
    matchups = game_matchup_frame(team_form_features(synthetic_team_games(60), window=5))
    model = GameOutcomeModel().fit(matchups)
    app.dependency_overrides[get_outcome_model] = lambda: model
    return api


def test_teams(api):
    r = api.get("/teams")
    assert r.status_code == 200
    assert r.json() == ["T1", "T2", "T3", "T4"]


def test_predict_game(api_with_model):
    r = api_with_model.get("/predict/game", params={"home": "T1", "away": "T4"})
    assert r.status_code == 200
    body = r.json()
    assert 0 < body["home_win_prob"] < 1
    assert body["home_win_prob"] > 0.5  # strongest synthetic team at home


def test_predict_unknown_team_404(api_with_model):
    r = api_with_model.get("/predict/game", params={"home": "T1", "away": "ZZZ"})
    assert r.status_code == 404


def test_predict_same_team_422(api_with_model):
    r = api_with_model.get("/predict/game", params={"home": "T1", "away": "T1"})
    assert r.status_code == 422


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
    assert api.get("/app/manifest.json").status_code == 200
    assert api.get("/", follow_redirects=False).status_code in (302, 307)


def test_card_html(api):
    r = api.get("/players/1/card")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "Alice Hooper" in r.text
    assert "PTS / game" in r.text
    assert "League percentile" in r.text
